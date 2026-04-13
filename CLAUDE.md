# CLAUDE.md — ذاكرة المشروع

> اقرأ هذا الملف أولاً قبل أي تعديل. يحتوي على كل القرارات التقنية والقواعد والمشاكل المحلولة.

---

## 1. وصف المشروع

بوت تداول تلقائي على Binance يعمل بـ **Paper Trading** (تداول افتراضي للتدريب).  
يمسح العملات → يحللها → يراجعها Claude → يرسل إشارات عبر Telegram → يتتبع النتائج.

**المستخدم**: Basim | **السيرفر**: Hetzner VPS (amd64) | **بيئة التشغيل**: Docker Compose

---

## 2. البنية الكاملة

```
trading-signal-bot/
├── scanner/          ← يمسح 160+ عملة USDT كل 5 دقائق
├── analyzer/         ← يحلل كل عملة على 4 timeframes (15m,1h,4h,1d)
├── signal_engine/    ← يختار أفضل إشارة (يشترط تأكيد 2+ timeframes)
├── claude_review/    ← Claude Haiku يراجع الإشارة ويوافق/يرفض
├── telegram/         ← يرسل الإشارات + يدير القوائم + أوامر التحكم
├── trade_tracker/    ← يتابع الصفقات المفتوحة كل 5 دقائق
├── shared/
│   ├── config.py     ← الإعدادات المشتركة
│   ├── database.py   ← Connection Pool لـ PostgreSQL
│   ├── logger.py     ← Logger موحد
│   └── alerts.py     ← تنبيهات Telegram للأخطاء الحرجة ← جديد
├── database/         ← init.sql + migrate.sql
├── docker-compose.yml
├── .env              ← المتغيرات السرية (لا تُرفع لـ GitHub)
└── DEV_LOG.md        ← سجل التطوير
```

### تدفق البيانات
```
Scanner → scan_candidates → Analyzer → analysis_results
→ Signal Engine → signals → Claude Review → Telegram
→ (موافقة/رفض) → Whitelist/Blacklist → Trade Tracker → trade_results
```

---

## 3. قاعدة البيانات

**الاتصال**: `postgresql://trading_bot:PASSWORD@postgres:5432/trading_signals`

### الجداول الرئيسية
| الجدول | الوصف |
|--------|-------|
| `scan_candidates` | نتائج Scanner المؤقتة |
| `analysis_results` | نتائج التحليل لكل (symbol, timeframe) |
| `signals` | الإشارات المولّدة |
| `approval_requests` | طلبات موافقة المستخدم (pending/approved/rejected) |
| `symbol_whitelist` | القائمة البيضاء — تُرسل مباشرة بدون سؤال |
| `symbol_blacklist` | القائمة السوداء — لا تُحلَّل ولا تُرسل أبداً |
| `active_trades` | الصفقات المفتوحة قيد المتابعة |
| `trade_results` | نتائج الصفقات المغلقة (WIN/LOSS) |
| `risk_management` | عداد يومي للإشارات والأرباح والخسائر |

### أوامر DB المتكررة
```bash
# الدخول لـ psql
docker compose exec postgres psql -U trading_bot -d trading_signals

# عرض الصفقات النشطة
SELECT symbol, status, entry_price, highest_target_hit, opened_at FROM active_trades WHERE status='open';

# عرض القائمة البيضاء
SELECT symbol, approved_at FROM symbol_whitelist;

# عرض القائمة السوداء
SELECT symbol, rejected_at, reason FROM symbol_blacklist;

# إعادة تعيين عداد الإشارات اليومية
UPDATE risk_management SET signals_sent=0 WHERE date=CURRENT_DATE;
```

---

## 4. إعدادات `.env` المهمة

```env
PAPER_TRADING=true                  # تداول ورقي (لا تغير لـ false إلا بعد اختبار كافٍ)
MAX_SIGNALS_PER_DAY=0               # 0 = بلا حد (للتدريب)
MIN_SCORE_TO_SIGNAL=5               # الحد الأدنى للنقاط (5-10)
TIMEFRAMES=15m,1h,4h,1d             # الـ timeframes للتحليل
MIN_TIMEFRAME_CONFIRMATIONS=2       # يشترط موافقة 2+ timeframes
TRADE_AMOUNT_USDT=50                # حجم الصفقة الافتراضية
APPROVAL_TIMEOUT_MINUTES=30         # وقت انتهاء طلب الموافقة
MAX_OPEN_TRADES=10                  # حد الصفقات المفتوحة في نفس الوقت (0 = بلا حد)
```

---

## 5. أوامر التشغيل

```bash
# بناء وتشغيل كامل من الصفر (مع --no-cache ضروري عند تغيير الكود)
docker compose down
docker compose build --no-cache
docker compose up -d

# إعادة بناء container واحد فقط
docker compose stop telegram
docker compose build --no-cache telegram
docker compose up -d telegram

# مشاهدة اللوقات
docker compose logs scanner --tail=30 -f
docker compose logs analyzer --tail=30 -f
docker compose logs signal_engine --tail=30
docker compose logs telegram --tail=30
docker compose logs trade_tracker --tail=30

# حالة كل الـ containers
docker compose ps

# رفع للـ GitHub
git add -A
git commit -m "وصف التغيير"
git push origin main
```

