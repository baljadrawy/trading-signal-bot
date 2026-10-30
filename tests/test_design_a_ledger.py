"""Design A v1.0 execution and accounting (brief items 7, 9-22, 24 and invalid transitions):
pending transitions, the Tuesday reference, deferral and expiry, the frozen cost formulas, minimum
orders, dust, conservation and deterministic replay. Synthetic only; nothing here measures
profitability."""
import functools
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal as D

import pytest

sys.path.insert(0, ".")
import design_a_synthetic as syn  # noqa: E402
from research.design_a import ledger as L  # noqa: E402
from research.design_a import state as S  # noqa: E402
from research.design_a import timing as T  # noqa: E402
from research.mechanisms.costs import CostModelError  # noqa: E402

E, LONG, FLAT, BUY, SELL = S.Event, S.Target.LONG, S.Target.FLAT, S.Side.BUY, S.Side.SELL
MONDAY = syn.day(203)
TUE, WED, THU, FRI, SAT = (MONDAY + k * S.DAY for k in range(1, 6))
DECISION = syn.at_decision(MONDAY)
WEEK = S.WEEK
COARSE = S.MinOrderRules(D("1"), D("0.001"), D("0.001"))
RECORDED_EVENTS = set(S.Event) - {E.NO_SIGNAL}


def at(day):
    """The daily check used throughout: 30 seconds after 00:00 UTC on ``day``."""
    return day + syn.OFFSET


def fresh(cash="1000", costs=S.BASELINE, rules=syn.RULES):
    return S.initial_state(D(cash), costs, rules)


def holding(btc, cash="0", rules=syn.RULES):
    return S.State(cash=D(cash), btc=D(btc), costs=S.BASELINE, rules=rules, target=LONG)


def signal(when, target, action=None):
    """A decision for ``target`` whose Sunday close and SMA agree with F5."""
    event, close = (E.DECIDE_LONG, D("101")) if target is LONG else (E.DECIDE_FLAT, D("99"))
    return S.Decision(when, event, target, action=action, sunday_close=close, sma=D("100"))


def decided(state, target, when=DECISION):
    """Apply a decision for ``target`` (the signal itself is tested in test_design_a_decision)."""
    return L.apply_decision(state, signal(when, target, S.required_action(state, target)))


def reference(day, open_, close=None):
    return syn.candle(day, close or open_, open_=open_)


def fill(state, open_="100", day=TUE, check=None):
    """Execute the pending transition at the open of the candle opening on ``day``."""
    return L.execute_pending(state, syn.snapshot(check or at(day + S.DAY), [reference(day, open_)]))


def events(state, n=None):
    names = [e.event for e in state.ledger]
    return names if n is None else names[-n:]


def executed(state):
    return [e for e in state.ledger if e.event is E.EXECUTED]


def round_trip(costs, buy_open="100", sell_open="110"):
    """FLAT -> LONG at a Tuesday open, then LONG -> FLAT at the next Tuesday open."""
    long = fill(decided(fresh(costs=costs), LONG), buy_open)
    return long, fill(decided(long, FLAT, DECISION + WEEK), sell_open, day=TUE + WEEK)


@functools.cache
def scenario():
    return syn.scenario()


@functools.cache
def rough():
    return syn.rough_scenario()


# --- pending transitions: the Tuesday reference, deferral and expiry ---------------------------

def test_the_tuesday_open_executes_after_the_monday_decision():                  # item 7
    state = decided(fresh(), LONG)
    assert events(state) == [E.DECIDE_LONG, E.PENDING_BUY]
    assert (state.cash, state.btc, state.execution_status) == (D("1000"), 0, S.ExecutionStatus.PENDING)
    assert state.pending.next_open == TUE and state.pending.expires_at == DECISION + 3 * S.DAY
    assert state.ledger[-1].expires_at == DECISION + 3 * S.DAY
    monday, tuesday = reference(MONDAY, "80"), reference(TUE, "100", "105")
    assert L.execute_pending(state, syn.snapshot(at(TUE), [monday, tuesday])) == state  # not done
    for check in (at(WED), at(SAT)):          # the booking does not depend on when we look
        done = L.execute_pending(state, syn.snapshot(check, [monday, tuesday]))
        e = done.ledger[-1]
        assert (e.event, e.side, e.reference_time, e.reference_price) == (E.EXECUTED, BUY, TUE, D("100"))
        assert e.decided_at == DECISION < e.reference_time and e.at == WED
        assert done.pending is None and done.execution_status is S.ExecutionStatus.EXECUTED
        assert S.actual_position(done) is LONG and done.target is LONG


