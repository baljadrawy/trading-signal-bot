"""
الإعدادات المشتركة بين جميع الـ Containers
"""
import os
from dataclasses import dataclass

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
    MIN_SCORE_TO_SIGNAL: int = int(os.getenv('MIN_SCORE_TO_SIGNAL', '7'))
    SCAN_INTERVAL_SECONDS: int = int(os.getenv('SCAN_INTERVAL_SECONDS', '300'))
    TIMEFRAME: str = os.getenv('TIMEFRAME', '4h')

    # حجم الصفقة
    TRADE_AMOUNT_USDT: float = float(os.getenv('TRADE_AMOUNT_USDT', '50'))

    # نظام الموافقة والـ Whitelist
    APPROVAL_TIMEOUT_MINUTES: int = int(os.getenv('APPROVAL_TIMEOUT_MINUTES', '30'))
    APPROVAL_MAX_PRICE_CHANGE_PCT: float = float(os.getenv('APPROVAL_MAX_PRICE_CHANGE_PCT', '0.5'))

    # حماية رأس المال
    MAX_DAILY_LOSS_PERCENT: float = float(os.getenv('MAX_DAILY_LOSS_PERCENT', '3'))
    STOP_ON_CONSECUTIVE_LOSSES: int = int(os.getenv('STOP_ON_CONSECUTIVE_LOSSES', '3'))
    
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
    MIN_VOLUME_USDT: float = 1_000_000  # حجم تداول يومي أدنى 1M USDT
    MIN_PRICE_CHANGE_PERCENT: float = 2.0  # حركة سعرية أدنى 2%
    CANDLES_TO_FETCH: int = 200  # عدد الشموع للتحليل
    
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

config = Config()
