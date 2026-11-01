"""WP-D03 (SE-66, WP-IR-06, WP-IT-06): tests of shared.position_state.

Synthetic, deterministic fixtures only: hand-written values or paths drawn from fixed seeds.
Levels, quantities, fractions and hours are arbitrary fixtures, not proposals for any owner
decision. Parity runs through the pinned production code itself (shared/triple_barrier.py,
shared/partial_exits.py, shared/entry_execution.py), imported read-only; its legacy defaults are
the ones those modules define.
"""
import ast
import random
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from shared import portfolio_ledger as pl
from shared import position_state as ps
from shared.entry_execution import decide_long_entry
from shared.funnel_records import REASON_CODES, SE_NAME_MAP
from shared.partial_exits import aggregate_close, fills_between, target_distribution
from shared.position_state import (CLOSED, EXPIRED_UNFILLED, OPEN, OPEN_STATES, PARTIAL_T1,
                                   PARTIAL_T2, PLANNED, REJECTED, STATES, TERMINAL_STATES,
                                   WORKING, Observation, TimeRule, TransitionRefused)
from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState,
                                   expiry_policy_for_timeframe, modeled_stop_exit, step_barrier)

ROOT = Path(__file__).resolve().parents[1]
STEP = D("0.00000001")
ALL_EXIT_KINDS = ("stop_exit", "invalidation_exit", "time_exit", "thesis_exit", "admin_exit")


def plan(**overrides):
    values = dict(intent_id="i-1", symbol="BTCUSDT", strategy_id="momentum_breakout",
                  planned_qty=D("1"), planned_entry=D("100"), stop=D("97"), invalidation=D("97"),
                  targets=(D("102"), D("104"), D("106")),
                  exit_fractions=(D("0.25"), D("0.5"), D("0.25")), qty_step=STEP)
    values.update(overrides)
    return ps.PositionPlan(**values)


def fresh(**overrides):
    return ps.new_position(plan(**overrides))


def reserved(**overrides):
    return ps.apply(fresh(**overrides), ps.Reserve(D("101")))[0]


def working():
    return ps.apply(reserved(), ps.RestEntry())[0]


def opened(qty="1", **overrides):
    return ps.apply(reserved(**overrides), ps.EntryFill(D(qty), D("100")))[0]


def partial_t1():
    return ps.apply(opened(), ps.TargetFill(1, D("0.25"), D("102"), D("100.4")))[0]


def partial_t2():
    return ps.apply(partial_t1(), ps.TargetFill(2, D("0.5"), D("104"), D("101.4")))[0]


def closed():
    return ps.apply(opened(), ps.StopExit(D("1"), D("96.903")))[0]


def rejected():
    return ps.apply(reserved(), ps.InvalidatedBeforeFill())[0]


def expired():
    return ps.apply(working(), ps.ExpireEntry())[0]


# OPEN uses a partly filled entry, so that end_entry and entry_fill are also exercisable.
STATE_FIXTURES = {PLANNED: reserved, WORKING: working, OPEN: lambda: opened("0.4"),
                  PARTIAL_T1: partial_t1, PARTIAL_T2: partial_t2, CLOSED: closed,
                  REJECTED: rejected, EXPIRED_UNFILLED: expired}


def sample(record, kind):
    """A well-formed event of ``kind`` for ``record`` (quantities sized to the record)."""
    open_qty = record.qty_open if record.state in OPEN_STATES else D("1")
    entry_qty = record.entry_remaining if record.entry_remaining > 0 else D("1")
    return {
        "reserve": ps.Reserve(D("101")),
        "rest_entry": ps.RestEntry(),
        "entry_fill": ps.EntryFill(entry_qty, D("100")),
        "end_entry": ps.EndEntry("entry_window_elapsed"),
        "expire_entry": ps.ExpireEntry(),
        "invalidated_before_fill": ps.InvalidatedBeforeFill(),
        "below_exchange_minimum": ps.BelowExchangeMinimum(),
        "risk_refused": ps.RiskRefused("F7.capacity_full"),
        "target_1": ps.TargetFill(1, D("0.25"), D("102"), D("100.4")),
        "target_2": ps.TargetFill(2, D("0.25"), D("104"), D("101.4")),
        "target_3": ps.TargetFill(3, open_qty, D("106"), None),
        "stop_update": ps.StopUpdate(record.stop_level + 1),
        "stop_exit": ps.StopExit(open_qty, D("96.903")),
        "invalidation_exit": ps.InvalidationExit(open_qty, D("96.5")),
        "time_exit": ps.TimeExit(open_qty, D("100.5"), "max_hold"),
        "thesis_exit": ps.ThesisExit(open_qty, D("100.5"), "regime_flip"),
        "admin_exit": ps.AdminExit(open_qty, D("100.5"), "owner_blacklist"),
    }[kind]


def refused(record, event, reason):
    before = record
    with pytest.raises(TransitionRefused) as info:
        ps.apply(record, event)
    assert info.value.reason == reason, info.value
    assert record == before                     # immutable: the refusal changed nothing
    return info.value


# ── 1. the transition table ───────────────────────────────────────────────────────────────

SE_B6_ROWS = {f"B6-{n:02d}" for n in range(1, 13)}


def test_table_contains_every_se_b6_row_and_labels_each_extension():
    ids = {rule.rule_id.split(":")[0] for rule in ps.TRANSITIONS}
    assert SE_B6_ROWS <= ids
    assert {r.rule_id.split(":")[0] for r in ps.TRANSITIONS if r.source == "SE-B6"} == SE_B6_ROWS
    extensions = {r.rule_id.split(":")[0] for r in ps.TRANSITIONS if r.source == "extension"}
    assert extensions == {f"X-0{n}" for n in range(1, 9)}
    assert all(r.source in ("SE-B6", "extension") and r.note for r in ps.TRANSITIONS)
    assert len(ps.TRANSITIONS) == 32
    pairs = [(r.from_state, r.event_kind) for r in ps.TRANSITIONS]
    assert len(pairs) == len(set(pairs))
    for rule in ps.TRANSITIONS:
        assert rule.from_state in STATES and rule.to_state in STATES
        assert rule.event_kind in ps.EVENT_KINDS
        assert rule.from_state not in TERMINAL_STATES          # terminal states are final
        assert rule.to_state_if_flat in (None, CLOSED)


