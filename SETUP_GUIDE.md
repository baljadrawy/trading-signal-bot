# 🤖 Trading Signal Bot - دليل الإعداد الكامل

## 📋 المتطلبات الأساسية

| المكوّن | التفاصيل |
|---------|----------|
| الجهاز | Raspberry Pi 4 - 8GB RAM |
| النظام | Ubuntu 24.04 LTS (aarch64) |
| Docker | مثبت مسبقاً |
| الاتصال | WiFi / LAN ثابت |

---

## 🔑 المفاتيح المطلوبة

### 1. Binance API
- افتح: `binance.com` ← Account ← API Management
- أنشئ API جديد باسم `trading-signal-bot`
- **فعّل فقط**: ✅ Read Info, ✅ Spot Trading
- **عطّل**: ❌ Withdrawals (مهم جداً للأمان)
- **قيّد الـ IP**: أضف IP الـ Raspberry Pi فقط
```
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

### 2. Telegram Bot
- افتح Telegram وابحث عن `@BotFather`
- أرسل: `/newbot` ← اتبع التعليمات
- احفظ الـ Token
- لمعرفة Chat ID: ابحث عن `@userinfobot` وأرسل `/start`
```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 3. Claude (Anthropic) API
- افتح: `console.anthropic.com`
- API Keys ← Create Key
```
ANTHROPIC_API_KEY=
```

### 4. PostgreSQL
- اختر كلمة مرور قوية (لا تستخدم كلمات بسيطة)
```
POSTGRES_PASSWORD=اختر_كلمة_مرور_قوية
```

---

## 🚀 خطوات الإعداد على الـ Raspberry Pi

### الخطوة 1: استنساخ المشروع
```bash
cd ~
git clone https://baljadrawy:TOKEN@github.com/baljadrawy/trading-signal-bot.git
cd trading-signal-bot
```

### الخطوة 2: إعداد ملف البيئة
```bash
cp .env.example .env
nano .env
```

**محتوى ملف `.env` الكامل:**
```env
# ==================== Binance ====================
BINANCE_API_KEY=ضع_مفتاحك_هنا
BINANCE_API_SECRET=ضع_السر_هنا

# ==================== Telegram ====================
TELEGRAM_BOT_TOKEN=ضع_توكن_البوت_هنا
TELEGRAM_CHAT_ID=ضع_chat_id_هنا

# ==================== Claude API ====================
ANTHROPIC_API_KEY=ضع_مفتاح_claude_هنا

# ==================== PostgreSQL ====================
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=trading_signals
POSTGRES_USER=trading_bot
POSTGRES_PASSWORD=ضع_كلمة_مرور_قوية_هنا

# ==================== Google Drive ====================
GOOGLE_DRIVE_FOLDER_ID=ضع_folder_id_هنا

# ==================== إعدادات التداول ====================
PAPER_TRADING=true
MAX_SIGNALS_PER_DAY=5
MIN_SCORE_TO_SIGNAL=7
SCAN_INTERVAL_SECONDS=300
TIMEFRAME=4h

# ==================== حجم الصفقة ====================
# الرقم بالـ USDT - غيّره حسب رأس مالك
# مثال: 50 = كل صفقة بـ 50 USDT
TRADE_AMOUNT_USDT=50

# ==================== إدارة المخاطر ====================
MAX_DAILY_LOSS_PERCENT=3
STOP_ON_CONSECUTIVE_LOSSES=3
```

### الخطوة 3: تشغيل المشروع
```bash
chmod +x setup.sh
./setup.sh
```

### الخطوة 4: التحقق من التشغيل
```bash
# مراقبة جميع الـ Containers
docker compose logs -f

# مراقبة container معين
docker compose logs -f scanner
docker compose logs -f analyzer
docker compose logs -f signal_engine
docker compose logs -f claude_review
docker compose logs -f telegram

# حالة الـ Containers
docker compose ps
```

---

## 📊 إعداد Google Colab للتدريب اليومي

### الخطوة 1: إنشاء مجلد على Google Drive
- افتح Google Drive
- أنشئ مجلد باسم `trading-bot-data`
- انسخ الـ Folder ID من الرابط:
  `drive.google.com/drive/folders/`**`هذا_هو_الـ_ID`**

### الخطوة 2: إعداد Colab Secrets
- افتح Google Colab
- افتح ملف `colab/daily_training.py`
- من القائمة: 🔑 Secrets ← أضف هذي المفاتيح:
```
POSTGRES_HOST     = IP الـ Raspberry Pi (192.168.100.64)
POSTGRES_PORT     = 5432
POSTGRES_DB       = trading_signals
POSTGRES_USER     = trading_bot
POSTGRES_PASSWORD = كلمة_المرور_التي_اخترتها
ANTHROPIC_API_KEY = مفتاح_Claude
```

> ⚠️ **ملاحظة مهمة**: لكي يصل Colab لـ PostgreSQL على الـ Raspberry Pi،
> يجب أن يكون الـ Raspberry Pi متاح عبر الإنترنت (Port Forwarding)
> أو استخدام ngrok مؤقتاً للاختبار.

