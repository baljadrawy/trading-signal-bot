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
from shared.retry_utils import format_error
from shared.ohlcv import prepare_ohlcv
from shared.signal_stop import plan_signal_stop
from shared.regime import classify_regime
from shared import evidence_v2
from shared.signal_identity import IdentityError, candle_bounds, integrity_mode
from simple_entry import detect_trade_setup

logger = setup_logger('technical_analyzer')


def indicator_warmup_bars() -> int:
    """Minimum history required before every production indicator is mature."""
    return max(
        config.EMA_LONG,
        config.MACD_SLOW + config.MACD_SIGNAL,
        config.STOCH_RSI_WINDOW + config.STOCH_K + config.STOCH_D,
        config.BB_PERIOD,
        config.ATR_PERIOD,
        50,
    )

class TechnicalAnalyzer:
    def __init__(self, client: AsyncClient):
        self.client = client

    async def analyze(self, symbol: str, timeframe: str = None) -> Optional[Dict]:
        tf = timeframe or config.TIMEFRAME
        try:
            df = await self._get_candles(symbol, tf)
            # P1 point-in-time stamps exist only while forward instrumentation is ON
            # (EVIDENCE_V2_ENABLED); OFF leaves the analysis result byte-identical to develop.
            ev2_on = evidence_v2.enabled()
            klines_fetched_at_ms = evidence_v2.now_ms() if ev2_on else None
            if df is None or len(df) < indicator_warmup_bars():
                return None
            pit = evidence_v2.candle_pit(df, tf, klines_fetched_at_ms) if ev2_on else None   # reads index/close_time only
            # A44: correctness-critical closed-candle identity, independent of instrumentation.
            # Only in SIGNAL_INTEGRITY_MODE=enforce, so 'off' keeps the result byte-identical.
            candle_identity_fields = {}
            if integrity_mode(config) == 'enforce':
                try:
                    candle_identity_fields = {'candle_identity': candle_bounds(df, tf)}
                except IdentityError as exc:
                    candle_identity_fields = {'candle_identity': None,
                                              'candle_identity_error': str(exc)}

            df = self._calculate_indicators(df)
            regime = dict(classify_regime(df))
            market_condition = str(regime['condition'])
            weights = await self._get_indicator_weights(market_condition)
            scores = self._calculate_scores(df, weights)
            trade_type = None
            entry_reason = None
            execution_features = {}
            if config.LIVE_LEARNING_MODE:
                trade_type, entry_reason, execution_features = detect_trade_setup(
                    df, breakout_n=config.MOM_BREAKOUT_N,
                    vol_mult=config.MOM_VOL_MULT, rev_rsi=config.REV_RSI,
                    bb_max_position=config.REV_BB_MAX_POSITION,
                    market_condition=market_condition)
            levels = self._calculate_levels(df, tf, trade_type)

            # فلتر الاتجاه طويل المدى: السعر فوق ema200
            last_close = float(df['close'].iloc[-1])
            ema200_val = df['ema200'].iloc[-1]
            trend_ok = bool(not pd.isna(ema200_val) and last_close > float(ema200_val))

            # لقطة الميزات الخام (feature store — تدقيق 2026-06-23): قيم المؤشرات الفعلية وقت الإشارة،
            # لا النقاط المبوّبة. تُمكّن بحث ML نزيهاً لاحقاً على ميزات خام (score_details المبوّبة AUC=0.50).
            features = self._raw_features(df)

            return {
                'symbol': symbol,
                'timeframe': tf,
                'market_condition': market_condition,
                'regime': regime,
                'total_score': scores['total'],
                'score_details': scores['details'],
                'features': features,
                'research_features': features,
                'execution_features': execution_features,
                'entry_reason': entry_reason,
                'selection_policy': ('fixed_execution_quality_v1'
                                     if config.LIVE_LEARNING_MODE else 'legacy_score_v1'),
                'entry_price': levels['entry'],
                'target_1': levels['t1'],
                'target_2': levels['t2'],
                'target_3': levels['t3'],
                'stop_loss': levels['stop'],
                'stop_policy': levels['stop_policy'],
                'stop_invalidation': levels['stop_invalidation'],
                'stop_risk_pct': levels['stop_risk_pct'],
                'stop_valid': levels['stop_valid'],
                'stop_reject_reason': levels['stop_reject_reason'],
                'atr': float(df['atr'].iloc[-1]),
                'rsi': float(df['rsi'].iloc[-1]),
                'macd_signal': scores['details'].get('macd', 0),
                'volume_ratio': float(df['volume_ratio'].iloc[-1]),
                'trend_ok': trend_ok,
                'trade_type': trade_type,
                **candle_identity_fields,
                # P1 point-in-time identity (instrumentation only; no decision reads it;
                # written to analysis_data.pit only while EVIDENCE_V2_ENABLED)
                **({'pit': evidence_v2.candidate_pit(pit, symbol, tf, trade_type, config, weights)}
                   if pit is not None else {}),
            }
        except Exception as e:
            logger.error(f"خطأ في التحليل الفني لـ {symbol} [{tf}]: {format_error(e)}")
            return None

    async def _get_candles(self, symbol: str, timeframe: str = None) -> Optional[pd.DataFrame]:
        tf = timeframe or config.TIMEFRAME
        try:
            klines = await self.client.get_klines(
                symbol=symbol,
                interval=tf,
                limit=config.CANDLES_TO_FETCH + 1  # +1 لاحتمال وجود شمعة جارية؛ الفرز أدناه يعتمد close_time
            )
            # نستخدم close_time الفعلي بدل افتراض أن آخر صف هو الجاري، ثم نرفض
            # التكرار والفجوات والشموع المستحيلة قبل حساب أي مؤشر.
            return prepare_ohlcv(klines, tf, limit=config.CANDLES_TO_FETCH)
        except Exception as e:
            logger.error(f"خطأ في جلب الشموع لـ {symbol} [{tf}]: {format_error(e)}")
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

        # ADX is a regime feature, not an entry vote.
        df['adx'] = ta.trend.ADXIndicator(
            high=df['high'], low=df['low'], close=df['close'], window=14
        ).adx()

        # Stochastic RSI
        stoch = ta.momentum.StochRSIIndicator(
            close=df['close'],
            window=config.STOCH_RSI_WINDOW,
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

    def _raw_features(self, df: pd.DataFrame) -> Dict:
        """قيم المؤشرات الخام في آخر شمعة مغلقة — للتخزين كـ feature store (بحث ML مستقبلي)."""
        last = df.iloc[-1]
        def f(v):
            try:
                v = float(v)
                return v if v == v else None  # NaN-safe
            except Exception:
                return None
        close = f(last['close'])
        bb_rng = f(last['bb_upper']) - f(last['bb_lower']) if f(last['bb_upper']) is not None and f(last['bb_lower']) is not None else None
        feats = {
            'rsi':         f(last['rsi']),
            'stoch_k':     f(last['stoch_k']),
            'stoch_d':     f(last['stoch_d']),
            'macd_hist':   f(last['macd_hist']),
            'bb_pos':      (f(last['close']) - f(last['bb_lower'])) / bb_rng if bb_rng and bb_rng > 0 else None,
            'bb_width':    f(last['bb_width']),
            'atr_pct':     (f(last['atr']) / close) if close else None,
            'volume_ratio': f(last['volume_ratio']),
            'dist_ema20':  ((close - f(last['ema20'])) / close) if close and f(last['ema20']) is not None else None,
            'dist_ema50':  ((close - f(last['ema50'])) / close) if close and f(last['ema50']) is not None else None,
            'dist_ema200': ((close - f(last['ema200'])) / close) if close and f(last['ema200']) is not None else None,
            'obv_vs_ema':  (f(last['obv']) - f(last['obv_ema'])) if f(last['obv']) is not None and f(last['obv_ema']) is not None else None,
        }

        # مؤشرات خام إضافية للـ feature store فقط (لا تُستخدم في الانتقاء/النقاط).
        # نستخدم محرك ta المثبت نفسه صراحة؛ pandas_ta غير متوافق مع صورة الإنتاج الحالية.
        def clean(x, bound=None):
            try:
                v = float(x.iloc[-1])
                if not np.isfinite(v):
                    return None
                if bound is not None and abs(v) > bound:
                    return None
                return round(v, 6)
            except Exception:
                return None
        h, l, c, vol = df['high'], df['low'], df['close'], df['volume']
        specs = (
            ('adx14',   lambda: df['adx'], None),
            ('cci20',   lambda: ta.trend.CCIIndicator(h, l, c, window=20).cci(), 1000),
            ('willr14', lambda: ta.momentum.WilliamsRIndicator(h, l, c, lbp=14).williams_r(), None),
            ('roc10',   lambda: ta.momentum.ROCIndicator(c, window=10).roc(), None),
            ('mfi14',   lambda: ta.volume.MFIIndicator(h, l, c, vol, window=14).money_flow_index(), None),
            ('cmf20',   lambda: ta.volume.ChaikinMoneyFlowIndicator(h, l, c, vol, window=20).chaikin_money_flow(), None),
        )
        for key, fn, bound in specs:
            try: val = clean(fn(), bound)
            except Exception: val = None
            feats[key] = val
        return feats

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
        """Backward-compatible string view of the canonical regime classifier."""
        return str(classify_regime(df)['condition'])

    def _calculate_scores(self, df: pd.DataFrame, weights: Dict) -> Dict:
        # Mean-reverting indicators only — momentum indicators (volume, macd,
        # ema_cross, obv) were empirically shown to hurt PnL on 2158 trades.
        details = {}
        total   = 0.0
        last    = df.iloc[-1]

        # 1. RSI (oversold zones) — مضيّق لتركيز الإشارات على oversold حقيقي
        # المنطق: RSI 20-30 oversold قوي (x1.5)، 30-40 oversold معتدل (x1.0)،
        # 40-50 ضعيف (x0.3)، فوق 50 لا نعطي نقاط (إلغاء — لا يتوافق مع mean-revert).
        # البيانات: RSI >1.2 أقوى مؤشر إيجابي في تحليل 240 صفقة (2026-05-11).
        rsi = last['rsi']
        base_rsi_weight = weights.get('rsi', 1.0)
        if 0 <= rsi < 30:
            rsi_score = base_rsi_weight * 1.5   # oversold قوي — تعزيز
        elif 30 <= rsi < 40:
            rsi_score = base_rsi_weight * 1.0   # oversold معتدل — بدون تغيير
        elif 40 <= rsi < 50:
            rsi_score = base_rsi_weight * 0.3   # حافة oversold — تخفيض كبير
        else:
            rsi_score = 0                        # RSI >= 50 — لا إشارة mean-revert
        details['rsi'] = round(rsi_score, 2)
        total += rsi_score

        # 2. Bollinger Bands (price near lower band)
        # تحليل 262 صفقة (2026-05-14): bollinger بدون RSI oversold حقيقي (RSI>=40)
        # يعطي WR=16-25% وخسارة -50 USDT. المنطق: السعر قرب band السفلي لكن
        # RSI ليس في منطقة oversold = سقوط قوي يستمر (مومنتوم هابط) وليس انعكاساً.
        # الحل: bollinger يُحتسب فقط عندما RSI في منطقة oversold (rsi_score >= 1.0 = RSI < 40).
        bb_score = 0
        bb_range = last['bb_upper'] - last['bb_lower']
        if bb_range > 0 and rsi_score >= 1.0:  # اشتراط RSI oversold (RSI < 40)
            bb_pos = (last['close'] - last['bb_lower']) / bb_range
            if bb_pos <= 0.3:
                bb_score = weights.get('bollinger', 1.0)
            elif bb_pos <= 0.5:
                bb_score = weights.get('bollinger', 1.0) * 0.5
        details['bollinger'] = round(bb_score, 2)
        total += bb_score

        # 3. Stochastic RSI (oversold + crossing up)
        # البيانات (275 صفقة، 2026-04-22→2026-05-15):
        #   stoch_k < 0.2 مع تقاطع صاعد → WR=44%، Expectancy=+0.62% → ممتاز
        #   stoch_k < 0.3 بدون تقاطع   → WR=41%، Expectancy=-0.64% → ضار (100 صفقة)
        #   stoch_k >= 0.9               → WR=44%، لكن يحدث في قمة  → تخفيض
        # القرار: حذف حالة "oversold بدون تقاطع" — الاشتراط أن يكون stoch_k < 0.2 مع تقاطع.
        stoch_score = 0
        if not pd.isna(last['stoch_k']):
            stoch_k = last['stoch_k']
            stoch_d = last['stoch_d'] if not pd.isna(last['stoch_d']) else stoch_k
            base_stoch = weights.get('stoch_rsi', 1.0)
            if stoch_k < 0.2 and stoch_k > stoch_d:
                stoch_score = base_stoch          # oversold مع تقاطع صاعد — ممتاز
            # حالة stoch_k < 0.3 بدون تقاطع مُحذوفة: expectancy سالب على 100 صفقة
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

    def _calculate_levels(self, df: pd.DataFrame, timeframe: str = '1h',
                          trade_type: str = None) -> Dict:
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

        # Cap على SL حسب الـ timeframe — البيانات (2433 صفقة):
        # 1d: avg_sl=10.53% → T1=10.10% بعيد جداً، معظم الخروج بـ expiry 48h
        # الحل: cap لـ 1d عند 3% و 4h عند 5% لجعل T1 قابلاً للتحقق
        max_sl_pct = {'1d': 0.03, '4h': 0.05, '1h': 0.04, '15m': 0.02}
        cap_pct = max_sl_pct.get(timeframe, 0.04)
        stop_policy = 'legacy_atr_support'
        stop_invalidation = stop_loss
        stop_valid = True
        stop_reject_reason = None

        if trade_type in ('momentum', 'reversion'):
            breakout_level = float(
                df['high'].iloc[-(config.MOM_BREAKOUT_N + 1):-1].max())
            plan = plan_signal_stop(
                entry=entry, atr=atr, trade_type=trade_type,
                structure_low=support, breakout_level=breakout_level,
                max_risk_pct=cap_pct)
            stop_loss = plan.stop_price
            stop_policy = plan.policy
            stop_invalidation = plan.invalidation_price
            stop_valid = plan.valid
            stop_reject_reason = plan.reason
        else:
            max_risk = entry * cap_pct
            if (entry - stop_loss) > max_risk:
                stop_loss = entry - max_risk

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
            resistance_fill = resistance * 0.99
            if resistance_fill > entry:
                target_1 = resistance_fill

        return {
            'entry': round(entry, 8),
            'stop':  round(stop_loss, 8),
            'stop_policy': stop_policy,
            'stop_invalidation': round(stop_invalidation, 8),
            'stop_risk_pct': round((entry - stop_loss) / entry * 100, 4),
            'stop_valid': stop_valid,
            'stop_reject_reason': stop_reject_reason,
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
