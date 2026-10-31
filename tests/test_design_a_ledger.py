"""Design A v1.0 execution and accounting (brief items 7, 9-22, 24 and invalid transitions):
pending transitions, the Tuesday reference, deferral and expiry, the frozen cost formulas, minimum
orders, dust, conservation, deterministic replay and candle integrity across replay calls and
restorations. Synthetic only; nothing here measures profitability."""
import copy
import dataclasses
import functools
import json
import os
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal as D

import pytest

sys.path.insert(0, ".")
import design_a_synthetic as syn  # noqa: E402
from research.design_a import decision as X  # noqa: E402
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


def holding(btc, cash="0", rules=syn.RULES, costs=S.BASELINE):
    return S.State(cash=D(cash), btc=D(btc), costs=costs, rules=rules, target=LONG)


FLAT_HISTORY = ["100"] * S.SMA_WINDOW


def signal(when, target, action=None):
    """A hand-built decision for ``target`` whose Sunday close and SMA agree with F5. Its window
    fingerprints are those of a flat synthetic history at 100, the same for every decision, so
    hand-built decisions never contradict one another (the signal is tested elsewhere)."""
    event, close = (E.DECIDE_LONG, D("101")) if target is LONG else (E.DECIDE_FLAT, D("99"))
    sunday = when.replace(hour=0, minute=0, second=0, microsecond=0) - S.DAY
    window = tuple(S.candle_fingerprint(c) for c in syn.ending(sunday, FLAT_HISTORY))
    return S.Decision(when, event, target, action=action, sunday_close=close, sma=D("100"),
                      window=window)


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


# --- owner decision 2026-10-31 (F10): weekly retries of transitions that did not execute ---------

NEXT = DECISION + WEEK


def expired(state):
    """Let the pending transition expire: no reference candle inside its window."""
    return L.execute_pending(state, syn.snapshot(at(state.pending.decided_at.replace(
        hour=0, minute=0, second=0) + 4 * S.DAY), []))


@pytest.mark.parametrize("costs", [S.BASELINE, S.STRESS], ids=["baseline", "stress"])
def test_an_expired_sell_is_retried_at_the_next_flat_decision(costs):           # 1, 7, 8
    s = expired(decided(holding("2", costs=costs), FLAT))
    assert s.execution_status is S.ExecutionStatus.EXPIRED and S.actual_position(s) is LONG
    retry = decided(s, FLAT, NEXT)
    assert events(retry, 2) == [E.DECIDE_FLAT, E.PENDING_SELL] and retry.ledger[-1].reason == "RETRY"
    assert (retry.pending.next_open, retry.pending.expires_at) == (TUE + WEEK, NEXT + 3 * S.DAY)
    assert (retry.cash, retry.btc) == (s.cash, s.btc)                       # nothing moves yet
    waiting = L.execute_pending(retry, syn.snapshot(at(WED + WEEK), []))    # missing data
    assert (waiting.cash, waiting.btc) == (s.cash, s.btc)
    done = fill(retry, "110", day=TUE + WEEK)
    e = done.ledger[-1]
    assert e.execution_price == D("110") * (1 - costs.half_spread - costs.slippage)
    assert done.cash == e.notional - e.notional * costs.fee and done.btc == 0
    lapsed = expired(retry)                                                  # the same 72 h window
    assert events(lapsed, 1) == [E.EXPIRED] and lapsed.ledger[-1].expires_at == NEXT + 3 * S.DAY


@pytest.mark.parametrize("costs", [S.BASELINE, S.STRESS], ids=["baseline", "stress"])
def test_an_expired_buy_is_retried_at_the_next_long_decision(costs):            # 3, 7, 8
    s = expired(decided(fresh(costs=costs), LONG))
    retry = decided(s, LONG, NEXT)
    assert events(retry, 2) == [E.DECIDE_LONG, E.PENDING_BUY] and retry.ledger[-1].reason == "RETRY"
    assert (retry.cash, retry.btc) == (D("1000"), 0)
    done = fill(retry, "100", day=TUE + WEEK)
    buy = done.ledger[-1]
    assert buy.execution_price == D("100") * (1 + costs.half_spread + costs.slippage)
    assert buy.quantity == (D("9.98002") if costs is S.BASELINE else D("9.97006"))
    assert done.cash == D("1000") - buy.notional - buy.notional * costs.fee
    assert (buy.reference_time, buy.at) == (TUE + WEEK, WED + WEEK)      # open vs availability


