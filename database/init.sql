-- ==================== إنشاء الجداول ====================
-- الترتيب مهم: الجداول المُشار إليها تُنشأ أولاً

-- جدول العملات المراقبة
CREATE TABLE IF NOT EXISTS symbols (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    base_asset VARCHAR(10) NOT NULL,
    quote_asset VARCHAR(10) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    added_at TIMESTAMP DEFAULT NOW()
);

-- جدول البيانات التاريخية للشموع
CREATE TABLE IF NOT EXISTS candles (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open_time TIMESTAMP NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(30, 8) NOT NULL,
    close_time TIMESTAMP NOT NULL,
    UNIQUE(symbol, timeframe, open_time)
);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_time ON candles(symbol, timeframe, open_time DESC);

-- جدول الإشارات
CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    signal_time TIMESTAMP DEFAULT NOW(),
    market_condition VARCHAR(20) NOT NULL, -- صاعد/هابط/متقلب/جانبي
    entry_price DECIMAL(20, 8) NOT NULL,
    target_1 DECIMAL(20, 8) NOT NULL,
    target_2 DECIMAL(20, 8) NOT NULL,
    target_3 DECIMAL(20, 8) NOT NULL,
    stop_loss DECIMAL(20, 8) NOT NULL,
    score INTEGER NOT NULL, -- النقاط من 10
    score_details JSONB, -- تفاصيل كل مؤشر
    claude_approved BOOLEAN DEFAULT NULL,
    claude_comment TEXT,
    telegram_sent BOOLEAN DEFAULT false,
    is_paper_trade BOOLEAN DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol, signal_time DESC);

-- جدول الـ Whitelist (العملات المعتمدة شرعياً)
CREATE TABLE IF NOT EXISTS symbol_whitelist (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    approved_at TIMESTAMP DEFAULT NOW(),
    approved_by VARCHAR(50) DEFAULT 'user',
    notes TEXT
);

-- جدول طلبات الموافقة (يأتي بعد signals لأنه يشير إليه)
CREATE TABLE IF NOT EXISTS approval_requests (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    requested_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    responded_at TIMESTAMP,
    entry_price_at_request DECIMAL(20, 8) NOT NULL,
    current_price_at_approval DECIMAL(20, 8),
    price_change_pct DECIMAL(10, 4)
);
CREATE INDEX IF NOT EXISTS idx_approval_signal ON approval_requests(signal_id, status);

-- جدول نتائج الصفقات
CREATE TABLE IF NOT EXISTS trade_results (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    symbol VARCHAR(20) NOT NULL,
    entry_price DECIMAL(20, 8) NOT NULL,
    exit_price DECIMAL(20, 8),
    exit_time TIMESTAMP,
    result VARCHAR(10), -- WIN/LOSS/PARTIAL
    profit_percent DECIMAL(10, 4),
    target_reached INTEGER DEFAULT 0, -- 0,1,2,3
    stop_hit BOOLEAN DEFAULT false,
    duration_hours DECIMAL(10, 2),
    failure_reason TEXT -- سبب الفشل إن وجد
);

-- جدول أوزان المؤشرات (التعلم الذاتي)
CREATE TABLE IF NOT EXISTS indicator_weights (
    id SERIAL PRIMARY KEY,
    indicator_name VARCHAR(50) NOT NULL,
    market_condition VARCHAR(20) NOT NULL,
    weight DECIMAL(5, 4) DEFAULT 1.0,
    total_signals INTEGER DEFAULT 0,
    successful_signals INTEGER DEFAULT 0,
    success_rate DECIMAL(5, 4) DEFAULT 0.0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(indicator_name, market_condition)
);

-- جدول سجل التعلم
CREATE TABLE IF NOT EXISTS learning_log (
    id SERIAL PRIMARY KEY,
    training_date TIMESTAMP DEFAULT NOW(),
    model_version VARCHAR(20),
    total_trades_analyzed INTEGER,
    win_rate DECIMAL(5, 4),
    avg_profit DECIMAL(10, 4),
    changes_made JSONB,
    claude_analysis TEXT
);

-- جدول حماية رأس المال
CREATE TABLE IF NOT EXISTS risk_management (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE DEFAULT CURRENT_DATE,
    signals_sent INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    daily_pnl_percent DECIMAL(10, 4) DEFAULT 0,
    is_trading_paused BOOLEAN DEFAULT false,
    pause_reason TEXT
);

-- جدول مرشحي المسح (للتواصل بين Scanner والـ Analyzer)
CREATE TABLE IF NOT EXISTS scan_candidates (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    data JSONB NOT NULL,
    scan_time TIMESTAMP DEFAULT NOW(),
    analyzed BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_scan_candidates_analyzed ON scan_candidates(analyzed, scan_time DESC);

-- إدراج الأوزان الأولية للمؤشرات
INSERT INTO indicator_weights (indicator_name, market_condition, weight) VALUES
    ('rsi', 'bullish', 1.0),
    ('rsi', 'bearish', 1.0),
    ('rsi', 'sideways', 1.0),
    ('rsi', 'volatile', 1.0),
    ('macd', 'bullish', 1.0),
    ('macd', 'bearish', 1.0),
    ('macd', 'sideways', 1.0),
    ('macd', 'volatile', 1.0),
    ('ema_cross', 'bullish', 1.0),
    ('ema_cross', 'bearish', 1.0),
    ('ema_cross', 'sideways', 1.0),
    ('ema_cross', 'volatile', 1.0),
    ('bollinger', 'bullish', 1.0),
    ('bollinger', 'bearish', 1.0),
    ('bollinger', 'sideways', 1.0),
    ('bollinger', 'volatile', 1.0),
    ('volume', 'bullish', 1.0),
    ('volume', 'bearish', 1.0),
    ('volume', 'sideways', 1.0),
    ('volume', 'volatile', 1.0),
    ('stoch_rsi', 'bullish', 1.0),
    ('stoch_rsi', 'bearish', 1.0),
    ('stoch_rsi', 'sideways', 1.0),
    ('stoch_rsi', 'volatile', 1.0),
    ('obv', 'bullish', 1.0),
    ('obv', 'bearish', 1.0),
    ('obv', 'sideways', 1.0),
    ('obv', 'volatile', 1.0),
    ('order_book', 'bullish', 1.0),
    ('order_book', 'bearish', 1.0),
    ('order_book', 'sideways', 1.0),
    ('order_book', 'volatile', 1.0),
    ('btc_trend', 'bullish', 1.0),
    ('btc_trend', 'bearish', 1.0),
    ('btc_trend', 'sideways', 1.0),
    ('btc_trend', 'volatile', 1.0)
ON CONFLICT (indicator_name, market_condition) DO NOTHING;

-- إدراج سجل إدارة المخاطر اليومي
INSERT INTO risk_management (date) VALUES (CURRENT_DATE)
ON CONFLICT (date) DO NOTHING;

