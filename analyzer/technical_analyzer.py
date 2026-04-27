"""
التحليل الفني الكامل - يحسب جميع المؤشرات ويعطي نقاط
يستخدم مكتبة ta (متوافقة مع arm64 و amd64)
"""
import pandas as pd
import numpy as np
import ta
from typing import Dict, Optional
from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('technical_analyzer')

class TechnicalAnalyzer:
    def __init__(self, client: AsyncClient):
        self.client = client

    async def analyze(self, symbol: str, timeframe: str = None) -> Optional[Dict]:
        tf = timeframe or config.TIMEFRAME
        try:
            df = await self._get_candles(symbol, tf)
            if df is None or len(df) < 50:
                return None

            df = self._calculate_indicators(df)
            market_condition = self._detect_market_condition(df)
            weights = await self._get_indicator_weights(market_condition)
            scores = self._calculate_scores(df, weights)
            levels = self._calculate_levels(df)

            # فلتر الاتجاه طويل المدى: السعر فوق ema200
            last_close = float(df['close'].iloc[-1])
            ema200_val = df['ema200'].iloc[-1]
            trend_ok = bool(not pd.isna(ema200_val) and last_close > float(ema200_val))

            return {
                'symbol': symbol,
                'timeframe': tf,
                'market_condition': market_condition,
                'total_score': scores['total'],
                'score_details': scores['details'],
                'entry_price': levels['entry'],
                'target_1': levels['t1'],
                'target_2': levels['t2'],
                'target_3': levels['t3'],
                'stop_loss': levels['stop'],
                'atr': float(df['atr'].iloc[-1]),
                'rsi': float(df['rsi'].iloc[-1]),
                'macd_signal': scores['details'].get('macd', 0),
                'volume_ratio': float(df['volume_ratio'].iloc[-1]),
                'trend_ok': trend_ok,
            }
        except Exception as e:
            logger.error(f"خطأ في التحليل الفني لـ {symbol} [{tf}]: {e}")
            return None

    async def _get_candles(self, symbol: str, timeframe: str = None) -> Optional[pd.DataFrame]:
        tf = timeframe or config.TIMEFRAME
        try:
            klines = await self.client.get_klines(
                symbol=symbol,
                interval=tf,
                limit=config.CANDLES_TO_FETCH
            )
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
                df[col] = pd.to_numeric(df[col])
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df = df.set_index('open_time')
            return df
        except Exception as e:
            logger.error(f"خطأ في جلب الشموع لـ {symbol}: {e}")
            return None

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب جميع المؤشرات باستخدام مكتبة ta"""

        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(
            close=df['close'], window=config.RSI_PERIOD
        ).rsi()

        # MACD
        macd = ta.trend.MACD(
            close=df['close'],
            window_fast=config.MACD_FAST,
            window_slow=config.MACD_SLOW,
            window_sign=config.MACD_SIGNAL
        )
        df['macd']        = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist']   = macd.macd_diff()

        # EMA
        df['ema20']  = ta.trend.EMAIndicator(df['close'], window=config.EMA_SHORT).ema_indicator()
        df['ema50']  = ta.trend.EMAIndicator(df['close'], window=config.EMA_MEDIUM).ema_indicator()
        df['ema200'] = ta.trend.EMAIndicator(df['close'], window=config.EMA_LONG).ema_indicator()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            close=df['close'], window=config.BB_PERIOD, window_dev=config.BB_STD
        )
        df['bb_upper']  = bb.bollinger_hband()
        df['bb_middle'] = bb.bollinger_mavg()
        df['bb_lower']  = bb.bollinger_lband()
        df['bb_width']  = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']

        # ATR
        df['atr'] = ta.volatility.AverageTrueRange(
            high=df['high'], low=df['low'], close=df['close'],
            window=config.ATR_PERIOD
        ).average_true_range()

        # Stochastic RSI
        stoch = ta.momentum.StochRSIIndicator(
            close=df['close'],
            window=config.RSI_PERIOD,
            smooth1=config.STOCH_K,
            smooth2=config.STOCH_D
        )
        df['stoch_k'] = stoch.stochrsi_k()
        df['stoch_d'] = stoch.stochrsi_d()

        # OBV
        df['obv']     = ta.volume.OnBalanceVolumeIndicator(
            close=df['close'], volume=df['volume']
        ).on_balance_volume()
        df['obv_ema'] = ta.trend.EMAIndicator(df['obv'], window=20).ema_indicator()

        # Volume Ratio
        df['volume_ma']    = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        return df

    def _detect_rsi_divergence(self, df: pd.DataFrame, lookback: int = 14) -> bool:
        """
        Bullish divergence: السعر يصنع low أدنى لكن RSI يصنع low أعلى
        على آخر شمعتين low في النوافذ الأخيرة.
        يعكس ضعف الزخم الهابط — إشارة محتملة لانعكاس صاعد.
        """
        if len(df) < lookback * 2:
            return False
        try:
            recent = df.iloc[-lookback:]
            older  = df.iloc[-lookback*2:-lookback]
            recent_low_idx = recent['low'].idxmin()
            older_low_idx  = older['low'].idxmin()

            recent_price_low = float(recent.loc[recent_low_idx, 'low'])
            older_price_low  = float(older.loc[older_low_idx, 'low'])
            recent_rsi_at_low = float(recent.loc[recent_low_idx, 'rsi'])
            older_rsi_at_low  = float(older.loc[older_low_idx, 'rsi'])

            if pd.isna(recent_rsi_at_low) or pd.isna(older_rsi_at_low):
                return False

            # Bullish divergence: price made a LOWER low, but RSI made a HIGHER low
            return recent_price_low < older_price_low and recent_rsi_at_low > older_rsi_at_low
        except Exception:
            return False

    def _calculate_fibonacci_score(self, df: pd.DataFrame, lookback: int = 50) -> float:
        """
        يحسب القرب من مستويات Fibonacci الرئيسية (38.2%, 50%, 61.8%) من
        swing high → swing low في آخر `lookback` شمعة.
        يعطي 1.0 لو السعر ضمن 1% من أي مستوى، 0.5 لو ضمن 2%، وإلا 0.
        """
        if len(df) < lookback:
            return 0.0
        try:
            recent     = df.iloc[-lookback:]
            swing_high = float(recent['high'].max())
            swing_low  = float(recent['low'].min())
            if swing_high <= swing_low:
                return 0.0
            diff = swing_high - swing_low
            fib_levels = (
                swing_high - 0.382 * diff,
                swing_high - 0.500 * diff,
                swing_high - 0.618 * diff,
            )
            current_price = float(df.iloc[-1]['close'])
            best = 0.0
            for level in fib_levels:
                if level <= 0:
                    continue
                proximity = abs(current_price - level) / level
                if proximity <= 0.01:
                    return 1.0
                if proximity <= 0.02 and best < 0.5:
                    best = 0.5
            return best
        except Exception:
            return 0.0

    def _detect_market_condition(self, df: pd.DataFrame) -> str:
        close  = df['close'].iloc[-1]
        ema20  = df['ema20'].iloc[-1]
        ema50  = df['ema50'].iloc[-1]
        ema200 = df['ema200'].iloc[-1] if not pd.isna(df['ema200'].iloc[-1]) else ema50
        atr     = df['atr'].iloc[-1]
        avg_atr = df['atr'].rolling(20).mean().iloc[-1]

        is_volatile = atr > avg_atr * 1.5

        if is_volatile:
            return "volatile"
        elif close > ema20 > ema50 > ema200:
            return "bullish"
        elif close < ema20 < ema50 < ema200:
            return "bearish"
        else:
            return "sideways"

    def _calculate_scores(self, df: pd.DataFrame, weights: Dict) -> Dict:
        # Mean-reverting indicators only — momentum indicators (volume, macd,
        # ema_cross, obv) were empirically shown to hurt PnL on 2158 trades.
        details = {}
        total   = 0.0
        last    = df.iloc[-1]

        # 1. RSI (oversold zones)
        rsi = last['rsi']
        if 30 <= rsi <= 50:
            rsi_score = weights.get('rsi', 1.0)
        elif 50 < rsi <= 60:
            rsi_score = weights.get('rsi', 1.0) * 0.5
        else:
            rsi_score = 0
        details['rsi'] = round(rsi_score, 2)
        total += rsi_score

        # 2. Bollinger Bands (price near lower band)
        bb_score = 0
        bb_range = last['bb_upper'] - last['bb_lower']
        if bb_range > 0:
            bb_pos = (last['close'] - last['bb_lower']) / bb_range
            if bb_pos <= 0.3:
                bb_score = weights.get('bollinger', 1.0)
            elif bb_pos <= 0.5:
                bb_score = weights.get('bollinger', 1.0) * 0.5
        details['bollinger'] = round(bb_score, 2)
        total += bb_score

        # 3. Stochastic RSI (oversold + crossing up)
        stoch_score = 0
        if not pd.isna(last['stoch_k']):
            stoch_k = last['stoch_k']
            stoch_d = last['stoch_d']
            if stoch_k < 0.2 and stoch_k > stoch_d:
                stoch_score = weights.get('stoch_rsi', 1.0)
            elif stoch_k < 0.3:
                stoch_score = weights.get('stoch_rsi', 1.0) * 0.5
        details['stoch_rsi'] = round(stoch_score, 2)
        total += stoch_score

        # 4. RSI Bullish Divergence (إضافة 2026-04-27)
        # السعر يصنع low أدنى لكن RSI أعلى → إشارة انعكاس
        div_score = 0
        if self._detect_rsi_divergence(df):
            div_score = weights.get('rsi_divergence', 1.0)
        details['rsi_divergence'] = round(div_score, 2)
        total += div_score

        # 5. Fibonacci Retracement Proximity (إضافة 2026-04-27)
        # القرب من مستويات 38.2%/50%/61.8% — مناطق دعم محتملة
        fib_score = self._calculate_fibonacci_score(df) * weights.get('fibonacci', 1.0)
        details['fibonacci'] = round(fib_score, 2)
        total += fib_score

        # Disabled indicators kept in details for backward compatibility
        # and so the optimizer can still measure them if re-enabled later.
        details['macd']      = 0
        details['ema_cross'] = 0
        details['volume']    = 0
        details['obv']       = 0
        details['btc_trend'] = 0

        return {'total': round(total, 2), 'details': details}

    def _calculate_levels(self, df: pd.DataFrame) -> Dict:
        last       = df.iloc[-1]
        atr        = float(last['atr'])
        close      = float(last['close'])
        recent     = df.tail(20)
        support    = float(recent['low'].min())
        resistance = float(recent['high'].max())

        entry     = close
        stop_atr  = entry - (atr * 1.5)
        stop_sup  = support * 0.99
        stop_loss = max(stop_atr, stop_sup)

        # تأكد أن stop_loss أقل من entry دائماً
        if stop_loss >= entry:
            stop_loss = entry * 0.97

        risk = entry - stop_loss

        # R:R tuned for mean-reverting strategy.
        # T3 خُفّض من 3.0R إلى 2.2R (2026-04-27) — البيانات: 0/168 لمست 3R
        # T1 quick bounce, T2 extended move, T3 reversal end.
        target_1 = entry + (risk * 1.0)
        target_2 = entry + (risk * 1.8)
        target_3 = entry + (risk * 2.2)

        if target_2 <= target_1:
            target_2 = entry + (risk * 1.8)
        if target_3 <= target_2:
            target_3 = entry + (risk * 2.2)

        # إذا كان الهدف الأول فوق المقاومة نستخدم المقاومة لكن فقط إذا كانت أعلى من الدخول
        if target_1 > resistance and resistance > entry:
            target_1 = resistance * 0.99

        return {
            'entry': round(entry, 8),
            'stop':  round(stop_loss, 8),
            't1':    round(target_1, 8),
            't2':    round(target_2, 8),
            't3':    round(target_3, 8),
        }

    async def _get_indicator_weights(self, market_condition: str) -> Dict:
        try:
            rows = await Database.fetch(
                "SELECT indicator_name, weight FROM indicator_weights WHERE market_condition = $1",
                market_condition
            )
            return {row['indicator_name']: float(row['weight']) for row in rows}
        except Exception:
            return {}