def test_a_rejected_sell_is_retried_only_at_the_next_valid_weekly_decision():   # 2, 6
    rejected = fill(decided(holding("0.05"), FLAT))           # 0.05 x 99.9 = 4.995 < 10
    assert rejected.execution_status is S.ExecutionStatus.REJECTED_MIN_ORDER
    with pytest.raises(S.TransitionError, match="no pending"):           # nothing between decisions
        L.execute_pending(rejected, syn.snapshot(at(THU), [reference(WED, "300")]))
    skipped = L.apply_decision(rejected, S.Decision(NEXT, E.SKIP_MISSING_SUNDAY,
                                                    reason="SUNDAY_CANDLE_UNAVAILABLE"))
    assert skipped.pending is None and events(skipped, 1) == [E.SKIP_MISSING_SUNDAY]
    retry = decided(skipped, FLAT, NEXT + WEEK)
    assert events(retry, 1) == [E.PENDING_SELL] and retry.ledger[-1].reason == "RETRY"
    sold = fill(retry, "300", day=TUE + 2 * WEEK)             # 0.05 x 299.7 = 14.985 >= 10
    assert sold.ledger[-1].event is E.EXECUTED and sold.btc == 0
    again = fill(decided(rejected, FLAT, NEXT), "100", day=TUE + WEEK)    # minimums still apply
    assert (again.ledger[-1].reason, again.btc) == ("BELOW_MIN_NOTIONAL", D("0.05"))


def test_missing_sunday_data_does_not_trigger_a_retry():                         # 6
    s = expired(decided(fresh(), LONG))                       # target LONG, actual FLAT
    sunday = MONDAY + WEEK - S.DAY
    closes = ["100"] * 199 + ["120"]
    lacking = [c for c in syn.ending(sunday, closes) if c.open_time != sunday]
    d = X.decide(s, syn.snapshot(NEXT, lacking))
    after = L.apply_decision(s, d)
    assert d.event is E.SKIP_MISSING_SUNDAY and after.pending is None
    assert (after.cash, after.btc) == (s.cash, s.btc)
    d2 = X.decide(after, syn.snapshot(NEXT + WEEK, syn.ending(sunday + WEEK, closes)))
    assert d2.action is BUY and L.apply_decision(after, d2).ledger[-1].reason == "RETRY"


def test_an_executed_transition_is_never_duplicated():                           # 4, 5
    long = fill(decided(fresh(), LONG))
    again = decided(long, LONG, NEXT)
    assert events(again, 2) == [E.DECIDE_LONG, E.NO_CHANGE] and again.pending is None
    flat = fill(decided(again, FLAT, NEXT + WEEK), day=TUE + 2 * WEEK)
    again = decided(flat, FLAT, NEXT + 2 * WEEK)
    assert events(again, 2) == [E.DECIDE_FLAT, E.NO_CHANGE] and again.pending is None
    assert [e.side for e in executed(again)] == [BUY, SELL]


def test_a_changed_signal_replaces_the_retry():
    s = expired(decided(fresh(), LONG))                       # the BUY expired
    flat = decided(s, FLAT, NEXT)                              # the signal turned: follow it
    assert events(flat, 2) == [E.DECIDE_FLAT, E.NO_CHANGE] and flat.pending is None


def test_dust_below_the_tradable_minimums_creates_no_repeated_orders():          # 10
    for btc, rules in (("0.000001", syn.RULES),                                  # below one step
                       ("0.0005", S.MinOrderRules(D("1"), D("0.001"), D("0.00001")))):  # < min_qty
        s = S.State(cash=D("0"), btc=D(btc), costs=S.BASELINE, rules=rules, target=FLAT)
        for week in range(3):
            s = decided(s, FLAT, DECISION + week * WEEK)
            assert events(s, 1) == [E.NO_CHANGE] and s.pending is None and s.btc == D(btc)


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
    assert again.ledger[-1].reason == "ALREADY_AT_TARGET"
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
    assert any(e.reason == "RETRY" for e in rough().ledger)          # the expired SELL is retried
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
    expected = {"scenario": L.digest(scenario()), "rough_scenario": L.digest(rough()),
                "restored_scenario": L.digest(scenario())}
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


