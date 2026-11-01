"""WP-E01 (PR-C02, R7): synthetic, deterministic tests of shared.portfolio_ledger.

All fixtures are hand-written or generated from fixed seeds. Thresholds, multipliers, capital and
settlement choices below are arbitrary test fixtures, not proposals for any owner decision.
"""
import ast
import dataclasses
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from shared import portfolio_ledger as pl
from shared.portfolio_ledger import (DeRiskingLadder, Deposit, EntryFill, ExitFill, LadderStep,
                                     LedgerError, LedgerEventConflict, LedgerInvariantViolation,
                                     Mark, ReleaseReservation, Reserve, SettlementRule)

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 10, tzinfo=UTC)          # a Monday
Q = D("0.00000001")
USDT = "USDT"


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def new_ledger(model="research_baseline_v1"):
    return pl.PortfolioLedger(ledger_id="L1", quote_asset=USDT, cost_model_id=model,
                              money_quantum=Q)


def entry(eid, minute, intent, qty, price, fee=D(0), cost=D(0), ref=None):
    return EntryFill(eid, at(minute), intent, D(qty), D(price), D(fee), USDT, D(cost), ref)


def exit_(eid, minute, pid, leg, qty, price, fee=D(0), cost=D(0), ref=None):
    return ExitFill(eid, at(minute), pid, leg, D(qty), D(price), D(fee), USDT, D(cost), ref)


def round_trip(ledger, pid, start, *, symbol="BTCUSDT", strategy="s_a", qty="2", buy="50",
               sell="55", fee_in="0.1", fee_out="0.11", reserve="101"):
    ledger.apply(Reserve(f"r-{pid}", at(start), pid, symbol, strategy, D(reserve)))
    ledger.apply(entry(f"e-{pid}", start + 1, pid, qty, buy, fee_in))
    ledger.apply(ReleaseReservation(f"rel-{pid}", at(start + 2), pid))
    return ledger.apply(exit_(f"x-{pid}", start + 3, pid, "final", qty, sell, fee_out))


def view(snapshot, pid):
    return next(v for v in snapshot.positions if v.position_id == pid)


def refused(ledger, event, reason):
    before_state, before_hash, before_len = ledger.state, ledger.state_hash, len(ledger.entries)
    with pytest.raises(LedgerError) as info:
        ledger.apply(event)
    assert info.value.reason == reason
    assert ledger.state is before_state and ledger.state_hash == before_hash
    assert len(ledger.entries) == before_len
    return info.value


# ── basic flows ────────────────────────────────────────────────────────────────────────────

def test_genesis_must_be_a_deposit():
    ledger = new_ledger()
    refused(ledger, Reserve("r1", at(0), "p1", "BTCUSDT", "s_a", D(10)), "genesis_required")
    first = ledger.apply(Deposit("d0", at(0), D(1000)))
    assert first.sequence == 1 and first.prev_state_hash == pl.GENESIS_HASH
    snap = first.snapshot
    assert (snap.cash, snap.available, snap.reserved, snap.net_contributions) == (D(1000),) * 2 + (D(0), D(1000))
    assert snap.equity_mtm == D(1000) and snap.unrealized == D(0)


def test_round_trip_books_fee_on_each_leg():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    snap = ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(101))).snapshot
    assert (snap.cash, snap.reserved, snap.available) == (D(1000), D(101), D(899))

    fill = ledger.apply(entry("e1", 2, "p1", "2", "50", "0.1"))
    snap = fill.snapshot
    assert fill.deltas == {"net_contributions": D(0), "cash": D("-100.1"), "reserved": D("-100.1"),
                           "committed_cost": D(100), "realized_gross": D(0), "fees": D("0.1"),
                           "costs": D(0)}
    assert (snap.cash, snap.reserved, snap.available) == (D("899.9"), D("0.9"), D("899.0"))
    assert snap.committed_cost == D(100) and snap.fees == D("0.1")
    assert snap.realized_gross == 0 and snap.realized_net == D("-0.1")
    assert snap.equity_cost == D("999.9")

    snap = ledger.apply(ReleaseReservation("rel1", at(3), "p1")).snapshot
    assert (snap.reserved, snap.available) == (D(0), D("899.9"))

    snap = ledger.apply(exit_("x1", 4, "p1", "final", "2", "55", "0.11")).snapshot
    assert snap.cash == D("1009.79") and snap.committed_cost == 0
    assert snap.realized_gross == D(10) and snap.fees == D("0.21") and snap.realized_net == D("9.79")
    assert snap.equity_cost == snap.equity_mtm == D(1000) + snap.realized_net
    pos = view(snap, "p1")
    assert pos.state == "closed" and pos.closed_at == at(4) and pos.close_index == 1
    assert pos.fees == D("0.21") and pos.realized_net == D("9.79")