def test_se_b6_rows_have_the_documented_endpoints():
    expected = {
        ("B6-01", PLANNED, "invalidated_before_fill", REJECTED), ("B6-02", PLANNED, "entry_fill", OPEN),
        ("B6-03", PLANNED, "rest_entry", WORKING), ("B6-04", WORKING, "expire_entry", EXPIRED_UNFILLED),
        ("B6-05:PLANNED", PLANNED, "below_exchange_minimum", REJECTED),
        ("B6-05:WORKING", WORKING, "below_exchange_minimum", REJECTED),
        ("B6-07", OPEN, "invalidation_exit", CLOSED), ("B6-08", OPEN, "target_1", PARTIAL_T1),
        ("B6-09", PARTIAL_T1, "target_2", PARTIAL_T2), ("B6-10", PARTIAL_T2, "target_3", CLOSED),
    }
    for state in OPEN_STATES:
        for rid, kind in (("B6-06", "stop_exit"), ("B6-11", "time_exit"), ("B6-12", "thesis_exit")):
            expected.add((f"{rid}:{state}", state, kind, CLOSED))
    actual = {(r.rule_id, r.from_state, r.event_kind, r.to_state)
              for r in ps.TRANSITIONS if r.source == "SE-B6"}
    assert actual == expected


def test_every_state_is_reachable_and_every_live_state_can_terminate():
    edges = {}
    for rule in ps.TRANSITIONS:
        edges.setdefault(rule.from_state, set()).update({rule.to_state, rule.to_state_if_flat} - {None})
    seen, queue = {PLANNED}, deque([PLANNED])
    while queue:
        for nxt in edges.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert seen == set(STATES)
    for state in set(STATES) - set(TERMINAL_STATES):
        assert edges[state] & set(TERMINAL_STATES) or any(
            edges[s] & set(TERMINAL_STATES) for s in edges[state])


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("kind", ps.EVENT_KINDS)
def test_exhaustive_state_event_pairs(state, kind):
    """Every (state, event) pair: a table row applies to its row's state, anything else refuses."""
    record = fresh() if (state, kind) == (PLANNED, "reserve") else STATE_FIXTURES[state]()
    rule = ps.rule_for(state, kind)
    event = sample(record, kind)
    if state in TERMINAL_STATES:
        refused(record, event, "terminal_state")
        return
    if rule is None:
        refused(record, event, "illegal_transition")
        return
    new, transition = ps.apply(record, event)
    assert transition.rule_id == rule.rule_id and transition.source == rule.source
    assert transition.from_state == state and transition.to_state == new.state
    assert new.state in (rule.to_state, rule.to_state_if_flat)
    assert set(transition.ledger_events) <= set(ps.LEDGER_EVENTS)
    ps.check_record(new)


@pytest.mark.parametrize("make", [closed, rejected, expired])
def test_terminal_states_are_final_for_every_event(make):
    record = make()
    for kind in ps.EVENT_KINDS:
        refused(record, sample(record, kind), "terminal_state")
    with pytest.raises(TransitionRefused):
        ps.entry_guard(record, D("100"))
    with pytest.raises(TransitionRefused):
        ps.closed_bar_events(record, bar_close=D("90"), exit_price=D("90"))


def test_bfs_over_the_machine_exercises_every_row_and_only_legal_projections():
    """WP-IT-06: every legal step maps to a legal Position.state projection step."""
    seen_rules, seen_steps = set(), set()
    start = fresh()
    queue, visited = deque([start]), set()
    while queue:
        record = queue.popleft()
        key = (record.state, record.reservation_active, record.entry_open, record.highest_target,
               record.qty_open > 0, record.qty_filled == record.plan.planned_qty)
        if key in visited:
            continue
        visited.add(key)
        for kind in ps.EVENT_KINDS:
            if ps.rule_for(record.state, kind) is None:
                continue
            for event in (sample(record, kind),) + (
                    (ps.EntryFill(D("0.4"), D("100")),) if kind == "entry_fill" else ()):
                try:
                    new, transition = ps.apply(record, event)
                except TransitionRefused:
                    continue
                seen_rules.add(transition.rule_id)
                seen_steps.add((record.projection, new.projection))
                queue.append(new)
    assert seen_rules == {r.rule_id for r in ps.TRANSITIONS}
    assert seen_steps <= ps.PROJECTION_STEPS
    assert seen_steps == ps.PROJECTION_STEPS


@pytest.mark.parametrize("before, after", [("closed", "open"), ("partially_exited", "open"),
                                           (None, "open"), ("closed", "closed"), ("open", None),
                                           ("open", "pending"), (None, None)])
def test_illegal_projection_steps_are_refused(before, after):
    with pytest.raises(TransitionRefused) as info:
        ps.check_projection_step(before, after)
    assert info.value.reason == "illegal_projection"


def test_projection_matches_wp_ir_06():
    assert ps.PROJECTION == {PLANNED: "pending", WORKING: "pending", OPEN: "open",
                             PARTIAL_T1: "partially_exited", PARTIAL_T2: "partially_exited",
                             CLOSED: "closed", REJECTED: None, EXPIRED_UNFILLED: None}


# ── 2. quantity and value validation ──────────────────────────────────────────────────────

def test_overfill_and_bad_entry_quantities_are_refused():
    record = opened("0.4")
    refused(record, ps.EntryFill(D("0.60000001"), D("100")), "overfill")
    refused(record, ps.EntryFill(D("0"), D("100")), "invalid_event")
    refused(record, ps.EntryFill(D("-0.1"), D("100")), "invalid_event")
    refused(record, ps.EntryFill(0.1, D("100")), "invalid_event")              # float
    refused(record, ps.EntryFill(D("0.1"), 100.0), "invalid_event")
    refused(record, ps.EntryFill(D("0.1"), D("0")), "invalid_event")
    refused(record, ps.EntryFill(D("0.000000001"), D("100")), "qty_not_step_aligned")
    refused(record, ps.EntryFill(D("NaN"), D("100")), "invalid_event")
    full = opened()
    refused(full, ps.EntryFill(D("0.1"), D("100")), "entry_not_open")
    refused(full, ps.EndEntry("late_cancel"), "entry_not_open")


