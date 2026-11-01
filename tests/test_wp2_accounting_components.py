"""Unit tests of the WP2 integration helpers: flags, cost label policies, the legacy ledger adapter
(WP-E02, PR-I13), the position-state shadow and the routed capacity decision. Synthetic only."""
from __future__ import annotations

import dataclasses
import itertools
import math
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from shared import accounting_flags as af
from shared import cost_label_policy as clp
from shared import fees
from shared import ledger_legacy_adapter as la
from shared import position_state as ps
from shared import position_state_shadow as pss
from shared.admission_capacity import routed_risk_decision
from shared.cost_models import LegacyTrackerV1
from shared.economic_halt_policy import evaluate_with_policy, legacy_fields
from shared.partial_exits import aggregate_close, fills_between
from shared.risk_management import RiskLimits, RiskSnapshot
from shared.triple_barrier import TripleBarrierConfig

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
BOUND = LegacyTrackerV1(fee_roundtrip_pct=0.3, stop_slippage=0.001, configured_notional_usdt=50.0)


# ── flags ────────────────────────────────────────────────────────────────────────────────

def test_flag_defaults_are_the_legacy_configuration():
    flags = af.resolve_accounting_flags({})
    assert flags == af.LEGACY_FLAGS and flags.is_legacy
    assert flags.cost_label_policy == fees.LABEL_POLICY


@pytest.mark.parametrize("name,good,bad", [
    ("PAPER_COST_LABEL_POLICY", "net_single_count_legacy_v1", "research_baseline_v1"),
    ("PAPER_BREAK_EVEN_POLICY", "single_count_legacy_v1", "research_stress_v1"),
    ("LEDGER_SHADOW", "on", "yes"), ("POSITION_STATE_SHADOW", "off", "enforce")])
def test_each_flag_parses_strictly(name, good, bad):
    af.resolve_accounting_flags({name: f"  {good.upper()} "})
    for value in (bad, "", " "):
        with pytest.raises(RuntimeError):
            af.resolve_accounting_flags({name: value})


def test_no_flag_value_selects_a_research_cost_model():
    for value in af.LABEL_POLICIES + af.BREAK_EVEN_POLICIES:
        assert "research" not in value
    with pytest.raises(RuntimeError):
        af.AccountingFlags(cost_label_policy="research_baseline_v1")
    with pytest.raises(RuntimeError):
        af.AccountingFlags(ledger_shadow="on")


# ── cost label policies ──────────────────────────────────────────────────────────────────

GROSSES = [-3.1, -0.15, -0.14995, 0.0, 0.1, 0.149949, 0.15, 0.15005, 2.75, 1e-9, -1e-9]


@pytest.mark.parametrize("fee,notional", [(0.3, 50.0), (0.3, 50), (0.4, 120.0), (0.0, 10.0)])
def test_legacy_booking_is_fees_economic_close(fee, notional, monkeypatch):
    from shared.config import config
    monkeypatch.setattr(config, "FEE_ROUNDTRIP_PCT", fee)
    monkeypatch.setattr(config, "TRADE_AMOUNT_USDT", notional)
    monkeypatch.setattr(config, "STOP_SLIPPAGE", 0.001)
    bound = clp.bound_costs(config)
    book = clp.close_booking(bound, af.LEGACY_LABEL_POLICY, entry_price=1.0, target_fills=(),
                             final_exit_price=1.0, remaining_fraction=1.0)
    for g in GROSSES:
        assert book(g) == fees.economic_close(g)                       # same dict, same floats
    assert bound.fee_usdt() == notional * fee / 100.0
    assert clp.barrier_cost_kwargs(bound, af.LEGACY_BREAK_EVEN) == {
        "stop_slippage": 0.001, "roundtrip_cost": fee / 100.0}


def test_single_count_full_stop_exit():
    entry, stop = 100.0, 97.0
    fill = stop * (1 - 0.001)
    gross = (fill / entry - 1) * 50
    out = clp.single_count_close(BOUND, gross, entry_price=entry, target_fills=(),
                                 final_exit_price=fill, remaining_fraction=1.0)
    cost = 0.001 * (50 + 50 * fill / entry)        # fee per side; slippage only in the fill
    assert out == {"cost_usdt": round(cost, 6), "net_profit_usdt": round(round(gross, 4) - cost, 6),
                   "economic_result": "LOSS", "label_policy": af.SINGLE_COUNT_LABEL_POLICY}
    legacy = BOUND.economic_close(gross)
    assert legacy["cost_usdt"] - out["cost_usdt"] == pytest.approx(0.05 - 0.05 * (fill / entry - 1),
                                                                    abs=1e-6)


