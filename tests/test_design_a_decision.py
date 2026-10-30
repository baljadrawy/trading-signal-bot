"""Design A v1.0 signal (brief items 1-5, 8): warm-up, the SMA200, the strict comparison, the
Sunday close, the decision instant and the missing-Sunday skip. Synthetic only."""
import sys
from datetime import timedelta
from decimal import Decimal as D

import pytest

sys.path.insert(0, ".")
import design_a_synthetic as syn  # noqa: E402
from research.design_a import decision as X  # noqa: E402
from research.design_a import ledger as L  # noqa: E402
from research.design_a import state as S  # noqa: E402

MONDAY = syn.day(203)
SUNDAY = MONDAY - S.DAY
DECISION = syn.at_decision(MONDAY)
E, LONG, FLAT = S.Event, S.Target.LONG, S.Target.FLAT


def fresh():
    return S.initial_state(syn.CASH, S.BASELINE, syn.RULES)


def holding(btc="5", target=LONG, rules=syn.RULES):
    return S.State(cash=D("0"), btc=D(btc), costs=S.BASELINE, rules=rules, target=target)


def decide(closes, state=None, extra=(), at=DECISION):
    return X.decide(state or fresh(), syn.snapshot(at, syn.ending(SUNDAY, closes) + list(extra)))


def test_the_primary_window_is_200():
    assert X.SMA_WINDOW == 200


def test_199_completed_candles_give_no_actionable_signal():                      # item 1
    state = fresh()
    d = decide(["100"] * 199, state, extra=[syn.candle(MONDAY, "500")])  # still open: never seen
    assert (d.event, d.target, d.action, d.reason) == (E.WARMUP, None, None, "INSUFFICIENT_HISTORY")
    after = L.apply_decision(state, d)
    assert [e.event for e in after.ledger] == [E.WARMUP]
    assert (after.cash, after.btc, after.target, after.pending) == (syn.CASH, 0, None, None)


def test_200_completed_candles_give_a_valid_sma():                               # item 2
    closes = [str(100 + i) for i in range(200)]
    d = decide(closes)
    assert d.sma == D("199.5") and d.sunday_close == D("299")
    assert (d.event, d.target, d.action) == (E.DECIDE_LONG, LONG, S.Side.BUY)


def test_greater_than_is_strict_and_equality_is_flat():                          # item 3
    base = ["99", "101"] * 99 + ["100"]       # 199 closes that sum to 199 x 100
    for sunday, target in (("100", FLAT), ("100.01", LONG), ("99.99", FLAT)):
        assert decide(base + [sunday]).target is target, sunday
    tie = decide(base + ["100"])
    assert tie.sma == tie.sunday_close == D("100") and tie.event is E.DECIDE_FLAT


def test_equality_is_exact_where_binary_floats_are_not():
    running = 0.0
    for _ in range(200):
        running += 0.1
    assert running / 200 != 0.1          # a naively accumulated float SMA misses the exact tie
    d = decide(["0.1"] * 200)
    assert d.sma == d.sunday_close == D("0.1") and d.target is FLAT


def test_only_the_sunday_close_is_compared():                                    # item 4
    closes = ["100"] * 198 + ["500", "90"]                # Saturday 500, Sunday 90
    d = decide(closes, extra=[syn.candle(MONDAY, "1000")])
    assert d.sunday_close == D("90") and d.sma == D("101.95") and d.target is FLAT


def test_non_decision_instants_give_no_signal_and_change_nothing():              # item 5
    state = fresh()
    for at in (MONDAY + timedelta(seconds=29), DECISION + timedelta(seconds=1), DECISION + S.DAY,
               DECISION - S.DAY):
        d = decide(["100"] * 199 + ["120"], state, at=at)
        assert (d.event, d.target, d.reason) == (E.NO_SIGNAL, None, "NOT_DECISION_INSTANT")
        assert L.apply_decision(state, d) is state
    assert decide(["100"] * 199 + ["120"], state).event is E.DECIDE_LONG


def test_a_missing_sunday_skips_the_decision_and_keeps_holdings():               # item 8
    state = holding()
    candles = [c for c in syn.ending(SUNDAY, ["100"] * 260) if c.open_time != SUNDAY]
    d = X.decide(state, syn.snapshot(DECISION, candles))
    assert (d.event, d.target, d.reason) == (E.SKIP_MISSING_SUNDAY, None, "SUNDAY_CANDLE_UNAVAILABLE")
    after = L.apply_decision(state, d)
    assert (after.cash, after.btc, after.target, after.pending) == (state.cash, state.btc, LONG, None)
    assert [e.event for e in after.ledger] == [E.SKIP_MISSING_SUNDAY]


def test_a_gap_in_the_window_skips_the_decision_and_keeps_holdings():
    state = holding()
    candles = [c for c in syn.ending(SUNDAY, ["100"] * 260) if c.open_time != SUNDAY - 30 * S.DAY]
    d = X.decide(state, syn.snapshot(DECISION, candles))
    assert (d.event, d.reason) == (E.SKIP_INVALID_DATA, "GAP_IN_WINDOW")
    assert L.apply_decision(state, d).btc == state.btc


def test_warm_up_is_only_the_initial_one():
    late_start = ["100"] * 150
    assert decide(late_start, fresh()).event is E.WARMUP
    d = decide(late_start, holding())          # an actionable decision was already taken
    assert (d.event, d.reason) == (E.SKIP_INVALID_DATA, "INSUFFICIENT_HISTORY")


def test_the_action_is_a_genuine_state_transition():
    up, down = ["100"] * 199 + ["120"], ["100"] * 199 + ["80"]
    assert decide(up, fresh()).action is S.Side.BUY                  # first target, from cash
    assert decide(down, fresh()).action is None                      # first target, already there
    assert decide(up, holding()).action is None                      # unchanged target
    assert decide(down, holding()).action is S.Side.SELL             # target changes
    # provisional F10 reading: an unchanged target never trades, even if the position differs
    stranded = S.State(cash=syn.CASH, btc=D("0"), costs=S.BASELINE, rules=syn.RULES, target=LONG)
    assert decide(up, stranded).action is None
    assert decide(down, stranded).action is None                     # already FLAT in fact
    dust = holding("0.000001", target=FLAT)                          # below one step: FLAT
    assert S.actual_position(dust) is FLAT and decide(up, dust).action is S.Side.BUY
    small = holding("0.0005", target=FLAT,                           # a whole step, below min_qty
                    rules=S.MinOrderRules(D("1"), D("0.001"), D("0.00001")))
    assert S.actual_position(small) is FLAT and decide(up, small).action is S.Side.BUY


def test_values_beyond_exact_decimal_arithmetic_are_refused():
    with pytest.raises(S.DesignAError, match="exact Decimal"):
        decide(["1234567890.123456789012345678"] * 200)


def test_decide_is_pure():
    state, snap = fresh(), syn.snapshot(DECISION, syn.ending(SUNDAY, ["100"] * 199 + ["120"]))
    before = L.digest(state)
    first, second = X.decide(state, snap), X.decide(state, snap)
    assert first == second and L.digest(state) == before and state.ledger == ()
