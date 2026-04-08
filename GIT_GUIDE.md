# 🌿 دليل Git Flow - طريقة العمل على الكود

---

## 📌 الفكرة الأساسية

تخيّل المشروع كشجرة:

```
main (الجذع) ← مستقر دائماً، يعمل على الـ Raspberry Pi
  └── dev (الفرع الرئيسي للتطوير) ← هنا تجمع كل الميزات
        ├── feature/whale-alert ← ميزة قيد التطوير
        ├── feature/news-sentiment ← ميزة أخرى
        └── hotfix/scanner-crash ← إصلاح طارئ
```

**القاعدة الذهبية:**
- `main` = ما يشتغل على الـ Raspberry Pi فعلاً
- `dev` = ما تعمل عليه وتجربه
- `feature/*` = كل ميزة جديدة في عزل تام

---

## 🔵 الفروع وأدوارها

### فرع `main`
- الكود المختبر والمستقر 100%
- لا تعدّل عليه أبداً بشكل مباشر
- الـ Raspberry Pi يسحب منه فقط
- يُحدَّث فقط عبر Pull Request من `dev`

### فرع `dev`
- قاعدة العمل اليومي
- تنطلق منه كل الميزات الجديدة
- تعود إليه كل الميزات بعد الاكتمال
- تختبره على الـ Raspberry Pi قبل نقله لـ `main`

### فرع `feature/اسم-الميزة`
- فرع مؤقت لكل ميزة جديدة
- معزول تماماً عن باقي الكود
- يُحذف بعد الدمج في `dev`

### فرع `hotfix/اسم-الإصلاح`
- لإصلاح أخطاء طارئة في `main`
- ينطلق من `main` مباشرة
- يُدمج في `main` و`dev` معاً

---

## 📋 السيناريوهات العملية

---

### 🟢 سيناريو 1: إضافة ميزة جديدة (الأكثر شيوعاً)

**مثال: إضافة تحليل Whale Alert**

**الخطوة 1 - ابدأ دائماً من dev محدّث:**
```bash
git checkout dev
git pull origin dev
```
> لماذا؟ لأن dev ممكن يكون فيه تعديلات أضافها شخص آخر (أو أنت من جهاز ثاني)
> تريد دائماً تبدأ من آخر نسخة

**الخطوة 2 - أنشئ فرع للميزة:**
```bash
git checkout -b feature/whale-alert
```
> هذا ينشئ فرع جديد اسمه `feature/whale-alert` وينقلك إليه تلقائياً
> الآن أي تعديل تسويه لن يأثر على dev أو main

**الخطوة 3 - اشتغل على الكود:**
```bash
# عدّل الملفات اللي تحتاجها
# مثلاً: أنشأت ملف scanner/whale_tracker.py
nano scanner/whale_tracker.py
```

**الخطوة 4 - احفظ تقدمك (يمكن تسوي هذا أكثر من مرة):**
```bash
git add .
git commit -m "✨ إضافة whale_tracker - مراقبة محافظ الحيتان"
```
> احفظ كلما أكملت جزء منطقي من العمل، مش لازم تكمل الميزة كلها

**الخطوة 5 - ارفع الفرع لـ GitHub:**
```bash
git push origin feature/whale-alert
```
> هذا يحفظ عملك على GitHub كنسخة احتياطية

**الخطوة 6 - افتح Pull Request على GitHub:**
```
1. افتح github.com/baljadrawy/trading-signal-bot
2. سيظهر لك زر أصفر: "Compare & pull request"
3. اضغطه
4. تأكد: base: dev ← compare: feature/whale-alert
5. اكتب وصفاً مختصراً لما عملته
6. اضغط "Create pull request"
```

**الخطوة 7 - ادمج الـ PR وانظّف:**
```bash
# بعد مراجعة الكود والموافقة على الـ PR في GitHub
git checkout dev
git pull origin dev   # يجلب التعديلات بعد الدمج

# احذف الفرع محلياً
git branch -d feature/whale-alert

# احذف الفرع من GitHub
git push origin --delete feature/whale-alert
```

---

### 🟡 سيناريو 2: نقل كود مستقر من dev إلى main

**متى تسوي هذا؟**
- اختبرت dev على الـ Raspberry Pi لفترة كافية
- ما في أخطاء
- الميزات الجديدة تعمل صح

```bash
# تأكد أن main و dev محدّثين
git checkout main
git pull origin main

git checkout dev
git pull origin dev

# ادمج dev في main
git checkout main
git merge dev

# ارفع main لـ GitHub
git push origin main
```

**على الـ Raspberry Pi بعدها مباشرة:**
```bash
cd ~/trading-signal-bot
git pull origin main
docker compose build
docker compose up -d
```

---

