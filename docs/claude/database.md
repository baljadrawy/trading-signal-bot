# قاعدة البيانات

**الاتصال:** `postgresql://trading_signal_bot:PASSWORD@postgres:5432/trading_signals`

> ⚠️ الدور الفعلي **`trading_signal_bot`** (وليس `trading_bot`). postgres نمط مشترك
> (شبكة `shared_db_net`، حاوية اسمها `postgres`، صورة postgres:16-alpine).

**وصول مباشر للفحص:**
```bash
docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "..."
```

## الجداول الرئيسية
| الجدول | الوصف |
|--------|-------|
| `scan_candidates` | نتائج Scanner المؤقتة |
| `analysis_results` | نتائج التحليل لكل (symbol, timeframe) |
| `signals` | الإشارات المولّدة (+ `trade_type`, `macro_snapshot` لوضع التعلّم الحي) |
| `approval_requests` | طلبات موافقة المستخدم |
| `symbol_whitelist` / `symbol_blacklist` | القوائم البيضاء/السوداء |
| `active_trades` | الصفقات المفتوحة قيد المتابعة |
| `trade_results` | نتائج الصفقات المغلقة (WIN/LOSS) |
| `risk_management` | عداد يومي للإشارات والأرباح/الخسائر |
| `optimizer_settings` | عتبات حيّة (min_score_to_signal، min_timeframe_confirmations) تغلب `.env` |
| `indicator_weights` | أوزان المؤشرات حسب market_condition |
| `macro_history` | لقطة USDT.D/BTC.D + اتجاه BTC/ETH اليومية (وضع التعلّم الحي) |
| `learned_gates` | أوزان (نوع × usdtd_state × إطار) من المتعلّم المستمر |

## أوامر psql متكررة
```sql
-- الصفقات المفتوحة
SELECT symbol, status, entry_price, highest_target_hit, opened_at
FROM active_trades WHERE status='open';

-- القوائم
SELECT symbol, approved_at FROM symbol_whitelist;
SELECT symbol, rejected_at, reason FROM symbol_blacklist;

-- إعادة تعيين عداد الإشارات اليومي
UPDATE risk_management SET signals_sent=0 WHERE date=CURRENT_DATE;

-- إشارات التعلّم الحي المجموعة
SELECT trade_type, timeframe, COUNT(*) FROM signals
WHERE trade_type IS NOT NULL GROUP BY 1,2;

-- تقدّم الإحماء (صفقات موسومة مغلقة من أصل 100)
SELECT COUNT(*) FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
WHERE s.trade_type IS NOT NULL;
```

> العتبات الحيّة في `optimizer_settings` و`indicator_weights` **تغلب `.env`** — راجع DB لا `.env` لمعرفة القيم الفعلية.