def test_reservation_rules():
    refused(fresh(), ps.EntryFill(D("1"), D("100")), "reservation_required")
    refused(fresh(), ps.RestEntry(), "reservation_required")
    refused(reserved(), ps.Reserve(D("101")), "reservation_exists")
    refused(fresh(), ps.Reserve(D("0")), "invalid_event")
    new, transition = ps.apply(fresh(), ps.InvalidatedBeforeFill())     # nothing reserved
    assert new.state == REJECTED and transition.ledger_events == ()
    assert transition.reason_code == ps.CODE_INVALIDATED


def test_exit_quantities_never_overrun_or_leave_a_partial_remainder():
    t1 = partial_t1()
    refused(t1, ps.TargetFill(2, D("0.75000001"), D("104"), D("101")), "over_exit")
    refused(t1, ps.StopExit(D("0.5"), D("100")), "remainder_mismatch")
    refused(t1, ps.StopExit(D("0"), D("100")), "invalid_event")
    refused(partial_t2(), ps.TargetFill(3, D("0.1"), D("106"), None), "remainder_mismatch")
    for kind in ALL_EXIT_KINDS:
        event = sample(t1, kind)
        if ps.rule_for(t1.state, kind) is not None:
            refused(t1, type(event)(*(D("0.7"),) + tuple(vars(event).values())[1:]),
                    "remainder_mismatch")
    refused(opened(), ps.TargetFill(1, D("0.25"), D("102"), None), "new_stop_required")
    refused(opened(), ps.TargetFill(1, D("1"), D("102"), D("100")), "new_stop_unexpected")
    refused(opened(), ps.TargetFill(1, D("0.25"), D("102"), 100.4), "invalid_event")
    refused(opened(), ps.StopUpdate(D("97")), "no_change")
    refused(opened(), ps.TargetFill(4, D("0.25"), D("102"), D("100")), "invalid_event")
    refused(opened(), ps.TargetFill(True, D("0.25"), D("102"), D("100")), "invalid_event")
    refused(opened(), ps.TargetFill(2, D("0.25"), D("104"), D("100")), "illegal_transition")
    refused(opened(), ps.TimeExit(D("1"), D("100"), " "), "invalid_event")


@pytest.mark.parametrize("code", ["capacity_full", "F4.no_setup", "F7.", "F7.Capacity", 7, None])
def test_risk_refusal_needs_an_f7_code(code):
    refused(reserved(), ps.RiskRefused(code), "invalid_reason_code")


def test_unknown_event_and_record_are_refused():
    with pytest.raises(TransitionRefused) as info:
        ps.apply(opened(), object())
    assert info.value.reason == "invalid_event"
    with pytest.raises(TransitionRefused) as info:
        ps.apply("not a record", ps.RestEntry())
    assert info.value.reason == "invalid_record"


@pytest.mark.parametrize("overrides", [
    dict(stop=D("100")), dict(targets=(D("102"), D("101"), D("106"))),
    dict(targets=(D("102"), D("104"))), dict(exit_fractions=(D("0.25"), D("0.5"), D("0.2"))),
    dict(exit_fractions=(D("-0.25"), D("1"), D("0.25"))), dict(planned_qty=1.0),
    dict(planned_qty=D("0")), dict(planned_qty=D("1.000000001")), dict(intent_id=" "),
    dict(qty_step=D("0")), dict(invalidation=D("0")), dict(planned_entry=D("Infinity")),
    dict(exit_fractions=[D("0.25"), D("0.5"), D("0.25")]),
])
def test_invalid_plans_are_refused(overrides):
    with pytest.raises(TransitionRefused) as info:
        ps.new_position(plan(**overrides))
    assert info.value.reason == "invalid_plan"


def test_restore_accepts_only_states_the_machine_can_produce():
    record = partial_t1()
    kwargs = dict(state=record.state, reservation_active=False, entry_open=False,
                  entry_legs=record.entry_legs, exit_legs=record.exit_legs, highest_target=1,
                  stop_level=record.stop_level, reason_code=None, exit_kind=None, exit_rule=None)
    assert ps.restore(record.plan, **kwargs) == record
    for bad in (dict(highest_target=2), dict(state=OPEN), dict(entry_open=True),
                dict(exit_legs=(ps.Leg("target", D("1"), D("102"), 1),)),
                dict(reason_code="F7.capacity_full"), dict(exit_kind="stop"),
                dict(entry_legs=(ps.Leg("entry", D("2"), D("100"), None),)),
                dict(stop_level=D("0")), dict(state="HALF_OPEN")):
        with pytest.raises(TransitionRefused) as info:
            ps.restore(record.plan, **(kwargs | bad))
        assert info.value.reason == "invalid_record", bad


def test_transitions_are_deterministic_and_never_mutate_inputs():
    events = [ps.Reserve(D("101")), ps.EntryFill(D("0.4"), D("100")), ps.EntryFill(D("0.6"), D("99.5")),
              ps.TargetFill(1, D("0.25"), D("102"), D("100.4")), ps.StopUpdate(D("100.5")),
              ps.TimeExit(D("0.75"), D("101"), "max_hold")]
    start = fresh()
    snapshot = ps.new_position(plan())
    first = ps.apply_all(start, events)
    second = ps.apply_all(start, events)
    assert first == second and start == snapshot
    with pytest.raises(TransitionRefused):
        ps.apply_all(start, events + [ps.RestEntry()])
    assert start == snapshot


# ── 3. partial entry fills, reservation release and ledger events ─────────────────────────

