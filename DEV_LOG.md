# DEV_LOG.md — سجل التطوير

> أحدث التغييرات في الأعلى.

---

## 2026-06-23

### 🔍 تدقيق نزاهة كمّي — لا حافة (مؤكَّد على 2518 صفقة حيّة)
تدقيق على كامل DB: `PF_gross=0.735` (خاسر قبل الرسوم)، `net=-0.365$/صفقة`، AUC≈0.50 لكل مؤشر،
كل شهر/حالة/إطار خاسر، 93% من الصفقات في أبريل وحده. الادعاءان (بوابة stoch، وCOMBO)
دُحضا بتحقّق عدائي متعدّد الوكلاء (0 ادعاء نجا): COMBO = أثر 5-صفقات-مايو (n=7، يتعادل OOS)،
وstoch>0 «مُخفِّف خسارة لا حافة» (تعليق الكود القديم «stoch=0→21%» خاطئ؛ الواقع 36.7%).
الأدوات: `research/skill_application/` (workflow + نتائج)، و`research/walk_forward_audit.sh` (cron كل 12h، حُكم PASS/FAIL).

### 🕯️ إصلاح الشمعة الجارية غير المكتملة (look-ahead/repaint)
**الملف:** `analyzer/technical_analyzer.py` + `scanner/scanner_logic.py`
كانت المؤشرات تُحسب على الشمعة الحالية المكوّنة (`iloc[-1]`) → RSI/Stoch/ATR تُعيد الرسم وتخالف
الباكتيست (مصدر فجوة sim/live). الحل: جلب `CANDLES_TO_FETCH+1` وإسقاط الأخيرة (`klines[:-1]`).
مثبَت: انزياح RSI حتى 2.58 نقطة. (BTC trend في السكانر أُصلح بالمثل: 11 شمعة 4h، إسقاط الجارية.)

### 🚪 بوابة السبريد (واقعية تنفيذ)
**الملفات:** `signal_engine/signal_logic.py` + `shared/config.py` (`MAX_SPREAD_PCT=0.15`)
رفض المرشّح إذا `order_book.spread_pct > MAX_SPREAD_PCT` (الرقم محسوب أصلاً). فلتر جدوى تنفيذ لا حافة.

### 🗃️ Feature Store — 18 ميزة خام
**الملفات:** `technical_analyzer.py` (`_raw_features`) + `signal_logic.py` + `database/migrate_features_snapshot_2026_06_23.sql`
`analyze()` يُصدِر قيم المؤشرات الخام (rsi,stoch_k/d,macd_hist,bb_pos,bb_width,atr_pct,volume_ratio,
dist_ema20/50/200,obv_vs_ema + adx14,cci20,willr14,roc10,mfi14,cmf20) → تُخزَّن في `analysis_data`
وتُلتقط في عمود جديد `signals.features_snapshot` (JSONB). الهدف: بحث ML نزيه لاحقاً على ميزات خام.

### ⬆️ ترقية Python 3.12 + pandas 3 + pandas_ta (الأنلايزر)
**الملفات:** كل الـ`Dockerfile`s السبعة (3.11→3.12) + `analyzer/requirements.txt`
الأنلايزر وحده يستخدم pandas → رُقّي إلى `pandas==3.0.3` + `numpy==2.2.6` + `pandas_ta==0.4.71b0`
(يتطلب py≥3.12). المؤشرات الإضافية تُحسب بـpandas_ta (مع fallback إلى `ta`). تحقّق كامل لمسار
كود الأنلايزر على pandas 3 قبل النشر؛ كل الحاويات Python 3.12.13، صفر أخطاء.
**ملاحظة:** scanner/signal_engine كانا يثبّتان pandas بلا استخدام → رُفعا للتوحيد فقط.

---

## 2026-05-16

### 🚫 حظر إطار 4h كإطار رئيسي (`1ab9ccb`)
**الملف:** `signal_engine/signal_logic.py`
تحليل 275 صفقة post-rebuild: إطار 4h مسؤول عن 73% من الخسارة (−27.38 من −37.49).
signal_engine يرفض الإشارة إذا كان `top_tf == '4h'`. 4h يبقى صالحاً كإطار مؤكِّد لإشارة 1h.

### 🎯 المرحلة 1 — ستوب ديناميكي في trade_tracker (`e4816b0`)
**الملف:** `trade_tracker/main.py`
- بعد T1 → الستوب يرتفع لنقطة الدخول (break-even)
- بعد T2 → trailing stop `TRAIL_STOP_PCT=2.5%` تحت القمة، أرضيته T1
- عمود جديد `active_trades.peak_price`
- المبرر: كل الخسارة من ضرب SL؛ T3 لم يتحقق 0/275؛ صفقة تحقق T1 ثم ترتد كانت تخسر −2.89%.

### 🔧 المرحلة 2 — تشديد الدخول
`optimizer_settings.min_score_to_signal` رُفع 3.0 → 4.0 (WR للـ score≥4 = 42% مقابل 33%).

