# 🤖 Trading Signal Bot - دليل الإعداد الكامل

## 📋 المتطلبات الأساسية

| المكوّن | التفاصيل |
|---------|----------|
| الجهاز | Hetzner VPS (أو أي خادم Ubuntu) |
| النظام | Ubuntu 22.04 / 24.04 LTS (amd64) |
| Docker | مثبت مسبقاً أو يُثبَّت عبر السكريبت |
| الاتصال | IP ثابت + SSH مفعّل |

---

## 🔑 المفاتيح المطلوبة

### 1. Binance API
- افتح: `binance.com` ← Account ← API Management
- أنشئ API جديد باسم `trading-signal-bot`
- **فعّل فقط**: ✅ Read Info, ✅ Spot Trading
- **عطّل**: ❌ Withdrawals (مهم جداً للأمان)
- **قيّد الـ IP**: أضف IP الخادم فقط
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

## 🚀 خطوات الإعداد على الخادم (VPS)

### الخطوة 1: تثبيت Docker (إذا لم يكن مثبتاً)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### الخطوة 2: استنساخ المشروع
```bash
cd ~
git clone https://github.com/baljadrawy/trading-signal-bot.git
cd trading-signal-bot
```

### الخطوة 3: إعداد ملف البيئة
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

### الخطوة 4: تشغيل المشروع
```bash
chmod +x setup.sh
./setup.sh
```

### الخطوة 5: التحقق من التشغيل
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

يتصل Colab بقاعدة البيانات عبر **SSH Tunnel آمن** — لا داعي لفتح أي منفذ إضافي.

### الخطوة 1: إنشاء SSH Key للـ Colab

على جهازك المحلي أو الخادم:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/colab_key -N ""
# انسخ المفتاح العام للخادم
cat ~/.ssh/colab_key.pub >> ~/.ssh/authorized_keys
# انسخ المفتاح الخاص — ستحتاجه في Colab
cat ~/.ssh/colab_key
```

### الخطوة 2: إعداد Colab Secrets

افتح Google Colab → 🔑 Secrets → أضف هذه المفاتيح:

| الاسم | القيمة |
|-------|--------|
| `SSH_HOST` | IP الخادم (مثال: `178.104.128.198`) |
| `SSH_USER` | اسم مستخدم SSH (مثال: `tradmin`) |
| `SSH_KEY` | محتوى المفتاح الخاص (كل النص بما فيه السطر الأول والأخير) |
| `POSTGRES_DB` | `trading_signals` |
| `POSTGRES_USER` | `trading_bot` |
| `POSTGRES_PASSWORD` | كلمة مرور قاعدة البيانات |
| `ANTHROPIC_API_KEY` | مفتاح Claude |

### الخطوة 3: تشغيل النوتبوك

- افتح الملف: `colab/daily_training.ipynb`
- شغّل الخلايا بالترتيب
- خلية SSH Tunnel تنشئ اتصالاً آمناً بـ PostgreSQL على الخادم
- التدريب يحدّث أوزان المؤشرات في قاعدة البيانات مباشرة

### الخطوة 4: جدولة التدريب (يومياً)
- في Colab Pro: Runtime ← Schedule
- أو شغّله يدوياً كل يوم في وقت ثابت (مثلاً كل صباح)

> ✅ عند نجاح التدريب ستظهر: `اكتمل التدريب اليومي!`

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

## 🕌 نظام الموافقة الشرعية والـ Whitelist

### كيف يعمل
```
إشارة جديدة
    ↓
هل العملة في الـ Whitelist؟
    ↓ نعم               ↓ لا
إرسال مباشر      طلب موافقة منك على Telegram
للمشتركين             ↓
                  تضغط ✅ أو ❌
                  خلال 30 دقيقة
                      ↓ ✅
               هل السعر تغير أكثر من 0.5%؟
                  ↓ لا          ↓ نعم
            إرسال الإشارة   رسالة "السعر تغير"
            + إضافة العملة  البحث عن فرصة أخرى
             للـ Whitelist
```

### أوامر التحكم من Telegram

الأوامر تظهر تلقائياً في قائمة البوت (/) عند الضغط عليها:

| الأمر | الوظيفة |
|-------|---------|
| `/start` | 🤖 قائمة الأوامر |
| `/status` | 📊 حالة النظام وإحصائيات اليوم |
| `/whitelist` | 📋 عرض كل العملات المعتمدة |
| `/stats` | 📈 إحصائيات آخر 7 أيام |
| `/pause` | ⏸️ إيقاف البوت مؤقتاً |
| `/resume` | ▶️ استئناف البوت |

### إعدادات الموافقة في `.env`
```env
APPROVAL_TIMEOUT_MINUTES=30       # وقت انتظار موافقتك
APPROVAL_MAX_PRICE_CHANGE_PCT=0.5 # أقصى تغير سعري مقبول
```

---

## 📱 صيغة رسائل Telegram

**إشارة مباشرة (عملة في الـ Whitelist):**
```
──────────────────────────────
🎯 BTCUSDT  ✅ معتمدة
وضع السوق: صاعد 📈

💰 حجم الصفقة: 50 USDT
📊 الكمية: 0.0005

📈 Buy: 83000.00

🎯 Target:
  T1: 84660.00
  T2: 86490.00
  T3: 88320.00

🛑 Stop: 81340.00

⏰ اغلاق 4h أقل من
⭐ القوة: 8/10
──────────────────────────────
```

**طلب موافقة (عملة جديدة):**
```
──────────────────────────────
🔍 مراجعة شرعية مطلوبة
──────────────────────────────

