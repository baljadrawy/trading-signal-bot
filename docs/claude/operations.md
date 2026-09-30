# التشغيل والإعدادات

## أوامر Docker
> ⛔ **السياسة الملزمة:** [docs/ops/COMPOSE_OPERATIONS.md](../ops/COMPOSE_OPERATIONS.md). هنا أوامر القراءة فقط (Class A).
> إعادة التشغيل/الإنشاء/النشر/التراجع لخدمة واحدة = Class B (موافقة المالك + إجراء مُبوَّب).
> البناء في نسخة الإنتاج، والإيقاف أو التشغيل الشامل للمشروع، وحذف الأحجام = Class C (ممنوع).

```bash
# الحالة واللوقات (قراءة فقط)
ops/compose-safe status
ops/compose-safe logs <service> --tail 30
docker compose -p trading-signal-bot -f docker-compose.yml ps
docker compose -p trading-signal-bot -f docker-compose.yml logs <service> --tail=30
```

## النشر الثابت والمشدّد

- الشيفرة مضمّنة داخل الصور ولا توجد bind mounts للشيفرة في الإنتاج.
- الصور تعمل كمستخدم غير root، بجذر read-only، مع `cap_drop: ALL` و`no-new-privileges`.
- مسارات الكتابة محصورة في volumes للسجلات/النماذج/الأدلة و`tmpfs` في `/tmp`.
- كل صورة تحمل `org.opencontainers.image.revision` ونسخة التطبيق.

أي تعديل محلي للشيفرة لا يصل إلى الحاويات إلا بعد إعادة البناء وإعادة الإنشاء. البناء يتم في نسخة معزولة
بوسم صورة فريد (لا في `/home/tradmin/trading-signal-bot`)، والنشر خدمةً واحدةً بتفويض المالك حسب Class B في
[COMPOSE_OPERATIONS.md](../ops/COMPOSE_OPERATIONS.md). telegram و trade_tracker و scanner على صور مثبّتة
(`deploy/aiohttp-3.14.3/IMAGES.md`) لا تُعاد بناؤها. الـmigrations عملية كتابة على DB وتحتاج موافقة المالك.

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

## مراجعة أداء الاستراتيجية

> المتعلّم (`continuous_learner`) متوقف عمداً. الـprofile `learner` يمنعه فقط من التشغيل الافتراضي، وليس حدّ تفويض: استهدافه مباشرةً ممكن تقنياً وممنوع دون تفويض منفصل من المالك. لا تشغّله لتشغيل هذا التقرير.
> تشغيل التقرير داخل حاوية إنتاج يحتاج موافقة المالك (Class B في [COMPOSE_OPERATIONS.md](../ops/COMPOSE_OPERATIONS.md)).

يحسب التقرير gross/net expectancy وProfit Factor وdrawdown، والتقسيم حسب النوع والإطار
والماكرو والزوج، ثم expanding walk-forward يقارن البوابات المتعلمة مع baseline ثابت.
التقرير للقراءة فقط ولا يعدّل البوابات.
