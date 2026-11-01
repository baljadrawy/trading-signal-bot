"""WP-D04 cost-model registry (SE-67; SE-44 to SE-46; R4 test 1; WP-IR-07 / WP-IT-07).

Synthetic, deterministic fixtures only; the one random sweep uses a fixed seed. Prices,
quantities and notionals below are arbitrary test values, not proposals for any owner decision.
"""
import dataclasses
import math
import random
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from shared import cost_models as cm
from shared import fees
from shared.cost_models import (BOOK_EXPLICIT_FEE, BOOK_FLAT_PER_TRADE, BOOK_IN_PRICE,
                                COST_MODEL_IDS, LEGACY_TRACKER_V1, REGISTRY, RESEARCH_BASELINE_V1,
                                RESEARCH_STRESS_V1, UNSPECIFIED, CostBook, CostComponent,
                                CostModelError, Leg, LegacyTrackerV1, ResearchPricer)

RESEARCH = (RESEARCH_BASELINE_V1, RESEARCH_STRESS_V1)
ROUND_TRIP = {RESEARCH_BASELINE_V1: D("0.004"), RESEARCH_STRESS_V1: D("0.006")}
UTC = timezone.utc
T0 = datetime(2026, 1, 5, 10, tzinfo=UTC)

# Golden content hashes. A change here means the economic content changed: bump the version.
PINNED = {
    LEGACY_TRACKER_V1: "2631b5af3b6325278dddebcf6bca3ed91af9a05589ff075358fd78b4d83f2421",
    RESEARCH_BASELINE_V1: "1db9fd52eb915159ef9a5d08c012227ddaecc35b0a2659c44e7aeacf114177fd",
    RESEARCH_STRESS_V1: "71b20e7d85767003bb3fa55fe73c202f2e6be0ce435f67551d183bd200de0475",
}


def legacy(fee=0.3, slip=0.001, notional=50.0):
    return LegacyTrackerV1(fee_roundtrip_pct=fee, stop_slippage=slip,
                           configured_notional_usdt=notional)


def pricer(model_id):
    return legacy() if model_id == LEGACY_TRACKER_V1 else ResearchPricer(model_id)


def leg(leg_id, role, qty, ref, taker=True):
    return Leg(leg_id, role, D(qty), D(ref), taker)


def trade(model_id, legs, position_id="p1"):
    book = CostBook(pricer(model_id), position_id=position_id)
    for item in legs:
        book.book(item)
    return book.close()


def reason(fn, code):
    with pytest.raises(CostModelError) as info:
        fn()
    assert info.value.reason == code, info.value
    return info.value


PARTIAL = [leg("e", "entry", "0.5", "100"), leg("t1", "target", "0.125", "102", taker=False),
           leg("t2", "target", "0.25", "103.6", taker=False), leg("s", "stop", "0.125", "100.4")]


# ── WP-IT-07 / WP-IR-07: identifiers, identity, no selection ────────────────────────────────

def test_registry_holds_exactly_the_three_identifiers():
    from shared import portfolio_ledger
    assert COST_MODEL_IDS == ("legacy_tracker_v1", "research_baseline_v1", "research_stress_v1")
    assert tuple(REGISTRY) == COST_MODEL_IDS == portfolio_ledger.COST_MODEL_IDS
    for mid in COST_MODEL_IDS:
        assert cm.get_cost_model(mid).cost_model_id == mid


def test_identifiers_carry_no_values():
    for mid in COST_MODEL_IDS:
        assert cm.IDENTIFIER.match(mid)
        stem = mid.rsplit("_v", 1)[0]
        assert not re.search(r"[0-9]|bps|pct", stem)