def test_partial_entry_fills_and_partial_exits():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "ETHUSDT", "s_a", D(400)))
    ledger.apply(entry("e1", 2, "p1", "1", "100", "0.1"))
    snap = ledger.apply(entry("e2", 3, "p1", "2", "103", "0.206")).snapshot
    pos = view(snap, "p1")
    assert pos.qty_open == D(3) and pos.cost_basis == D(306) and pos.avg_entry_price == D(102)
    assert snap.cash == D("693.694") and snap.reserved == D("93.694") and snap.available == D(600)
    snap = ledger.apply(ReleaseReservation("rel1", at(4), "p1")).snapshot
    assert snap.reserved == 0 and snap.available == D("693.694")

    leg1 = ledger.apply(exit_("x1", 5, "p1", "t1", "0.75", "110", "0.0825"))
    assert leg1.deltas["committed_cost"] == D("-76.5") and leg1.deltas["realized_gross"] == D(6)
    assert view(leg1.snapshot, "p1").state == "partially_exited"
    leg2 = ledger.apply(exit_("x2", 6, "p1", "t2", "1.5", "120", "0.18"))
    assert leg2.deltas["committed_cost"] == D(-153) and leg2.deltas["realized_gross"] == D(27)
    leg3 = ledger.apply(exit_("x3", 7, "p1", "t3", "0.75", "90", "0.0675"))
    assert leg3.deltas["committed_cost"] == D("-76.5") and leg3.deltas["realized_gross"] == D(-9)

    snap = leg3.snapshot
    pos = view(snap, "p1")
    assert pos.state == "closed" and pos.qty_open == 0 and pos.cost_basis == 0
    assert snap.realized_gross == D(24) and snap.fees == D("0.636")
    assert snap.realized_net == D("23.364") and snap.cash == D("1023.364")
    state_pos = ledger.state.positions["p1"]
    assert state_pos.qty_entered == state_pos.qty_exited == D(3)
    assert [leg.fee for leg in state_pos.entries] == [D("0.1"), D("0.206")]
    assert [leg.fee for leg in state_pos.exits] == [D("0.0825"), D("0.18"), D("0.0675")]


def test_pro_rata_release_is_quantized_and_final_leg_releases_the_remainder():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "SOLUSDT", "s_b", D(100)))
    ledger.apply(entry("e1", 2, "p1", "1", "10"))
    ledger.apply(entry("e2", 3, "p1", "2", "10.005"))
    assert ledger.state.positions["p1"].cost_basis == D("30.01")      # 30.01 / 3 does not terminate
    first = ledger.apply(exit_("x1", 4, "p1", "a", "1", "11"))
    assert first.deltas["committed_cost"] == -D("10.00333333")
    assert first.deltas["realized_gross"] == D("0.99666667")
    last = ledger.apply(exit_("x2", 5, "p1", "b", "2", "11"))
    assert last.deltas["committed_cost"] == -D("20.00666667")
    assert ledger.state.committed_cost == 0 and ledger.state.positions["p1"].cost_basis == 0
    assert ledger.state.realized_gross == D(33) - D("30.01")


def test_losing_trade_reduces_equity_and_sizing_base_at_once():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(500)))
    snap = round_trip(ledger, "p1", 1, buy="50", sell="45", qty="1", fee_in="0.05",
                      fee_out="0.045", reserve="60").snapshot
    assert snap.realized_gross == D(-5) and snap.fees == D("0.095")
    assert snap.realized_net == D("-5.095") and snap.equity_cost == D("494.905")
    for reconciled in ((), ("p1",)):
        base = pl.compounding_base(snap, starting_capital=D(500), as_of=at(10),
                                   settlement=SettlementRule("next_utc_week", None),
                                   reconciled_position_ids=reconciled)
        assert base.base == D("494.905")
    assert pl.loss_streak(snap) == 1