def test_a_missing_tuesday_defers_to_the_next_available_candle():                # item 9
    state = decided(fresh(), LONG)
    wednesday = reference(WED, "104", "110")
    deferred = L.execute_pending(state, syn.snapshot(at(WED), [wednesday]))
    missing = deferred.ledger[-1]
    assert (missing.event, missing.reference_time, missing.at) == (E.MISSING_MARKET_DATA, TUE, WED)
    assert deferred.execution_status is S.ExecutionStatus.DEFERRED and deferred.pending.next_open == WED
    assert (deferred.cash, deferred.btc) == (state.cash, state.btc)
    late_tuesday = reference(TUE, "50")      # turns up after it was recorded missing: never used
    done = L.execute_pending(deferred, syn.snapshot(at(THU), [late_tuesday, wednesday]))
    e = done.ledger[-1]
    assert (e.event, e.reference_time, e.reference_price, e.at) == (E.EXECUTED, WED, D("104"), THU)


def test_the_thursday_open_is_the_last_eligible_reference():
    thursday = reference(THU, "130")
    done = L.execute_pending(decided(fresh(), LONG), syn.snapshot(at(FRI), [thursday]))
    assert events(done, 3) == [E.MISSING_MARKET_DATA, E.MISSING_MARKET_DATA, E.EXECUTED]
    assert (done.ledger[-1].reference_time, done.ledger[-1].reference_price) == (THU, D("130"))


def test_three_day_expiry_cancels_and_keeps_holdings():                          # item 10
    state = decided(fresh(), LONG)
    friday = reference(FRI, "120")           # opens after the three-day window: never eligible
    for day in (WED, THU):
        state = L.execute_pending(state, syn.snapshot(at(day), [friday]))
        assert state.pending is not None and state.execution_status is S.ExecutionStatus.DEFERRED
    expired = L.execute_pending(state, syn.snapshot(at(FRI), [friday]))
    assert events(expired) == [E.DECIDE_LONG, E.PENDING_BUY] + [E.MISSING_MARKET_DATA] * 3 + [E.EXPIRED]
    assert [e.reference_time for e in expired.ledger[2:5]] == [TUE, WED, THU]
    cancel = expired.ledger[-1]
    assert (cancel.at, cancel.expires_at, cancel.decided_at) == (FRI, DECISION + 3 * S.DAY, DECISION)
    assert expired.pending is None and expired.execution_status is S.ExecutionStatus.EXPIRED
    assert (expired.cash, expired.btc) == (D("1000"), 0)
    assert set(L.cost_totals(expired).values()) == {0}
    late = L.execute_pending(decided(fresh(), LONG), syn.snapshot(at(SAT + S.DAY), [friday]))
    assert late.ledger == expired.ledger      # a single late look records exactly the same


def test_after_expiry_an_unchanged_target_does_not_trade():
    """Provisional F10 reading (spec §7, §19 item 11): no trade while the target is unchanged,
    even though the expired buy left the position FLAT; the next change of target decides."""
    expired = L.execute_pending(decided(fresh(), LONG), syn.snapshot(at(FRI), []))
    again = decided(expired, LONG, DECISION + WEEK)
    assert events(again, 2) == [E.DECIDE_LONG, E.NO_CHANGE] and again.pending is None
    assert again.ledger[-1].reason == "TARGET_UNCHANGED" and again.cash == D("1000")
    flat = decided(again, FLAT, DECISION + 2 * WEEK)
    assert (events(flat, 1), flat.ledger[-1].reason) == ([E.NO_CHANGE], "ALREADY_AT_TARGET")
    assert flat.target is FLAT
    long = decided(flat, LONG, DECISION + 3 * WEEK)
    assert events(long, 2) == [E.DECIDE_LONG, E.PENDING_BUY]


