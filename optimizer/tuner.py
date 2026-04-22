"""
Parameter Tuner - يضبط إعدادات البوت تلقائياً بناءً على الأداء
يعدّل MIN_SCORE_TO_SIGNAL و MIN_TIMEFRAME_CONFIRMATIONS في DB
"""
from typing import Dict, List
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('optimizer.tuner')

# حدود الإعدادات (حماية من التطرف)
MIN_SCORE_LIMIT    = 3.0
MAX_SCORE_LIMIT    = 10.0
MIN_TF_CONFIRM     = 1
MAX_TF_CONFIRM     = 4

# عتبات الأداء لاتخاذ قرار التعديل
GOOD_WIN_RATE      = 55.0   # % — أداء جيد، لا تغيير
BAD_WIN_RATE       = 40.0   # % — أداء سيء، شدّد الشروط
VERY_BAD_WIN_RATE  = 30.0   # % — أداء سيء جداً، شدّد أكثر
GOOD_AVG_PROFIT    = 1.5    # % — متوسط ربح جيد


class ParameterTuner:

    async def auto_tune(self, stats: Dict) -> List[str]:
        """
        يحلل الإحصائيات ويعدّل الإعدادات إذا لزم.
        يعيد قائمة بالتغييرات التي حدثت.
        """
        changes = []
        win_rate   = stats['win_rate']
        avg_profit = stats['avg_profit']
        total      = stats['total_trades']

        # نحتاج على الأقل 20 صفقة قبل ضبط الإعدادات
        if total < 20:
            logger.info(f"⏳ Tuner: {total} صفقة فقط، نحتاج 20 للضبط")
            return changes

        # جلب الإعدادات الحالية من DB
        current = await self._get_current_settings()
        current_score = current.get('min_score', 5.0)
        current_tf    = current.get('min_tf_confirmations', 2)

        logger.info(
            f"📋 Tuner: Win Rate={win_rate:.1f}% | "
            f"MIN_SCORE={current_score} | MIN_TF={current_tf}"
        )

        # ── قرار تعديل MIN_SCORE_TO_SIGNAL ──────────────────────────
        new_score = current_score

        if win_rate >= GOOD_WIN_RATE and avg_profit >= GOOD_AVG_PROFIT:
            # أداء جيد → خفّف قليلاً لتوليد إشارات أكثر
            if current_score > MIN_SCORE_LIMIT + 0.5:
                new_score = round(current_score - 0.5, 1)
                changes.append(f"MIN_SCORE: {current_score} → {new_score} (أداء جيد، خفّف الشروط)")

        elif win_rate < VERY_BAD_WIN_RATE:
            # أداء سيء جداً → شدّد كثيراً
            if current_score < MAX_SCORE_LIMIT - 1.0:
                new_score = round(current_score + 1.0, 1)
                changes.append(f"MIN_SCORE: {current_score} → {new_score} (أداء سيء جداً، شدّد الشروط)")

        elif win_rate < BAD_WIN_RATE:
            # أداء سيء → شدّد قليلاً
            if current_score < MAX_SCORE_LIMIT - 0.5:
                new_score = round(current_score + 0.5, 1)
                changes.append(f"MIN_SCORE: {current_score} → {new_score} (أداء سيء، شدّد الشروط)")

        # ── قرار تعديل MIN_TIMEFRAME_CONFIRMATIONS ──────────────────
        new_tf = current_tf

        if win_rate < VERY_BAD_WIN_RATE and current_tf < MAX_TF_CONFIRM:
            new_tf = current_tf + 1
            changes.append(f"MIN_TF_CONFIRMATIONS: {current_tf} → {new_tf} (أداء سيء جداً)")

        elif win_rate >= GOOD_WIN_RATE and avg_profit >= GOOD_AVG_PROFIT and current_tf > MIN_TF_CONFIRM:
            new_tf = current_tf - 1
            changes.append(f"MIN_TF_CONFIRMATIONS: {current_tf} → {new_tf} (أداء ممتاز)")

        # ── تطبيق التغييرات ──────────────────────────────────────────
        if new_score != current_score:
            new_score = max(MIN_SCORE_LIMIT, min(MAX_SCORE_LIMIT, new_score))
            await self._save_setting('min_score_to_signal', str(new_score))
            logger.info(f"⚙️ تم تغيير MIN_SCORE: {current_score} → {new_score}")

        if new_tf != current_tf:
            new_tf = max(MIN_TF_CONFIRM, min(MAX_TF_CONFIRM, new_tf))
            await self._save_setting('min_timeframe_confirmations', str(new_tf))
            logger.info(f"⚙️ تم تغيير MIN_TF_CONFIRMATIONS: {current_tf} → {new_tf}")

        if not changes:
            if win_rate < BAD_WIN_RATE:
                at_score_cap = current_score >= MAX_SCORE_LIMIT - 0.5
                at_tf_cap    = current_tf >= MAX_TF_CONFIRM
                if at_score_cap or at_tf_cap:
                    logger.warning(
                        f"⚠️ Tuner: أداء سيء (Win Rate={win_rate:.1f}%) لكن الإعدادات عند السقف "
                        f"(score={current_score}/{MAX_SCORE_LIMIT}, tf={current_tf}/{MAX_TF_CONFIRM}) — "
                        f"رفع الحدود أو مراجعة الاستراتيجية مطلوب"
                    )
                else:
                    logger.info("✅ Tuner: الإعدادات مناسبة، لا تغييرات مطلوبة")
            else:
                logger.info("✅ Tuner: الإعدادات مناسبة، لا تغييرات مطلوبة")

        return changes

    async def _get_current_settings(self) -> Dict:
        """جلب الإعدادات الحالية من جدول optimizer_settings"""
        await self._ensure_settings_table()

        rows = await Database.fetch(
            "SELECT key, value FROM optimizer_settings"
        )
        settings = {row['key']: row['value'] for row in rows}

        return {
            'min_score':            float(settings.get('min_score_to_signal', '5.0')),
            'min_tf_confirmations': int(settings.get('min_timeframe_confirmations', '2')),
        }

    async def _save_setting(self, key: str, value: str):
        """حفظ إعداد في DB"""
        await self._ensure_settings_table()
        await Database.execute("""
            INSERT INTO optimizer_settings (key, value, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = $2, updated_at = NOW()
        """, key, value)

    async def _ensure_settings_table(self):
        """إنشاء جدول الإعدادات إذا لم يوجد"""
        await Database.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_settings (
                id         SERIAL PRIMARY KEY,
                key        VARCHAR(100) UNIQUE NOT NULL,
                value      TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # قيم افتراضية
        await Database.execute("""
            INSERT INTO optimizer_settings (key, value)
            VALUES
                ('min_score_to_signal', '5.0'),
                ('min_timeframe_confirmations', '2')
            ON CONFLICT (key) DO NOTHING
        """)