def test_simultaneous_positions_exposure_and_equity_identity():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("ra", at(1), "a", "BTCUSDT", "s1", D(110)))
    ledger.apply(entry("ea", 2, "a", "1", "100"))
    ledger.apply(Reserve("rb", at(3), "b", "ETHUSDT", "s1", D(210)))
    ledger.apply(entry("eb", 4, "b", "2", "100"))
    ledger.apply(Reserve("rc", at(5), "c", "BTCUSDT", "s2", D(60)))
    ledger.apply(entry("ec", 6, "c", "0.5", "100"))
    snap = ledger.apply(Reserve("rd", at(7), "d", "SOLUSDT", "s2", D(40))).snapshot
    assert snap.cash == D(650) and snap.reserved == D(70) and snap.available == D(580)
    assert snap.committed_cost == D(350)
    assert snap.unrealized is None and snap.equity_mtm is None
    assert snap.unmarked_symbols == ("BTCUSDT", "ETHUSDT")

    ledger.apply(Mark("m1", at(8), "BTCUSDT", D(110), "stream"))
    snap = ledger.apply(Mark("m2", at(9), "ETHUSDT", D(90), "rest")).snapshot
    assert snap.unrealized == D(-5) and snap.equity_mtm == D(995)
    assert snap.equity_mtm == snap.equity_cost + snap.unrealized
    assert snap.equity_mtm == snap.cash + sum(v.market_value for v in snap.positions)
    gross = snap.gross_exposure
    assert (gross.committed_cost, gross.market_value, gross.reserved, gross.open_positions) == \
        (D(350), D(345), D(70), 3)
    btc, eth, sol = (snap.by_symbol[s] for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    assert (btc.committed_cost, btc.market_value, btc.reserved, btc.open_positions) == (D(150), D(165), D(20), 2)
    assert (eth.committed_cost, eth.market_value, eth.reserved, eth.open_positions) == (D(200), D(180), D(10), 1)
    assert (sol.committed_cost, sol.market_value, sol.reserved, sol.open_positions) == (D(0), D(0), D(40), 0)
    s1, s2 = snap.by_strategy["s1"], snap.by_strategy["s2"]
    assert (s1.committed_cost, s1.market_value, s1.reserved) == (D(300), D(290), D(20))
    assert (s2.committed_cost, s2.market_value, s2.reserved) == (D(50), D(55), D(50))
    assert view(snap, "a").unrealized == D(10) and view(snap, "b").unrealized == D(-20)


def test_available_and_cash_never_include_unrealized_gains():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("ra", at(1), "a", "BTCUSDT", "s1", D(100)))
    base_snap = ledger.apply(entry("ea", 2, "a", "1", "100")).snapshot
    rule = SettlementRule("at_close", None)
    for minute, price in enumerate(("1", "100", "1000000", "250"), start=3):
        entry_ = ledger.apply(Mark(f"m{minute}", at(minute), "BTCUSDT", D(price), "stream"))
        assert all(value == 0 for value in entry_.deltas.values())
        snap = entry_.snapshot
        assert (snap.cash, snap.available, snap.reserved) == \
            (base_snap.cash, base_snap.available, base_snap.reserved)
        assert pl.capital_available(snap) == base_snap.available == snap.cash - snap.reserved
        base = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(minute),
                                   settlement=rule, reconciled_position_ids=())
        assert base.base == D(1000) and base.base <= snap.equity_cost
    assert snap.equity_mtm == D(900) + D(250)


# ── reservations ───────────────────────────────────────────────────────────────────────────

def test_reservation_release_returns_exactly_the_remainder():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(300)))
    ledger.apply(entry("e1", 2, "p1", "1", "100", "0.1"))
    rel = ledger.apply(ReleaseReservation("rel1", at(3), "p1"))
    assert rel.deltas["reserved"] == D("-199.9") and rel.deltas["cash"] == 0
    res = ledger.state.reservations["p1"]
    assert (res.amount, res.consumed, res.released, res.remaining, res.active) == \
        (D(300), D("100.1"), D("199.9"), D(0), False)
    refused(ledger, ReleaseReservation("rel2", at(4), "p1"), "reservation_inactive")
    refused(ledger, entry("e2", 4, "p1", "1", "100"), "reservation_inactive")
    refused(ledger, ReleaseReservation("rel3", at(4), "nope"), "unknown_intent")
    refused(ledger, Reserve("r1b", at(4), "p1", "BTCUSDT", "s_a", D(5)), "intent_exists")


def test_working_reservation_blocks_capital_and_unfilled_release_restores_it():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(100)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(70)))
    refused(ledger, Reserve("r2", at(2), "p2", "ETHUSDT", "s_a", D(31)), "insufficient_available")
    ledger.apply(Reserve("r3", at(2), "p3", "ETHUSDT", "s_a", D(30)))
    assert ledger.snapshot().available == 0
    snap = ledger.apply(ReleaseReservation("rel1", at(3), "p1")).snapshot
    assert snap.available == D(70) and snap.reserved == D(30) and snap.positions == ()


def test_entry_fill_cannot_overdraw_cash_and_no_entries_after_an_exit():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(100)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(50)))
    refused(ledger, entry("e1", 2, "p1", "2", "50", "0.1"), "insufficient_available")
    ledger.apply(entry("e1", 2, "p1", "1", "50", "0.05"))
    ledger.apply(exit_("x1", 3, "p1", "t1", "0.5", "51"))
    refused(ledger, entry("e2", 4, "p1", "0.1", "50"), "position_not_accepting_entries")


# ── refusals, idempotency, invariants ──────────────────────────────────────────────────────

