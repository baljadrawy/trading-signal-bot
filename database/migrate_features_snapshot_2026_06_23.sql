-- Feature store (تدقيق 2026-06-23): عمود JSONB يلتقط قيم المؤشرات الخام + سياق دفتر الأوامر
-- وقت توليد الإشارة، مرتبطاً بالنتيجة عبر trade_results.signal_id. يُمكّن بحث ML نزيهاً على
-- ميزات خام بدل score_details المبوّبة (التي أعطت AUC=0.50). آمن: عمود قابل للـ NULL، إضافة فورية.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS features_snapshot JSONB;
COMMENT ON COLUMN signals.features_snapshot IS
  'لقطة ميزات خام وقت الإشارة: rsi,stoch_k/d,macd_hist,bb_pos,bb_width,atr_pct,volume_ratio,dist_ema20/50/200,obv_vs_ema,spread_pct,bid_ask_ratio,... (feature store 2026-06-23)';