def test_partial_entry_fills_then_complete_release_the_reservation_once():
    record = reserved()
    record, t1 = ps.apply(record, ps.EntryFill(D("0.4"), D("100")))
    assert (record.state, record.entry_open, record.reservation_active) == (OPEN, True, True)
    assert t1.ledger_events == (ps.ENTRY_FILL,) and t1.rule_id == "B6-02"
    record, t2 = ps.apply(record, ps.EntryFill(D("0.6"), D("99.5")))
    assert t2.ledger_events == (ps.ENTRY_FILL, ps.RELEASE) and t2.rule_id == "X-04"
    assert (record.entry_open, record.reservation_active, record.qty_filled) == (False, False, D("1"))


def test_entry_remainder_ends_on_cancel_or_on_the_first_exit():
    record, transition = ps.apply(opened("0.4"), ps.EndEntry("entry_window_elapsed"))
    assert transition.ledger_events == (ps.RELEASE,) and record.state == OPEN
    refused(record, ps.EntryFill(D("0.1"), D("100")), "entry_not_open")
    record, transition = ps.apply(opened("0.4"), ps.TargetFill(1, D("0.1"), D("102"), D("100.4")))
    assert transition.ledger_events == (ps.RELEASE, ps.EXIT_FILL)
    assert not record.entry_open and not record.reservation_active
    record, transition = ps.apply(opened("0.4"), ps.AdminExit(D("0.4"), D("99"), "owner_blacklist"))
    assert transition.ledger_events == (ps.RELEASE, ps.EXIT_FILL) and record.exit_kind == "admin"


def test_rejections_and_expiry_carry_canonical_f7_codes():
    assert ps.CODE_INVALIDATED in REASON_CODES and ps.CODE_WAIT_EXPIRED in REASON_CODES
    assert ps.CODE_BELOW_MINIMUM in REASON_CODES
    assert SE_NAME_MAP[ps.RULE_INVALIDATED] == ("F7", ps.CODE_INVALIDATED, ps.ORDER_INTENT_SUB_STAGE)
    assert SE_NAME_MAP["EXPIRED_UNFILLED"] == ("F7", ps.CODE_WAIT_EXPIRED, ps.ORDER_INTENT_SUB_STAGE)
    assert SE_NAME_MAP["below_exchange_minimum"] == ("F7", ps.CODE_BELOW_MINIMUM,
                                                     ps.ORDER_INTENT_SUB_STAGE)
    cases = [(reserved(), ps.InvalidatedBeforeFill(), ps.CODE_INVALIDATED),
             (working(), ps.InvalidatedBeforeFill(), ps.CODE_INVALIDATED),
             (reserved(), ps.BelowExchangeMinimum(), ps.CODE_BELOW_MINIMUM),
             (working(), ps.BelowExchangeMinimum(), ps.CODE_BELOW_MINIMUM),
             (working(), ps.ExpireEntry(), ps.CODE_WAIT_EXPIRED),
             (working(), ps.RiskRefused("F7.economic_limit:daily_loss_limit"),
              "F7.economic_limit:daily_loss_limit")]
    for record, event, code in cases:
        new, transition = ps.apply(record, event)
        assert transition.reason_code == code == new.reason_code
        assert transition.ledger_events == (ps.RELEASE,)
        assert new.projection is None


def test_lot_step_flooring_keeps_tranches_aligned_and_sums_exact():
    record = opened("0.01", planned_qty=D("0.01"), qty_step=D("0.001"))
    assert ps.tranche_qty(record, 1, record.qty_open) == D("0.002")
    events = ps.observation_events(record, tick("106.5", 1), peak=D("100"),
                                   stop_policy=fixed_policy, stop_fill=identity,
                                   time_rules=()).events
    assert [(e.target, e.qty) for e in events] == [(1, D("0.002")), (2, D("0.005")), (3, D("0.003"))]
    final, _ = ps.apply_all(record, events)
    assert final.state == CLOSED and final.qty_exited == D("0.01")


@pytest.mark.parametrize("seed", range(6))
def test_random_lifecycles_conserve_quantities_and_reservations(seed):
    """Partial sums: whatever valid events arrive, Σ exits <= Σ entries <= planned, CLOSED means
    Σ exits == Σ entries, and every RESERVE is matched by exactly one RELEASE at a terminal."""
    rng = random.Random(1000 + seed)
    for _ in range(40):
        fractions = rng.choice([(D("0.25"), D("0.5"), D("0.25")), (D("0"), D("1"), D("0")),
                                (D("0"), D("0"), D("1")), (D("0.5"), D("0"), D("0.5"))])
        record = ps.new_position(plan(exit_fractions=fractions, qty_step=D("0.01")))
        ledger, peak, hours = [], D("100"), D("0")
        for _ in range(60):
            if record.state in TERMINAL_STATES:
                break
            if record.state in OPEN_STATES and rng.random() < 0.7:
                price = D(rng.randrange(9500, 10800)) / 100
                hours += D(rng.choice((1, 4)))
                result = ps.step(record, tick(price, hours), peak=peak, stop_policy=fixed_policy,
                                 stop_fill=identity, time_rules=TIME_RULES)
                record, peak = result.record, result.peak
                ledger += [e for t in result.transitions for e in t.ledger_events]
                continue
            kind = rng.choice(ps.EVENT_KINDS)
            event = sample(record, kind)
            if kind == "entry_fill" and record.entry_remaining > 0:
                event = ps.EntryFill(min(record.entry_remaining, D(rng.randrange(1, 80)) / 100), D("100"))
            try:
                record, transition = ps.apply(record, event)
            except TransitionRefused:
                continue
            ledger += list(transition.ledger_events)
            assert record.qty_exited <= record.qty_filled <= record.plan.planned_qty
        if record.state in TERMINAL_STATES:
            assert ledger.count(ps.RESERVE) == ledger.count(ps.RELEASE) <= 1
        if record.state == CLOSED:
            assert record.qty_exited == record.qty_filled > 0
            assert ledger.count(ps.EXIT_FILL) == len(record.exit_legs)
            assert ledger.count(ps.ENTRY_FILL) == len(record.entry_legs)


# ── 4. guards: SE-41, gap-through, time rules, closed-bar invalidation, entry ─────────────

def fixed_policy(highest, peak):
    """Arbitrary fixture policy: original stop, then break-even-like, then a trail under peak."""
    if highest == 0:
        return D("97")
    if highest == 1:
        return D("100.4")
    return max(D("102"), peak - D("2.5"))