def test_invalid_events_are_refused_with_a_named_reason_and_leave_state_unchanged():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(200)))
    ledger.apply(entry("e1", 2, "p1", "1", "100"))
    ledger.apply(exit_("x1", 3, "p1", "t1", "0.4", "110"))
    refused(ledger, exit_("x2", 4, "p1", "t2", "0.61", "110"), "over_exit")
    refused(ledger, exit_("x3", 4, "p1", "t1", "0.1", "110"), "duplicate_leg")
    refused(ledger, exit_("x4", 4, "nope", "t1", "0.1", "110"), "unknown_position")
    refused(ledger, Deposit("d1", datetime(2026, 1, 5, 11), D(1)), "naive_time")
    refused(ledger, Deposit("d2", at(-1), D(1)), "time_regression")
    refused(ledger, Deposit("d3", at(5), 1.5), "invalid_event")
    refused(ledger, Deposit("d4", at(5), D("NaN")), "invalid_event")
    refused(ledger, Deposit("d5", at(5), D("Infinity")), "invalid_event")
    refused(ledger, Deposit("d6", at(5), D(0)), "invalid_event")
    refused(ledger, Mark("m1", at(5), "BTCUSDT", D(0), "stream"), "invalid_event")
    refused(ledger, Mark("m2", at(5), "BTCUSDT", D(1), ""), "invalid_event")
    bnb_fee = ExitFill("x5", at(5), "p1", "t3", D("0.1"), D(110), D("0.01"), "BNB", D(0))
    refused(ledger, bnb_fee, "fee_asset_unsupported")
    refused(ledger, "not an event", "invalid_event")
    ledger.apply(exit_("x6", 6, "p1", "t9", "0.6", "120"))
    refused(ledger, exit_("x7", 7, "p1", "t10", "0.1", "120"), "position_closed")
    with pytest.raises(LedgerError) as info:
        pl.PortfolioLedger(ledger_id="L", quote_asset=USDT, cost_model_id="flat_30bps",
                           money_quantum=Q)
    assert info.value.reason == "cost_model_unknown"
    with pytest.raises(TypeError):
        pl.PortfolioLedger(ledger_id="L", quote_asset=USDT, cost_model_id="legacy_tracker_v1")


def test_duplicate_event_is_a_recorded_no_op_and_a_conflict_raises():
    ledger = new_ledger()
    first = ledger.apply(Deposit("d0", at(0), D(1000)))
    again = ledger.apply(Deposit("d0", at(0), D(1000)))
    assert again is first and len(ledger.entries) == 1 and ledger.duplicate_log == ("d0",)
    # the same instant written with another offset and the same amount at another exponent
    plus2 = timezone(timedelta(hours=2))
    same = Deposit("d0", datetime(2026, 1, 5, 12, tzinfo=plus2), D("1000.000"))
    assert ledger.apply(same) is first and ledger.duplicate_log == ("d0", "d0")
    err = refused(ledger, Deposit("d0", at(0), D(999)), "ledger_event_conflict")
    assert isinstance(err, LedgerEventConflict) and err.f7_code == "F7.ledger_event_conflict"


def test_double_booking_of_a_leg_is_impossible_under_replayed_or_renamed_events():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(100)))
    ledger.apply(entry("e1", 2, "p1", "1", "100"))
    leg = exit_("x1", 3, "p1", "t1", "0.25", "110", "0.0275")
    ledger.apply(leg)
    fees_once = ledger.state.fees
    assert ledger.apply(leg).event_id == "x1" and ledger.state.fees == fees_once
    refused(ledger, dataclasses.replace(leg, event_id="x1-retry"), "duplicate_leg")
    assert len(ledger.state.positions["p1"].exits) == 1


def _populated_ledger():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(300)))
    ledger.apply(entry("e1", 2, "p1", "2", "100", "0.2"))
    ledger.apply(exit_("x1", 3, "p1", "t1", "1", "105", "0.105"))
    ledger.apply(Mark("m1", at(4), "BTCUSDT", D(104), "stream"))
    return ledger


@pytest.mark.parametrize("label, corrupt", [
    ("PR-I1", lambda s: dataclasses.replace(s, cash=s.cash + 1)),
    ("PR-I2", lambda s: dataclasses.replace(s, cash=D(-1), net_contributions=D(-1) + s.committed_cost
                                            - s.realized_gross + s.fees + s.costs)),
    ("PR-I2", lambda s: dataclasses.replace(s, reserved=s.cash + 1)),
    ("PR-I3", lambda s: dataclasses.replace(s, reserved=s.reserved + 1)),
    ("PR-I3", lambda s: dataclasses.replace(s, reservations={
        k: dataclasses.replace(r, consumed=r.consumed + 1) for k, r in s.reservations.items()})),
    ("PR-I4", lambda s: dataclasses.replace(s, positions={
        k: dataclasses.replace(p, qty_open=p.qty_open + 1) for k, p in s.positions.items()})),
    ("PR-I5", lambda s: dataclasses.replace(s, committed_cost=s.committed_cost + 1, cash=s.cash - 1)),
    ("PR-I6", lambda s: dataclasses.replace(s, fees=s.fees + 1, net_contributions=s.net_contributions + 1)),
])
def test_invariant_checker_raises_on_each_corruption(label, corrupt):
    state = _populated_ledger().state
    pl.check_invariants(state)
    with pytest.raises(LedgerInvariantViolation, match=label):
        pl.check_invariants(corrupt(state))