# --- transitions ---------------------------------------------------------------------------------

def test_flat_to_long_and_long_to_flat():                                        # items 11, 12
    long, flat = round_trip(S.BASELINE)
    assert S.actual_position(long) is LONG and long.btc == D("9.98002")
    assert events(flat, 3) == [E.DECIDE_FLAT, E.PENDING_SELL, E.EXECUTED]
    assert S.actual_position(flat) is FLAT and flat.btc == 0 and flat.target is FLAT
    assert [e.side for e in executed(flat)] == [BUY, SELL]


def test_an_unchanged_target_never_rebalances():                                 # item 13
    long = fill(decided(fresh(), LONG))
    again = decided(long, LONG, DECISION + WEEK)
    assert events(again, 2) == [E.DECIDE_LONG, E.NO_CHANGE] and again.pending is None
    assert again.ledger[-1].reason == "TARGET_UNCHANGED"
    assert (again.cash, again.btc) == (long.cash, long.btc) == (D("0.000997998"), D("9.98002"))
    flat = decided(fresh(), FLAT)
    assert events(flat) == [E.DECIDE_FLAT, E.NO_CHANGE] and flat.pending is None
    assert (flat.ledger[-1].reason, flat.target, flat.cash) == ("ALREADY_AT_TARGET", FLAT, D("1000"))


# --- the frozen cost model -----------------------------------------------------------------------

def test_baseline_fee_arithmetic():                                              # item 14
    long, flat = round_trip(S.BASELINE)
    buy, sell = executed(flat)
    assert (buy.execution_price, buy.quantity, buy.notional, buy.fee) == (
        D("100.1"), D("9.98002"), D("999.000002"), D("0.999000002"))
    assert long.cash == D("0.000997998")
    assert (sell.execution_price, sell.notional, sell.fee) == (
        D("109.89"), D("1096.7043978"), D("1.0967043978"))
    assert sell.notional - sell.fee == D("1095.6076934022")
    assert flat.cash == D("0.000997998") + D("1095.6076934022")
    # the brief's closed forms, evaluated directly
    assert long.cash == D("1000") - buy.quantity * buy.execution_price * (1 + S.BASELINE.fee)
    assert sell.notional - sell.fee == buy.quantity * sell.execution_price * (1 - S.BASELINE.fee)


def test_stress_fee_arithmetic():                                                # item 15
    long, flat = round_trip(S.STRESS)
    buy, sell = executed(flat)
    assert (buy.execution_price, buy.quantity, buy.notional, buy.fee) == (
        D("100.2"), D("9.97006"), D("999.000012"), D("0.999000012"))
    assert long.cash == D("0.000987988")
    assert (sell.execution_price, sell.notional - sell.fee) == (D("109.78"), D("1093.4186736132"))


def test_the_frozen_rates():
    assert (S.BASELINE.fee, S.BASELINE.half_spread, S.BASELINE.slippage) == (
        D("0.001"), D("0.0005"), D("0.0005"))
    assert (S.STRESS.fee, S.STRESS.half_spread, S.STRESS.slippage) == (
        D("0.001"), D("0.001"), D("0.001"))
    assert 2 * (S.BASELINE.fee + S.BASELINE.half_spread + S.BASELINE.slippage) == D("0.004")
    assert 2 * (S.STRESS.fee + S.STRESS.half_spread + S.STRESS.slippage) == D("0.006")


def test_spread_and_slippage_are_applied_inside_the_price():                     # item 16
    _, flat = round_trip(S.BASELINE)
    for e, sign in zip(executed(flat), (1, -1)):
        assert e.spread_cost == e.quantity * e.reference_price * D("0.0005")
        assert e.slippage_cost == e.quantity * e.reference_price * D("0.0005")
        assert e.notional == e.quantity * e.reference_price + sign * (e.spread_cost + e.slippage_cost)
    spread_only = S.CostSpec(D("0.001"), D("0.0005"), D("0"), "spread_only")
    slippage_only = S.CostSpec(D("0.001"), D("0"), D("0.0005"), "slippage_only")
    for spec in (spread_only, slippage_only):
        e = executed(fill(decided(fresh(costs=spec), LONG)))[0]
        expected = (e.quantity * D("0.05"), 0)
        assert e.execution_price == D("100.05")
        assert (e.spread_cost, e.slippage_cost) == (expected if spec is spread_only else expected[::-1])


