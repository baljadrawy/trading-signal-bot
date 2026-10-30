"""Design A synthetic fixtures: fabricated UTC daily candles, snapshots and two replay scenarios.

The dates are in 2001-2002, before Bitcoin existed, and the prices come from a seeded stdlib
random walk rounded to cents. They exercise arithmetic and state transitions only and say nothing
about whether Design A earns money."""
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, ".")
from research.design_a import ledger as L  # noqa: E402
from research.design_a import state as S  # noqa: E402
from research.mechanisms.simulate import SYNTHETIC  # noqa: E402

D = Decimal
EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)   # a Monday
OFFSET = timedelta(seconds=S.DECISION_OFFSET_SECONDS)
RULES = S.MinOrderRules(min_notional=D("10"), min_qty=D("0.00001"), qty_step=D("0.00001"))
CASH = D("1000")


def day(n):
    """00:00 UTC on day ``n`` after EPOCH; day 0 and every seventh day after it are Mondays."""
    return EPOCH + S.DAY * n


def at_decision(monday):
    """The decision instant of the Monday that opens at ``monday``."""
    assert monday.weekday() == 0 and S.is_midnight(monday)
    return monday + OFFSET


def candle(open_time, close, open_=None, high=None, low=None):
    close = D(close)
    open_ = close if open_ is None else D(open_)
    high = max(open_, close) if high is None else D(high)
    low = min(open_, close) if low is None else D(low)
    return S.Candle(open_time, open_, high, low, close)


def series(first_open, closes):
    """Consecutive daily candles from ``first_open``; each candle opens at its own close."""
    return [candle(first_open + S.DAY * i, c) for i, c in enumerate(closes)]


def ending(last_open, closes):
    """Consecutive daily candles, the last of which opens at ``last_open``."""
    return series(last_open - S.DAY * (len(closes) - 1), closes)


def snapshot(as_of, candles, hidden=frozenset()):
    """What is known at ``as_of``: every completed candle except those opening at ``hidden``."""
    known = sorted((c for c in candles
                    if S.available_from(c.open_time) <= as_of and c.open_time not in hidden),
                   key=lambda c: c.open_time)
    return S.Snapshot(as_of, tuple(known), SYNTHETIC)


def walk(segments, seed, start=100.0, vol=0.02):
    """Seeded random walk of cent prices; ``segments`` is a sequence of (days, daily drift)."""
    rng = random.Random(seed)
    price, out = start, []
    for days, drift in segments:
        for _ in range(days):
            price = max(0.01, price * math.exp(drift + vol * rng.gauss(0, 1)))
            out.append(D(f"{price:.2f}"))
    return out


def walk_candles(closes, first_open=EPOCH):
    """Continuous daily candles: each one opens at the previous close."""
    out, previous = [], closes[0]
    for i, close in enumerate(closes):
        out.append(candle(first_open + S.DAY * i, close, open_=previous))
        previous = close
    return out


SEGMENTS = ((260, 0.004), (140, -0.006), (140, 0.005))   # up, down, up: forces transitions


def scenario_snapshots(seed=7, outages=None, offset=OFFSET):
    """One snapshot per day at 00:00 UTC + ``offset`` (the Monday ones are decision instants).
    ``outages`` maps a candle's day index to the half-open range of snapshot day indices in which
    it is missing: data that arrive late, or (with a range covering every snapshot) are lost."""
    candles = walk_candles(walk(SEGMENTS, seed))
    outages = outages or {}
    snaps = []
    for k in range(len(candles)):
        hidden = {day(i) for i, (start, stop) in outages.items() if start <= k < stop}
        snaps.append(snapshot(day(k) + offset, candles, hidden))
    return snaps


def scenario(costs=S.BASELINE, seed=7):
    """The state after replaying the clean synthetic scenario from cash."""
    return L.replay(S.initial_state(CASH, costs, RULES), scenario_snapshots(seed))


# The rough scenario: the same prices with late data (temporary outages), a carried dust balance
# and a minimum quantity that rejects a later, smaller buy. Day indices refer to the clean
# scenario, whose first BUY is decided on day 203 and first SELL on day 294.
OUTAGES = {
    204: (204, 206),                                    # Tuesday late: deferred to Wednesday
    295: (295, 299), 296: (295, 299), 297: (295, 299),  # Tuesday-Thursday late: expiry
    349: (349, 351),                                    # a Sunday late at its decision: skip
    330: (357, 358),                                    # a window day missing on day 357: skip
}
ROUGH_RULES = S.MinOrderRules(min_notional=D("10"), min_qty=D("3.9"), qty_step=D("0.00001"))
DUST = D("1E-7")


def rough_start():
    return S.State(cash=CASH, btc=DUST, costs=S.BASELINE, rules=ROUGH_RULES)


def rough_snapshots(seed=7):
    return scenario_snapshots(seed, OUTAGES)


def rough_scenario(seed=7):
    return L.replay(rough_start(), rough_snapshots(seed))