def test_replay_is_deterministic_and_the_hash_chain_detects_tampering():
    ledger = _populated_ledger()
    entries = ledger.entries
    pl.verify_chain(entries)
    rebuilt = pl.replay_entries(entries, money_quantum=Q, quote_asset=USDT)
    assert rebuilt.state_hash == ledger.state_hash
    assert pl.state_digest(rebuilt.state) == pl.state_digest(ledger.state)
    events = [e.event for e in entries]
    assert pl.replay(events, ledger_id="L1", quote_asset=USDT, cost_model_id="research_baseline_v1",
                     money_quantum=Q).state_hash == ledger.state_hash
    other_model = pl.replay(events, ledger_id="L1", quote_asset=USDT,
                            cost_model_id="legacy_tracker_v1", money_quantum=Q)
    assert other_model.state_hash != ledger.state_hash
    with pytest.raises(LedgerInvariantViolation, match="PR-I8"):
        pl.verify_chain(entries[:1] + entries[2:])
    broken = list(entries)
    broken[2] = dataclasses.replace(broken[2], prev_state_hash="f" * 64)
    with pytest.raises(LedgerInvariantViolation, match="PR-I8"):
        pl.verify_chain(broken)
    edited = list(entries)
    edited[2] = dataclasses.replace(edited[2], event=dataclasses.replace(edited[2].event, qty=D(3)))
    with pytest.raises(LedgerInvariantViolation, match="PR-I8"):
        pl.replay_entries(edited, money_quantum=Q, quote_asset=USDT)


def test_crash_and_restart_at_every_prefix_is_exactly_once():
    full = _populated_ledger()
    full.apply(exit_("x2", 5, "p1", "t2", "1", "101", "0.101"))
    full.apply(ReleaseReservation("rel1", at(6), "p1"))
    events = [e.event for e in full.entries]
    for cut in range(len(events) + 1):
        restarted = pl.replay_entries(full.entries[:cut], money_quantum=Q, quote_asset=USDT) \
            if cut else new_ledger()
        restarted.apply_all(events)
        assert restarted.state_hash == full.state_hash
        assert len(restarted.entries) == len(events) and len(restarted.duplicate_log) == cut
        assert restarted.state.fees == full.state.fees
        assert restarted.state.reserved == 0


def test_utc_normalization_and_mark_staleness():
    ledger = new_ledger()
    plus5 = timezone(timedelta(hours=5))
    first = ledger.apply(Deposit("d0", datetime(2026, 1, 5, 15, tzinfo=plus5), D(1000)))
    assert first.as_of == T0 and first.as_of.tzinfo is UTC
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(100)))
    ledger.apply(entry("e1", 2, "p1", "1", "100"))
    ledger.apply(Mark("m1", at(3), "BTCUSDT", D(110), "stream"))
    fresh = ledger.valuation(now=at(8), mark_max_age=timedelta(minutes=10))
    assert fresh.status == "FRESH" and fresh.reason is None and fresh.snapshot.equity_mtm == D(1010)
    stale = ledger.valuation(now=at(8), mark_max_age=timedelta(minutes=1))
    assert stale.status == "UNKNOWN" and stale.reason == "F7.mark_stale"
    assert stale.stale_symbols == ("BTCUSDT",) and stale.snapshot.equity_mtm is None
    assert stale.snapshot.unrealized is None and stale.snapshot.cash == fresh.snapshot.cash
    with pytest.raises(LedgerError, match="time_regression"):
        ledger.valuation(now=at(1), mark_max_age=timedelta(minutes=10))
    with pytest.raises(LedgerError, match="naive_time"):
        ledger.valuation(now=datetime(2026, 1, 5, 11), mark_max_age=timedelta(minutes=10))
    with pytest.raises(LedgerError):
        ledger.valuation(now=at(8), mark_max_age=600)


# ── compounding from realized net only ─────────────────────────────────────────────────────

def _winner_plus_open_position():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    round_trip(ledger, "p1", 1)                             # net +9.79, closed at at(4)
    ledger.apply(Reserve("r2", at(5), "p2", "ETHUSDT", "s_b", D(60)))
    ledger.apply(entry("e2", 6, "p2", "0.5", "100", "0.05"))
    ledger.apply(Mark("m2", at(7), "ETHUSDT", D(200), "stream"))
    return ledger


def test_compounding_uses_realized_net_and_never_unrealized():
    ledger = _winner_plus_open_position()
    snap = ledger.snapshot()
    assert snap.unrealized == D(50)
    rule = SettlementRule("at_close", None)
    base = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(8), settlement=rule,
                               reconciled_position_ids={"p1"})
    assert base.base == D(1000) + D("9.79") - D("0.05") == snap.equity_cost
    assert base.settled_position_ids == ("p1",) and base.pending_position_ids == ("p2",)
    assert base.immediate_losses == D("-0.05") and base.excluded_gains == 0
    unreconciled = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(8),
                                       settlement=rule, reconciled_position_ids=())
    assert unreconciled.base == D("999.95") and unreconciled.excluded_gains == D("9.79")
    for minute, price in ((9, "1"), (10, "100000")):
        snap = ledger.apply(Mark(f"m{minute}", at(minute), "ETHUSDT", D(price), "rest")).snapshot
        again = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(minute),
                                    settlement=rule, reconciled_position_ids={"p1"})
        assert again.base == base.base