def test_costs_are_counted_once_and_only_on_fills():                             # item 17
    _, flat = round_trip(S.BASELINE, "100", "100")      # the same reference price both ways
    totals = L.cost_totals(flat)
    assert D("1000") - flat.cash == totals["fee"] + totals["spread_cost"] + totals["slippage_cost"]
    for e in executed(flat):
        assert e.fee == e.notional * S.BASELINE.fee
    for state in (flat, scenario(), rough()):
        for e in state.ledger:
            charged = (e.fee, e.spread_cost, e.slippage_cost) != (None, None, None)
            assert charged == (e.event is E.EXECUTED), e


# --- minimum orders and dust ---------------------------------------------------------------------

def test_minimum_order_rejection_preserves_balances_and_invents_no_fill():       # item 18
    rejected = fill(decided(fresh(rules=S.MinOrderRules(D("2000"), D("0.00001"), D("0.00001"))), LONG))
    e = rejected.ledger[-1]
    assert (e.event, e.reason, e.quantity, e.at) == (E.REJECTED_MIN_ORDER, "BELOW_MIN_NOTIONAL",
                                                     D("9.98002"), WED)
    assert (rejected.cash, rejected.btc, rejected.pending) == (D("1000"), 0, None)
    assert rejected.execution_status is S.ExecutionStatus.REJECTED_MIN_ORDER
    assert e.fee is None and set(L.cost_totals(rejected).values()) == {0}
    by_qty = fill(decided(fresh(rules=S.MinOrderRules(D("0"), D("20"), D("0.00001"))), LONG))
    assert by_qty.ledger[-1].reason == "BELOW_MIN_QTY" and by_qty.cash == D("1000")
    crumbs = fresh(cash="0.0005", rules=S.MinOrderRules(D("0"), D("0"), D("0.00001")))
    zero = fill(decided(crumbs, LONG))
    assert zero.ledger[-1].reason == "ZERO_QUANTITY" and zero.cash == D("0.0005")
    kept = fill(decided(holding("0.05"), FLAT))          # 0.05 x 99.9 = 4.995 < 10 minimum notional
    assert (kept.ledger[-1].event, kept.ledger[-1].reason) == (E.REJECTED_MIN_ORDER, "BELOW_MIN_NOTIONAL")
    assert kept.btc == D("0.05") and S.actual_position(kept) is LONG and kept.target is FLAT
    v = L.valuation(kept, D("100"))                      # the unsold BTC is reported, not hidden
    assert (v.target, v.position, v.residual_btc, v.residual_value) == (FLAT, LONG, D("0.05"), D("5"))


def test_residual_btc_is_preserved():                                            # item 19
    sold = fill(decided(holding("1.234567", rules=COARSE), FLAT))
    sell, dust = sold.ledger[-2:]
    assert (sell.event, sell.quantity, sold.btc) == (E.EXECUTED, D("1.234"), D("0.000567"))
    assert (dust.event, dust.reason, dust.quantity) == (E.RESIDUAL_DUST, "BELOW_QTY_STEP", D("0.000567"))
    assert S.actual_position(sold) is FLAT
    kept = decided(sold, FLAT, DECISION + WEEK)
    assert events(kept, 1) == [E.NO_CHANGE] and kept.btc == D("0.000567")
    bought = fill(decided(kept, LONG, DECISION + 2 * WEEK), day=TUE + 2 * WEEK)
    assert bought.btc == D("0.000567") + bought.ledger[-1].quantity


