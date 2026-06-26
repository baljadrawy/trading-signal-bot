# التشغيل والإعدادات

## أوامر Docker
```bash
# بناء وتشغيل كامل (--no-cache ضروري بعد تغيير الكود)
docker compose down
docker compose build --no-cache
docker compose up -d

# إعادة بناء حاوية واحدة
docker compose build --no-cache signal_engine && docker compose up -d signal_engine

# اللوقات والحالة
docker compose logs <service> --tail=30 -f
docker compose ps
```

## رفع للـ GitHub
```bash
git add <paths>      # تجنّب git add -A (مخرجات بحث ضخمة غير متعقّبة)
git commit -m "..."
git push origin main
```

## متغيّرات `.env` المهمة
```env
PAPER_TRADING=true                  # تداول ورقي — لا تغيّره
LIVE_LEARNING_MODE=true             # وضع التعلّم الحي مُفعّل (راجع live-learning.md)
TIMEFRAMES=15m,4h,1d                # أطر وضع التعلّم الحي
MAX_SIGNALS_PER_DAY=0               # 0 = بلا حد. القيمة 5 توقف البوت!
MIN_SCORE_TO_SIGNAL=3.0             # ⚠️ القيمة الفعلية في optimizer_settings (DB يغلب .env)
TRADE_AMOUNT_USDT=50
MAX_OPEN_TRADES=10                  # 0 = بلا حد
TRADE_EXPIRY_HOURS=48               # إغلاق تلقائي بعد 48 ساعة
LEARN_CRON_HOURS=24                 # وتيرة المتعلّم + الملخّص اليومي
```
> معاملات وضع التعلّم الحي الإضافية (MOM_*, REV_RSI, USDTD_*, WARMUP_N, ROLL_N, MIN_CELL_N...) موثّقة في [live-learning.md](live-learning.md).

## أوامر Telegram
| الأمر | الوظيفة |
|-------|---------|
| `/status` | حالة النظام |
| `/whitelist` `/blacklist` | عرض القوائم |
| `/remove_whitelist SYMBOL` | نقل للسوداء |
| `/remove_blacklist SYMBOL` | إزالة من السوداء |
| `/trades` | الصفقات النشطة والمغلقة |
| `/performance` `/signals` `/daily` | الأداء/الإشارات/ملخص اليوم |
| `/pause` `/resume` | إيقاف/استئناف |

**القوائم:** الموافقة على عملة → بيضاء (إشاراتها مباشرة)؛ الرفض → سوداء (لا تُحلَّل من Scanner)؛ `/remove_whitelist` ينقل للسوداء؛ trade_tracker يغلق تلقائياً صفقات العملات في السوداء.

## نظام التنبيهات (shared/alerts.py)
`send_alert(message, level, component)` — مستويات `info|warning|critical`. كل حاوية فيها عدّاد `consecutive_errors`؛ عند 3 أخطاء متتالية → تنبيه critical؛ backoff = `min(60×errors, 300)` ثانية.
