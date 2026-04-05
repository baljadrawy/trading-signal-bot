"""
التحليل الفني الكامل - يحسب جميع المؤشرات ويعطي نقاط
"""
import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Dict, Optional
from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('technical_analyzer')

class TechnicalAnalyzer:
    def __init__(self, client: AsyncClient):
        self.client = client

    async def analyze(self, symbol: str) -> Optional[Dict]:
        """التحليل الفني الكامل لعملة"""
        try:
            # جلب الشموع
            df = await self._get_candles(symbol)
            if df is None or len(df) < 50:
                return None

            # حساب المؤشرات
            df = self._calculate_indicators(df)
            
            # الحصول على أوزان المؤشرات من التعلم الذاتي
            market_condition = self._detect_market_condition(df)
            weights = await self._get_indicator_weights(market_condition)
            
            # حساب النقاط
            scores = self._calculate_scores(df, weights)
            
            # حساب مستويات الدخول والأهداف
            levels = self._calculate_levels(df)
            
            return {
                'symbol': symbol,
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
            }
            
        except Exception as e:
            logger.error(f"خطأ في التحليل الفني لـ {symbol}: {e}")
            return None

    async def _get_candles(self, symbol: str) -> Optional[pd.DataFrame]:
        """جلب بيانات الشموع"""
        try:
            klines = await self.client.get_klines(
                symbol=symbol,
                interval=config.TIMEFRAME,
                limit=config.CANDLES_TO_FETCH
            )
            
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # تحويل الأنواع
            for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
                df[col] = pd.to_numeric(df[col])
            
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df = df.set_index('open_time')
            
            return df
            
        except Exception as e:
            logger.error(f"خطأ في جلب الشموع لـ {symbol}: {e}")
            return None

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب جميع المؤشرات الفنية"""
        
        # RSI
        df['rsi'] = ta.rsi(df['close'], length=config.RSI_PERIOD)
        
        # MACD
        macd = ta.macd(df['close'], 
                       fast=config.MACD_FAST,
                       slow=config.MACD_SLOW,
                       signal=config.MACD_SIGNAL)
        df['macd'] = macd[f'MACD_{config.MACD_FAST}_{config.MACD_SLOW}_{config.MACD_SIGNAL}']
        df['macd_signal'] = macd[f'MACDs_{config.MACD_FAST}_{config.MACD_SLOW}_{config.MACD_SIGNAL}']
        df['macd_hist'] = macd[f'MACDh_{config.MACD_FAST}_{config.MACD_SLOW}_{config.MACD_SIGNAL}']
        
        # EMA
        df['ema20'] = ta.ema(df['close'], length=config.EMA_SHORT)
        df['ema50'] = ta.ema(df['close'], length=config.EMA_MEDIUM)
        df['ema200'] = ta.ema(df['close'], length=config.EMA_LONG)
        
        # Bollinger Bands
        bb = ta.bbands(df['close'], length=config.BB_PERIOD, std=config.BB_STD)
        df['bb_upper'] = bb[f'BBU_{config.BB_PERIOD}_{config.BB_STD}']
        df['bb_middle'] = bb[f'BBM_{config.BB_PERIOD}_{config.BB_STD}']
        df['bb_lower'] = bb[f'BBL_{config.BB_PERIOD}_{config.BB_STD}']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        
        # ATR
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=config.ATR_PERIOD)
        
        # Stochastic RSI
        stoch = ta.stochrsi(df['close'], length=config.STOCH_K, rsi_length=config.RSI_PERIOD)
        if stoch is not None:
            df['stoch_k'] = stoch[f'STOCHRSIk_{config.STOCH_K}_{config.RSI_PERIOD}_{config.STOCH_K}_{config.STOCH_D}']
            df['stoch_d'] = stoch[f'STOCHRSId_{config.STOCH_K}_{config.RSI_PERIOD}_{config.STOCH_K}_{config.STOCH_D}']
        
        # OBV
        df['obv'] = ta.obv(df['close'], df['volume'])
        df['obv_ema'] = ta.ema(df['obv'], length=20)
        
        # Volume Ratio (حجم الشمعة الحالية مقارنة بالمتوسط)
        df['volume_ma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        return df

    def _detect_market_condition(self, df: pd.DataFrame) -> str:
        """تحديد حالة السوق"""
        close = df['close'].iloc[-1]
        ema20 = df['ema20'].iloc[-1]
        ema50 = df['ema50'].iloc[-1]
        ema200 = df['ema200'].iloc[-1] if not pd.isna(df['ema200'].iloc[-1]) else ema50
        bb_width = df['bb_width'].iloc[-1]
        atr = df['atr'].iloc[-1]
        avg_atr = df['atr'].rolling(20).mean().iloc[-1]
        
        # قياس التقلب
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
        """حساب نقاط كل مؤشر"""
        details = {}
        total = 0.0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 1. RSI (نقطة كاملة)
        rsi = last['rsi']
        if 30 <= rsi <= 50:  # منطقة شراء مثالية
            rsi_score = weights.get('rsi', 1.0)
        elif 50 < rsi <= 60:  # مقبول
            rsi_score = weights.get('rsi', 1.0) * 0.5
        else:
            rsi_score = 0
        details['rsi'] = round(rsi_score, 2)
        total += rsi_score

        # 2. MACD
        macd_score = 0
        if last['macd'] > last['macd_signal'] and prev['macd'] <= prev['macd_signal']:
            macd_score = weights.get('macd', 1.0)  # تقاطع صعودي
        elif last['macd'] > last['macd_signal']:
            macd_score = weights.get('macd', 1.0) * 0.5  # فوق خط الإشارة
        details['macd'] = round(macd_score, 2)
        total += macd_score

        # 3. EMA Cross
        ema_score = 0
        if last['close'] > last['ema20'] > last['ema50']:
            ema_score = weights.get('ema_cross', 1.0)
        elif last['close'] > last['ema20']:
            ema_score = weights.get('ema_cross', 1.0) * 0.5
        details['ema_cross'] = round(ema_score, 2)
        total += ema_score

        # 4. Bollinger Bands
        bb_score = 0
        bb_pos = (last['close'] - last['bb_lower']) / (last['bb_upper'] - last['bb_lower'])
        if bb_pos <= 0.3:  # قريب من الحافة السفلية - فرصة شراء
            bb_score = weights.get('bollinger', 1.0)
        elif bb_pos <= 0.5:
            bb_score = weights.get('bollinger', 1.0) * 0.5
        details['bollinger'] = round(bb_score, 2)
        total += bb_score

        # 5. Volume
        volume_ratio = last['volume_ratio']
        if volume_ratio >= 2.0:  # حجم أكبر من الضعف
            vol_score = weights.get('volume', 1.0)
        elif volume_ratio >= 1.5:
            vol_score = weights.get('volume', 1.0) * 0.7
        elif volume_ratio >= 1.2:
            vol_score = weights.get('volume', 1.0) * 0.4
        else:
            vol_score = 0
        details['volume'] = round(vol_score, 2)
        total += vol_score

        # 6. Stochastic RSI
        stoch_score = 0
        if 'stoch_k' in df.columns and not pd.isna(last['stoch_k']):
            stoch_k = last['stoch_k']
            stoch_d = last['stoch_d']
            if stoch_k < 20 and stoch_k > stoch_d:  # تقاطع في منطقة التشبع البيعي
                stoch_score = weights.get('stoch_rsi', 1.0)
            elif stoch_k < 30:
                stoch_score = weights.get('stoch_rsi', 1.0) * 0.5
        details['stoch_rsi'] = round(stoch_score, 2)
        total += stoch_score

        # 7. OBV
        obv_score = 0
        if last['obv'] > last['obv_ema']:  # OBV فوق المتوسط = ضغط شراء
            obv_score = weights.get('obv', 1.0)
        details['obv'] = round(obv_score, 2)
        total += obv_score

        # 8. BTC Trend (يُحسب في Signal Engine)
        details['btc_trend'] = 0  # سيُحدث لاحقاً

        # النقاط من 10 (8 مؤشرات + Order Book + BTC = 10)
        total_normalized = round((total / 8) * 8, 2)  # سيُضاف OB و BTC

        return {
            'total': total_normalized,
            'details': details
        }

    def _calculate_levels(self, df: pd.DataFrame) -> Dict:
        """حساب مستويات الدخول والأهداف ووقف الخسارة"""
        last = df.iloc[-1]
        atr = float(last['atr'])
        close = float(last['close'])
        
        # حساب الدعم والمقاومة من آخر 20 شمعة
        recent = df.tail(20)
        support = float(recent['low'].min())
        resistance = float(recent['high'].max())
        
        # نقطة الدخول - قريبة من السعر الحالي
        entry = close
        
        # وقف الخسارة - تحت الدعم أو ATR*1.5
        stop_atr = entry - (atr * 1.5)
        stop_support = support * 0.99  # 1% تحت الدعم
        stop_loss = max(stop_atr, stop_support)  # أعلى القيمتين للحماية
        
        # الأهداف بناءً على نسبة المخاطرة
        risk = entry - stop_loss
        target_1 = entry + (risk * 1.5)  # 1.5:1
        target_2 = entry + (risk * 2.5)  # 2.5:1
        target_3 = entry + (risk * 4.0)  # 4:1
        
        # التحقق من مستوى المقاومة
        if target_1 > resistance:
            target_1 = resistance * 0.98
        
        return {
            'entry': round(entry, 8),
            'stop': round(stop_loss, 8),
            't1': round(target_1, 8),
            't2': round(target_2, 8),
            't3': round(target_3, 8),
        }

    async def _get_indicator_weights(self, market_condition: str) -> Dict:
        """جلب أوزان المؤشرات من قاعدة البيانات"""
        try:
            rows = await Database.fetch(
                """
                SELECT indicator_name, weight
                FROM indicator_weights
                WHERE market_condition = $1
                """,
                market_condition
            )
            return {row['indicator_name']: float(row['weight']) for row in rows}
        except Exception:
            return {}  # أوزان افتراضية = 1.0
