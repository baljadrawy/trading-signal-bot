"""
Performance Analyzer - يحلل نتائج الصفقات ويحدّث أوزان المؤشرات
"""
import json
from typing import Dict, List
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('optimizer.analyzer')

# حدود الأوزان
MIN_WEIGHT = 0.3
MAX_WEIGHT = 2.5
# الحد الأدنى للصفقات لحساب وزن مؤشر معين
MIN_SAMPLES_PER_INDICATOR = 5


class PerformanceAnalyzer:

    async def get_overall_stats(self) -> Dict:
        """إحصائيات الأداء العام للـ 30 يوم الأخيرة"""
        row = await Database.fetchrow("""
            SELECT
                COUNT(*)                                        AS total_trades,
                SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END)  AS wins,
                SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                AVG(profit_percent)                             AS avg_profit,
                AVG(CASE WHEN result='WIN' THEN profit_percent END) AS avg_win,
                AVG(CASE WHEN result='LOSS' THEN profit_percent END) AS avg_loss
            FROM trade_results
            WHERE result IS NOT NULL
            AND exit_time > NOW() - INTERVAL '30 days'
        """)

        total = int(row['total_trades'] or 0)
        wins  = int(row['wins'] or 0)

        # أفضل حالة سوق
        best_row = await Database.fetchrow("""
            SELECT s.market_condition,
                   COUNT(*) as cnt,
                   AVG(CASE WHEN tr.result='WIN' THEN 1.0 ELSE 0.0 END) AS wr
            FROM trade_results tr
            JOIN signals s ON tr.signal_id = s.id
            WHERE tr.result IS NOT NULL
            AND tr.exit_time > NOW() - INTERVAL '30 days'
            GROUP BY s.market_condition
            ORDER BY wr DESC
            LIMIT 1
        """)

        return {
            'total_trades': total,
            'wins': wins,
            'losses': int(row['losses'] or 0),
            'win_rate': (wins / total * 100) if total > 0 else 0,
            'avg_profit': float(row['avg_profit'] or 0),
            'avg_win': float(row['avg_win'] or 0),
            'avg_loss': float(row['avg_loss'] or 0),
            'best_condition': best_row['market_condition'] if best_row else 'غير معروف',
        }

    async def get_stats_by_condition(self) -> Dict[str, Dict]:
        """إحصائيات مقسّمة حسب حالة السوق"""
        rows = await Database.fetch("""
            SELECT
                s.market_condition,
                COUNT(*)                                        AS total,
                AVG(CASE WHEN tr.result='WIN' THEN 1.0 ELSE 0.0 END) AS win_rate,
                AVG(tr.profit_percent)                          AS avg_profit
            FROM trade_results tr
            JOIN signals s ON tr.signal_id = s.id
            WHERE tr.result IS NOT NULL
            AND tr.exit_time > NOW() - INTERVAL '30 days'
            GROUP BY s.market_condition
        """)

        return {
            row['market_condition']: {
                'total': int(row['total']),
                'win_rate': float(row['win_rate'] or 0),
                'avg_profit': float(row['avg_profit'] or 0),
            }
            for row in rows
        }

    async def update_indicator_weights(self) -> int:
        """
        يحسب ارتباط كل مؤشر بالنجاح ويحدّث وزنه في DB.
        يعيد عدد الأوزان التي تم تحديثها.
        """
        # جلب الإشارات مع نتائجها
        rows = await Database.fetch("""
            SELECT
                s.market_condition,
                s.score_details,
                CASE WHEN tr.result = 'WIN' THEN 1.0 ELSE 0.0 END AS success
            FROM signals s
            JOIN trade_results tr ON s.id = tr.signal_id
            WHERE tr.result IS NOT NULL
            AND tr.exit_time > NOW() - INTERVAL '30 days'
        """)

        if not rows:
            return 0

        # تجميع البيانات حسب (indicator, condition)
        data: Dict[str, Dict[str, List]] = {}

        for row in rows:
            condition = row['market_condition']
            success   = float(row['success'])

            details = row['score_details']
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    continue
            if not isinstance(details, dict):
                continue

            for indicator, value in details.items():
                # نتخطى القيم غير الرقمية
                if isinstance(value, (list, str)):
                    continue
                try:
                    score = float(value)
                except (TypeError, ValueError):
                    continue

                key = f"{indicator}|{condition}"
                if key not in data:
                    data[key] = {'scores': [], 'successes': []}
                data[key]['scores'].append(score)
                data[key]['successes'].append(success)

        updated = 0

        for key, vals in data.items():
            indicator, condition = key.split('|', 1)
            scores    = vals['scores']
            successes = vals['successes']

            if len(scores) < MIN_SAMPLES_PER_INDICATOR:
                continue

            # حساب الوزن الجديد بناءً على معدل النجاح عند المؤشر > 0
            positive_indices = [i for i, s in enumerate(scores) if s > 0]
            if not positive_indices:
                continue

            success_when_active = sum(successes[i] for i in positive_indices) / len(positive_indices)
            overall_success     = sum(successes) / len(successes)

            # الوزن: كيف يؤثر المؤشر إيجابياً مقارنة بالمتوسط
            if overall_success > 0:
                ratio = success_when_active / overall_success
            else:
                ratio = 1.0

            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, ratio))
            new_weight = round(new_weight, 4)

            # تحديث DB
            await Database.execute("""
                UPDATE indicator_weights
                SET weight       = $1,
                    success_rate = $2,
                    last_updated = NOW()
                WHERE indicator_name    = $3
                AND   market_condition  = $4
            """, new_weight, round(success_when_active, 4), indicator, condition)

            logger.debug(
                f"⚖️ {indicator}/{condition}: "
                f"نجاح عند نشاط={success_when_active:.2f} "
                f"وزن جديد={new_weight}"
            )
            updated += 1

        return updated

    async def get_worst_indicators(self, condition: str = None) -> List[Dict]:
        """المؤشرات الأسوأ أداءً (لمساعدة الـ tuner)"""
        rows = await Database.fetch("""
            SELECT indicator_name, market_condition, weight, success_rate
            FROM indicator_weights
            WHERE ($1::text IS NULL OR market_condition = $1)
            ORDER BY success_rate ASC
            LIMIT 5
        """, condition)

        return [dict(r) for r in rows]
