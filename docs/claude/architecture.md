# البنية والقرارات التقنية

## البنية الكاملة
```
trading-signal-bot/
├── scanner/          ← يمسح 160+ عملة USDT كل 5 دقائق
├── analyzer/         ← يحلل كل عملة على عدة timeframes (15m,4h,1d في وضع التعلّم الحي)
├── signal_engine/    ← يختار الإشارة (وضع التعلّم: محرّك بسيط + بوابة ماكرو)
├── claude_review/    ← مراجعة الإشارة (يوافق تلقائياً في وضع التعلّم الحي)
├── telegram/         ← يرسل الإشارات + يدير القوائم + أوامر التحكم
├── trade_tracker/    ← يتابع الصفقات المفتوحة كل 5 دقائق
├── continuous_learner/ ← خدمة كرون: تعلّم مستمر + ملخّص يومي (وضع التعلّم الحي)
├── shared/
│   ├── config.py     ← الإعدادات المشتركة
│   ├── database.py   ← Connection Pool لـ PostgreSQL (asyncpg)
│   ├── logger.py     ← Logger موحّد (يتراجع لـ console خارج Docker)
│   ├── alerts.py     ← تنبيهات Telegram للأخطاء الحرجة
│   └── macro_context.py ← سياق BTC/ETH/USDT.D + بوابة خفيفة (وضع التعلّم الحي)
├── database/         ← init.sql + migrations
├── research/         ← أدوات بحث + continuous_learner.py
├── docs/             ← superpowers/ (specs+plans) + claude/ (هذه التوثيقات)
└── docker-compose.yml
```

## تدفّق البيانات
```
Scanner → scan_candidates → Analyzer → analysis_results
→ Signal Engine → signals → Claude Review → Telegram
→ Trade Tracker → trade_results → Continuous Learner → learned_gates
```

## القرارات التقنية (لماذا)
| القرار | السبب |
|--------|-------|
| Docker Compose متعدد الحاويات | عزل كل خدمة، إعادة بناء جزئية سهلة |
| asyncpg بدل psycopg2 | أداء أفضل مع async/await |
| Claude Haiku للمراجعة | سريع وأقل تكلفة (مُتجاوَز في وضع التعلّم الحي) |
| UNIQUE(symbol, timeframe) في analysis_results | يمنع تكرار التحليل لنفس الزوج والإطار |
| Paper Trading افتراضي | الأمان — لا تداول حقيقي |
| القائمة السوداء في Scanner | تمنع التحليل من المصدر لا الإرسال فقط |

## مراجعة البنية (تاريخي — 2026-04-14)
النتيجة آنذاك: **39/64 = 61%** (كانت 45% قبل التحسينات). أبرز التحسينات: Task Timeout في Analyzer، تنبيهات Telegram، حدّ MAX_OPEN_TRADES، Exponential Backoff، Health Checks لكل الحاويات.