def test_partial_leg_gains_wait_for_the_close_but_partial_losses_count_at_once():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    ledger.apply(Reserve("r1", at(1), "p1", "BTCUSDT", "s_a", D(200)))
    ledger.apply(entry("e1", 2, "p1", "2", "100"))
    rule = SettlementRule("at_close", None)
    snap = ledger.apply(exit_("x1", 3, "p1", "t1", "1", "120")).snapshot
    gain = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(3), settlement=rule,
                               reconciled_position_ids={"p1"})
    assert gain.base == D(1000) and gain.excluded_gains == D(20)
    snap = ledger.apply(exit_("x2", 4, "p1", "t2", "0.5", "40")).snapshot
    mixed = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(4), settlement=rule,
                                reconciled_position_ids={"p1"})
    assert view(snap, "p1").realized_net == D(-10) and mixed.base == D(990)


def _three_closes():
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(1000)))
    round_trip(ledger, "p1", 1)                                         # +9.79 at at(4)
    round_trip(ledger, "p2", 10, sell="60", fee_out="0.12")             # +19.78 at at(13)
    round_trip(ledger, "p3", 20, sell="45", fee_out="0.09")             # -10.19 at at(23)
    return ledger


def test_settlement_rules_delay_gains_and_never_delay_losses():
    snap = _three_closes().snapshot()
    nets = {v.position_id: v.realized_net for v in snap.positions}
    assert nets == {"p1": D("9.79"), "p2": D("19.78"), "p3": D("-10.19")}
    every = {"p1", "p2", "p3"}

    def base(kind, n, when):
        return pl.compounding_base(snap, starting_capital=D(1000), as_of=when,
                                   settlement=SettlementRule(kind, n),
                                   reconciled_position_ids=every).base

    assert base("at_close", None, at(30)) == D(1000) + D("19.38")
    before_midnight = datetime(2026, 1, 5, 23, 59, tzinfo=UTC)
    midnight = datetime(2026, 1, 6, tzinfo=UTC)
    assert base("next_utc_day", None, before_midnight) == D(1000) - D("10.19")
    assert base("next_utc_day", None, midnight) == D(1000) + D("19.38")
    sunday_late = datetime(2026, 1, 11, 23, 59, tzinfo=UTC)
    next_monday = datetime(2026, 1, 12, tzinfo=UTC)
    assert base("next_utc_week", None, sunday_late) == D(1000) - D("10.19")
    assert base("next_utc_week", None, next_monday) == D(1000) + D("19.38")
    assert base("after_n_closes", 2, at(30)) == D(1000) + D("9.79") - D("10.19")
    assert base("after_n_closes", 1, at(30)) == D(1000) + D("19.38")
    assert base("after_n_closes", 3, at(30)) == D(1000) - D("10.19")


def test_settlement_point_is_utc_whatever_the_input_offset():
    rule = SettlementRule("next_utc_day", None)
    plus2 = timezone(timedelta(hours=2))
    late_utc_as_local = datetime(2026, 1, 6, 1, 30, tzinfo=plus2)      # 2026-01-05 23:30 UTC
    assert pl.settlement_point(rule, late_utc_as_local) == datetime(2026, 1, 6, tzinfo=UTC)
    week = SettlementRule("next_utc_week", None)
    assert pl.settlement_point(week, datetime(2026, 1, 11, 23, tzinfo=UTC)) == datetime(2026, 1, 12, tzinfo=UTC)
    assert pl.settlement_point(week, datetime(2026, 1, 12, tzinfo=UTC)) == datetime(2026, 1, 19, tzinfo=UTC)
    with pytest.raises(LedgerError, match="naive_time"):
        pl.settlement_point(rule, datetime(2026, 1, 5, 23))


def test_deposits_never_feed_the_base_and_inputs_are_required():
    ledger = _winner_plus_open_position()
    ledger.apply(Deposit("d1", at(9), D(500)))
    snap = ledger.snapshot()
    rule = SettlementRule("at_close", None)
    base = pl.compounding_base(snap, starting_capital=D(1000), as_of=at(9), settlement=rule,
                               reconciled_position_ids={"p1"})
    assert base.base == D("1009.74") and base.base <= snap.equity_cost
    with pytest.raises(LedgerError, match="starting_capital"):
        pl.compounding_base(snap, starting_capital=D(1501), as_of=at(9), settlement=rule,
                            reconciled_position_ids=())
    with pytest.raises(LedgerError, match="time_regression"):
        pl.compounding_base(snap, starting_capital=D(1000), as_of=at(8), settlement=rule,
                            reconciled_position_ids=())
    with pytest.raises(TypeError):
        pl.compounding_base(snap, starting_capital=D(1000), as_of=at(9), settlement=rule)
    with pytest.raises(TypeError):
        SettlementRule("at_close")
    for bad in (SettlementRule("at_close", 2), SettlementRule("after_n_closes", None),
                SettlementRule("after_n_closes", 0), SettlementRule("monthly", None),
                SettlementRule("after_n_closes", True)):
        with pytest.raises(LedgerError):
            pl.compounding_base(snap, starting_capital=D(1000), as_of=at(9), settlement=bad,
                                reconciled_position_ids=())