def test_no_default_and_no_activation_path():
    for bad in (None, "", "default", "legacy_tracker_30bps", "cost_model_version"):
        reason(lambda bad=bad: cm.get_cost_model(bad), "cost_model_unknown")
    public = [n for n in dir(cm) if not n.startswith("_")]
    assert not [n for n in public if re.search(r"default|activ|select|current", n, re.I)]
    for mid, model in REGISTRY.items():
        assert model.descriptor()["activation_path"] == "none"
    assert (REGISTRY[LEGACY_TRACKER_V1].kind, REGISTRY[LEGACY_TRACKER_V1].status) == (
        cm.KIND_LEGACY, cm.STATUS_LEGACY)
    for mid in RESEARCH:
        assert (REGISTRY[mid].kind, REGISTRY[mid].status) == (cm.KIND_RESEARCH, cm.STATUS_PROPOSED)
        assert "WP3" in REGISTRY[mid].adoption and "no activation path" in REGISTRY[mid].adoption
    with pytest.raises(TypeError):
        REGISTRY["x"] = REGISTRY[LEGACY_TRACKER_V1]          # read-only mapping
    reason(lambda: ResearchPricer(LEGACY_TRACKER_V1), "not_a_research_model")


def test_content_hash_is_pinned_and_uses_the_strategy_identity_canonical_form():
    from shared import strategy_identity as si
    for mid, model in REGISTRY.items():
        payload = {"scheme": cm.COST_MODEL_SCHEME, "descriptor": model.descriptor()}
        assert cm.canonical_json(payload) == si.canonical_json(payload)
        assert model.content_hash == si.canonical_hash(payload) == PINNED[mid]
        assert model.identity() == {"cost_model_id": mid, "version": "1.0.0",
                                    "content_hash": PINNED[mid]}
    ident = cm.registry_identity()
    assert set(ident["models"]) == set(COST_MODEL_IDS) and re.fullmatch(r"[0-9a-f]{64}", ident["digest"])
    reason(lambda: cm.canonical_json({"rate": 0.1}), "not_canonical")


def test_provenance_is_not_hashed_but_content_is():
    base = REGISTRY[RESEARCH_BASELINE_V1]
    assert dataclasses.replace(base, sources=("elsewhere",), adoption="x").content_hash == base.content_hash
    renamed = tuple(dataclasses.replace(c, source="moved", note="") for c in base.components)
    assert dataclasses.replace(base, components=renamed).content_hash == base.content_hash
    assert dataclasses.replace(base, version="1.0.1").content_hash != base.content_hash
    params = tuple(dataclasses.replace(p, value="0.0011") if p.name == "fee_per_side" else p
                   for p in base.parameters)
    assert dataclasses.replace(base, parameters=params).content_hash != base.content_hash


def test_legacy_binding_hash_covers_the_bound_values():
    a, b = legacy(), legacy(fee=0.25)
    assert a.config_hash != b.config_hash and a.config_hash == legacy().config_hash
    assert a.binding()["content_hash"] == PINNED[LEGACY_TRACKER_V1]
    assert a.matches_code_defaults() and not b.matches_code_defaults()
    assert legacy(notional=100.0).matches_code_defaults()     # the notional is an input
    for bad in (dict(fee=float("nan")), dict(fee=-0.1), dict(slip=1.0), dict(slip=-0.001),
                dict(notional=0.0), dict(notional=float("inf")), dict(fee=True), dict(fee="0.3")):
        reason(lambda bad=bad: legacy(**bad), "invalid_binding")
    with pytest.raises(TypeError):
        LegacyTrackerV1()                                      # every value is required


# ── components and sources ─────────────────────────────────────────────────────────────────

def test_research_values_are_the_charter_proposal_and_the_split_is_unspecified():
    for mid, total, in_price in ((RESEARCH_BASELINE_V1, "0.40", "0.001"),
                                 (RESEARCH_STRESS_V1, "0.60", "0.002")):
        m = REGISTRY[mid]
        assert m.round_trip_pct == total and m.label_policy == UNSPECIFIED
        assert m.parameter("fee_per_side").value == "0.001"
        assert m.parameter("spread_and_slippage_per_side").value == in_price
        assert "TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L25" in m.parameter("fee_per_side").source
        assert all("proposed" in m.parameter(n).evidence
                   for n in ("fee_per_side", "spread_and_slippage_per_side"))
        for name, comp in (("half_spread_per_side", "half_spread"), ("slippage_per_side", "slippage")):
            assert m.parameter(name).value == UNSPECIFIED and m.component(comp).status == UNSPECIFIED
            assert m.component(comp).booking == cm.BOOK_ATTRIBUTION
        assert "SE-81" in m.parameter("half_spread_per_side").source
        assert not m.required_inputs and not m.declared_double_counts


