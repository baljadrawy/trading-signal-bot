"""
Optimizer Agent - يحسّن الخوارزمية تلقائياً بناءً على نتائج الصفقات
يعمل كل ساعة ويحدّث الأوزان والإعدادات بشكل ذكي
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.alerts import send_alert
from optimizer.analyzer import PerformanceAnalyzer
from optimizer.tuner import ParameterTuner

logger = setup_logger('optimizer')

# الحد الأدنى للصفقات المطلوبة قبل التحسين
MIN_TRADES_TO_OPTIMIZE = 10

# كل كم دقيقة يعمل الـ optimizer
OPTIMIZER_INTERVAL_MINUTES = 60


async def main():
    logger.info("🤖 بدء تشغيل Optimizer Agent...")
    await Database.connect()

    analyzer = PerformanceAnalyzer()
    tuner = ParameterTuner()

    consecutive_errors = 0

    try:
        while True:
            try:
                logger.info("🔍 Optimizer: بدء دورة التحسين...")
                await run_optimization_cycle(analyzer, tuner)
                consecutive_errors = 0
                logger.info(f"✅ Optimizer: انتهت الدورة. الانتظار {OPTIMIZER_INTERVAL_MINUTES} دقيقة...")
                await asyncio.sleep(OPTIMIZER_INTERVAL_MINUTES * 60)

            except Exception as e:
                consecutive_errors += 1
                wait = min(60 * consecutive_errors, 300)
                logger.error(f"❌ خطأ في Optimizer ({consecutive_errors}): {e}")
                if consecutive_errors >= 3:
                    await send_alert(
                        f"Optimizer فشل {consecutive_errors} مرات متتالية\nالخطأ: {str(e)[:200]}",
                        level='critical', component='Optimizer'
                    )
                await asyncio.sleep(wait)

    finally:
        await Database.disconnect()


async def run_optimization_cycle(analyzer: PerformanceAnalyzer, tuner: ParameterTuner):
    """دورة تحسين كاملة"""

    # 1. تحليل الأداء العام (مصفّى على صفقات ما بعد rebuild)
    stats = await analyzer.get_overall_stats()

    # 2. تحقق من توفر صفقات كافية ما بعد rebuild
    if stats['total_trades'] < MIN_TRADES_TO_OPTIMIZE:
        logger.info(
            f"⏳ بيانات غير كافية للتحسين بعد rebuild: "
            f"{stats['total_trades']}/{MIN_TRADES_TO_OPTIMIZE} صفقة"
        )
        return

    logger.info(
        f"📊 الأداء الحالي: Win Rate={stats['win_rate']:.1f}% | "
        f"متوسط ربح={stats['avg_profit']:.2f}% | "
        f"إجمالي صفقات={stats['total_trades']}"
    )

    # 3. تحديث أوزان المؤشرات
    weights_updated = await analyzer.update_indicator_weights()
    if weights_updated > 0:
        logger.info(f"⚖️ تم تحديث {weights_updated} وزن مؤشر")

    # 4. ضبط الإعدادات تلقائياً
    changes = await tuner.auto_tune(stats)

    # 5. تسجيل الدورة في قاعدة البيانات
    await log_optimization(stats, weights_updated, changes)

    # 6. إرسال تقرير إذا في تغييرات مهمة
    if changes or weights_updated > 0:
        await send_optimization_report(stats, weights_updated, changes)


async def log_optimization(stats: dict, weights_updated: int, changes: list):
    """تسجيل نتيجة دورة التحسين"""
    import json
    try:
        await Database.execute("""
            INSERT INTO learning_log (
                model_version, total_trades_analyzed,
                win_rate, avg_profit, changes_made
            ) VALUES ($1, $2, $3, $4, $5)
        """,
            'optimizer_v1',
            stats['total_trades'],
            stats['win_rate'] / 100,
            stats['avg_profit'],
            json.dumps({
                'weights_updated': weights_updated,
                'parameter_changes': changes
            })
        )
    except Exception as e:
        logger.error(f"خطأ في تسجيل دورة التحسين: {e}")


async def send_optimization_report(stats: dict, weights_updated: int, changes: list):
    """إرسال تقرير التحسين على Telegram"""
    lines = [
        "🤖 *تقرير Optimizer Agent*",
        "",
        f"📊 *الأداء الحالي:*",
        f"• معدل الفوز: {stats['win_rate']:.1f}%",
        f"• متوسط الربح: {stats['avg_profit']:.2f}%",
        f"• إجمالي الصفقات: {stats['total_trades']}",
        f"• أفضل حالة سوق: {stats.get('best_condition', 'غير معروف')}",
        "",
    ]

    if weights_updated > 0:
        lines.append(f"⚖️ *تحديث الأوزان:* {weights_updated} مؤشر")

    if changes:
        lines.append("")
        lines.append("⚙️ *تغييرات الإعدادات:*")
        for change in changes:
            lines.append(f"• {change}")

    message = "\n".join(lines)

    try:
        import aiohttp
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={
                'chat_id': config.TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            }, timeout=aiohttp.ClientTimeout(total=10))
        logger.info("📱 تم إرسال تقرير Optimizer على Telegram")
    except Exception as e:
        logger.error(f"خطأ في إرسال تقرير Telegram: {e}")


if __name__ == "__main__":
    asyncio.run(main())
