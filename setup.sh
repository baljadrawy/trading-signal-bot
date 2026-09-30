#!/bin/bash
# سكريبت الإعداد الأول — لتثبيت أول على خادم فارغ فقط (initial install on an EMPTY host only).
# ليس أداة نشر أو تشغيل للإنتاج: عمليات الإنتاج في docs/ops/COMPOSE_OPERATIONS.md

echo "🚀 إعداد Trading Signal Bot..."

BUILD_REVISION="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
export BUILD_REVISION

# التحقق من Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker غير مثبت!"
    exit 1
fi

# حارس fail-closed: يرفض التشغيل إذا وُجدت أي حاوية للمشروع أو أي حاوية trading_*
# (قبل أي build أو start). أي فشل في الاستعلام يُعامل كرفض.
if ! existing_project="$(docker ps -a --filter label=com.docker.compose.project=trading-signal-bot -q)" \
   || ! existing_named="$(docker ps -a --filter name=trading_ --format '{{.Names}}')"; then
    echo "❌ تعذّر فحص الحاويات الحالية؛ رفض الإعداد (fail-closed)."
    exit 1
fi
if [ -n "$existing_project" ] || printf '%s\n' "$existing_named" | grep -q '^trading_'; then
    echo "⛔ رفض: توجد حاويات trading-signal-bot / trading_* على هذا الخادم."
    echo "   setup.sh للتثبيت الأول على خادم فارغ فقط، ولا يُستخدم للنشر أو إعادة التشغيل."
    echo "   اتبع docs/ops/COMPOSE_OPERATIONS.md (أي تعديل يحتاج موافقة المالك)."
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
echo "⏹️ الإيقاف وأي عملية تشغيلية لاحقة: اتبع docs/ops/COMPOSE_OPERATIONS.md"
echo "   (لا أوامر Compose شاملة في الإنتاج؛ خدمة واحدة وبموافقة المالك)"
