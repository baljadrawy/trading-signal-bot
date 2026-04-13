# DEV_LOG.md — سجل التطوير

> أحدث التغييرات في الأعلى.

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