### الخطوة 3: جدولة التدريب
- في Colab: Runtime ← Schedule (Colab Pro)
- أو يدوياً كل يوم في وقت ثابت

---

## 🔧 أوامر الصيانة اليومية

```bash
# إيقاف النظام
docker compose down

# تشغيل النظام
docker compose up -d

# إعادة تشغيل container معين
docker compose restart scanner

# تحديث الكود من GitHub
git pull origin main
docker compose build
docker compose up -d

# مراقبة استخدام الموارد
docker stats

# النسخ الاحتياطي لقاعدة البيانات
docker exec trading_postgres pg_dump -U trading_bot trading_signals > backup_$(date +%Y%m%d).sql

# استعادة النسخ الاحتياطي
docker exec -i trading_postgres psql -U trading_bot trading_signals < backup_YYYYMMDD.sql
```

---

## 📱 صيغة رسالة Telegram

الرسائل تُرسل بهذا الشكل تلقائياً:
```
──────────────────────────────
🎯 SHIBUSDT
📝 بيبر تريد | وضع السوق: متقلب

📈 Buy: 0.00000597

🎯 Target:
  T1: 0.0000062
  T2: 0.00000638
  T3: 0.00000647

🛑 Stop: 0.00000571

⏰ اغلاق 4h أقل من
⭐ القوة: 8/10

🤖 Claude: إشارة قوية مع دعم واضح في Order Book
──────────────────────────────
```

---

## 🏗️ هيكل المشروع

```
trading-signal-bot/
├── .env                 # ← مفاتيحك السرية (لا تُرفع على GitHub)
├── .env.example         # نموذج المفاتيح
├── .gitignore           # يحمي ملف .env
├── docker-compose.yml   # تعريف جميع الـ Containers
├── setup.sh             # سكريبت التشغيل الأول
│
├── scanner/             # مسح العملات 24/7
├── analyzer/            # التحليل الفني + Order Book
├── signal_engine/       # اختيار أفضل إشارة
├── claude_review/       # مراجعة Claude
├── telegram/            # إرسال الإشارات
│
├── shared/              # كود مشترك بين الـ Containers
│   ├── config.py        # الإعدادات
│   ├── database.py      # إدارة PostgreSQL
│   └── logger.py        # نظام السجلات
│
├── database/
│   └── init.sql         # جداول قاعدة البيانات
│
├── models/              # النماذج المدربة
└── colab/
    └── daily_training.py # نوتبوك التدريب اليومي
```

---

## 🗄️ جداول قاعدة البيانات

| الجدول | الوصف |
|--------|-------|
| `symbols` | العملات المراقبة |
| `candles` | بيانات الشموع التاريخية |
| `signals` | جميع الإشارات مع تفاصيلها |
| `trade_results` | نتائج الصفقات (ربح/خسارة) |
| `indicator_weights` | أوزان المؤشرات - يتحدث تلقائياً |
| `learning_log` | سجل جلسات التعلم |
| `risk_management` | إدارة المخاطر اليومية |
| `scan_candidates` | عملات مرشحة للتحليل (مؤقت) |
| `analysis_results` | نتائج التحليل الفني (مؤقت) |

---

## 🔒 نظام الأمان

| الإجراء | التفاصيل |
|---------|----------|
| Binance API | Spot فقط + تقييد IP |
| ملف `.env` | محمي بـ `.gitignore` |
| PostgreSQL | مستخدم محدود الصلاحيات |
| Docker Network | شبكة داخلية معزولة |
| Paper Trading | مفعّل افتراضياً للاختبار |
| وقف تلقائي | عند 3 خسائر متتالية أو 3% خسارة يومية |

---

## 🧠 نظام التعلم الذاتي

```
الصفقة تُرسل
    ↓
النتيجة تُحفظ (ربح/خسارة)
    ↓
Colab يحلل يومياً
    ↓
يحسب ارتباط كل مؤشر بالنجاح
    ↓
يحدث أوزان المؤشرات في PostgreSQL
    ↓
Claude يحلل الأداء ويعطي توصيات
    ↓
البوت يستخدم الأوزان الجديدة تلقائياً
```

---

## 🔄 الانتقال لـ VPS مستقبلاً

```bash
# على الـ VPS الجديد
git clone https://baljadrawy:TOKEN@github.com/baljadrawy/trading-signal-bot.git
cd trading-signal-bot
cp .env.example .env
nano .env  # نفس الإعدادات
./setup.sh  # نفس الأمر - لا يوجد أي تغيير
```

---

## ⚡ مؤشر صحة النظام

```bash
# تحقق سريع من حالة النظام
docker compose ps | grep -E "Up|Exit"

# عدد الإشارات اليوم
docker exec trading_postgres psql -U trading_bot trading_signals \
  -c "SELECT signals_sent, wins, losses FROM risk_management WHERE date = CURRENT_DATE;"

# آخر إشارة مرسلة
docker exec trading_postgres psql -U trading_bot trading_signals \
  -c "SELECT symbol, score, signal_time FROM signals ORDER BY signal_time DESC LIMIT 1;"
```

---

*آخر تحديث: أبريل 2026*