def test_legacy_values_are_the_code_defaults_with_runtime_recorded():
    from shared import triple_barrier
    m = REGISTRY[LEGACY_TRACKER_V1]
    fee, slip = m.parameter("fee_roundtrip_pct"), m.parameter("stop_slippage")
    assert D(fee.value) == D(repr(triple_barrier.ROUNDTRIP_COST_DEFAULT)) * 100
    assert D(slip.value) == D(repr(triple_barrier.STOP_SLIPPAGE_DEFAULT))
    assert "shared/config.py:L92 @ bb7825f" in fee.source and "VER-19" in fee.runtime
    assert "shared/config.py:L107 @ bb7825f" in slip.source and "VER-19" in slip.runtime
    assert m.required_inputs == ("configured_notional_usdt",) and "L106" in m.adoption
    assert m.label_policy == fees.LABEL_POLICY == "net_after_modeled_cost_v1"
    assert m.component("spread").status == UNSPECIFIED
    assert m.component("spread").booking == cm.BOOK_NOT_MODELLED
    parts = [m.parameter(m.component(c).parameter).value
             for c in ("flat_fee_part", "flat_slippage_allowance")]
    assert parts == ["0.2", "0.1"] and "~0.1%" in m.parameter("slippage_allowance_pct").source
    for c in m.components:
        assert c.source, c.component_id
        if c.booking in cm.BOOKED:
            assert "@ bb7825f" in c.source


def test_legacy_code_defaults_equal_the_unconfigured_runtime_config():
    import os
    from shared.config import config
    if any(k in os.environ for k in ("FEE_ROUNDTRIP_PCT", "STOP_SLIPPAGE", "TRADE_AMOUNT_USDT")):
        pytest.skip("configuration overridden by the environment")
    assert cm.legacy_tracker_v1_from_config(config).matches_code_defaults()
    assert config.TRADE_AMOUNT_USDT == 50.0


# ── double counting ────────────────────────────────────────────────────────────────────────

def test_overlap_detection_agrees_with_the_a48_detector():
    from shared.execution_calibration import detect_cost_overlap
    for mid, model in REGISTRY.items():
        booked = {c.component_id: c.charges for c in model.booked_components()}
        assert cm.detect_overlaps(model.components) == tuple(detect_cost_overlap(booked))
    assert cm.detect_overlaps(REGISTRY[LEGACY_TRACKER_V1].components) == ("slippage",)
    assert REGISTRY[LEGACY_TRACKER_V1].declared_double_counts == ("slippage",)
    assert any(d.startswith("R4:") for d in REGISTRY[LEGACY_TRACKER_V1].defects)
    for mid in RESEARCH:
        assert cm.detect_overlaps(REGISTRY[mid].components) == ()


def test_a_research_model_with_a_second_slippage_charge_is_refused():
    base = REGISTRY[RESEARCH_BASELINE_V1]
    allowance = CostComponent("slippage_allowance", ("slippage",), BOOK_EXPLICIT_FEE,
                              cm.BASIS_EXECUTED_LEG_NOTIONAL, cm.LEGS_EVERY, "fee_per_side",
                              "SPECIFIED")
    reason(lambda: cm.validate_model(dataclasses.replace(
        base, components=base.components + (allowance,))), "undeclared_double_count")
    reason(lambda: cm.validate_model(dataclasses.replace(
        base, components=base.components + (allowance,), declared_double_counts=("slippage",))),
        "research_not_per_leg")
    flat = CostComponent("flat", ("fee",), BOOK_FLAT_PER_TRADE, cm.BASIS_CONFIGURED_NOTIONAL,
                         cm.LEGS_TRADE, "fee_per_side", "SPECIFIED")
    stripped = tuple(c for c in base.components if c.component_id != "exchange_fee")
    reason(lambda: cm.validate_model(dataclasses.replace(base, components=stripped + (flat,))),
           "research_not_per_leg")