def test_known_limitation_unconsumed_candles_are_checked_within_one_call_only():
    """Documented limitation (spec §5): only consumed candles are integrity evidence. A candle
    delivered before a cut but not yet read by a decision or an execution (here a warm-up day)
    is checked for revision within one replay call, not across the cut."""
    snaps = syn.scenario_snapshots()[:11]
    old = snaps[10].candles[3]
    new = S.Candle(old.open_time, old.open, old.high * 2, old.low, old.close)
    revised = S.Snapshot(snaps[10].as_of, tuple(new if c is old else c for c in snaps[10].candles),
                         snaps[10].permission)
    start = S.initial_state(syn.CASH, S.BASELINE, syn.RULES)
    with pytest.raises(S.DesignAError, match="revised"):
        L.replay(start, snaps[:10] + [revised])               # one call: refused
    L.replay(L.replay(start, snaps[:10]), [revised])           # two calls: not detected


# --- durable candle integrity across replay calls, serialisation and restoration ----------------

CUT = 206      # after the first decision (day 203) and its fill (Tuesday 204, booked on day 205)


def restore(state):
    """Serialise to JSON and restore, as across a process boundary."""
    return L.state_from_record(json.loads(json.dumps(L.state_record(state))))


def replaced(snap, day, **values):
    old = next(c for c in snap.candles if c.open_time == day)
    new = S.Candle(old.open_time, **{**{f: getattr(old, f) for f in ("open", "high", "low",
                                                                     "close")}, **values})
    return S.Snapshot(snap.as_of, tuple(new if c is old else c for c in snap.candles),
                      snap.permission)


def without(snap, day):
    return S.Snapshot(snap.as_of, tuple(c for c in snap.candles if c.open_time != day),
                      snap.permission)


def starting(snap, day):
    """``snap`` without its candles before ``day``: a source that keeps a shorter history."""
    return S.Snapshot(snap.as_of, tuple(c for c in snap.candles if c.open_time >= day),
                      snap.permission)


def clean_start():
    return S.initial_state(syn.CASH, S.BASELINE, syn.RULES)


def test_identical_candles_resume_across_calls_and_restoration():
    snaps = syn.scenario_snapshots()
    part = L.replay(clean_start(), snaps[:CUT])
    assert len(part.consumed) == 201 and sum(e.reference_fingerprint is not None
                                             for e in part.ledger) == 1
    for resumed in (part, restore(part)):
        assert L.digest(resumed) == L.digest(part)
        assert L.digest(L.replay(resumed, snaps[CUT:])) == L.digest(scenario())


@pytest.mark.parametrize("day", [5, 100, 202, 204], ids=["old_window_day", "window_day",
                                                        "decision_sunday", "execution_reference"])
def test_a_revised_consumed_candle_is_refused_across_calls(day):
    """Day 5 is read by no later window; the others are read again by the next decision."""
    snaps = syn.scenario_snapshots()
    part = L.replay(clean_start(), snaps[:CUT])
    old = next(c for c in snaps[CUT].candles if c.open_time == syn.day(day))
    for later in (part, restore(part)):            # a separate call, and after serialisation
        assert syn.day(day) in dict(later.consumed)
        for change in ({"high": old.high * 2}, {"low": old.low / 2}):
            # revised alike in every snapshot of a call that ends before the next decision: only
            # the consumed index can see it, and it is refused before anything is processed
            revised = [replaced(s, syn.day(day), **change) for s in snaps[CUT:CUT + 3]]
            with pytest.raises(S.DesignAError, match="differs from the one consumed"):
                L.replay(later, revised)
        same = replaced(snaps[CUT], syn.day(day), close=with_trailing_zeros(old.close))
        assert L.digest(L.replay(later, [same] + snaps[CUT + 1:])) == L.digest(scenario())


def with_trailing_zeros(value):
    """The same number written with extra trailing zeros: not a revision."""
    return D(str(value) + "000") if "." in str(value) else D(str(value) + ".000")


