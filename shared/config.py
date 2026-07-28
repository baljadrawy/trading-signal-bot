"""
الإعدادات المشتركة بين جميع الـ Containers
"""
import os
from dataclasses import dataclass, field

@dataclass
class Config:
    # Binance
    BINANCE_API_KEY: str = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET: str = os.getenv('BINANCE_API_SECRET', '')
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID: str = os.getenv('TELEGRAM_CHAT_ID', '')
    
    # Claude
    ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
    
    # PostgreSQL
    POSTGRES_HOST: str = os.getenv('POSTGRES_HOST', 'postgres')
    POSTGRES_PORT: int = int(os.getenv('POSTGRES_PORT', '5432'))
    POSTGRES_DB: str = os.getenv('POSTGRES_DB', 'trading_signals')
    POSTGRES_USER: str = os.getenv('POSTGRES_USER', 'trading_bot')
    POSTGRES_PASSWORD: str = os.getenv('POSTGRES_PASSWORD', '')
    
    # إعدادات التداول
    PAPER_TRADING: bool = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
    MAX_SIGNALS_PER_DAY: int = int(os.getenv('MAX_SIGNALS_PER_DAY', '5'))
    MIN_SCORE_TO_SIGNAL: float = float(os.getenv('MIN_SCORE_TO_SIGNAL', '5'))
    SCAN_INTERVAL_SECONDS: int = int(os.getenv('SCAN_INTERVAL_SECONDS', '300'))
    TIMEFRAME: str = os.getenv('TIMEFRAME', '4h')  # الإطار الرئيسي (للتوافق)

    # Timeframes متعددة للتحليل
    # يمكن تعديلها في .env: TIMEFRAMES=15m,1h,4h,1d
    TIMEFRAMES: list = field(default_factory=lambda: os.getenv('TIMEFRAMES', '15m,1h,4h,1d').split(','))

    # الحد الأدنى لعدد Timeframes المتفقة لإصدار إشارة (من أصل 4)
    MIN_TIMEFRAME_CONFIRMATIONS: int = int(os.getenv('MIN_TIMEFRAME_CONFIRMATIONS', '2'))

    # ── Evidence flight-recorder (PR #3c) ───────────────────────────────
    # مُسجِّل أدلة معزول: يلتقط snapshot لحظة القرار إلى طابور محلي ثم flush غير متزامن.
    # معطّل افتراضياً. لا يلمس قرارات التداول/DB/المراقب؛ أي فشل فيه يُدفن ولا يصل لمحرك الإشارة.
    ENABLE_EVIDENCE_RECORDER: bool = os.getenv('ENABLE_EVIDENCE_RECORDER', 'false').lower() == 'true'
    APP_VERSION: str = os.getenv('APP_VERSION', 'sb-2026.06')   # tag evidence by system version
    EVIDENCE_DIR: str = os.getenv('EVIDENCE_DIR', 'data/evidence')
    EVIDENCE_BATCH_SIZE: int = int(os.getenv('EVIDENCE_BATCH_SIZE', '100'))
    EVIDENCE_FLUSH_INTERVAL_S: float = float(os.getenv('EVIDENCE_FLUSH_INTERVAL_S', '5'))
    EVIDENCE_MAX_QUEUE: int = int(os.getenv('EVIDENCE_MAX_QUEUE', '10000'))
    EVIDENCE_FLUSH_RETRY_COUNT: int = int(os.getenv('EVIDENCE_FLUSH_RETRY_COUNT', '3'))
    EVIDENCE_FLUSH_BACKOFF_MS: float = float(os.getenv('EVIDENCE_FLUSH_BACKOFF_MS', '50'))
    EVIDENCE_SHUTDOWN_FLUSH_TIMEOUT_MS: float = float(os.getenv('EVIDENCE_SHUTDOWN_FLUSH_TIMEOUT_MS', '2000'))
    EVIDENCE_TELEMETRY_HISTORY: int = int(os.getenv('EVIDENCE_TELEMETRY_HISTORY', '500'))  # ring-buffer snapshots
    EVIDENCE_PHASE_ID: str = os.getenv('EVIDENCE_PHASE_ID', '')  # canary run label (e.g. PhaseA-R2)
    # Capture filter (canary scoping). Empty list = allow all; max/hour 0 = unlimited.
    EVIDENCE_FILTER_SYMBOLS: list = field(default_factory=lambda: [s for s in os.getenv('EVIDENCE_FILTER_SYMBOLS', '').split(',') if s])
    EVIDENCE_FILTER_TIMEFRAMES: list = field(default_factory=lambda: [s for s in os.getenv('EVIDENCE_FILTER_TIMEFRAMES', '').split(',') if s])
    EVIDENCE_FILTER_SOURCES: list = field(default_factory=lambda: [s for s in os.getenv('EVIDENCE_FILTER_SOURCES', '').split(',') if s])
    EVIDENCE_FILTER_MAX_SIGNALS_PER_HOUR: int = int(os.getenv('EVIDENCE_FILTER_MAX_SIGNALS_PER_HOUR', '0'))

    # ── Live-Learning mode ──────────────────────────────────────────────
    LIVE_LEARNING_MODE: bool = os.getenv('LIVE_LEARNING_MODE', 'false').lower() == 'true'
    TIMEFRAMES_LL: list = field(default_factory=lambda: os.getenv('TIMEFRAMES_LL', '15m,4h,1d').split(','))
    MOM_BREAKOUT_N: int = int(os.getenv('MOM_BREAKOUT_N', '20'))
    MOM_VOL_MULT: float = float(os.getenv('MOM_VOL_MULT', '1.2'))
    REV_RSI: float = float(os.getenv('REV_RSI', '35'))
    USDTD_SPIKE_PP: float = float(os.getenv('USDTD_SPIKE_PP', '0.5'))
    MACRO_CACHE_HOURS: int = int(os.getenv('MACRO_CACHE_HOURS', '1'))
    WARMUP_N: int = int(os.getenv('WARMUP_N', '100'))
    ROLL_N: int = int(os.getenv('ROLL_N', '150'))
    MIN_CELL_N: int = int(os.getenv('MIN_CELL_N', '10'))
    THROTTLE_EXPECTANCY: float = float(os.getenv('THROTTLE_EXPECTANCY', '0'))
    # رسوم الذهاب والإياب (%) التي يجب أن يتجاوزها التوقّع الإجمالي للخلية لتبقى مفعّلة.
    # 0.3 = 0.1%/جهة رسوم + ~0.1% انزلاق (محاسبة البوت، متسقة مع STOP_SLIPPAGE=0.1%).
    # المُتعلّم يخنق على التوقّع الصافي (إجمالي − رسوم) لا الإجمالي (إصلاح البوابة العمياء للرسوم).
    FEE_ROUNDTRIP_PCT: float = float(os.getenv('FEE_ROUNDTRIP_PCT', '0.3'))
    LEARN_CRON_HOURS: int = int(os.getenv('LEARN_CRON_HOURS', '12'))

    # حجم الصفقة
    TRADE_AMOUNT_USDT: float = float(os.getenv('TRADE_AMOUNT_USDT', '50'))
    STOP_SLIPPAGE: float = float(os.getenv('STOP_SLIPPAGE', '0.001'))  # 0.1% modeled stop-fill slippage

    # نظام الموافقة والـ Whitelist
    APPROVAL_TIMEOUT_MINUTES: int = int(os.getenv('APPROVAL_TIMEOUT_MINUTES', '30'))
    APPROVAL_MAX_PRICE_CHANGE_PCT: float = float(os.getenv('APPROVAL_MAX_PRICE_CHANGE_PCT', '0.5'))

    # حماية رأس المال
    MAX_DAILY_LOSS_PERCENT: float = float(os.getenv('MAX_DAILY_LOSS_PERCENT', '3'))
    STOP_ON_CONSECUTIVE_LOSSES: int = int(os.getenv('STOP_ON_CONSECUTIVE_LOSSES', '3'))
    MAX_OPEN_TRADES: int = int(os.getenv('MAX_OPEN_TRADES', '10'))  # 0 = بلا حد
    # Cooldown عام بعد ضربة SL حقيقية (ساعات). 0 = معطّل.
    # عُطّل 2026-06-20 (paper trading) لزيادة عدد الإشارات وإزالة تحيّز انتقاء البيانات.
    GLOBAL_LOSS_COOLDOWN_HOURS: int = int(os.getenv('GLOBAL_LOSS_COOLDOWN_HOURS', '6'))

    # المؤشرات
    RSI_PERIOD: int = 14
    RSI_OVERSOLD: float = 35
    RSI_OVERBOUGHT: float = 65
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9
    EMA_SHORT: int = 20
    EMA_MEDIUM: int = 50
    EMA_LONG: int = 200
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    ATR_PERIOD: int = 14
    STOCH_K: int = 14
    STOCH_D: int = 3
    
    # فلاتر Scanner
    MIN_VOLUME_USDT: float = float(os.getenv('MIN_VOLUME_USDT', '10000000'))  # حجم تداول يومي أدنى — افتراضي 10M USDT (رُفع من 1M في 2026-04-27)
    MIN_PRICE_CHANGE_PERCENT: float = 1.0  # حركة سعرية أدنى 1% (خُفّض من 2% في 2026-05-17: السوق الهابط/الهادئ ينتج 4-9 عملات فقط من 430)
    CANDLES_TO_FETCH: int = 200  # عدد الشموع المغلقة للتحليل (تُسقط الشمعة الجارية)
    MAX_SPREAD_PCT: float = float(os.getenv('MAX_SPREAD_PCT', '0.15'))  # حدّ السبريد % لقبول الإشارة (واقعية تنفيذ — تدقيق 2026-06-23؛ توزيع حيّ 0.0002–0.36%)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

config = Config()