### 🔴 سيناريو 3: إصلاح خطأ طارئ في main (Hotfix)

**متى تسوي هذا؟**
- البوت وقف فجأة على الـ Raspberry Pi
- في خطأ في main يحتاج إصلاح فوري
- ما تريد تنتظر تكمل الميزات اللي في dev

```bash
# ابدأ من main مباشرة (مش dev)
git checkout main
git pull origin main

# أنشئ فرع الإصلاح
git checkout -b hotfix/scanner-crash

# صحح الخطأ
nano scanner/scanner_logic.py

# احفظ
git add .
git commit -m "🐛 إصلاح crash في scanner عند انقطاع الاتصال"

# ادمجه في main أولاً
git checkout main
git merge hotfix/scanner-crash
git push origin main

# ادمجه في dev أيضاً (مهم!)
git checkout dev
git merge hotfix/scanner-crash
git push origin dev

# احذف فرع الـ Hotfix
git branch -d hotfix/scanner-crash
git push origin --delete hotfix/scanner-crash
```

> لماذا تدمجه في dev أيضاً؟
> لأن dev لازم يحتوي على نفس الإصلاح وإلا عند نقل dev لـ main لاحقاً سيرجع الخطأ

---

### 🔵 سيناريو 4: تجربة فكرة غير مؤكدة

**متى تسوي هذا؟**
- تريد تجرب فكرة جديدة مش متأكد منها
- ممكن تتراجع عنها كلياً

```bash
git checkout dev
git checkout -b experiment/reinforcement-learning

# جرب وعدّل براحتك
# إذا نجحت الفكرة:
git push origin experiment/reinforcement-learning
# افتح PR → dev

# إذا فشلت الفكرة:
git checkout dev
git branch -D experiment/reinforcement-learning   # -D للحذف القسري
```

---

## 📝 أسماء Commits

الزم نفس الأسلوب في كل commit:

| الرمز | المعنى | مثال |
|-------|--------|-------|
| ✨ | ميزة جديدة | `✨ إضافة تحليل Whale Alert` |
| 🐛 | إصلاح خطأ | `🐛 إصلاح crash في Scanner` |
| ⚡ | تحسين أداء | `⚡ تسريع مسح العملات بـ async` |
| 🔧 | تعديل إعدادات | `🔧 تحديث MIN_SCORE_TO_SIGNAL إلى 8` |
| 📖 | توثيق | `📖 تحديث SETUP_GUIDE` |
| 🧹 | تنظيف كود | `🧹 إزالة كود قديم من analyzer` |
| 🔒 | أمان | `🔒 تقييد صلاحيات PostgreSQL` |

---

## ⚡ أوامر Git اليومية السريعة

```bash
# أين أنا الآن؟
git status

# على أي فرع أنا؟
git branch

# كل الفروع (محلي + GitHub)
git branch -a

# تاريخ الـ Commits
git log --oneline --graph --all

# الفروع الموجودة على GitHub
git fetch --prune
git branch -r

# تراجع عن تعديل لم تحفظه بعد
git checkout -- اسم_الملف

# تراجع عن آخر commit (مع الاحتفاظ بالتعديلات)
git reset --soft HEAD~1
```

---

## 🚨 أخطاء شائعة وحلها

**المشكلة: نسيت تنشئ فرع وعدّلت على dev مباشرة**
```bash
# لا تذعر - الحل سهل
# احفظ التعديلات في stash مؤقتاً
git stash

# أنشئ الفرع الصح
git checkout -b feature/اسم-الميزة

# استرجع التعديلات
git stash pop

# الآن أكمل بشكل طبيعي
```

**المشكلة: فرعي متأخر عن dev (فيه commits جديدة في dev)**
```bash
git checkout feature/اسم-الميزة
git rebase dev
# هذا يأخذ آخر تحديثات dev ويضع commits الميزة فوقها
```

**المشكلة: تعارض (Conflict) عند الدمج**
```bash
# Git سيخبرك بالملفات المتعارضة
git status
# افتح الملف وستجد:
# <<<<<<< HEAD
# كودك
# =======
# الكود الثاني
# >>>>>>> dev
# احذف الأسطر الزيادة واحتفظ بالصح
# ثم:
git add .
git commit -m "🔀 حل تعارض دمج feature/whale-alert"
```

---

## 🗺️ الخلاصة البصرية

```
main ────────────────────────────── ← مستقر دائماً
  │                        ↑
  │                    git merge dev
  │                        │
dev ──────●──────●──────●──●──────── ← قاعدة العمل
          │      ↑      ↑
          │      │      │
          │   merge   merge
          │      │      │
feature/A ●──────●      │           ← ميزة اكتملت
                        │
feature/B      ●────────●           ← ميزة ثانية اكتملت
```

---

*آخر تحديث: أبريل 2026*
