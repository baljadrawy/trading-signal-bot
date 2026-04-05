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

# تشغيل قاعدة البيانات أولاً
echo "🗄️ تشغيل PostgreSQL..."
docker compose up -d postgres

# انتظار جاهزية قاعدة البيانات
echo "⏳ انتظار جاهزية قاعدة البيانات..."
sleep 10

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