def test_a_missing_consumed_candle_is_refused_never_assumed():
    snaps = syn.scenario_snapshots()
    part = L.replay(clean_start(), snaps[:CUT])
    for later in (restore(part), part):
        with pytest.raises(S.DesignAError, match="previously consumed candle .* is missing"):
            L.replay(later, [without(snaps[CUT], syn.day(100))] + snaps[CUT + 1:])
        # cut short inside the window the next decision reads (days 10-209): refused, not skipped
        with pytest.raises(S.DesignAError, match="consumed candle 2001-01-11T.* is missing"):
            L.replay(later, (starting(s, syn.day(150)) for s in snaps[CUT:]))
    # consumed days 3-9 are read by no later window: a history starting at day 10 still resumes
    shorter = [starting(s, syn.day(10)) for s in snaps[CUT:]]
    assert L.digest(L.replay(part, shorter)) == L.digest(scenario())
    with pytest.raises(S.DesignAError, match="is missing"):              # within one call too
        L.replay(clean_start(), snaps[:CUT] + [without(snaps[CUT], syn.day(204))])
    # no snapshot is expected to hold consumed candles that complete only after its as_of
    assert X.decide(part, snaps[CUT - 9]).event is E.NO_SIGNAL
    # the rough fixture's former outage: day 330, read by earlier decisions, hidden on day 357
    former = {k: v for k, v in syn.OUTAGES.items() if k != 352} | {330: (357, 358)}
    with pytest.raises(S.DesignAError, match="consumed candle 2001-11-27T.* is missing"):
        L.replay(syn.rough_start(), syn.scenario_snapshots(outages=former))


def test_a_missing_unconsumed_candle_follows_the_missing_data_rules():
    """Only consumed candles are integrity evidence: unconsumed ones missing from a resumed call
    keep the existing rules. A window day is a gap and a due reference defers; both are read
    later, once present, and only then recorded as consumed."""
    snaps = syn.scenario_snapshots(outages={205: (210, 211), 295: (296, 297)})
    part = restore(L.replay(clean_start(), snaps[:CUT]))
    assert not {syn.day(205), syn.day(295)} & set(dict(part.consumed))
    resumed = L.replay(part, snaps[CUT:])
    assert L.digest(resumed) == L.digest(L.replay(clean_start(), snaps))    # as in one call
    gap = next(e for e in resumed.ledger if e.at == syn.at_decision(syn.day(210)))
    assert (gap.event, gap.reason) == (E.SKIP_INVALID_DATA, "GAP_IN_WINDOW")
    missing = next(e for e in resumed.ledger if e.event is E.MISSING_MARKET_DATA)
    sold = next(e for e in resumed.ledger if e.event is E.EXECUTED and e.at > missing.at)
    assert (missing.reference_time, missing.at) == (syn.day(295), syn.day(296))
    assert (sold.side, sold.reference_time) == (SELL, syn.day(296))      # deferred to Wednesday
    assert {syn.day(205), syn.day(295)} <= set(dict(resumed.consumed))  # read by later windows
    moved = next(e for e in rough().ledger if e.at == syn.at_decision(syn.day(357)))
    assert (moved.event, moved.reason) == (E.SKIP_INVALID_DATA, "GAP_IN_WINDOW")  # day 352