### 🔧 المرحلة 3 — إصلاح الحافة
`indicator_weights`: وزن `rsi_divergence` في `sideways` كان 0 رغم أنه المؤشر الوحيد بحافة
(WR 60%، expectancy +3.67%) — رُفع إلى 2.0.

### ⬆️ رفع aiohttp 3.13.5 + تجاهل .claude/ (`8eabdf6`)

### 🤖 أتمتة
الكرون التلقائي: كل 6 ساعات، تقارير تيليغرام تلقائية، صلاحية كاملة (عدا التداول الحقيقي)،
حاجز صارم signal-bot فقط. أُضيف بناء **باكتيستر** تدريجي ضمن مهام الإيجنت.

---

## 2026-04-27

### 🎯 6 تعديلات استراتيجية بناءً على بيانات 168 صفقة

**السياق:** بعد 5 أيام من rebuild (2026-04-22)، 168 صفقة مغلقة، WR=35.7%، Net=-$21.

**التحليل أظهر:**
- bullish regime يفشل تماماً (18 صفقة، 100% فشل، WR 27.8%)
- T3 = 3R لم يتحقق ولا مرة (0/168) → بعيد جداً
- 53% من الصفقات خرجت بدون لمس أي هدف → إشارات خاملة كثيرة
- Claude approved 168/168 → غير فعّال كفلتر
- R:R المتحقق 1.38 < 1.5 المصمم → يُفقد ربحية هامشية

**التعديلات:**

1. **`.env` + `shared/config.py`**: `MIN_VOLUME_USDT` رُفع من 1M → **10M**
   - أثر فوري: من 134 إلى 22 عملة مؤهلة (84% تخفيض)
   - السبب: تقليل ضوضاء العملات منخفضة السيولة المتلاعب بها

2. **`signal_engine/signal_logic.py`**: تخطي bullish regime
   - رفض إذا أغلب الـ timeframes = bullish
   - السبب: استراتيجية mean-reverting لا تجد dips للشراء في صعود قوي

3. **`signal_engine/signal_logic.py`**: BTC Crash Pause
   - `_is_btc_crashing()` يقرأ تحليل BTC 4h من analysis_results
   - لو market_condition='bearish' → إيقاف كل الإشارات
   - السبب: في انهيار BTC، الـ alts تتبعه، mean-reverting يفشل

4. **`analyzer/technical_analyzer.py`**: T3 من 3R → **2.2R**
   - السبب: 0/168 لمست 3R، تقليل الهدف يجعله قابلاً للتحقق

5. **`analyzer/technical_analyzer.py`**: إضافة **RSI Bullish Divergence**
   - دالة `_detect_rsi_divergence(lookback=14)`
   - bullish divergence = price LL + RSI HL
   - مكون scoring جديد بوزن 1.0 (افتراضي)

6. **`analyzer/technical_analyzer.py`**: إضافة **Fibonacci Retracement Proximity**
   - دالة `_calculate_fibonacci_score(lookback=50)`
   - يحسب القرب من 38.2%/50%/61.8% من swing high → low
   - 1% قرب = 1.0 نقاط، 2% = 0.5 نقاط
   - مكون scoring جديد بوزن 1.0 (افتراضي)

**قاعدة البيانات:**
- 8 صفوف جديدة في `indicator_weights` للـ rsi_divergence و fibonacci في كل regime

**ملاحظة مهمة:**
هذه التعديلات قد تكسر التوازن المُثبَت من 2158 صفقة باكتست سابقة.
سنراقب 100+ صفقة جديدة ونقارن قبل/بعد قبل قبول التعديلات نهائياً.

---

## 2026-04-14

### 🔒 تحسينات الموثوقية (من مراجعة البنية)

**1. Task Timeout في Analyzer**
- أضيف `asyncio.wait_for(task, timeout=60)` لكل عملة
- عملة واحدة بطيئة لا تعطّل تحليل باقي الـ 49
- timeout warning يُسجَّل في اللوق عند التجاوز

**2. تنبيهات Telegram للأخطاء الحرجة**
- ملف جديد `shared/alerts.py` — دالة `send_alert(msg, level, component)`
- كل container عنده عداد أخطاء متتالية
- عند 3 أخطاء متتالية → تنبيه 🚨 critical يُرسل للتيليجرام تلقائياً
- مستويات: `info` ℹ️ | `warning` ⚠️ | `critical` 🚨

**3. حد MAX_OPEN_TRADES**
- إضافة `MAX_OPEN_TRADES=10` في config (0 = بلا حد)
- trade_tracker يتحقق قبل تسجيل صفقة جديدة
- يمنع فتح عشرات الصفقات في نفس الوقت

**4. Exponential Backoff**
- كل container يطبّق: `wait = min(60 * consecutive_errors, 300)`
- scanner: 60s → 120s → 180s... max 5 دقائق
- analyzer/claude_review: 30s → 60s → 90s... max 5 دقائق
- يمنع قصف Binance API بطلبات عند الأعطال