def test_the_legacy_double_count_must_stay_declared():
    m = REGISTRY[LEGACY_TRACKER_V1]
    reason(lambda: cm.validate_model(dataclasses.replace(m, declared_double_counts=())),
           "undeclared_double_count")
    reason(lambda: cm.validate_model(dataclasses.replace(m, label_policy="gross")),
           "invalid_label_policy")
    params = tuple(dataclasses.replace(p, value="0.15") if p.name == "fee_part_pct" else p
                   for p in m.parameters)
    reason(lambda: cm.validate_model(dataclasses.replace(m, parameters=params)),
           "attribution_mismatch")
    reason(lambda: cm.validate_model(dataclasses.replace(m, round_trip_pct="0.40")),
           "round_trip_mismatch")
    reason(lambda: cm.validate_model(dataclasses.replace(m, status=cm.STATUS_PROPOSED)),
           "invalid_status")


@pytest.mark.parametrize("mid", COST_MODEL_IDS)
def test_double_application_on_a_leg_is_refused(mid):
    book = CostBook(pricer(mid), position_id="p")
    priced = book.book(leg("e", "entry", "1", "100"))
    reason(lambda: book.book(leg("e", "entry", "1", "100")), "double_booking")
    reason(lambda: book.book(priced), "already_priced")
    reason(lambda: pricer(mid).price_leg(priced), "already_priced")
    for other in COST_MODEL_IDS:
        reason(lambda other=other: CostBook(pricer(other), position_id="q").book(priced),
               "already_priced")
    book.book(leg("x", "stop", "0.6", "98"))
    reason(lambda: book.book(leg("x2", "stop", "0.5", "98")), "oversold")
    reason(lambda: book.book(leg("e2", "entry", "1", "100")), "entry_after_exit")
    book.book(leg("x3", "stop", "0.4", "97"))
    closed = book.close()
    reason(book.close, "already_closed")                  # a per-trade charge is booked once
    reason(lambda: book.book(leg("x4", "target", "0.1", "105", taker=False)), "already_closed")
    assert len(closed.trade_bookings) == (1 if mid == LEGACY_TRACKER_V1 else 0)
    reason(lambda: CostBook(pricer(mid), position_id="z").close(), "incomplete_trade")
    reason(lambda: CostBook(pricer(mid), position_id="z").book(leg("x", "stop", "1", "98")),
           "oversold")


@pytest.mark.parametrize("mid", COST_MODEL_IDS)
def test_a_tampered_trade_record_is_detected(mid):
    t = trade(mid, PARTIAL)
    assert cm.check_single_booking(t) is t
    stop = t.legs[-1]
    doubled = dataclasses.replace(stop, bookings=stop.bookings + stop.bookings[:1])
    reason(lambda: cm.check_single_booking(dataclasses.replace(t, legs=t.legs[:-1] + (doubled,))),
           "double_booking")
    inflated = dataclasses.replace(stop, in_price_cost=stop.in_price_cost * 2)
    reason(lambda: cm.check_single_booking(dataclasses.replace(t, legs=t.legs[:-1] + (inflated,))),
           "booking_mismatch")
    repeated = dataclasses.replace(t, legs=t.legs + (t.legs[-1],))
    reason(lambda: cm.check_single_booking(repeated), "double_booking")
    foreign = dataclasses.replace(stop, cost_model_id=next(i for i in COST_MODEL_IDS if i != mid))
    reason(lambda: cm.check_single_booking(dataclasses.replace(t, legs=t.legs[:-1] + (foreign,))),
           "mixed_cost_models")
    twice = dataclasses.replace(t, trade_bookings=t.trade_bookings * 2 or t.legs[0].bookings[:1])
    reason(lambda: cm.check_single_booking(twice), "double_booking")