def identity(reference):
    return reference


TIME_RULES = (TimeRule("stall_after_t1", D("24"), frozenset({1})),
              TimeRule("no_t1", D("24"), frozenset({0})),
              TimeRule("max_hold", D("48"), frozenset({0, 1, 2})))


def tick(price, hours, gap=True):
    price = D(price)
    return Observation(price, price, price, D(hours), price if gap else None)


def bar(high, low, close, hours):
    return Observation(D(high), D(low), D(close), D(hours), None)


def run(record, obs, peak="100", rules=TIME_RULES):
    return ps.step(record, obs, peak=D(peak), stop_policy=fixed_policy, stop_fill=identity,
                   time_rules=rules)


def test_se41_stop_in_force_wins_over_targets_on_the_same_bar():
    result = run(opened(), bar("107", "96", "105", "1"))
    assert [t.event_kind for t in result.transitions] == ["stop_exit"]
    assert result.record.state == CLOSED and result.record.highest_target == 0
    assert result.record.exit_legs[-1].price == D("97")


def test_target_then_post_target_stop_on_the_same_bar():
    result = run(opened(), bar("103", "99", "102", "1"))
    assert [t.event_kind for t in result.transitions] == ["target_1", "stop_exit"]
    assert [t.to_state for t in result.transitions] == [PARTIAL_T1, CLOSED]
    assert result.record.exit_legs[-1].price == D("100.4")


def test_gap_through_several_targets_is_one_transition_per_target_at_each_level():
    result = run(opened(), tick("104.5", "1"))
    assert [(t.rule_id, t.to_state) for t in result.transitions] == [("B6-08", PARTIAL_T1),
                                                                    ("B6-09", PARTIAL_T2)]
    assert [(leg.target, leg.qty, leg.price) for leg in result.record.exit_legs] == [
        (1, D("0.25"), D("102")), (2, D("0.5"), D("104"))]
    assert result.record.stop_level == D("102") and result.peak == D("104.5")
    result = run(opened(), tick("110", "1"))
    assert [t.event_kind for t in result.transitions] == ["target_1", "target_2", "target_3"]
    assert result.record.state == CLOSED and result.record.qty_exited == D("1")


def test_gap_through_the_stop_references_the_observed_price():
    result = run(opened(), tick("94", "1"))
    assert result.record.exit_legs[-1].price == D("94")
    result = run(opened(), tick("94", "1", gap=False))
    assert result.record.exit_legs[-1].price == D("97")


def test_trailing_stop_moves_with_a_new_peak_and_is_checked_on_the_same_bar():
    record = partial_t2()
    result = run(record, bar("108", "105.4", "106", "1"), peak="104")
    assert [t.event_kind for t in result.transitions] == ["target_3"]
    record = ps.restore(record.plan, state=PARTIAL_T2, reservation_active=False, entry_open=False,
                        entry_legs=record.entry_legs, exit_legs=record.exit_legs, highest_target=2,
                        stop_level=D("102"), reason_code=None, exit_kind=None, exit_rule=None)
    result = run(record, bar("105.8", "103.2", "103.5", "1"), peak="104")
    assert [t.event_kind for t in result.transitions] == ["stop_update", "stop_exit"]
    assert result.record.exit_legs[-1].price == D("103.3")


def test_merged_tranches_advance_the_state_without_a_leg_and_close_when_flat():
    record = opened(exit_fractions=(D("0"), D("1"), D("0")))
    result = run(record, tick("102.5", "1"))
    (transition,) = [t for t in result.transitions if t.event_kind == "target_1"]
    assert transition.ledger_events == () and result.record.state == PARTIAL_T1
    assert result.record.exit_legs == () and result.record.projection == "partially_exited"
    result = run(result.record, tick("104", "2"), peak="102.5")
    assert result.record.state == CLOSED and result.record.exit_kind == "target"
    assert result.record.highest_target == 2 and result.transitions[-1].rule_id == "B6-09"
    record = opened(exit_fractions=(D("0.25"), D("0.75"), D("0")))
    result = run(record, tick("104", "1"))
    assert result.record.state == CLOSED and result.record.qty_exited == D("1")


def test_time_rules_apply_in_declared_order_and_only_at_their_targets():
    assert run(opened(), tick("100", "23")).record.state == OPEN
    result = run(opened(), tick("100", "24"))
    assert result.record.exit_kind == "time" and result.record.exit_rule == "no_t1"
    result = run(partial_t1(), tick("101", "24"), peak="102")
    assert result.record.exit_rule == "stall_after_t1"
    result = run(partial_t2(), tick("103", "47"), peak="104")
    assert result.record.state == PARTIAL_T2
    result = run(partial_t2(), tick("103", "48"), peak="104")
    assert result.record.exit_rule == "max_hold" and result.record.exit_legs[-1].price == D("103")
    assert run(opened(), tick("100", "1000"), rules=()).record.state == OPEN


def test_closed_bar_invalidation_is_pre_t1_only():
    record = opened(invalidation=D("98.5"))
    (event,) = ps.closed_bar_events(record, bar_close=D("98.5"), exit_price=D("98.2"))
    final, transition = ps.apply(record, event)
    assert transition.rule_id == "B6-07" and final.exit_kind == "invalidation"
    assert ps.closed_bar_events(record, bar_close=D("98.6"), exit_price=D("98.2")) == ()
    assert ps.closed_bar_events(partial_t1(), bar_close=D("90"), exit_price=D("90")) == ()
    with pytest.raises(TransitionRefused):
        ps.closed_bar_events(working(), bar_close=D("90"), exit_price=D("90"))