def test_single_count_partial_path_books_each_leg_once():
    fills = fills_between(previous_target=0, reached_target=3, entry=100.0,
                          targets={1: 102.0, 2: 104.0, 3: 106.0}, trade_amount=50.0, min_notional=5.0)
    legs = [(f.fraction, f.price) for f in fills]
    gross = sum(f.gross_usdt for f in fills)
    out = clp.single_count_close(BOUND, gross, entry_price=100.0, target_fills=legs,
                                 final_exit_price=106.0, remaining_fraction=0.0)
    notional = 50 + sum(50 * f * p / 100 for f, p in legs)
    assert out["cost_usdt"] == round(0.001 * notional, 6)
    assert len(clp.leg_notionals(notional=50, entry_price=100, target_fills=legs, final_exit_price=1,
                                 remaining_fraction=0.0)) == 4


def test_single_count_refuses_an_unattributed_cost_basis():
    other = LegacyTrackerV1(fee_roundtrip_pct=0.4, stop_slippage=0.001, configured_notional_usdt=50.0)
    with pytest.raises(clp.SingleCountBasisError):
        clp.single_count_close(other, 1.0, entry_price=1, target_fills=(), final_exit_price=1,
                               remaining_fraction=1)
    with pytest.raises(clp.SingleCountBasisError):
        clp.barrier_cost_kwargs(other, af.SINGLE_COUNT_BREAK_EVEN)
    clp.validate_policies(other, cost_label_policy=af.LEGACY_LABEL_POLICY,
                          break_even_policy=af.LEGACY_BREAK_EVEN)
    with pytest.raises(ValueError):
        clp.single_count_close(BOUND, float("nan"), entry_price=1, target_fills=(),
                               final_exit_price=1, remaining_fraction=1)


def test_break_even_levels():
    legacy = TripleBarrierConfig("X", 100.0, 110.0, 120.0, 130.0, 90.0,
                                 **clp.barrier_cost_kwargs(BOUND, af.LEGACY_BREAK_EVEN))
    single = TripleBarrierConfig("X", 100.0, 110.0, 120.0, 130.0, 90.0,
                                 **clp.barrier_cost_kwargs(BOUND, af.SINGLE_COUNT_BREAK_EVEN))
    assert legacy.net_break_even_stop() == 100.0 * 1.003 / 0.999
    s = single.net_break_even_stop()
    assert s == pytest.approx(100.0 * 1.001 / (0.999 * 0.999), rel=1e-15)
    # an exit at that stop nets zero after its fill slippage and one fee per side
    assert s * 0.999 * (1 - 0.001) == pytest.approx(100.0 * 1.001, rel=1e-12)
    assert legacy.net_break_even_stop() - s == pytest.approx(0.1, abs=0.01)
    capped = TripleBarrierConfig("X", 100.0, 100.2, 120.0, 130.0, 90.0,
                                 **clp.barrier_cost_kwargs(BOUND, af.SINGLE_COUNT_BREAK_EVEN))
    assert capped.net_break_even_stop() == 100.2                     # still capped at T1


# ── ledger adapter (WP-E02) ──────────────────────────────────────────────────────────────

def tracker_close(rng: random.Random, policy=af.LEGACY_LABEL_POLICY, *, notional=50.0):
    entry = round(rng.uniform(0.01, 500), rng.choice([2, 4, 8]))
    reached = rng.choice([0, 0, 1, 2, 3])
    min_notional = rng.choice([5.0, 5.0, 20.0])
    targets = {t: entry * (1 + 0.02 * t) for t in (1, 2, 3)}
    fills = fills_between(previous_target=0, reached_target=reached, entry=entry, targets=targets,
                          trade_amount=notional, min_notional=min_notional)
    realized_pct = sum(f.gross_pct_contribution for f in fills)
    realized_usdt = sum(f.gross_usdt for f in fills)
    remaining = max(0.0, 1.0 - sum(f.fraction for f in fills))
    final = targets[3] if reached == 3 else entry * rng.choice([0.97 * 0.999, 1.004, 0.995, 1.01])
    _pct, gross = aggregate_close(entry=entry, final_exit=final, trade_amount=notional,
                                  realized_pct=realized_pct, realized_usdt=realized_usdt,
                                  remaining_fraction=remaining)
    legs = tuple((f.fraction, f.price) for f in fills)
    bound = LegacyTrackerV1(0.3, 0.001, notional)
    econ = clp.close_booking(bound, policy, entry_price=entry, target_fills=legs,
                             final_exit_price=final, remaining_fraction=remaining)(gross)
    return la.TrackerClose(trade_id=rng.randint(1, 10**6), symbol="AAAUSDT", strategy_id="momentum",
                           opened_at=T0, closed_at=T0 + timedelta(hours=5), entry_price=entry,
                           notional=notional, target_fills=legs, final_exit_price=final,
                           remaining_fraction=remaining, booked_profit_usdt=round(gross, 4),
                           booked_cost_usdt=econ["cost_usdt"], booked_net_profit_usdt=econ["net_profit_usdt"],
                           label_policy=econ["label_policy"]), bound