def test_stress_is_never_added_to_the_baseline():
    base, stress = trade(RESEARCH_BASELINE_V1, PARTIAL), trade(RESEARCH_STRESS_V1, PARTIAL)
    reason(lambda: cm.aggregate([base, stress]), "mixed_cost_models")
    reason(lambda: cm.aggregate([]), "empty")
    both = cm.aggregate([base, trade(RESEARCH_BASELINE_V1, PARTIAL, "p2")])
    assert both["cost_model_id"] == RESEARCH_BASELINE_V1 and both["net_pnl"] == 2 * base.net_pnl


# ── SE-67 ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mid", RESEARCH)
@pytest.mark.parametrize("qty,price", [("1", "100"), ("0.37", "61234.5"), ("1250", "0.0042")])
@pytest.mark.parametrize("exit_role", ["time_exit", "stop", "thesis_exit"])
def test_symmetric_round_trip_is_040_and_060(mid, qty, price, exit_role):
    t = trade(mid, [leg("e", "entry", qty, price), leg("x", exit_role, qty, price)])
    notional = D(qty) * D(price)
    assert t.total_costs / notional == ROUND_TRIP[mid]           # exact, no tolerance
    assert t.gross_reference_pnl == 0 and t.net_pnl == -t.total_costs
    assert t.trade_bookings == () and t.double_counted_kinds == () and t.unsold_quantity == 0
    assert t.model_status == cm.STATUS_PROPOSED


@pytest.mark.parametrize("mid", RESEARCH)
def test_a_stop_exit_is_charged_once(mid):
    p = ResearchPricer(mid)
    f, a = p.fee_per_side, p.spread_and_slippage_per_side
    t = trade(mid, [leg("e", "entry", "2", "100"), leg("s", "stop", "2", "97")])
    stop = t.legs[1]
    assert [b.component_id for b in stop.bookings] == ["exchange_fee", "spread_and_slippage"]
    assert stop.execution_price == D("97") * (1 - a)
    assert stop.in_price_cost == 2 * D("97") * a                   # slippage once, in the price
    assert stop.fee == f * 2 * D("97") * (1 - a)                   # fee once, on executed notional
    assert stop.explicit_cost == 0 and t.trade_bookings == ()      # no flat allowance on top
    entry = t.legs[0]
    assert t.total_costs == f * (entry.executed_notional + stop.executed_notional) + a * 2 * (100 + 97)
    assert t.double_counted_kinds == ()


@pytest.mark.parametrize("mid", RESEARCH)
def test_costs_apply_to_per_leg_executed_notional(mid):
    p = ResearchPricer(mid)
    t = trade(mid, PARTIAL)
    for l in t.legs:
        assert l.fee == p.fee_per_side * l.quantity * l.execution_price == p.fee_per_side * l.executed_notional
        assert l.in_price_cost == (0 if not l.taker else l.quantity * l.reference_price
                                   * p.spread_and_slippage_per_side)
    assert t.fees == p.fee_per_side * sum(l.executed_notional for l in t.legs)
    bigger = trade(mid, PARTIAL[:2] + [leg("t2", "target", "0.3", "103.6", taker=False),
                                       leg("s", "stop", "0.075", "100.4")])
    changed = [i for i, (x, y) in enumerate(zip(t.legs, bigger.legs)) if x.fee != y.fee]
    assert changed == [2, 3]                    # only the resized legs change their fees
    assert not hasattr(p, "configured_notional_usdt") and not REGISTRY[mid].required_inputs
    reason(lambda: p.price_leg(leg("s", "stop", "1", "98", taker=False)), "taker_required")
    reason(lambda: p.price_leg(Leg("s", "stop", 0.5, D("98"), True)), "invalid_leg")   # float qty


# ── agreement with a48-cost-v1 on synthetic legs ───────────────────────────────────────────

SCENARIOS = {
    "stop_full": [leg("e", "entry", "0.5", "100"), leg("s", "stop", "0.5", "97.9")],
    "partial_then_stop": PARTIAL,
    "targets_then_time": [leg("e", "entry", "0.5", "100.2"),
                          leg("t1", "target", "0.125", "102", taker=False),
                          leg("x", "time_exit", "0.375", "101.1")],
    "maker_entry": [leg("e", "entry", "3", "20", taker=False), leg("x", "thesis_exit", "3", "19.5")],
}