def test_dust_is_marked_to_market():                                             # item 20
    sold = fill(decided(holding("1.234567", rules=COARSE), FLAT))
    assert sold.ledger[-1].mark_price == D("100")
    for mark, value in ((D("100"), D("0.0567")), (D("150"), D("0.08505"))):
        v = L.valuation(sold, mark)
        assert (v.position, v.residual_btc, v.residual_value) == (FLAT, D("0.000567"), value)
        assert v.equity == sold.cash + value and v.residual_cash == 0
    v = L.valuation(fill(decided(fresh(), LONG)), D("100"))
    assert (v.position, v.residual_btc, v.residual_cash) == (LONG, 0, D("0.000997998"))
    snap = syn.snapshot(at(WED), [reference(TUE, "100", "101"), reference(WED, "120")])
    assert L.mark_price(snap) == D("101")     # the latest completed close, not the open candle


# --- the replays: coverage, conservation, determinism, interruption -------------------------------

def test_the_clean_scenario_trades_on_the_weekly_schedule():
    sides = [e.side for e in executed(scenario())]
    assert len(sides) >= 2 and all(s is (BUY if i % 2 == 0 else SELL) for i, s in enumerate(sides))
    decisions = [e for e in scenario().ledger if e.event in S.DECISION_EVENTS]
    assert decisions and all(T.is_decision_instant(e.at) for e in decisions)
    assert decisions[0].event is E.WARMUP
    assert all(e.reference_time.weekday() == 1 for e in executed(scenario()))   # Tuesday opens


def test_the_rough_scenario_reaches_every_recorded_event():
    assert {e.event for e in rough().ledger} == RECORDED_EVENTS
    dust = next(e for e in rough().ledger if e.event is E.RESIDUAL_DUST)
    assert dust.record()["quantity"] == "1E-7"


@pytest.mark.parametrize("which", ["scenario", "rough"])
def test_ledger_conservation(which):                                             # item 21
    state, rules = (scenario(), syn.RULES) if which == "scenario" else (rough(), syn.ROUGH_RULES)
    cash, btc = syn.CASH, (D(0) if which == "scenario" else syn.DUST)
    assert [e.seq for e in state.ledger] == list(range(len(state.ledger)))
    assert all(a.at <= b.at for a, b in zip(state.ledger, state.ledger[1:]))
    for e in state.ledger:
        if e.event is E.EXECUTED:
            gross = e.quantity * e.reference_price
            assert e.fee == e.notional * S.BASELINE.fee
            if e.side is BUY:
                assert cash == e.cash + e.notional + e.fee and e.btc - btc == e.quantity
                assert e.notional == gross + e.spread_cost + e.slippage_cost
                assert e.cash < e.execution_price * (1 + S.BASELINE.fee) * rules.qty_step
            else:
                assert e.cash - cash == e.notional - e.fee and btc - e.btc == e.quantity
                assert e.notional == gross - e.spread_cost - e.slippage_cost
                assert e.btc < rules.qty_step                       # only dust stays
        else:
            assert (e.cash, e.btc) == (cash, btc), e      # nothing but a fill moves a balance
        cash, btc = e.cash, e.btc
    assert (cash, btc) == (state.cash, state.btc)
    assert L.cost_totals(state)["fee"] == sum(e.fee for e in executed(state))


def test_replay_is_deterministic():                                              # item 22
    expected = {"scenario": L.digest(scenario()), "rough_scenario": L.digest(rough())}
    assert L.digest(syn.scenario()) == expected["scenario"]
    assert L.digest(syn.rough_scenario()) == expected["rough_scenario"]
    hostile = ("import sys, decimal; sys.path[:0] = ['.', 'tests']; "
               "decimal.DefaultContext.Emax = 3; decimal.DefaultContext.capitals = 0; "
               "decimal.setcontext(decimal.Context(prec=3, capitals=0)); "
               "import design_a_synthetic as syn; from research.design_a import ledger as L; ")
    for name, digest in expected.items():
        for seed in ("0", "4242"):      # other hash seeds, and a hostile ambient decimal context
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": seed,
                   "PYTHONDONTWRITEBYTECODE": "1"}
            out = subprocess.run([sys.executable, "-c", hostile + f"print(L.digest(syn.{name}()))"],
                                 capture_output=True, text=True, env=env, timeout=300, check=True)
            assert out.stdout.strip() == digest, (name, seed)


