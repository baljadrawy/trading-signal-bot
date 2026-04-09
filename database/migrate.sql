-- Migration: إنشاء الجداول الناقصة إن لم تكن موجودة

-- جدول scan_candidates (للـ Scanner والـ Analyzer)
CREATE TABLE IF NOT EXISTS scan_candidates (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    data JSONB NOT NULL,
    scan_time TIMESTAMP DEFAULT NOW(),
    analyzed BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_scan_candidates_analyzed ON scan_candidates(analyzed, scan_time DESC);

-- جدول approval_requests (للـ Telegram)
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

-- جدول risk_management (للـ Scanner)
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

-- إدراج سجل اليوم في risk_management
INSERT INTO risk_management (date) VALUES (CURRENT_DATE)
ON CONFLICT (date) DO NOTHING;

-- جدول القائمة السوداء (العملات المرفوضة نهائياً)
CREATE TABLE IF NOT EXISTS symbol_blacklist (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    rejected_at TIMESTAMP DEFAULT NOW(),
    reason TEXT DEFAULT 'رفض يدوي من Telegram'
);
CREATE INDEX IF NOT EXISTS idx_blacklist_symbol ON symbol_blacklist(symbol);

-- التحقق من وجود جميع الجداول
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
