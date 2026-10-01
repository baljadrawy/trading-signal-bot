# البنية والقرارات التقنية

## البنية الكاملة
```
trading-signal-bot/
├── scanner/          ← يمسح 160+ عملة USDT كل 5 دقائق
├── analyzer/         ← يحلل كل عملة على عدة timeframes (15m,4h,1d في وضع التعلّم الحي)
├── signal_engine/    ← يختار الإشارة (وضع التعلّم: محرّك بسيط + بوابة ماكرو)
├── claude_review/    ← قديم ومُعطَّل عن المسار النشط منذ CR-1 (2026-10-01)؛ يُزال في CR-2
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
→ Signal Engine → signals (+ outbox signal.ready) → Telegram
→ Trade Tracker → trade_results → Continuous Learner → learned_gates
```

### عقد الجاهزية (CR-1 — `shared/signal_readiness.py`)
- **المنتج:** `signal_engine.save_signal()` يُدرج الإشارة بـ`decision_source='policy_ready'` وينشر
  `signal.ready` `{signal_id, decision_source, strategy_version}` **في نفس المعاملة** (فشل أيٍّ منهما = لا إشارة ولا حدث).
  `claude_approved` يبقى `NULL` للإشارات الجديدة (لا موافقة Claude مزيّفة). لم يعد يُنشر `signal.created`.
- **Telegram:** يستهلك `signal.ready` (البوابة: `decision_source='policy_ready'`) ويُبقي استهلاك
  `signal.reviewed` القديم (البوابة: `claude_approved=true`) للأحداث العالقة وللتراجع. `telegram_sent` يمنع التسليم المزدوج،
  وبوابة الإيقاف/B3 (`can_deliver_candidate`) تسبق أي تسليم.
- **Trade Tracker:** شرط الجاهزية `(decision_source='policy_ready' OR claude_approved=true)` (صيغة آمنة من NULL)
  بدل `claude_approved=true`؛ باقي الشروط وحارس المخاطر كاملاً دون تغيير. الجاهزية **لا** تتجاوز المخاطر أبداً.
- **التراجع:** إعادة commits الـCR-1 (المنتج يعود لنشر `signal.created`) + تشغيل حاوية `claude_review` الموجودة.

## القرارات التقنية (لماذا)
| القرار | السبب |
|--------|-------|
| Docker Compose متعدد الحاويات | عزل كل خدمة، إعادة بناء جزئية سهلة |
| asyncpg بدل psycopg2 | أداء أفضل مع async/await |
| Claude Haiku للمراجعة | تاريخي — أُخرج من المسار النشط في CR-1 (الجاهزية بالسياسة الآلية `policy_ready`) |
| UNIQUE(symbol, timeframe) في analysis_results | يمنع تكرار التحليل لنفس الزوج والإطار |
| Paper Trading افتراضي | الأمان — لا تداول حقيقي |
| القائمة السوداء في Scanner | تمنع التحليل من المصدر لا الإرسال فقط |

## مراجعة البنية (تاريخي — 2026-04-14)
النتيجة آنذاك: **39/64 = 61%** (كانت 45% قبل التحسينات). أبرز التحسينات: Task Timeout في Analyzer، تنبيهات Telegram، حدّ MAX_OPEN_TRADES، Exponential Backoff، Health Checks لكل الحاويات.