@pytest.mark.parametrize("policy", af.LABEL_POLICIES)
def test_reconciliation_is_exact_within_quantization(policy):
    rng = random.Random(11)
    for _ in range(600):
        close, bound = tracker_close(rng, policy)
        rec = la.reconcile(close, bound)
        assert rec.ok, rec.as_dict()
        assert abs(rec.difference) <= la.NET_TOLERANCE
        assert rec.notes == ("notional_at_open_not_persisted",)


def test_a_booking_mismatch_is_named_never_adjusted():
    close, bound = tracker_close(random.Random(3))
    bad = dataclasses.replace(close, booked_net_profit_usdt=close.booked_net_profit_usdt + 0.01)
    rec = la.reconcile(bad, bound)
    assert not rec.ok and rec.reason_code == "F7.ledger_mismatch" and "net_mismatch" in rec.discrepancies
    assert rec.ledger_realized_net == la.reconcile(close, bound).ledger_realized_net
    flat = dataclasses.replace(close, label_policy=af.SINGLE_COUNT_LABEL_POLICY)
    assert "cost_mismatch" in la.reconcile(flat, bound).discrepancies


def test_named_discrepancies_pr17_and_fraction():
    close, bound = tracker_close(random.Random(5))
    assert "PR-17" in la.reconcile(dataclasses.replace(close, notional_at_open=40.0), bound).discrepancies
    assert la.reconcile(dataclasses.replace(close, notional_at_open=50.0), bound).ok
    lost = dataclasses.replace(close, remaining_fraction=close.remaining_fraction + 0.25)
    assert "fraction_not_conserved" in la.reconcile(lost, bound).discrepancies
    refused = la.reconcile(dataclasses.replace(close, label_policy="research_baseline_v1"), bound)
    assert not refused.ok and refused.discrepancies[-1].startswith("ledger_refused:")


def test_reconciliation_is_deterministic():
    close, bound = tracker_close(random.Random(9))
    assert la.reconcile(close, bound).state_hash == la.reconcile(close, bound).state_hash


@pytest.mark.parametrize("mark", [101.0, 103.0, 99.0, 105.5])
def test_pr07_divergence_and_unrealized_gains_are_never_spendable(mark):
    fills = [(0.25, 102.0), (0.5, 104.0)]
    out = la.pr07_divergence(trade_id=1, symbol="AAAUSDT", opened_at=T0, as_of=T0 + timedelta(hours=1),
                             entry_price=100.0, notional=50.0, target_fills=fills, mark_price=mark)
    expected = sum(D(repr(f)) * 50 * (D(repr(mark)) - D(repr(p))) / 100 for f, p in fills)
    assert abs(out["divergence"] - expected) < D("1e-9")
    assert out["spendable_after_mark"] == out["spendable_before_mark"]       # PR-I9 / PR-I10
    assert out["equity_mtm"] is not None


# ── position-state shadow ────────────────────────────────────────────────────────────────

def trade(**kw):
    row = {"id": 7, "symbol": "AAAUSDT", "entry_price": 100.0, "target_1": 102.0, "target_2": 104.0,
           "target_3": 106.0, "stop_loss": 97.0, "stop_invalidation": 97.5, "highest_target_hit": 0,
           "remaining_fraction": 1.0, "exit_policy_version": "partial_25_50_25_v1",
           "peak_price": None}
    row.update(kw)
    return row


def cfg():
    return TripleBarrierConfig("AAAUSDT", 100.0, 102.0, 104.0, 106.0, 97.0, stop_slippage=0.001,
                               roundtrip_cost=0.003)


def hit(row, prev, new, min_notional=5.0, peak=106.0):
    fills = fills_between(previous_target=prev, reached_target=new, entry=100.0,
                          targets={1: 102.0, 2: 104.0, 3: 106.0}, trade_amount=50.0,
                          min_notional=min_notional)
    return pss.validate_target_hits(row, cfg=cfg(), peak_before=100.0, peak=peak, prev_highest=prev,
                                    new_highest=new, fills=fills, notional=50.0,
                                    min_notional=min_notional)


