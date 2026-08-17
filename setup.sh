#!/bin/bash
# سكريبت الإعداد الأول للـ Raspberry Pi

echo "🚀 إعداد Trading Signal Bot..."

# التحقق من Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker غير مثبت!"
    exit 1
fi

# نسخ ملف البيئة
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📝 تم إنشاء ملف .env - يرجى تعديله بمعلوماتك"
    echo "    nano .env"
    exit 0
fi

# بناء الـ Containers
echo "🔨 بناء الـ Containers..."
docker compose build

# PostgreSQL خدمة مشتركة وليست ضمن Compose الخاص بالبوت.
echo "🗄️ التحقق من PostgreSQL المشترك..."
if ! docker inspect postgres >/dev/null 2>&1; then
    echo "❌ حاوية postgres المشتركة غير موجودة؛ شغّل /home/tradmin/shared-postgres أولاً"
    exit 1
fi
docker start postgres >/dev/null
echo "⏳ انتظار جاهزية قاعدة البيانات..."
for _ in $(seq 1 30); do
    if docker exec postgres pg_isready -U trading_signal_bot -d trading_signals >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if ! docker exec postgres pg_isready -U trading_signal_bot -d trading_signals >/dev/null 2>&1; then
    echo "❌ PostgreSQL لم يصبح جاهزاً خلال 60 ثانية"
    exit 1
fi

# تطبيق migrations قبل تشغيل أي خدمة؛ الفشل يوقف الإعداد بدلاً من تشغيل schema قديم.
echo "🧱 تطبيق migrations..."
python3 database/migrate.py || exit 1

# تشغيل باقي الـ Containers
echo "▶️ تشغيل جميع الـ Containers..."
docker compose up -d

echo "✅ تم التشغيل بنجاح!"
echo ""
echo "📊 لمراقبة السجلات:"
echo "   docker compose logs -f"
echo ""
echo "⏹️ للإيقاف:"
echo "   docker compose down"