def test_guards_refuse_bad_inputs():
    with pytest.raises(TransitionRefused) as info:
        run(opened(), Observation(D("99"), D("100"), D("99.5"), D("1"), None))
    assert info.value.reason == "invalid_observation"
    with pytest.raises(TransitionRefused) as info:
        ps.step(opened(), tick("101", "1"), peak=D("100"), stop_policy=lambda h, p: 97.0,
                stop_fill=identity, time_rules=())
    assert info.value.reason == "invalid_policy_output"
    with pytest.raises(TransitionRefused) as info:
        ps.step(opened(), tick("101", "1"), peak=D("100"), stop_policy=fixed_policy,
                stop_fill=identity, time_rules=None)
    assert info.value.reason == "invalid_policy"
    with pytest.raises(TransitionRefused) as info:
        run(opened(), tick("101", "1"), rules=(TimeRule("x", D("1"), frozenset({3})),))
    assert info.value.reason == "invalid_policy"
    with pytest.raises(TransitionRefused):
        run(working(), tick("101", "1"))


@pytest.mark.parametrize("invalidation", [None, "98.5", "99.9"])
@pytest.mark.parametrize("state", [PLANNED, WORKING])
def test_entry_guard_matches_decide_long_entry(invalidation, state):
    """Parity with shared/entry_execution.py decide_long_entry (the observed_price_v0 policy)."""
    inv = D(invalidation) if invalidation else D("97")
    record = reserved(invalidation=inv) if state == PLANNED else ps.apply(
        reserved(invalidation=inv), ps.RestEntry())[0]
    expected = {"reject": ps.ENTRY_INVALIDATED, "market": ps.ENTRY_FILLABLE,
                "limit_wait": ps.ENTRY_REST if state == PLANNED else ps.ENTRY_WAIT}
    for cents in range(9500, 10300, 7):
        price = D(cents) / 100
        legacy = decide_long_entry(trade_type="momentum", planned_entry=100.0,
                                   current_price=float(price), stop_loss=97.0,
                                   invalidation_price=float(invalidation) if invalidation else None)
        assert ps.entry_guard(record, price) == expected[legacy.action], (price, legacy)


# ── 5. ledger interoperability (WP-IT-06) ─────────────────────────────────────────────────

T0 = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)


def ledger_replay(record, events, fee=D("0.05")):
    """Translate each transition's ledger events into shared.portfolio_ledger events; the ledger
    re-checks PR-I1..PR-I6 after every one. Returns the records and the ledger."""
    ledger = pl.PortfolioLedger(ledger_id="L1", quote_asset="USDT",
                                cost_model_id="research_baseline_v1", money_quantum=STEP)
    ledger.apply(pl.Deposit("genesis", T0, D("1000")))
    pid, n, history = record.plan.intent_id, 0, []
    for event in events:
        record, transition = ps.apply(record, event)
        for name in transition.ledger_events:
            n += 1
            at, eid = T0 + timedelta(minutes=n), f"e-{n}"
            if name == ps.RESERVE:
                ledger.apply(pl.Reserve(eid, at, pid, record.plan.symbol, record.plan.strategy_id,
                                        event.amount))
            elif name == ps.ENTRY_FILL:
                ledger.apply(pl.EntryFill(eid, at, pid, event.qty, event.price, fee, "USDT", D("0")))
            elif name == ps.RELEASE:
                ledger.apply(pl.ReleaseReservation(eid, at, pid))
            else:
                ledger.apply(pl.ExitFill(eid, at, pid, f"leg-{n}", event.qty, event.price, D("0"),
                                         "USDT", D("0")))
        history.append((record, ledger.state))
    return history, ledger


def test_full_lifecycle_drives_the_portfolio_ledger_with_matching_projection():
    events = [ps.Reserve(D("101")), ps.EntryFill(D("0.4"), D("100")), ps.EntryFill(D("0.6"), D("99.5")),
              ps.TargetFill(1, D("0.25"), D("102"), D("100.4")),
              ps.TargetFill(2, D("0.5"), D("104"), D("101.4")), ps.StopExit(D("0.25"), D("101.3"))]
    history, ledger = ledger_replay(fresh(), events)
    for record, state in history:
        position = state.positions.get(record.plan.intent_id)
        assert (position.state if position else "pending") == record.projection
        assert (state.reserved > 0) == record.reservation_active
    final = history[-1][1]
    assert final.reserved == 0 and final.positions["i-1"].qty_open == 0
    assert not final.reservations["i-1"].active


@pytest.mark.parametrize("events", [
    [ps.Reserve(D("101")), ps.RestEntry(), ps.InvalidatedBeforeFill()],
    [ps.Reserve(D("101")), ps.RestEntry(), ps.ExpireEntry()],
    [ps.Reserve(D("101")), ps.BelowExchangeMinimum()],
    [ps.Reserve(D("101")), ps.RiskRefused("F7.capacity_full")],
])
def test_pre_fill_terminals_release_exactly_the_reservation(events):
    history, ledger = ledger_replay(fresh(), events)
    assert history[-1][0].projection is None
    assert ledger.state.reserved == 0 and ledger.state.cash == D("1000")
    assert ledger.state.positions == {}


def test_entry_remainder_release_before_an_exit_keeps_the_ledger_consistent():
    events = [ps.Reserve(D("101")), ps.EntryFill(D("0.4"), D("100")),
              ps.AdminExit(D("0.4"), D("99"), "owner_blacklist")]
    history, ledger = ledger_replay(fresh(), events)
    assert ledger.state.reserved == 0 and ledger.state.positions["i-1"].state == "closed"


def test_zero_tranche_target_projects_partially_exited_while_the_ledger_says_open():
    """Documented divergence: WP-IR-06 maps PARTIAL_T1 to partially_exited, but a merged (zero)
    T1 tranche books no EXIT_FILL, so the ledger position is still 'open'."""
    record = fresh(exit_fractions=(D("0"), D("1"), D("0")))
    events = [ps.Reserve(D("101")), ps.EntryFill(D("1"), D("100")),
              ps.TargetFill(1, D("0"), D("102"), D("100.4")), ps.TargetFill(2, D("1"), D("104"), None)]
    history, _ = ledger_replay(record, events)
    record, state = history[2]
    assert record.projection == "partially_exited" and state.positions["i-1"].state == "open"
    record, state = history[3]
    assert record.projection == "closed" == state.positions["i-1"].state


# ── 6. parity with shared/triple_barrier.py and shared/partial_exits.py ───────────────────

