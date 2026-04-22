"""
Performance Analyzer - يحلل نتائج الصفقات ويحدّث أوزان المؤشرات
"""
import json
import os
from typing import Dict, List
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('optimizer.analyzer')

# حدود الأوزان — MIN=0 يسمح بتصفية المؤشرات الضارة تماماً
MIN_WEIGHT = 0.0
MAX_WEIGHT = 2.5
# الحد الأدنى للصفقات لحساب وزن مؤشر معين
MIN_SAMPLES_PER_INDICATOR = 20

# فاصل زمني: أي صفقة قبل هذا التاريخ تستخدم نظام تسجيل قديم
# ولا يجب استخدامها لضبط الإعدادات الحالية.
# عدّلها عبر env var عند أي rebuild كبير للاستراتيجية.
STRATEGY_REBUILD_AT = os.getenv('STRATEGY_REBUILD_AT', '2026-04-22 20:00:00')


class PerformanceAnalyzer:

    async def get_overall_stats(self) -> Dict:
        """إحصائيات الأداء العام — تستثني الصفقات قبل آخر rebuild للاستراتيجية"""
        row = await Database.fetchrow("""
            SELECT
                COUNT(*)                                        AS total_trades,
                SUM(CASE WHEN tr.result='WIN' THEN 1 ELSE 0 END)  AS wins,
                SUM(CASE WHEN tr.result='LOSS' THEN 1 ELSE 0 END) AS losses,
                AVG(tr.profit_percent)                          AS avg_profit,
                AVG(CASE WHEN tr.result='WIN' THEN tr.profit_percent END) AS avg_win,
                AVG(CASE WHEN tr.result='LOSS' THEN tr.profit_percent END) AS avg_loss
            FROM trade_results tr
            JOIN signals s ON tr.signal_id = s.id
            WHERE tr.result IS NOT NULL
            AND tr.exit_time > NOW() - INTERVAL '30 days'
            AND s.signal_time >= $1::timestamp
        """, STRATEGY_REBUILD_AT)

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
            AND s.signal_time >= $1::timestamp
            GROUP BY s.market_condition
            ORDER BY wr DESC
            LIMIT 1
        """, STRATEGY_REBUILD_AT)

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
        """إحصائيات مقسّمة حسب حالة السوق — صفقات ما بعد rebuild فقط"""
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
            AND s.signal_time >= $1::timestamp
            GROUP BY s.market_condition
        """, STRATEGY_REBUILD_AT)

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
        يحسب أثر كل مؤشر على PnL ويحدّث وزنه في DB.
        المنهجية: مقارنة متوسط الربح/الخسارة عند تفعيل المؤشر مقابل تعطيله.
        مؤشر يحسّن PnL → وزن > 1، مؤشر يضر → وزن < 1، يضر بشدة → وزن 0.
        """
        rows = await Database.fetch("""
            SELECT
                s.market_condition,
                s.score_details,
                tr.profit_percent,
                CASE WHEN tr.result = 'WIN' THEN 1.0 ELSE 0.0 END AS success
            FROM signals s
            JOIN trade_results tr ON s.id = tr.signal_id
            WHERE tr.result IS NOT NULL
            AND tr.exit_time > NOW() - INTERVAL '30 days'
            AND s.signal_time >= $1::timestamp
        """, STRATEGY_REBUILD_AT)

        if not rows:
            return 0

        # تجميع البيانات حسب (indicator, condition)
        data: Dict[str, Dict[str, List]] = {}

        for row in rows:
            condition = row['market_condition']
            success   = float(row['success'])
            pnl       = float(row['profit_percent'] or 0)

            details = row['score_details']
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    continue
            if not isinstance(details, dict):
                continue

            for indicator, value in details.items():
                if isinstance(value, (list, str)):
                    continue
                try:
                    score = float(value)
                except (TypeError, ValueError):
                    continue

                key = f"{indicator}|{condition}"
                if key not in data:
                    data[key] = {'scores': [], 'successes': [], 'pnls': []}
                data[key]['scores'].append(score)
                data[key]['successes'].append(success)
                data[key]['pnls'].append(pnl)

        updated = 0

        for key, vals in data.items():
            indicator, condition = key.split('|', 1)
            scores    = vals['scores']
            successes = vals['successes']
            pnls      = vals['pnls']

            if len(scores) < MIN_SAMPLES_PER_INDICATOR:
                continue

            active_idx = [i for i, s in enumerate(scores) if s > 0]
            off_idx    = [i for i, s in enumerate(scores) if s == 0]

            # المؤشر الذي لا يُفعَّل أبداً → وزن 0 (إزالة من الحسبة)
            if len(active_idx) < MIN_SAMPLES_PER_INDICATOR:
                new_weight = 0.0
                pnl_active = 0.0
                success_when_active = 0.0
            elif len(off_idx) < MIN_SAMPLES_PER_INDICATOR:
                # المؤشر دائماً مفعّل — لا يمكن قياس أثره، اتركه محايداً
                new_weight = 1.0
                pnl_active = sum(pnls[i] for i in active_idx) / len(active_idx)
                success_when_active = sum(successes[i] for i in active_idx) / len(active_idx)
            else:
                pnl_active = sum(pnls[i] for i in active_idx) / len(active_idx)
                pnl_off    = sum(pnls[i] for i in off_idx) / len(off_idx)
                success_when_active = sum(successes[i] for i in active_idx) / len(active_idx)

                # PnL lift: كم يحسّن المؤشر متوسط الربح
                # lift > 0 → نافع | lift < 0 → ضار
                lift = pnl_active - pnl_off
                # كل 1% lift يضيف 0.5 للوزن (مؤشر يحسّن 1% → وزن 1.5)
                new_weight = 1.0 + lift * 0.5

            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            new_weight = round(new_weight, 4)

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
                f"PnL_active={pnl_active:.2f}% وزن={new_weight}"
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