🪙 NEWUSDT  🆕 عملة جديدة
وضع السوق: صاعد 📈

📈 Buy: 1.2345
🎯 T1 / T2 / T3 ...
🛑 Stop: 1.1800

⏰ ينتهي الطلب خلال 30 دقيقة
──────────────────────────────
[✅ موافق - شرعياً مقبولة]  [❌ رفض]
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
├── telegram/            # إرسال الإشارات + أوامر التحكم
│
├── shared/              # كود مشترك بين الـ Containers
│   ├── config.py        # الإعدادات
│   ├── database.py      # إدارة PostgreSQL
│   └── logger.py        # نظام السجلات
│
├── database/
│   └── init.sql         # جداول قاعدة البيانات (تُشغَّل مرة واحدة)
│
└── colab/
    └── daily_training.ipynb  # نوتبوك التدريب اليومي (Google Colab)
```

---

## 🗄️ جداول قاعدة البيانات

| الجدول | الوصف |
|--------|-------|
| `symbols` | العملات المراقبة |
| `candles` | بيانات الشموع التاريخية |
| `signals` | جميع الإشارات مع تفاصيلها |
| `symbol_whitelist` | العملات المعتمدة شرعياً |
| `approval_requests` | طلبات الموافقة المعلّقة |
| `trade_results` | نتائج الصفقات (ربح/خسارة) |
| `indicator_weights` | أوزان المؤشرات - يتحدث تلقائياً |
| `learning_log` | سجل جلسات التعلم اليومي |
| `risk_management` | إدارة المخاطر اليومية |
| `scan_candidates` | عملات مرشحة للتحليل (مؤقت) |

> ⚠️ الجداول تُنشأ تلقائياً عند أول تشغيل عبر `database/init.sql`
> إذا أردت إعادة إنشاء الجداول: `docker compose down -v && docker compose up -d`

---

## 🗺️ Git Flow - طريقة العمل على الكود

### الفروع الموجودة

| الفرع | الغرض |
|-------|-------|
| `main` | الكود المستقر فقط - **لا تعدّل عليه مباشرة** |
| `dev` | قاعدة التطوير - كل الميزات تنطلق وتعود هنا |
| `feature/اسم-الميزة` | ميزة جديدة - يُنشأ من dev ويُدمج فيه |

---

### سيناريو 1: تطوير ميزة جديدة
```bash
# 1. تأكد أنك على dev وهو محدث
git checkout dev
git pull origin dev

# 2. أنشئ فرع للميزة
git checkout -b feature/whale-alert

# 3. اشتغل وعدّل الكود
# ... التعديلات ...

# 4. احفظ التعديلات
git add .
git commit -m "✨ إضافة تحليل Whale Alert"

# 5. ادفع الفرع لـ GitHub
git push origin feature/whale-alert

# 6. افتح Pull Request من feature/whale-alert → dev
# على GitHub: Compare & pull request

# 7. بعد المراجعة والاختبار ادمج
git checkout dev
git merge feature/whale-alert
git push origin dev

# 8. احذف الفرع بعد الدمج
git branch -d feature/whale-alert
git push origin --delete feature/whale-alert
```

---

### سيناريو 2: نقل كود مستقر من dev إلى main
```bash
# بعد اختبار dev على الخادم وتأكد من استقراره
git checkout main
git pull origin main
git merge dev
git push origin main
```

---

### سيناريو 3: إصلاح خطأ طارئ في main (Hotfix)
```bash
# 1. أنشئ فرع الإصلاح من main مباشرة
git checkout main
git checkout -b hotfix/fix-scanner-crash

# 2. صحح الخطأ
# ... التعديل ...

# 3. ادمجه في main وdev معاً
git checkout main
git merge hotfix/fix-scanner-crash
git push origin main

git checkout dev
git merge hotfix/fix-scanner-crash
git push origin dev

# 4. احذف فرع الـ Hotfix
git branch -d hotfix/fix-scanner-crash
```

---

### أسماء Commits الموصى بها
```
✨ feat: إضافة ميزة جديدة
🐛 fix: إصلاح خطأ
📖 docs: تحديث الدوكيومنتيشن
⚡ perf: تحسين الأداء
🔧 config: تعديل إعدادات
🧹 refactor: إعادة هيكلة الكود
```

---

### على الخادم - تحديث الكود
```bash
cd ~/trading-signal-bot

# تحديث من main (الكود المستقر)
git pull origin main
docker compose build
docker compose up -d

# أو تجربة dev أولاً
git pull origin dev
docker compose build
docker compose up -d
```

---

## 🔒 نظام الأمان

| الإجراء | التفاصيل |
|---------|----------|
| Binance API | Spot فقط + تقييد IP |
| ملف `.env` | محمي بـ `.gitignore` |
| PostgreSQL | مستخدم محدود الصلاحيات، يُقبل على `127.0.0.1` فقط |
| Docker Network | شبكة داخلية معزولة |
| SSH Tunnel | الاتصال بـ Colab عبر SSH مشفّر فقط |
| Paper Trading | مفعّل افتراضياً للاختبار |
| وقف تلقائي | عند 3 خسائر متتالية أو 3% خسارة يومية |

---

## 🧠 نظام التعلم الذاتي

```
الصفقة تُرسل
    ↓
النتيجة تُحفظ (ربح/خسارة)
    ↓
Colab يحلل يومياً (daily_training.ipynb)
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

# عملات في الـ Whitelist
docker exec trading_postgres psql -U trading_bot trading_signals \
  -c "SELECT symbol, approved_at FROM symbol_whitelist ORDER BY approved_at DESC;"
```

---

*آخر تحديث: أبريل 2026*