def legacy_policies(cfg):
    """The legacy configuration, read through the pinned production functions."""
    def stop_policy(highest, peak):
        level = TripleBarrierState(peak=float(peak), highest_target=highest).effective_stop(cfg)[0]
        return ps.decimal_from_legacy(level)

    def stop_fill(reference):
        return ps.decimal_from_legacy(modeled_stop_exit(cfg.entry, float(reference), cfg.stop_slippage)[0])

    rules = (TimeRule("T1_expired_24h", ps.decimal_from_legacy(cfg.t1_expiry_h), frozenset({1})),
             TimeRule(f"no_T1_expired_{int(cfg.no_t1_expiry_h)}h",
                      ps.decimal_from_legacy(cfg.no_t1_expiry_h), frozenset({0})),
             TimeRule(f"expired_{int(cfg.expiry_h)}h", ps.decimal_from_legacy(cfg.expiry_h),
                      frozenset({0, 1, 2})))
    return stop_policy, stop_fill, rules


def legacy_label(record):
    if record.exit_kind == "stop":
        return {0: "stop_loss", 1: "break_even"}.get(record.highest_target, "trailing_stop")
    if record.exit_kind == "target":
        return "T3" if record.highest_target == 3 else "target_flat"
    return record.exit_rule


def make_cfg(levels, timeframe=None):
    entry, t1, t2, t3, stop = levels
    kwargs = {}
    if timeframe:
        kwargs = dict(zip(("expiry_h", "t1_expiry_h", "no_t1_expiry_h"),
                          expiry_policy_for_timeframe(timeframe)))
    return TripleBarrierConfig(symbol="SYN", entry=entry, target_1=t1, target_2=t2, target_3=t3,
                               stop_loss=stop, **kwargs)


def machine_record(cfg, fractions):
    p = ps.PositionPlan(intent_id="p", symbol="SYN", strategy_id="legacy", planned_qty=D("1"),
                        planned_entry=ps.decimal_from_legacy(cfg.entry),
                        stop=ps.decimal_from_legacy(cfg.stop_loss),
                        invalidation=ps.decimal_from_legacy(cfg.stop_loss),
                        targets=tuple(ps.decimal_from_legacy(t) for t in
                                      (cfg.target_1, cfg.target_2, cfg.target_3)),
                        exit_fractions=fractions, qty_step=STEP)
    record = ps.apply(ps.new_position(p), ps.Reserve(D("100")))[0]
    return ps.apply(record, ps.EntryFill(D("1"), p.planned_entry))[0]


def compare_paths(cfg, bars, *, tick_mode, trade_amount, min_notional, partial=True):
    """Run one synthetic path through step_barrier + fills_between and through the machine."""
    distribution = target_distribution(trade_amount, min_notional) if partial else {1: 0, 2: 0, 3: 1}
    fractions = tuple(ps.decimal_from_legacy(float(distribution[k])) for k in (1, 2, 3))
    stop_policy, stop_fill, rules = legacy_policies(cfg)
    record, peak, hours = machine_record(cfg, fractions), ps.decimal_from_legacy(cfg.entry), D(0)
    state = TripleBarrierState(peak=cfg.entry)
    targets = {1: cfg.target_1, 2: cfg.target_2, 3: cfg.target_3}
    legacy_legs, machine_legs, realized_pct, realized_usdt, remaining = [], [], 0.0, 0.0, 1.0
    out = {"diverged": None}
    for i, (high, low, close, dh) in enumerate(bars):
        prev = state.highest_target
        res = step_barrier(cfg, state, high, low, close, dh,
                           stop_observation_price=close if tick_mode else None)
        if partial and state.highest_target > prev:
            for f in fills_between(previous_target=prev, reached_target=state.highest_target,
                                   entry=cfg.entry, targets=targets, trade_amount=trade_amount,
                                   min_notional=min_notional):
                legacy_legs.append((i, f.target, f.fraction, f.price))
                realized_pct += f.gross_pct_contribution
                realized_usdt += f.gross_usdt
                remaining = max(0.0, remaining - f.fraction)
        if record.state not in TERMINAL_STATES:
            hours += ps.decimal_from_legacy(dh)
            obs = Observation(*(ps.decimal_from_legacy(x) for x in (high, low, close)), hours,
                              ps.decimal_from_legacy(close) if tick_mode else None)
            result = ps.step(record, obs, peak=peak, stop_policy=stop_policy, stop_fill=stop_fill,
                             time_rules=rules)
            for t in result.transitions:
                if t.event_kind.startswith("target_") and t.event.qty > 0:
                    machine_legs.append((i, t.event.target, float(t.event.qty), float(t.event.price)))
            record, peak = result.record, result.peak
            assert float(peak) == state.peak
            assert record.highest_target == state.highest_target
            if record.state == CLOSED and legacy_label(record) == "target_flat":
                out["diverged"] = (i, remaining)          # machine flat at T2; legacy stays open
            elif record.state != CLOSED:
                assert res is None
                assert float(record.stop_level) == state.effective_stop(cfg)[0]
            else:
                assert legacy_label(record) == res.exit_reason
                assert round(float(record.exit_legs[-1].price), 8) == res.exit_price
        if res is not None:
            gross_pct, _ = aggregate_close(entry=cfg.entry, final_exit=res.exit_price,
                                           trade_amount=trade_amount, realized_pct=realized_pct,
                                           realized_usdt=realized_usdt,
                                           remaining_fraction=remaining)
            assert record.state == CLOSED
            if res.exit_reason == "T3" and remaining > 0:     # legacy books an unsold T3 remainder
                legacy_legs.append((i, 3, remaining, cfg.target_3))   # as the terminal exit
            assert legacy_legs == machine_legs
            machine_pct = sum(float(leg.qty) * (float(leg.price) / cfg.entry - 1) * 100
                              for leg in record.exit_legs)
            assert machine_pct == pytest.approx(gross_pct, abs=1e-6)
            out.update(closed_bar=i, record=record, legacy=res)
            return out
    out.update(closed_bar=None, record=record, legacy=None)
    return out


LEVEL_SETS = ((100.0, 102.0, 104.0, 106.0, 97.0),     # tests/test_triple_barrier.py levels
              (100.0, 100.2, 104.0, 106.0, 97.0))     # T1 below the net break-even stop


