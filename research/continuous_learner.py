"""التعلّم الحي المستمرّ: نافذة متحرّكة → أوزان learned_gates لكل (نوع × ماكرو × إطار)."""
import asyncio
from collections import defaultdict
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
try:
    from shared.alerts import send_alert
except Exception:
    send_alert = None

logger = setup_logger('continuous_learner')


def compute_cells(trades, min_cell_n: int, throttle_expectancy: float):
    groups = defaultdict(list)
    for t in trades:
        groups[(t['trade_type'], t['macro_state'], t['timeframe'])].append(t)
    out = []
    for (tt, ms, tf), items in groups.items():
        n = len(items)
        wins = sum(1 for x in items if x['is_win'])
        exp = sum(float(x['profit_percent']) for x in items) / n
        if n >= min_cell_n:
            weight = 1.0 if exp > throttle_expectancy else 0.0
        else:
            weight = 1.0
        out.append({'trade_type': tt, 'macro_state': ms, 'timeframe': tf,
                    'n': n, 'wr': round(wins / n * 100, 1), 'expectancy': round(exp, 4),
                    'weight': weight})
    return out


async def run():
    closed = await Database.fetchval("SELECT COUNT(*) FROM trade_results")
    if (closed or 0) < config.WARMUP_N:
        logger.info(f"warm-up: {closed}/{config.WARMUP_N} closed trades; skipping learning")
        return
    rows = await Database.fetch(
        """SELECT s.trade_type, s.macro_snapshot, s.timeframe, tr.profit_percent,
                  (tr.result='WIN') AS is_win
           FROM trade_results tr JOIN signals s ON tr.signal_id = s.id
           WHERE s.trade_type IS NOT NULL
           ORDER BY tr.exit_time DESC LIMIT $1""", config.ROLL_N)
    trades = []
    for r in rows:
        ms = r['macro_snapshot'] or {}
        if isinstance(ms, str):
            import json; ms = json.loads(ms)
        trades.append({'trade_type': r['trade_type'],
                       'macro_state': f"usdtd_{ms.get('usdtd_trend', 'flat')}",
                       'timeframe': r['timeframe'], 'profit_percent': r['profit_percent'],
                       'is_win': r['is_win']})
    cells = compute_cells(trades, config.MIN_CELL_N, config.THROTTLE_EXPECTANCY)
    for c in cells:
        await Database.execute(
            """INSERT INTO learned_gates (trade_type, macro_state, timeframe, n, wr, expectancy, weight, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
               ON CONFLICT (trade_type, macro_state, timeframe)
               DO UPDATE SET n=$4, wr=$5, expectancy=$6, weight=$7, updated_at=NOW()""",
            c['trade_type'], c['macro_state'], c['timeframe'], c['n'], c['wr'], c['expectancy'], c['weight'])
    winners = sorted([c for c in cells if c['weight'] > 0 and c['n'] >= config.MIN_CELL_N],
                     key=lambda x: x['expectancy'], reverse=True)[:5]
    losers = [c for c in cells if c['weight'] == 0]
    msg = ("📚 Learner: " + f"{len(cells)} cells, {len(losers)} throttled.\n" +
           "Top: " + ", ".join(f"{c['trade_type']}/{c['macro_state']}/{c['timeframe']}(E={c['expectancy']},n={c['n']})" for c in winners))
    logger.info(msg)
    if send_alert:
        try:
            await send_alert(msg, level='info', component='Learner')
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run())