**5. Health Checks لجميع الـ containers**
- أضيف healthcheck لـ scanner, analyzer, signal_engine, claude_review, trade_tracker, telegram
- الفحص: `pgrep -f 'python.*main.py'` كل 60 ثانية
- Docker يعيد التشغيل تلقائياً عند 3 فشل متتالي

---

## 2026-04-13

### ✨ نظام القائمة البيضاء والسوداء الكامل
- إضافة جدول `symbol_blacklist` في قاعدة البيانات
- **Scanner** يستثني العملات السوداء قبل المسح من المصدر
- عند رفض عملة → تُضاف تلقائياً للقائمة السوداء
- عند الموافقة → تُضاف للقائمة البيضاء وتُرسل مباشرة
- `/remove_whitelist SYMBOL` → ينقل العملة من البيضاء للسوداء مباشرة (لا سؤال)
- `/remove_blacklist SYMBOL` → يعيد العملة للتحليل الطبيعي
- **trade_tracker** يغلق تلقائياً صفقات العملات في القائمة السوداء

### 🐛 إصلاح signal_engine يكرر العملات المرفوضة
- SQL query يستثني `symbol_blacklist` و `active_trades (open)` من المصدر
- طبقة حماية ثانية في `find_best_signal()` في `signal_logic.py`

### 🐛 إصلاح جميع Dockerfiles
- كانت تنسخ `requirements.txt` فقط ولا تنسخ الكود
- أضيف `COPY shared/ ./shared/` و `COPY service/ ./` لكل Dockerfile

### 🐛 إصلاح `datetime` غير معرّف في trade_tracker
- الاستيراد كان داخل دالة `evaluate_trade` فقط
- نُقل لأعلى الملف: `from datetime import datetime, timezone`

---

## 2026-04-09

### ✨ لوحة التحكم في Telegram
- أمر `/performance` — أداء Claude ونسبة القبول/الرفض
- أمر `/signals` — آخر 5 إشارات مع حالتها
- أمر `/daily` — ملخص يومي كامل
- أمر `/trades` — الصفقات النشطة والمغلقة مع النسب
- رسالة الإشارة تعرض نسبة كل هدف ونسبة وقف الخسارة ونسبة R/R

### ✨ Trade Tracker
- container جديد يراقب الصفقات كل 5 دقائق
- يسجل WIN/LOSS/EXPIRED بناءً على الأهداف ووقف الخسارة
- TRADE_EXPIRY_HOURS = 48 (إغلاق تلقائي بعد 48 ساعة)
- إغلاق تلقائي للصفقات المرفوضة من المستخدم

### 🐛 إصلاح تكرار الصفقات في `/trades`
- استخدام `DISTINCT ON (symbol)` في query الـ active_trades
- استثناء الإشارات المرفوضة من تسجيل الصفقات

---

## 2026-04-08

### ✨ دعم Multi-Timeframe
- التحليل على 4 timeframes: 15m, 1h, 4h, 1d
- يشترط تأكيد 2+ timeframes لإصدار إشارة
- إضافة `TIMEFRAMES` و `MIN_TIMEFRAME_CONFIRMATIONS` لـ config
- إضافة عمود `timeframe` لجدول `analysis_results`
- UNIQUE(symbol, timeframe) يمنع تكرار التحليل

### 🐛 إصلاح signal_engine كان يتوقف
- `MAX_SIGNALS_PER_DAY=5` في `.env` كان يوقف البوت
- الحل: `MAX_SIGNALS_PER_DAY=0` للتدريب + الكود يتحقق `> 0`
- `MIN_SCORE_TO_SIGNAL` خُفِّض من 7 إلى 5

### 🐛 إصلاح target_1 أقل من entry_price
- `_calculate_levels` في `technical_analyzer.py` كانت تحسب أهدافاً خاطئة
- الحل: التحقق من `stop < entry` و `targets > entry` بعد الحساب

### 🐛 إصلاح mutable default list في dataclass
- `TIMEFRAMES: list = [...]` يسبب خطأ Python
- الحل: `field(default_factory=lambda: ...)`

### ✨ فلتر الأحرف غير اللاتينية في Scanner
- إضافة `.isascii()` لاستبعاد العملات ذات الأحرف الصينية

### ✨ Claude Review محسّن
- الـ prompt يشرح أن 4-6/10 جيد في هذا النظام
- يوافق إذا R/R >= 1.0 وتأكيدات >= 2
- إصلاح query: يتحقق من `claude_approved IS NULL OR false`

---

## 2026-04-05

### 🚀 إطلاق المشروع
- إعداد Docker Compose متعدد الـ containers
- Scanner + Analyzer + Signal Engine + Claude Review + Telegram
- نظام إدارة المخاطر (risk_management)
- نظام الموافقة اليدوية (approval_requests + symbol_whitelist)
- إعداد على Hetzner VPS