---

## 6. أوامر Telegram

| الأمر | الوظيفة |
|-------|---------|
| `/status` | حالة النظام |
| `/whitelist` | عرض القائمة البيضاء |
| `/blacklist` | عرض القائمة السوداء |
| `/remove_whitelist SYMBOL` | نقل عملة من البيضاء للسوداء |
| `/remove_blacklist SYMBOL` | إزالة عملة من السوداء |
| `/trades` | الصفقات النشطة والمغلقة |
| `/performance` | أداء Claude ونسب القبول |
| `/signals` | آخر 5 إشارات |
| `/daily` | ملخص اليوم |
| `/pause` / `/resume` | إيقاف/استئناف البوت |

---

## 7. القرارات التقنية (لماذا)

| القرار | السبب |
|--------|-------|
| Docker Compose متعدد الـ containers | عزل كل خدمة، سهولة إعادة البناء الجزئي |
| asyncpg بدلاً من psycopg2 | أداء أفضل مع async/await |
| Claude Haiku للمراجعة | سريع وأقل تكلفة لمراجعة إشارات متكررة |
| UNIQUE(symbol, timeframe) في analysis_results | يمنع تكرار التحليل لنفس الزوج والـ timeframe |
| Paper Trading افتراضي | الأمان — لا تداول حقيقي إلا بعد اختبار كافٍ |
| القائمة السوداء في Scanner (لا في signal_engine فقط) | تمنع التحليل من المصدر وليس فقط الإرسال |

---

## 8. نظام التنبيهات (shared/alerts.py)

دالة `send_alert(message, level, component)` تُرسل تنبيهاً لـ Telegram:
```python
from shared.alerts import send_alert

# مستويات: 'info' | 'warning' | 'critical'
await send_alert("Scanner فشل 3 مرات", level='critical', component='Scanner')
```
- كل container عنده عداد `consecutive_errors`
- عند 3 أخطاء متتالية → تنبيه critical تلقائي
- الـ backoff: `min(60 * consecutive_errors, 300)` ثانية (max 5 دقائق)

## 9. المشاكل الشائعة وحلولها

### الـ Dockerfile لا ينسخ الكود
**المشكلة**: الـ Dockerfiles كانت تنسخ `requirements.txt` فقط، والكود يأتي من volume mount — لكن بعض الـ containers ليس لها volume.  
**الحل**: كل Dockerfile يجب أن يحتوي على:
```dockerfile
COPY shared/ ./shared/
COPY service_name/ ./
```
**القاعدة**: دائماً استخدم `--no-cache` عند بناء image جديد بعد تعديل الكود.

### signal_engine يكرر العملات المرفوضة
**المشكلة**: signal_engine يولّد إشارات لعملات رفضها المستخدم.  
**الحل**: SQL query في `signal_engine/main.py` يستثني `symbol_blacklist` و `active_trades`.

### `datetime` غير معرّف في trade_tracker
**المشكلة**: الاستيراد كان داخل دالة فقط، فـ `close_trade` لا ترى `datetime`.  
**الحل**: `from datetime import datetime, timezone` في أعلى الملف.

### MAX_SIGNALS_PER_DAY يوقف البوت
**المشكلة**: القيمة 5 في `.env` تسبب توقف البوت بعد 5 إشارات.  
**الحل**: `MAX_SIGNALS_PER_DAY=0` للتدريب. الكود يتحقق: `if config.MAX_SIGNALS_PER_DAY > 0`.

### target_1 أقل من entry_price
**المشكلة**: `_calculate_levels` في `technical_analyzer.py` كانت تحسب أهدافاً أقل من سعر الدخول.  
**الحل**: التحقق من `stop_loss < entry` و `targets > entry` بعد الحساب.

### تكرار الصفقات في `/trades`
**المشكلة**: نفس العملة تظهر عدة مرات.  
**الحل**: `DISTINCT ON (symbol)` في query الـ active_trades.

### خطأ `mutable default list` في dataclass
**المشكلة**: `TIMEFRAMES: list = ['15m','1h','4h','1d']` يسبب خطأ في Python dataclass.  
**الحل**: `field(default_factory=lambda: os.getenv('TIMEFRAMES','15m,1h,4h,1d').split(','))`.

---

## 10. نقاط مهمة

- **القائمة البيضاء**: الموافقة على عملة → تُضاف تلقائياً، إشاراتها القادمة مباشرة بدون سؤال
- **القائمة السوداء**: الرفض → تُضاف تلقائياً، لا تُحلَّل من Scanner أصلاً
- **إزالة من البيضاء** `/remove_whitelist` → تنتقل للسوداء مباشرة (لا تعود للسؤال)
- **إزالة من السوداء** `/remove_blacklist` → تعود للتحليل الطبيعي
- **trade_tracker** يغلق تلقائياً صفقات العملات في القائمة السوداء
- **TRADE_EXPIRY_HOURS = 48** — الصفقات تُغلق تلقائياً بعد 48 ساعة

---

## 11. المراجع

- [DEV_LOG.md](DEV_LOG.md) — سجل كل التحديثات مع التواريخ
- [SETUP_GUIDE.md](SETUP_GUIDE.md) — إعداد المشروع من الصفر
- **GitHub**: https://github.com/baljadrawy/trading-signal-bot