def test_tampered_or_malformed_integrity_metadata_is_refused():
    part = L.replay(clean_start(), syn.scenario_snapshots()[:CUT])
    good = json.loads(json.dumps(L.state_record(part)))
    assert L.digest(L.state_from_record(good)) == L.digest(part)
    decision = next(i for i, e in enumerate(good["ledger"]) if "window_digest" in e)
    fill_at = next(i for i, e in enumerate(good["ledger"]) if "reference_fingerprint" in e)

    def flip(fingerprint):
        return ("1" if fingerprint[0] == "0" else "0") + fingerprint[1:]

    def edited(change):
        record = copy.deepcopy(good)
        change(record)
        return record

    older = (syn.EPOCH - 400 * S.DAY).isoformat()
    bad = [
        edited(lambda r: r["consumed"][5].__setitem__(1, flip(r["consumed"][5][1]))),
        edited(lambda r: r["ledger"][decision].__setitem__("window_digest",
                                                           flip(r["ledger"][decision]["window_digest"]))),
        edited(lambda r: r["ledger"][fill_at].__setitem__(
            "reference_fingerprint", flip(r["ledger"][fill_at]["reference_fingerprint"]))),
        edited(lambda r: r["consumed"].pop(7)),                              # an entry dropped
        edited(lambda r: r["consumed"].insert(0, [older, "a" * 64])),        # an entry added
        edited(lambda r: r["consumed"].insert(1, list(r["consumed"][0]))),   # a day twice
        edited(lambda r: r["consumed"].insert(0, r["consumed"].pop(1))),     # out of order
        edited(lambda r: r["consumed"][3].__setitem__(1, "not-a-fingerprint")),
        edited(lambda r: r["ledger"][0].__setitem__("window_digest", "b" * 64)),  # on a WARMUP
        edited(lambda r: r.__setitem__("consumed", "garbage")),
        edited(lambda r: r.pop("consumed")),
        edited(lambda r: r.__setitem__("cash", "not a number")),
        edited(lambda r: r.__setitem__("version", "design-a-v0")),
    ]
    for record in bad:
        with pytest.raises(S.DesignAError):
            L.state_from_record(record)
    non_canonical = [                       # consistent, but not exactly what state_record wrote
        edited(lambda r: r.__setitem__("note", "unexpected")),
        edited(lambda r: r.__setitem__("last_decision_at",
                                       r["last_decision_at"].replace("+00:00", "Z"))),
        edited(lambda r: r["costs"].__setitem__("fee", float(r["costs"]["fee"]))),  # binary float
    ]
    for record in non_canonical:
        with pytest.raises(S.DesignAError, match="not canonical"):
            L.state_from_record(record)
    tampered = dataclasses.replace(part, consumed=part.consumed[:-1])     # in memory
    with pytest.raises(S.DesignAError, match="integrity"):
        L.replay(tampered, [])
    with pytest.raises(S.DesignAError, match="differs from the one consumed"):  # a forged window
        L.apply_decision(part, signal(syn.at_decision(syn.day(210)), LONG))


def test_restoration_inside_a_retry_window_resumes_identically():
    snaps = syn.rough_snapshots()
    retry = next(e for e in rough().ledger if e.reason == "RETRY")
    cut = next(i for i, s in enumerate(snaps) if s.as_of > retry.at)
    part = L.replay(syn.rough_start(), snaps[:cut])
    assert part.pending is not None and part.ledger[-1].reason == "RETRY"
    assert L.digest(L.replay(restore(part), snaps[cut:])) == L.digest(rough())


def test_a_state_saved_by_one_process_resumes_in_another():
    """A real process boundary: one interpreter saves the state as JSON; another, with another
    hash seed and a hostile ambient decimal context, restores it and resumes."""
    prelude = ("import sys; sys.path[:0] = ['.', 'tests']; import json; "
               "import design_a_synthetic as syn; from research.design_a import ledger as L; ")
    save = prelude + ("start = syn.S.initial_state(syn.CASH, syn.S.BASELINE, syn.RULES); "
                      "print(json.dumps(L.state_record("
                      "L.replay(start, syn.scenario_snapshots()[:300]))))")
    resume = ("import decimal; decimal.setcontext(decimal.Context(prec=3, capitals=0)); "
              + prelude + "state = L.state_from_record(json.loads(sys.stdin.read())); "
                          "print(L.digest(L.replay(state, syn.scenario_snapshots()[300:])))")

    def run(code, seed, stdin=None):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": seed,
               "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, "-c", code], input=stdin, capture_output=True,
                              text=True, env=env, timeout=300, check=True).stdout
    saved = run(save, "0")
    assert json.loads(saved)["consumed"] and run(resume, "4242", saved).strip() == L.digest(
        scenario())


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
    cuts = [1, inside, inside + 1, len(snaps) // 2, len(snaps) - 1]
    retry = next((e for e in whole.ledger if e.reason == "RETRY"), None)
    if retry is not None:                                      # a cut inside a retry window
        cuts.append(next(i for i, s in enumerate(snaps) if s.as_of > retry.at))
    for cut in cuts:
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
    with pytest.raises(S.DesignAError, match="200 window"):              # no window fingerprints
        S.Decision(DECISION, E.DECIDE_LONG, LONG, sunday_close=D("101"), sma=D("100"))
    with pytest.raises(S.DesignAError, match="200 window"):
        S.Decision(DECISION, E.WARMUP, window=signal(DECISION, LONG).window)
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