def test_the_normal_lifecycle_is_accepted():
    assert hit(trade(), 0, 1).ok
    assert hit(trade(highest_target_hit=1, remaining_fraction=0.75), 1, 2).ok
    r = hit(trade(highest_target_hit=2, remaining_fraction=0.25), 2, 3)
    assert r.ok and r.final_state == ps.CLOSED
    assert hit(trade(), 0, 3).final_state == ps.CLOSED                       # gap through all three
    for reason, highest, rem in (("stop_loss", 0, 1.0), ("break_even", 1, 0.75),
                                 ("trailing_stop", 2, 0.25), ("no_T1_expired_24h", 0, 1.0),
                                 ("T1_expired_24h", 1, 0.75), ("signal_candle_invalidation", 0, 1.0),
                                 ("manual blacklist close", 1, 0.75), ("T3", 3, 0.0)):
        r = pss.validate_close(trade(highest_target_hit=highest, remaining_fraction=rem), reason=reason,
                               exit_price=99.0, notional=50.0, min_notional=5.0)
        assert r.ok, (reason, r.as_dict())


def test_the_merge_difference_is_recorded():
    # min notional 20: T1 and T3 merge into T2, which empties the position in the machine
    r = hit(trade(highest_target_hit=1, remaining_fraction=1.0), 1, 2, min_notional=20.0)
    assert r.ok and r.final_state == ps.CLOSED
    late = pss.validate_close(trade(highest_target_hit=2, remaining_fraction=0.0), reason="trailing_stop",
                              exit_price=104.0, notional=50.0, min_notional=20.0)
    assert not late.ok and late.refusals[0].reason == "close_with_no_open_quantity"


def test_inconsistent_rows_are_refused_not_raised():
    r = pss.validate_close(trade(highest_target_hit=0, remaining_fraction=0.5), reason="stop_loss",
                           exit_price=96.0, notional=50.0, min_notional=5.0)
    assert not r.ok and r.refusals[0].reason == "invalid_record"
    r = pss.validate_close(trade(highest_target_hit=1, remaining_fraction=0.75),
                           reason="signal_candle_invalidation", exit_price=96.0, notional=50.0,
                           min_notional=5.0)
    assert not r.ok and r.refusals[0].reason == "illegal_transition"
    bad = pss.validate_target_hits(trade(target_1=99.0), cfg=cfg(), peak_before=100.0, peak=103.0,
                                   prev_highest=0, new_highest=1, fills=[], notional=50.0,
                                   min_notional=5.0)
    assert not bad.ok and bad.refusals[0].reason == "invalid_plan"


# ── routed capacity decision ─────────────────────────────────────────────────────────────

def limits(**kw):
    base = dict(capital_usdt=500.0, trade_amount_usdt=50.0, max_open_trades=2,
                max_gross_exposure_pct=80.0, max_symbol_exposure_pct=10.0)
    base.update(kw)
    return RiskLimits(**base)


def snap(**kw):
    base = dict(realized_total_usdt=0.0, daily_pnl_usdt=0.0, weekly_pnl_usdt=0.0,
                unrealized_pnl_usdt=0.0, peak_equity_usdt=500.0, open_count=0, symbol_open_count=0,
                consecutive_losses=0)
    base.update(kw)
    return RiskSnapshot(**base)


GRID = list(itertools.product((0, 1, 2, 3), (0, 1), (0.0, -20.0, float("nan")), (0, 2, 5),
                              (2, 1, 0), ("enforce", "observe"), (False, True)))


def test_routed_decision_is_the_policy_object_on_a_grid():
    for open_count, sym, daily, streak, cap, mode, paused in GRID:
        s = snap(open_count=open_count, symbol_open_count=sym, daily_pnl_usdt=daily,
                 consecutive_losses=streak, manually_paused=paused)
        lim = limits(max_open_trades=cap)
        seen = []

        def policy(*a):
            seen.append(evaluate_with_policy(*a))
            return seen[-1]
        d, authority = routed_risk_decision(s, lim, mode, evaluate=policy)
        assert d is seen[0] and len(seen) == 1
        assert legacy_fields(d) == legacy_fields(evaluate_with_policy(s, lim, mode)) or math.isnan(daily)
        assert authority is not None and authority.risk_decision is d
        assert authority.admitted == bool(d.allowed)


def test_routed_decision_outside_the_domain_and_on_errors():
    lim = dataclasses.replace(limits(), max_open_trades=2.0)
    calls = []

    def policy(*a):
        calls.append(a)
        return evaluate_with_policy(*a)
    d, authority = routed_risk_decision(snap(), lim, "enforce", evaluate=policy)
    assert authority is None and len(calls) == 1
    with pytest.raises(ZeroDivisionError):
        routed_risk_decision(snap(), limits(), "enforce", evaluate=lambda *a: 1 / 0)
    errors = []
    odd = SimpleNamespace(allowed=False, reason="nonsense")
    d, authority = routed_risk_decision(snap(), limits(), "enforce", evaluate=lambda *a: odd,
                                        on_attribution_error=errors.append)
    assert d is odd and authority is None and len(errors) == 1