@pytest.mark.parametrize("mid", RESEARCH)
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_agreement_with_a48_cost_v1(mid, name):
    from shared.execution_calibration import COST_VERSION, FEE_RATE_PER_SIDE, ExecutedLeg, cost_ledger
    assert COST_VERSION == "a48-cost-v1"
    assert D(repr(FEE_RATE_PER_SIDE)) == ResearchPricer(mid).fee_per_side
    t = trade(mid, SCENARIOS[name])
    legs = [ExecutedLeg("entry" if l.side == "buy" else l.role, 0.0, float(l.reference_price),
                        float(l.execution_price), l.taker, quantity=float(l.quantity))
            for l in t.legs]
    # h + s already sit inside the execution price (SE-45), so a48's separate half-spread is 0.
    a48 = cost_ledger(legs, notional_usdt=float(t.legs[0].executed_notional), half_spread_pct=0.0,
                      quantity=float(t.quantity_bought))
    pairs = [(a48.gross_price_pnl_usdt, t.gross_reference_pnl), (a48.explicit_fees_usdt, t.fees),
             (a48.execution_slippage_usdt, t.in_price_costs),
             (a48.total_modeled_costs_usdt, t.total_costs), (a48.net_modeled_pnl_usdt, t.net_pnl),
             (a48.execution_price_pnl_usdt, t.execution_pnl), (a48.spread_cost_usdt, D(0))]
    for theirs, ours in pairs:
        assert theirs == pytest.approx(float(ours), abs=1e-9)
    assert a48.unsold_quantity == pytest.approx(float(t.unsold_quantity), abs=1e-12)


# ── legacy_tracker_v1 reproduces shared/fees.py and the tracker's booking ──────────────────

GROSS = [0.5, -1.0, 0.0, -0.0, 0.15, 0.1500004, 0.14999996, -0.15, 1e-9, 123.456789, -48.9,
         0.12345678901, 2.5e-5, -3.33333]
BINDINGS = [(0.3, 50.0), (0.3, 100.0), (0.25, 12.5), (0.0, 50.0), (0.6, 33.3)]


def test_float_surface_reproduces_fees_py_on_fixtures():
    rng = random.Random(20261101)
    grosses = GROSS + [rng.uniform(-60, 60) for _ in range(500)]
    for fee, notional in BINDINGS:
        m = legacy(fee=fee, notional=notional)
        assert m.fee_usdt() == fees.fee_usdt(notional, fee) == notional * fee / 100.0
        for g in grosses:
            assert m.economic_close(g) == fees.economic_close(g, notional=notional, fee_roundtrip=fee)
            assert list(m.economic_close(g)) == ["cost_usdt", "net_profit_usdt", "economic_result",
                                                 "label_policy"]
            assert m.net_usdt(g) == fees.net_usdt(g, notional, fee) == g - notional * fee / 100.0
            assert m.net_pct(g) == fees.net_pct(g, fee)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError) as ours:
            legacy().economic_close(bad)
        with pytest.raises(ValueError) as theirs:
            fees.economic_close(bad, notional=50.0, fee_roundtrip=0.3)
        assert str(ours.value) == str(theirs.value)


