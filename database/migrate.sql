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

-- 2026-05-14: إضافة عملات مدمرة للقائمة السوداء بناءً على بيانات 22 أبريل – 14 مايو
-- المعيار: 4+ صفقات + WR<20% + صافي خسارة حادة أو avg_loss >> avg_win
INSERT INTO symbol_blacklist (symbol, rejected_at, reason)
VALUES
  ('BTTCUSDT',  NOW(), 'بلاك ليست تلقائي: 45 صفقة، WR 4%، خسارة -48.39 USDT، 42 SL hit — أسوأ أداء كلي'),
  ('PARTIUSDT', NOW(), 'بلاك ليست تلقائي: 7 صفقات، WR 14%، خسارة -53.62 USDT، avg_loss -18% — مدمر لرأس المال'),
  ('FFUSDT',    NOW(), 'بلاك ليست تلقائي: 8 صفقات، WR 13%، خسارة -30.61 USDT، avg_loss -11%'),
  ('FIOUSDT',   NOW(), 'بلاك ليست تلقائي: 20 صفقة، WR 15%، خسارة -29.09 USDT، 12 SL hit'),
  ('DEGOUSDT',  NOW(), 'بلاك ليست تلقائي: 6 صفقات، WR 0%، خسارة -10.96 USDT'),
  ('NOTUSDT',   NOW(), 'بلاك ليست تلقائي: 4 صفقات، WR 0%، خسارة -8.15 USDT، 3 SL hit'),
  ('FUNUSDT',   NOW(), 'بلاك ليست تلقائي: 16 صفقة، WR 31% لكن avg_loss -11.53% >> avg_win +10.22%، صافي -37.83 USDT')
ON CONFLICT (symbol) DO NOTHING;