# ── de-risking ladders (externally supplied) ───────────────────────────────────────────────

FIXTURE_LADDERS = (
    DeRiskingLadder("drawdown", (LadderStep(D("0.2"), D("0.6")), LadderStep(D("0.4"), D("0.3")))),
    DeRiskingLadder("loss_streak", (LadderStep(4, D("0.7")), LadderStep(6, D("0.2")))),
)


def test_ladder_takes_the_deepest_fired_step_and_the_minimum_across_ladders():
    out = pl.apply_derisking(D(1000), ladders=FIXTURE_LADDERS,
                             metrics={"drawdown": D("0.25"), "loss_streak": 2})
    assert out.multiplier == D("0.6") and out.adjusted_base == D(600)
    assert out.reasons == (("drawdown", D("0.25"), D("0.2"), D("0.6")),)
    out = pl.apply_derisking(D(1000), ladders=FIXTURE_LADDERS,
                             metrics={"drawdown": D("0.5"), "loss_streak": 6})
    assert out.multiplier == D("0.2") and out.adjusted_base == D(200) and len(out.reasons) == 2
    calm = pl.apply_derisking(D(1000), ladders=FIXTURE_LADDERS,
                              metrics={"drawdown": D(0), "loss_streak": 0})
    assert calm.multiplier == 1 and calm.adjusted_base == D(1000) and calm.reasons == ()
    none = pl.apply_derisking(D(1000), ladders=(), metrics={})
    assert none.multiplier == 1 and none.adjusted_base == D(1000)


def test_ladder_inputs_are_required_and_validated():
    with pytest.raises(TypeError):
        LadderStep(D("0.1"))
    with pytest.raises(TypeError):
        DeRiskingLadder("drawdown")
    with pytest.raises(TypeError):
        pl.apply_derisking(D(1000), ladders=FIXTURE_LADDERS)
    good = {"drawdown": D("0.1"), "loss_streak": 1}
    bad_metrics = ({"drawdown": D("0.1")}, {**good, "drawdown": D(-1)},
                   {**good, "drawdown": D("NaN")}, {**good, "drawdown": 0.1})
    for metrics in bad_metrics:
        with pytest.raises(LedgerError):
            pl.apply_derisking(D(1000), ladders=FIXTURE_LADDERS, metrics=metrics)
    bad_ladders = (
        None,
        (DeRiskingLadder("dd", ()),),
        (DeRiskingLadder("dd", (LadderStep(D("0.2"), D("0.5")), LadderStep(D("0.2"), D("0.4")))),),
        (DeRiskingLadder("dd", (LadderStep(D("0.2"), D("0.4")), LadderStep(D("0.3"), D("0.5")))),),
        (DeRiskingLadder("dd", (LadderStep(D("0.2"), D("1.5")),)),),
        (DeRiskingLadder("dd", (LadderStep(D("-0.1"), D("0.5")),)),),
        (DeRiskingLadder("dd", (LadderStep(D("0.1"), D("0.5")),)),) * 2,
    )
    for ladders in bad_ladders:
        with pytest.raises(LedgerError):
            pl.apply_derisking(D(1000), ladders=ladders, metrics={"dd": D("0.5")})


def test_ladder_multiplier_is_monotone_in_each_trigger_seeded():
    rng = random.Random(20261101)
    for _ in range(50):
        thresholds = sorted(rng.sample(range(1, 100), rng.randint(1, 4)))
        multipliers = sorted((D(rng.randint(0, 100)) / 100 for _ in thresholds), reverse=True)
        ladder = DeRiskingLadder("m", tuple(LadderStep(D(t), m) for t, m in zip(thresholds, multipliers)))
        previous = D(1)
        for value in range(0, 110, 3):
            out = pl.apply_derisking(D(777), ladders=(ladder,), metrics={"m": value})
            assert out.multiplier <= previous and out.adjusted_base <= D(777)
            previous = out.multiplier


def test_loss_streak_matches_the_existing_net_semantics_and_feeds_a_ladder():
    from shared.risk_epoch import tail_loss_streak
    rng = random.Random(7)
    for trial in range(10):
        nets = [rng.randint(-3, 3) for _ in range(rng.randint(1, 8))]
        ledger = new_ledger()
        ledger.apply(Deposit("d0", at(0), D(10000)))
        for i, net in enumerate(nets):
            round_trip(ledger, f"p{i}", 10 * i + 1, qty="1", buy="100", sell=str(100 + net),
                       fee_in="0", fee_out="0", reserve="100")
        snap = ledger.snapshot()
        assert pl.loss_streak(snap) == tail_loss_streak(nets)
    out = pl.apply_derisking(D(500), ladders=FIXTURE_LADDERS[1:],
                             metrics={"loss_streak": pl.loss_streak(snap)})
    assert out.adjusted_base <= D(500)


# ── property-style randomized (seeded) event sequences ─────────────────────────────────────