def test_bound_from_config_reproduces_the_tracker_call_sites():
    from shared.config import config
    from shared.triple_barrier import create_config_from_trade
    m = cm.legacy_tracker_v1_from_config(config)
    # trade_tracker/main.py:L409 and L947 compute the flat charge inline.
    assert m.fee_usdt() == config.TRADE_AMOUNT_USDT * config.FEE_ROUNDTRIP_PCT / 100.0
    for g in GROSS:
        assert m.economic_close(g) == fees.economic_close(g)           # L1350 (config defaults)
        assert m.net_usdt(g) == g - config.TRADE_AMOUNT_USDT * config.FEE_ROUNDTRIP_PCT / 100.0
    assert m.barrier_cost_kwargs() == {"stop_slippage": config.STOP_SLIPPAGE,
                                       "roundtrip_cost": config.FEE_ROUNDTRIP_PCT / 100.0}
    row = {"symbol": "XUSDT", "entry_price": 100.0, "target_1": 102.0, "target_2": 103.6,
           "target_3": 104.4, "stop_loss": 98.0}
    ours = create_config_from_trade(row, trade_amount=config.TRADE_AMOUNT_USDT, **m.barrier_cost_kwargs())
    theirs = create_config_from_trade(row, trade_amount=config.TRADE_AMOUNT_USDT,
                                      stop_slippage=config.STOP_SLIPPAGE,
                                      roundtrip_cost=config.FEE_ROUNDTRIP_PCT / 100.0)
    assert ours == theirs and ours.net_break_even_stop() == theirs.net_break_even_stop()


def _barrier_close(entry, stop, observed, *, t1_first=False):
    """The tracker's pure path: step_barrier → fills_between → aggregate_close (floats)."""
    from shared.partial_exits import aggregate_close, fills_between
    from shared.triple_barrier import TripleBarrierState, create_config_from_trade, step_barrier
    m = legacy()
    row = {"symbol": "XUSDT", "entry_price": entry, "target_1": 102.0, "target_2": 103.6,
           "target_3": 104.4, "stop_loss": stop}
    cfg = create_config_from_trade(row, trade_amount=50.0, **m.barrier_cost_kwargs())
    state = TripleBarrierState(peak=entry)
    realized, remaining = 0.0, 1.0
    if t1_first:
        assert step_barrier(cfg, state, 102.1, 102.1, 102.1, 0.0, stop_observation_price=102.1) is None
        fills = fills_between(previous_target=0, reached_target=1, entry=entry,
                              targets={1: 102.0, 2: 103.6, 3: 104.4}, trade_amount=50.0, min_notional=5)
        realized, remaining = sum(f.gross_usdt for f in fills), 1.0 - sum(f.fraction for f in fills)
    result = step_barrier(cfg, state, observed, observed, observed, 0.0, stop_observation_price=observed)
    _, gross = aggregate_close(entry=entry, final_exit=result.exit_price, trade_amount=50.0,
                               realized_pct=0.0, realized_usdt=realized, remaining_fraction=remaining)
    return cfg, result, gross, m.economic_close(gross)


def test_decimal_surface_agrees_with_the_tracker_path():
    # Full stop exit through a gap: the reference is min(stop, observation) (triple_barrier L198-200).
    cfg, result, gross, econ = _barrier_close(100.0, 98.0, 97.5)
    assert result.exit_reason == "stop_loss"
    t = trade(LEGACY_TRACKER_V1, [leg("e", "entry", "0.5", "100"), leg("s", "stop", "0.5", "97.5")])
    assert t.legs[1].execution_price == D("97.5") * D("0.999")
    assert float(t.legs[1].execution_price) == pytest.approx(result.exit_price, abs=1e-8)
    assert float(t.execution_pnl) == pytest.approx(gross, abs=1e-9)
    assert t.explicit_costs == D(repr(econ["cost_usdt"])) == D("0.15")
    assert float(t.net_pnl) == pytest.approx(econ["net_profit_usdt"], abs=1e-4)   # 4-dp storage
    # T1 tranche, then the break-even stop on the remainder.
    cfg, result, gross, econ = _barrier_close(100.0, 98.0, 100.2, t1_first=True)
    assert result.exit_reason == "break_even"
    be = D(repr(cfg.net_break_even_stop()))
    t = trade(LEGACY_TRACKER_V1, [leg("e", "entry", "0.5", "100"),
                                  leg("t1", "target", "0.125", "102", taker=False),
                                  Leg("s", "stop", D("0.375"), min(be, D("100.2")), True)])
    assert float(t.execution_pnl) == pytest.approx(gross, abs=1e-8)
    assert float(t.net_pnl) == pytest.approx(econ["net_profit_usdt"], abs=1e-4)


