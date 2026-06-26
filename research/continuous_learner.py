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
try:
    from shared.macro_context import classify_usdtd_trend, should_block
except Exception:
    classify_usdtd_trend = None
    should_block = None

logger = setup_logger('continuous_learner')


async def send_status_digest():
    """ملخّص حالة يومي إلى Telegram: ماكرو + جمع الإشارات + تقدّم الإحماء + خلايا التعلّم.
    يُرسَل دائماً (حتى أثناء الإحماء) قبل منطق التعلّم."""
    # ── الماكرو ──
    mrows = await Database.fetch(
        "SELECT date, usdt_d, btc_d, btc_trend, eth_trend FROM macro_history ORDER BY date DESC LIMIT 4")
    if mrows:
        latest = mrows[0]
        usdt_now = float(latest['usdt_d'] or 0)
        prior = [float(r['usdt_d']) for r in mrows[1:] if r['usdt_d'] is not None]
        avg_3d = (sum(prior) / len(prior)) if prior else usdt_now
        usdtd_trend = (classify_usdtd_trend(usdt_now, avg_3d, config.USDTD_SPIKE_PP)
                       if classify_usdtd_trend else 'n/a')
        blocking = (should_block((latest['btc_trend'] or 'neutral'), usdtd_trend)
                    if should_block else False)
        macro_line = (f"🌍 BTC={latest['btc_trend']} ETH={latest['eth_trend']} "
                      f"USDT.D={usdt_now:.2f}({usdtd_trend}) BTC.D={float(latest['btc_d'] or 0):.1f}"
                      f" | البوابة: {'🔴 تحجب' if blocking else '🟢 مفتوحة'}")
    else:
        macro_line = "🌍 لا بيانات ماكرو بعد"
    # ── جمع الإشارات الموسومة ──
    total_tagged = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE trade_type IS NOT NULL") or 0
    byrows = await Database.fetch(
        "SELECT trade_type, timeframe, COUNT(*) c FROM signals WHERE trade_type IS NOT NULL "
        "GROUP BY 1,2 ORDER BY 1,2")
    by_line = ", ".join(f"{r['trade_type'][:3]}/{r['timeframe']}={r['c']}" for r in byrows) or "—"
    closed = await Database.fetchval(
        "SELECT COUNT(*) FROM trade_results tr JOIN signals s ON tr.signal_id=s.id "
        "WHERE s.trade_type IS NOT NULL") or 0
    warm_line = (f"🎯 موسومة: {total_tagged} ({by_line}) | مغلقة: {closed}/{config.WARMUP_N} للإحماء")
    # ── خلايا التعلّم ──
    lg = await Database.fetch(
        "SELECT trade_type, macro_state, timeframe, n, wr, expectancy, weight FROM learned_gates "
        "WHERE n>=$1 ORDER BY expectancy DESC", config.MIN_CELL_N)
    if lg:
        throttled = sum(1 for r in lg if float(r['weight'] or 0) <= 0)
        t = lg[0]
        lg_line = (f"🏆 خلايا: {len(lg)} (مخنوقة {throttled}). الأفضل: "
                   f"{t['trade_type']}/{t['macro_state']}/{t['timeframe']} "
                   f"E={float(t['expectancy']):.3f} WR={float(t['wr']):.0f}% n={t['n']}")
    else:
        lg_line = "🏆 المتعلّم: لا خلايا مؤكَّدة بعد (إحماء)"
    msg = "📊 ملخّص التعلّم الحي (يومي)\n" + macro_line + "\n" + warm_line + "\n" + lg_line
    logger.info(msg)
    if send_alert:
        try:
            await send_alert(msg, level='info', component='LiveLearning')
        except Exception as e:
            logger.warning(f"digest send failed: {e}")


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
    # ملخّص الحالة اليومي يُرسَل دائماً (حتى أثناء الإحماء) قبل منطق التعلّم
    try:
        await send_status_digest()
    except Exception as e:
        logger.warning(f"status digest failed: {e}")
    closed = await Database.fetchval("SELECT COUNT(*) FROM trade_results tr JOIN signals s ON tr.signal_id = s.id WHERE s.trade_type IS NOT NULL")
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