REGIMES = ((0, 180), (35, 90), (0, 25), (-10, 60))      # (drift, volatility) in cents per step


def random_bars(rng, *, tick_mode, n):
    price, bars = 100.0, []
    drift, vol = rng.choice(REGIMES)
    for _ in range(n):
        move = (drift + rng.randrange(-vol, vol + 1)) / 100
        if tick_mode:
            price = max(80.0, round(price + move, 2))
            bars.append((price, price, price, rng.choice((0.25, 1.0, 4.0))))
        else:
            close = max(80.0, round(price + move, 2))
            high = round(max(price, close) + rng.randrange(0, 120) / 100, 2)
            low = round(min(price, close) - rng.randrange(0, 120) / 100, 2)
            bars.append((high, low, close, rng.choice((1.0, 4.0))))
            price = close
    return bars


@pytest.mark.parametrize("tick_mode", [True, False], ids=["tick", "bar"])
@pytest.mark.parametrize("levels", LEVEL_SETS, ids=["standard", "small_t1"])
@pytest.mark.parametrize("timeframe", [None, "4h"])
def test_parity_with_triple_barrier_and_partial_exits_on_synthetic_paths(tick_mode, levels, timeframe):
    rng = random.Random(f"wp-d03-{tick_mode}-{levels[1]}-{timeframe}")
    cfg = make_cfg(levels, timeframe)
    closes = set()
    for _ in range(60):
        bars = random_bars(rng, tick_mode=tick_mode, n=120)
        result = compare_paths(cfg, bars, tick_mode=tick_mode, trade_amount=50.0, min_notional=5.0)
        assert result["diverged"] is None
        if result["legacy"] is not None:
            closes.add(result["legacy"].exit_reason)
        result = compare_paths(cfg, bars, tick_mode=tick_mode, trade_amount=50.0, min_notional=5.0,
                               partial=False)
        assert result["diverged"] is None
    assert {"stop_loss", "break_even"} <= closes


@pytest.mark.parametrize("tick_mode", [True, False], ids=["tick", "bar"])
def test_merged_t3_tranche_closes_at_t2_where_legacy_stays_open_with_zero_remainder(tick_mode):
    """Documented divergence (partial_exits.py L14-23): with T1 and T3 merged into T2 the T2 leg
    sells everything. The machine closes (CLOSED: quantity 0); legacy keeps the trade open with
    remaining_fraction 0 until a stop, T3 or a time rule. Realized gross P&L is identical."""
    cfg = make_cfg(LEVEL_SETS[0])
    rng = random.Random("wp-d03-merged")
    seen = 0
    for _ in range(60):
        bars = random_bars(rng, tick_mode=tick_mode, n=120)
        result = compare_paths(cfg, bars, tick_mode=tick_mode, trade_amount=10.0, min_notional=5.0)
        if result["diverged"] is not None:
            seen += 1
            bar_index, remaining = result["diverged"]
            assert remaining == 0.0
            assert result["record"].exit_kind == "target" and result["record"].highest_target == 2
            assert result["legacy"] is None or result["closed_bar"] >= bar_index
    assert seen > 0


def test_parity_hand_cases_from_the_legacy_regression_suite():
    cfg = make_cfg(LEVEL_SETS[0])
    cases = [([(107, 96, 105, 1.0)], "stop_loss", 96.903),
             ([(103, 99, 102, 1.0)], "break_even", 100.3),
             ([(107, 100.5, 106, 1.0)], "T3", 106.0)]
    for bars, reason, price in cases:
        result = compare_paths(cfg, bars, tick_mode=False, trade_amount=50.0, min_notional=5.0)
        assert result["legacy"].exit_reason == reason and result["legacy"].exit_price == price
    result = compare_paths(cfg, [(94, 94, 94, 1.0)], tick_mode=True, trade_amount=50.0,
                           min_notional=5.0)
    assert result["legacy"].exit_price == 93.906
    hold = [(103.5, 103.5, 103.5, 1.0)] * 47
    for bars, reason in (([(104.5, 104.5, 104.5, 1.0), (101.5, 101.5, 101.5, 1.0)], "trailing_stop"),
                         ([(102.5, 102.5, 102.5, 1.0)] + [(101.0, 101.0, 101.0, 1.0)] * 23,
                          "T1_expired_24h"),
                         ([(100.5, 100.5, 100.5, 1.0)] * 24, "no_T1_expired_24h"),
                         ([(104.5, 104.5, 104.5, 1.0)] + hold, "expired_48h")):
        result = compare_paths(cfg, bars, tick_mode=True, trade_amount=50.0, min_notional=5.0)
        assert result["legacy"].exit_reason == reason
        assert result["closed_bar"] == len(bars) - 1
    small = make_cfg(LEVEL_SETS[1])
    result = compare_paths(small, [(100.2, 100.2, 100.2, 1.0)], tick_mode=True, trade_amount=50.0,
                           min_notional=5.0)
    assert result["legacy"].exit_reason == "break_even"
    assert [leg.kind for leg in result["record"].exit_legs] == ["target", "stop"]


# ── 7. isolation ──────────────────────────────────────────────────────────────────────────

def test_module_imports_only_the_standard_library():
    tree = ast.parse(Path(ps.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {"__future__", "dataclasses", "decimal", "math", "re", "typing"}


def test_only_the_tracker_shadow_imports_the_module():
    """Wired (WP2 integration): exactly one importer, the default-off tracker shadow
    (POSITION_STATE_SHADOW); no service imports the machine directly and none enforces it."""
    pattern = re.compile(r"(from\s+shared(\.|\s+import\s+[^\n]*\b)|import\s+shared\.)position_state\b")
    offenders = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
                 if "tests" not in p.parts and p.stem != "position_state"
                 and pattern.search(p.read_text(errors="ignore"))]
    assert offenders == ["shared/position_state_shadow.py"]


def test_removed_from_the_experimental_registry_once_wired():
    from experimental_modules import EXPERIMENTAL_SHARED
    assert "position_state" not in EXPERIMENTAL_SHARED