FOREVER = (0, 10**6)
CADENCE_CASES = {     # data that never arrive late: the clean path, and candles lost for good
    "clean": (syn.CASH, False, {}, {E.EXECUTED}),
    "thursday_fill_rejection_dust": (syn.CASH, True, {204: FOREVER, 205: FOREVER},
                                     {E.MISSING_MARKET_DATA, E.EXECUTED, E.REJECTED_MIN_ORDER,
                                      E.RESIDUAL_DUST}),
    "expiry": (syn.CASH, False, {204: FOREVER, 205: FOREVER, 206: FOREVER},
               {E.MISSING_MARKET_DATA, E.EXPIRED}),
}


@pytest.mark.parametrize("case", sorted(CADENCE_CASES))
def test_the_ledger_does_not_depend_on_the_check_cadence(case):
    cash, rough_start, losses, expected = CADENCE_CASES[case]
    start = syn.rough_start() if rough_start else S.initial_state(cash, S.BASELINE, syn.RULES)
    daily = syn.scenario_snapshots(outages=losses)
    whole = L.replay(start, daily)
    weekly = [s for s in daily if T.is_decision_instant(s.as_of)]
    sparse = [s for i, s in enumerate(daily) if i % 3 == 0 or T.is_decision_instant(s.as_of)]
    for cadence in (weekly, sparse):
        assert L.digest(L.replay(start, cadence)) == L.digest(whole)
    assert expected <= {e.event for e in whole.ledger}
    if rough_start:
        assert any(e.event is E.EXECUTED and e.reference_time.weekday() == 3 for e in whole.ledger)


def test_replay_refuses_revised_candles_and_resumes_into_the_past():
    snaps = syn.scenario_snapshots()[:12]
    old = snaps[10].candles[3]
    new = S.Candle(old.open_time, old.open, old.high * 2, old.low, old.close)
    revised = snaps[:10] + [S.Snapshot(snaps[10].as_of, tuple(new if c is old else c
                                                               for c in snaps[10].candles),
                                       snaps[10].permission)]
    start = S.initial_state(syn.CASH, S.BASELINE, syn.RULES)
    with pytest.raises(S.DesignAError, match="revised"):
        L.replay(start, revised)
    part = L.replay(start, snaps[:9])                          # decided on day 7
    with pytest.raises(S.DesignAError, match="not later than the state's ledger"):
        L.replay(part, snaps[2:12])


def test_a_skipped_decision_instant_is_refused():
    start = S.initial_state(syn.CASH, S.BASELINE, syn.RULES)
    for offset in (timedelta(0), timedelta(minutes=1)):         # snapshots that miss the instant
        with pytest.raises(S.DesignAError, match="decision instant"):
            L.replay(start, syn.scenario_snapshots(offset=offset)[:10])
    snaps = syn.scenario_snapshots()
    part = L.replay(start, snaps[:8])                           # decided on day 7
    with pytest.raises(S.DesignAError, match="decision instant"):
        L.replay(part, snaps[15:])                              # resumes after the day-14 decision