def _check_snapshot(snap, ledger):
    state = ledger.state
    assert snap.cash + snap.committed_cost == (snap.net_contributions + snap.realized_gross
                                               - snap.fees - snap.costs)
    assert snap.cash >= 0 and snap.reserved >= 0 and snap.available == snap.cash - snap.reserved >= 0
    assert snap.reserved == sum((r.remaining for r in state.reservations.values() if r.active), D(0))
    assert snap.committed_cost == sum((v.cost_basis for v in snap.positions), D(0))
    assert snap.realized_gross == sum((v.realized_gross for v in snap.positions), D(0))
    assert snap.fees == sum((v.fees for v in snap.positions), D(0))
    for pos in state.positions.values():
        assert pos.qty_entered - pos.qty_exited == pos.qty_open >= 0
    if snap.equity_mtm is not None:
        assert snap.equity_mtm == snap.equity_cost + snap.unrealized
        assert snap.equity_mtm == snap.cash + sum((v.market_value for v in snap.positions), D(0))


@pytest.mark.parametrize("seed", range(25))
def test_seeded_random_sequences_keep_every_invariant(seed):
    rng = random.Random(seed)
    ledger = new_ledger()
    ledger.apply(Deposit("d0", at(0), D(rng.randint(500, 5000))))
    symbols, strategies = ("AAAUSDT", "BBBUSDT", "CCCUSDT"), ("s1", "s2")
    applied, minute, counter, refusals = [ledger.entries[0].event], 0, 0, 0
    rule = SettlementRule(rng.choice(pl.SETTLEMENT_KINDS[:3]), None)
    for _ in range(90):
        minute += rng.randint(0, 3)
        counter += 1
        eid = f"ev{counter}"
        state = ledger.state
        active = [r for r in state.reservations.values() if r.active]
        open_pos = [p for p in state.positions.values() if p.qty_open > 0]
        price = D(rng.randint(1000, 20000)) / 100
        kind = rng.random()
        if kind < 0.2:
            amount = D(rng.randint(1, 400)) * (3 if rng.random() < 0.15 else 1)
            event = Reserve(eid, at(minute), f"i{counter}", rng.choice(symbols),
                            rng.choice(strategies), amount)
        elif kind < 0.42 and active:
            res = rng.choice(active)
            qty = D(rng.randint(1, 300)) / 100
            event = entry(eid, minute, res.intent_id, qty, price, qty * price * D("0.001"),
                          cost=D(rng.randint(0, 5)) / 100)
        elif kind < 0.5 and active:
            event = ReleaseReservation(eid, at(minute), rng.choice(active).intent_id)
        elif kind < 0.72 and open_pos:
            pos = rng.choice(open_pos)
            pick = rng.random()
            qty = pos.qty_open if pick < 0.4 else (pos.qty_open / 2 if pick < 0.9 else pos.qty_open + 1)
            event = exit_(eid, minute, pos.position_id, f"leg{counter}", qty, price,
                          qty * price * D("0.001"))
        elif kind < 0.85:
            event = Mark(eid, at(minute), rng.choice(symbols), price, "stream")
        elif kind < 0.92 and applied:
            event = rng.choice(applied)                       # an exact duplicate: a no-op
        elif kind < 0.96 and applied:
            prior = rng.choice(applied)
            event = dataclasses.replace(prior, as_of=prior.as_of + timedelta(seconds=1))
        else:
            event = Deposit(eid, datetime(2026, 1, 5, 9), D(1))      # naive: refused
        before = (ledger.state, ledger.state_hash, len(ledger.entries))
        try:
            entry_ = ledger.apply(event)
        except LedgerError:
            refusals += 1
            assert (ledger.state, ledger.state_hash, len(ledger.entries)) == before
            continue
        if entry_.sequence == before[2] + 1:
            applied.append(entry_.event)
            if isinstance(event, Mark):
                assert all(value == 0 for value in entry_.deltas.values())
        else:
            assert ledger.state_hash == before[1]               # duplicate left state as it was
        snap = ledger.snapshot()
        _check_snapshot(snap, ledger)
        sized = pl.compounding_base(
            snap, starting_capital=snap.net_contributions, as_of=snap.as_of, settlement=rule,
            reconciled_position_ids={v.position_id for v in snap.positions if rng.random() < 0.7})
        assert 0 <= sized.base <= snap.equity_cost
    assert refusals > 0
    pl.verify_chain(ledger.entries)
    rebuilt = pl.replay_entries(ledger.entries, money_quantum=Q, quote_asset=USDT)
    assert rebuilt.state_hash == ledger.state_hash
    shuffled_dupes = list(applied) + rng.sample(applied, min(10, len(applied)))
    again = new_ledger()
    again.apply_all([e for e in shuffled_dupes[:len(applied)]])
    again.apply_all(shuffled_dupes[len(applied):])
    assert again.state_hash == ledger.state_hash


def test_module_imports_only_the_standard_library():
    tree = ast.parse(Path(pl.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {"__future__", "dataclasses", "hashlib", "json", "datetime", "decimal", "typing"}