# ── R4 test 1 ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stop_ref", ["98", "97.5", "101.3"])
def test_r4_single_count_versus_the_legacy_flat_plus_s(stop_ref):
    S, E, Q = D(stop_ref), D("100"), D("0.5")                  # Q × E = the configured 50
    s, flat = D("0.001"), D("50.0") * D("0.3") / 100
    legs = [leg("e", "entry", Q, E), leg("s", "stop", Q, S)]
    old = trade(LEGACY_TRACKER_V1, legs)
    # legacy_tracker_v1: flat 0.30% of the configured notional plus s inside the stop fill, exactly.
    assert old.explicit_costs == flat and old.in_price_costs == s * Q * S
    assert old.total_costs == flat + s * Q * S and old.fees == 0
    assert old.double_counted_kinds == ("slippage",) == REGISTRY[LEGACY_TRACKER_V1].declared_double_counts
    # The single-count per-leg ledger: fee per side plus s once, no flat allowance.
    new = trade(RESEARCH_BASELINE_V1, legs)
    p = ResearchPricer(RESEARCH_BASELINE_V1)
    stop_leg = new.legs[1]
    assert [b.component_id for b in stop_leg.bookings].count("spread_and_slippage") == 1
    assert stop_leg.in_price_cost == p.spread_and_slippage_per_side * Q * S
    assert new.fees == p.fee_per_side * (new.legs[0].executed_notional + stop_leg.executed_notional)
    assert new.explicit_costs == 0 and new.double_counted_kinds == ()
    # The two models never mix (R4.c: report both side by side, never pooled).
    reason(lambda: cm.aggregate([old, new]), "mixed_cost_models")


# ── WP-IT-07: every ledger entry and fill names a registered model ─────────────────────────

@pytest.mark.parametrize("mid", COST_MODEL_IDS)
def test_ledger_fold_names_the_model_and_reconciles(mid):
    from shared import portfolio_ledger as pl
    t = trade(mid, PARTIAL)
    fills = t.ledger_fills()
    assert {f["cost_model_id"] for f in fills} == {mid} and mid in REGISTRY
    ledger = pl.PortfolioLedger(ledger_id="L", quote_asset="USDT", cost_model_id=mid,
                                money_quantum=D("0.00000001"))
    at = [T0 + timedelta(minutes=i) for i in range(10)]
    ledger.apply(pl.Deposit("d", at[0], D("1000")))
    ledger.apply(pl.Reserve("r", at[1], "p1", "XUSDT", "s_a", D("60")))
    entry = fills[0]
    ledger.apply(pl.EntryFill("e", at[2], "p1", entry["qty"], entry["price"], entry["fee"], "USDT",
                              entry["cost"], entry["ref_price"]))
    ledger.apply(pl.ReleaseReservation("rel", at[3], "p1"))
    for i, f in enumerate(fills[1:], start=4):
        ledger.apply(pl.ExitFill(f"x{i}", at[i], "p1", f["leg_id"], f["qty"], f["price"], f["fee"],
                                 "USDT", f["cost"], f["ref_price"]))
    assert {e.cost_model_id for e in ledger.entries} == {mid}
    state = ledger.state
    assert state.realized_gross == t.execution_pnl
    assert (state.fees, state.costs) == (t.fees, t.explicit_costs)
    assert state.realized_net == t.net_pnl
    with pytest.raises(pl.LedgerError):
        pl.PortfolioLedger(ledger_id="L", quote_asset="USDT", cost_model_id="legacy_tracker_30bps",
                           money_quantum=D("0.00000001"))


def test_module_is_pure_and_imports_no_experimental_module():
    import ast
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from experimental_modules import EXPERIMENTAL_SHARED
    src = Path(cm.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
    assert not imported & {"os", "time", "datetime", "random", "asyncio", "asyncpg", "aiohttp",
                           "shared.database", "shared.config"}
    assert not {f"shared.{name}" for name in EXPERIMENTAL_SHARED if name != "cost_models"} & imported
    assert not re.search(r"signal_quality|counterfactual_barrier", src)
    assert math.isfinite(float(REGISTRY[RESEARCH_STRESS_V1].round_trip_pct))