@pytest.mark.parametrize("which", ["scenario", "rough"])
def test_an_interrupted_replay_resumes_to_the_same_ledger(which):                # item 24
    snaps = syn.scenario_snapshots() if which == "scenario" else syn.rough_snapshots()
    start = (S.initial_state(syn.CASH, S.BASELINE, syn.RULES) if which == "scenario"
             else syn.rough_start())
    whole = scenario() if which == "scenario" else rough()
    first_pending = next(e for e in whole.ledger if e.event in (E.PENDING_BUY, E.PENDING_SELL))
    inside = next(i for i, s in enumerate(snaps) if s.as_of > first_pending.at)
    assert L.replay(start, snaps[:inside]).pending is not None
    for cut in (1, inside, inside + 1, len(snaps) // 2, len(snaps) - 1):
        part = L.replay(start, snaps[:cut])
        assert L.digest(L.replay(part, snaps[cut:])) == L.digest(whole), cut


def test_one_lost_candle_suspends_every_decision_whose_window_contains_it():
    """Provisional consecutive-window rule (spec §8, §19 item 16): one permanently missing day
    blocks the 28 or 29 weekly decisions whose 200-day window includes it, then decisions resume."""
    lost = 303                                               # a Wednesday
    snaps = syn.scenario_snapshots(outages={lost: (0, 10_000)})
    state = L.replay(S.initial_state(syn.CASH, S.BASELINE, syn.RULES), snaps)
    expected = [syn.at_decision(syn.day(m)) for m in range(lost + 1, lost + 201)
                if m % 7 == 0]                               # Mondays whose Sunday window holds it
    skipped = [e.at for e in state.ledger if e.event is E.SKIP_INVALID_DATA]
    assert skipped == expected and len(expected) == 28
    after = next(e for e in state.ledger if e.at > expected[-1] and e.event in S.DECISION_EVENTS)
    assert after.event in (E.DECIDE_LONG, E.DECIDE_FLAT)


# --- invalid transitions and values --------------------------------------------------------------

def test_invalid_state_transitions_are_refused():
    s = fresh()
    with pytest.raises(S.TransitionError, match="no pending"):
        L.execute_pending(s, syn.snapshot(at(WED), []))
    pending = decided(s, LONG)
    with pytest.raises(S.TransitionError, match="strictly after"):
        L.execute_pending(pending, syn.snapshot(DECISION, []))
    with pytest.raises(S.TransitionError, match="unresolved"):
        decided(pending, LONG, DECISION + WEEK)
    with pytest.raises(S.TransitionError, match="NO_SIGNAL"):
        L.apply_decision(pending, S.Decision(DECISION + WEEK, E.NO_SIGNAL))
    deferred = L.execute_pending(pending, syn.snapshot(at(THU), []))
    with pytest.raises(S.TransitionError, match="older than the last ledger entry"):
        L.execute_pending(deferred, syn.snapshot(at(TUE), []))
    done = fill(pending)
    with pytest.raises(S.TransitionError, match="no pending"):            # one decision, one fill
        fill(done, check=at(THU))
    with pytest.raises(S.TransitionError, match="already applied"):
        L.apply_decision(done, signal(DECISION, LONG, BUY))
    with pytest.raises(S.TransitionError, match="different target or position"):
        L.apply_decision(done, signal(DECISION + WEEK, FLAT))
    with pytest.raises(S.TransitionError, match="decision instant"):
        L.apply_decision(s, signal(MONDAY, LONG, BUY))
    with pytest.raises(S.TransitionError, match="initial"):               # warm-up after a decision
        L.apply_decision(done, S.Decision(DECISION + WEEK, E.WARMUP))
    warm = L.apply_decision(s, S.Decision(DECISION, E.WARMUP, reason="INSUFFICIENT_HISTORY"))
    with pytest.raises(S.TransitionError, match="already applied"):       # skips count too
        L.apply_decision(warm, S.Decision(DECISION, E.WARMUP, reason="INSUFFICIENT_HISTORY"))
    later = S.LedgerEntry(seq=0, at=DECISION + WEEK, event=E.WARMUP, cash=s.cash, btc=s.btc)
    with pytest.raises(S.TransitionError, match="older than the last ledger entry"):
        L.apply_decision(S.State(cash=s.cash, btc=s.btc, costs=s.costs, rules=s.rules,
                                 ledger=(later,)), S.Decision(DECISION, E.WARMUP))
    with pytest.raises(TypeError):
        L.apply_decision(s, "DECIDE_LONG")
    with pytest.raises(S.DesignAError, match="increasing"):
        L.replay(s, [syn.snapshot(at(TUE), []), syn.snapshot(at(TUE), [])])


def test_inconsistent_values_cannot_be_constructed():
    for args in ((E.DECIDE_LONG, FLAT), (E.WARMUP, LONG), (E.DECIDE_FLAT, FLAT, BUY), (E.EXECUTED,),
                 ("WARMUP",)):
        with pytest.raises(S.DesignAError):
            S.Decision(DECISION, *args)
    with pytest.raises(TypeError):
        S.Decision(DECISION, E.DECIDE_LONG, LONG, action="BUY")
    with pytest.raises(TypeError):
        S.Decision(DECISION, E.DECIDE_LONG, LONG, sunday_close=1.5)
    with pytest.raises(S.DesignAError, match="F5"):                       # SELL although close > SMA
        S.Decision(DECISION, E.DECIDE_FLAT, FLAT, SELL, sunday_close=D("200"), sma=D("100"))
    with pytest.raises(S.DesignAError, match="F5"):                       # no signal values at all
        S.Decision(DECISION, E.DECIDE_LONG, LONG)
    with pytest.raises(S.DesignAError, match="only DECIDE"):
        S.Decision(DECISION, E.WARMUP, sunday_close=D("1"), sma=D("1"))
    for decided_at, next_open in ((DECISION, MONDAY), (DECISION, FRI), (DECISION, TUE + timedelta(hours=1)),
                                  (DECISION + S.DAY, WED)):
        with pytest.raises(S.DesignAError):
            S.PendingTransition(BUY, decided_at, next_open)
    base = dict(cash=D("1"), btc=D("0"), costs=S.BASELINE, rules=syn.RULES)
    pending = S.PendingTransition(BUY, DECISION, TUE)
    for bad in (dict(pending=pending, target=LONG, last_decision_at=DECISION,
                     execution_status=S.ExecutionStatus.EXPIRED),
                dict(execution_status=S.ExecutionStatus.PENDING),
                dict(pending=pending, target=FLAT, last_decision_at=DECISION,
                     execution_status=S.ExecutionStatus.PENDING),
                dict(pending=pending, target=LONG, last_decision_at=DECISION + WEEK,
                     execution_status=S.ExecutionStatus.PENDING)):
        with pytest.raises(S.DesignAError):
            S.State(**base, **bad)
    with pytest.raises(TypeError):
        S.State(**base, ledger=("not an entry",))
    entry = functools.partial(S.LedgerEntry, event=E.WARMUP, btc=D("0"))
    for ledger in ((entry(seq=1, at=DECISION, cash=D("1")),),                       # numbering
                   (entry(seq=0, at=DECISION, cash=D("1")),
                    entry(seq=1, at=DECISION - S.DAY, cash=D("1"))),                # time order
                   (entry(seq=0, at=DECISION, cash=D("9")),)):                      # balances
        with pytest.raises(S.DesignAError):
            S.State(**base, ledger=ledger)
    with pytest.raises(S.DesignAError):
        S.LedgerEntry(seq=-1, at=DECISION, event=E.WARMUP, cash=D("1"), btc=D("0"))
    with pytest.raises(S.DesignAError):
        entry(seq=0, at=DECISION, cash=D("1"), quantity=D("-1"))
    with pytest.raises(TypeError):
        entry(seq=0, at=DECISION, cash=D("1"), fee=0.5)
    with pytest.raises(S.DesignAError):
        S.State(cash=D("-1"), btc=D(0), costs=S.BASELINE, rules=syn.RULES)
    with pytest.raises(TypeError):
        S.State(cash=1000.0, btc=D(0), costs=S.BASELINE, rules=syn.RULES)
    with pytest.raises(S.DesignAError):
        S.State(cash=D("1"), btc=D("NaN"), costs=S.BASELINE, rules=syn.RULES)
    with pytest.raises(S.DesignAError):
        S.initial_state(D("0"), S.BASELINE, syn.RULES)
    for fee in ("0.0009", "0.0009999999999999999999"):     # float conversion would hide the second
        with pytest.raises(CostModelError):
            S.CostSpec(D(fee), D("0"), D("0"), "discounted")
    for fee, hs, sl in (("1", "0", "0"), ("0.001", "0.6", "0.5")):
        with pytest.raises(S.DesignAError):
            S.CostSpec(D(fee), D(hs), D(sl), "absurd")
    with pytest.raises(TypeError):
        S.CostSpec(0.001, D("0"), D("0"), "float")
    with pytest.raises(S.DesignAError):
        S.MinOrderRules(D("1"), D("0"), D("0"))
