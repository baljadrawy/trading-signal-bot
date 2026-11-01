"""WP-E08 (WP-IR-03, WP-IT-03, WP-IT-05, PR-T09): the legacy_v1 capacity authority and its mirrors.

Synthetic, deterministic fixtures only (one fixed-seed generator for the shadow sequences). Every
configuration value is a test fixture. ``RUNTIME`` repeats the runtime-verified configuration
already used by tests/test_paper_observe_capacity.py (VER-12: canary 2, MAX_OPEN_TRADES 10); it is
not a proposal. The mirror parity tests run the REAL service functions with a faked database.
"""
import ast
import asyncio
import hashlib
import itertools
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared import capacity_authority as ca
from shared import funnel_records as fr
from shared.economic_halt_policy import ENFORCE, OBSERVE, evaluate_with_policy, legacy_fields
from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = dict(RISK_CAPITAL_USDT=500.0, TRADE_AMOUNT_USDT=50.0, MAX_OPEN_TRADES=10,
               RISK_CANARY_MAX_OPEN_TRADES=2, MAX_GROSS_EXPOSURE_PERCENT=80.0,
               MAX_SYMBOL_EXPOSURE_PERCENT=10.0, MAX_STRATEGY_EXPOSURE_PERCENT=40.0,
               MAX_REGIME_EXPOSURE_PERCENT=50.0, MAX_DAILY_LOSS_PERCENT=3.0,
               MAX_WEEKLY_LOSS_PERCENT=10.0, MAX_DRAWDOWN_PERCENT=15.0, STOP_ON_CONSECUTIVE_LOSSES=7)
# The legacy L-1 ladder (shared/risk_management.py:L95-L114), reproduced for checking only.
LADDER_MULTIPLIER = {"drawdown_warning": 0.25, "drawdown_caution": 0.5, "weekly_minimum": 0.1,
                     "weekly_reduce": 0.5, "loss_streak_minimum": 0.1, "loss_streak_reduce": 0.5}
CANDIDATE = fr.CandidateRef(symbol="AAAUSDT", strategy_id="momentum_breakout",
                            strategy_version="test-version", timeframe="4h",
                            bar_close_time=1_700_000_000_000)


def cfg(**over):
    values = dict(RUNTIME)
    values.update(over)
    return SimpleNamespace(**values)


def snap(open_count=0, symbol_open=0, streak=0, realized=0.0, daily=0.0, weekly=0.0, unrealized=0.0,
         strategy_open=0, regime_open=0, paused=False, pause_reason=None, peak=500.0):
    return RiskSnapshot(realized_total_usdt=realized, daily_pnl_usdt=daily, weekly_pnl_usdt=weekly,
                        unrealized_pnl_usdt=unrealized, peak_equity_usdt=peak,
                        open_count=open_count, symbol_open_count=symbol_open,
                        consecutive_losses=streak, strategy_open_count=strategy_open,
                        regime_open_count=regime_open, manually_paused=paused,
                        manual_pause_reason=pause_reason)


def decide(s, c=None, mode=ENFORCE, working=None):
    return ca.decide_capacity(s, ca.legacy_risk_limits(c or cfg()), economic_halt_mode=mode,
                              working_orders=working)


def gate(open_count, c=None, paused=False, reason=None):
    c = c or cfg()
    return ca.delivery_gate(paused=paused, pause_reason=reason, open_count=open_count,
                            max_open_trades=c.MAX_OPEN_TRADES,
                            risk_canary_max_open_trades=c.RISK_CANARY_MAX_OPEN_TRADES)


def precheck(open_count, c=None, site="per_signal"):
    c = c or cfg()
    return ca.tracker_precheck(open_count if c.MAX_OPEN_TRADES > 0 else None, c.MAX_OPEN_TRADES,
                               site=site)


def kinds(comparison):
    return sorted((d.mirror, d.kind) for d in comparison.disagreements)


def record_kwargs():
    return dict(cycle_id="cycle-1", as_of=1_700_000_100_000, decision_time=1_700_000_100_000,
                rule_ref="shared/capacity_authority.py", snapshot_hash="s" * 8, config_hash="c" * 8)


# ── golden grids (PR-T09; WP-IT-03 item 1) ──────────────────────────────────

GRID_CFGS = [cfg(MAX_OPEN_TRADES=m, RISK_CANARY_MAX_OPEN_TRADES=c)
             for m, c in [(10, 2), (10, 1), (2, 10), (1, 1), (3, 3), (0, 2), (10, 0), (-1, 2)]] + [
    cfg(TRADE_AMOUNT_USDT=100.0), cfg(TRADE_AMOUNT_USDT=450.0), cfg(RISK_CAPITAL_USDT=0.0),
    cfg(MAX_STRATEGY_EXPOSURE_PERCENT=15.0, MAX_REGIME_EXPOSURE_PERCENT=25.0, MAX_OPEN_TRADES=3,
        RISK_CANARY_MAX_OPEN_TRADES=3),
    cfg(MAX_REGIME_EXPOSURE_PERCENT=25.0, MAX_OPEN_TRADES=3, RISK_CANARY_MAX_OPEN_TRADES=3)]
GRID_SNAPS = [snap(open_count=o, symbol_open=so, streak=st, realized=r, daily=d, weekly=w,
                   strategy_open=o, regime_open=o)
              for o, so, st, r, d, w in itertools.product(range(4), (0, 1), (0, 3, 5, 7), (0.0, -80.0),
                                                           (0.0, -16.0), (0.0, -26.0, -51.0))
              if so <= o]
EDGE_SNAPS = [snap(paused=True), snap(open_count=2, paused=True, pause_reason="risk:daily_loss_limit"),
              snap(unrealized=float("nan")), snap(open_count=1, unrealized=float("inf")),
              snap(open_count=-1), snap(symbol_open=-1), snap(streak=-1), snap(peak=float("nan")),
              snap(open_count=1, realized=-30.0), snap(open_count=1, weekly=-36.0)]


def _all_cases():
    for c in GRID_CFGS:
        lim = ca.legacy_risk_limits(c)
        for s in GRID_SNAPS + EDGE_SNAPS:
            yield c, lim, s


def test_golden_grid_is_byte_identical_to_the_legacy_policy():
    codes, n = set(), 0
    for _, lim, s in _all_cases():
        legacy = evaluate_new_trade(s, lim)
        for mode in (ENFORCE, OBSERVE):
            d = ca.decide_capacity(s, lim, economic_halt_mode=mode, working_orders=None)
            ref = evaluate_with_policy(s, lim, mode)
            assert repr(d.risk_decision) == repr(ref)
            assert d.admitted is bool(ref.allowed) and d.outcome in (ca.ADMIT, ca.REFUSE)
            if mode == ENFORCE or ref.observed_economic_stop is None:
                assert repr(d.legacy_fields()) == repr(legacy_fields(legacy))
            codes.add(d.reason_code)
            n += 1
    assert n == 2 * len(GRID_CFGS) * (len(GRID_SNAPS) + len(EDGE_SNAPS)) > 8000
    assert codes == {None, ca.CODE_CAPACITY_FULL, ca.CODE_RISK_STATE_INVALID, ca.CODE_PAUSED,
                     ca.CODE_EXPOSURE_GROSS, ca.CODE_EXPOSURE_SYMBOL, ca.CODE_EXPOSURE_STRATEGY,
                     ca.CODE_EXPOSURE_REGIME, *ca.ECONOMIC_LIMIT_CODES}


def test_golden_grid_reproduces_slot_limit_exposure_bound_and_multiplier():
    for _, lim, s in _all_cases():
        for mode in (ENFORCE, OBSERVE):
            d = ca.decide_capacity(s, lim, economic_halt_mode=mode, working_orders=None)
            det = d.detail
            assert det["open"] == s.open_count and det["reserved"] == 0
            assert det["budget_version"] == ca.BUDGET_VERSION_LEGACY_V1
            assert det["configured_limit"] == lim.max_open_trades
            if d.slots == ca.SLOTS_INVALID:
                assert d.reason_code == ca.CODE_RISK_STATE_INVALID and det["limit"] == 0
                assert det["exposure_slot_bound"] is None and det["invalid_inputs"]
                continue
            bound = math.floor(lim.capital_usdt * lim.max_gross_exposure_pct / 100
                               / lim.trade_amount_usdt + 1e-12)
            mult = min([1.0] + [LADDER_MULTIPLIER[r] for r in det["ladder_reasons"]])
            assert det["exposure_slot_bound"] == bound
            assert det["multiplier"] == mult == d.risk_decision.size_multiplier
            assert det["limit"] == d.risk_decision.max_positions == max(
                1, math.floor(min(lim.max_open_trades, bound) * mult))
            assert d.slots == (ca.SLOTS_FULL if s.open_count >= det["limit"] else ca.SLOTS_FREE)


def test_shared_risk_management_is_byte_identical():
    """PR-T09: the pinned file is unchanged (sha256 as in deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json)."""
    digest = hashlib.sha256((ROOT / "shared" / "risk_management.py").read_bytes()).hexdigest()
    assert digest == "d860d324a9606ef59b60fd38798a6b661f13e892a7ebf5a36d8b9da4f647bead"


def test_decision_is_deterministic_and_keeps_the_policy_object():
    s, lim = snap(open_count=1, streak=3), ca.legacy_risk_limits(cfg())
    seen = []

    def evaluate(snapshot, limits, mode):
        seen.append(evaluate_with_policy(snapshot, limits, mode))
        return seen[-1]
    a = ca.decide_capacity(s, lim, economic_halt_mode=OBSERVE, working_orders=0, evaluate=evaluate)
    b = ca.decide_capacity(s, lim, economic_halt_mode=OBSERVE, working_orders=0)
    assert a.risk_decision is seen[0]                 # the caller's evaluator result, untouched
    assert a == b and a.as_dict() == b.as_dict()
    with pytest.raises(TypeError):
        a.detail["open"] = 5                          # read-only


# ── available and full capacity ──────────────────────────────────────────────

@pytest.mark.parametrize("open_count", [0, 1])
def test_available_capacity_admits(open_count):
    d = decide(snap(open_count=open_count))
    assert d.admitted and d.reason_code is None and d.sub_stage is None and d.slots == ca.SLOTS_FREE
    assert d.detail["limit"] == 2 and d.detail["configured_limit"] == 2
    assert d.detail["exposure_slot_bound"] == 8 and d.detail["multiplier"] == 1.0
    assert d.record_fields() is None
    assert ca.compare_shadow(d, [gate(open_count), precheck(open_count)]).agree


def test_full_capacity_refuses_with_capacity_full_and_its_inputs():
    d = decide(snap(open_count=2))
    assert not d.admitted and d.reason_code == ca.CODE_CAPACITY_FULL and d.slots == ca.SLOTS_FULL
    assert d.sub_stage == ca.SUB_STAGE_ADMISSION
    assert d.detail["legacy_reason"] == "max_open_trades" and d.risk_decision.reason == "max_open_trades"
    assert (d.detail["open"], d.detail["reserved"], d.detail["limit"], d.detail["multiplier"]) == (2, 0, 2, 1.0)
    assert d.inputs["snapshot"]["open_count"] == 2 and d.inputs["limits"]["max_open_trades"] == 2
    assert d.inputs["economic_halt_mode"] == ENFORCE


def test_capacity_full_record_matches_the_funnel_builder():
    d = decide(snap(open_count=2, streak=3), mode=OBSERVE, working=1)
    fields = d.record_fields()
    direct = fr.RejectionRecord(**fields, **record_kwargs(), symbol=CANDIDATE.symbol,
                                strategy_id=CANDIDATE.strategy_id,
                                strategy_version=CANDIDATE.strategy_version,
                                timeframe=CANDIDATE.timeframe, bar_close_time=CANDIDATE.bar_close_time)
    det = dict(fields["detail"])
    core = {k: det.pop(k) for k in ("open", "reserved", "limit", "multiplier", "budget_version")}
    built = fr.capacity_full_record(candidate=CANDIDATE, open_count=core["open"],
                                    reserved=core["reserved"], limit=core["limit"],
                                    multiplier=core["multiplier"],
                                    budget_version=core["budget_version"], extra_detail=det,
                                    **record_kwargs())
    assert built.to_json() == direct.to_json()
    assert built.reason_code == "F7.capacity_full" and built.stage == "F7"
    assert built.detail["legacy_reason"] == "loss_streak_reduce"


# ── reason attribution (WP-IR-04, WP-IR-05, WP-IT-05) ───────────────────────

def test_every_code_is_canonical_f7_and_never_a_rank_code():
    codes = [ca.CODE_CAPACITY_FULL, ca.CODE_RISK_STATE_INVALID, ca.CODE_PAUSED,
             ca.CODE_ALREADY_REGISTERED, ca.CODE_SUPERSEDED, ca.CODE_EXPOSURE_GROSS,
             ca.CODE_EXPOSURE_SYMBOL, ca.CODE_EXPOSURE_STRATEGY, ca.CODE_EXPOSURE_REGIME,
             *ca.ECONOMIC_LIMIT_CODES]
    for code in codes:
        assert fr.validate_reason_code(code, "F7") == code
        assert code not in fr.RANKED_CODES
    assert ca.CODE_CAPACITY_FULL != "F6.rank_below_cap"
    assert fr.SUB_STAGE_STAGE[ca.SUB_STAGE_ADMISSION] == ca.STAGE
    src = (ROOT / "shared" / "capacity_authority.py").read_text()
    for forbidden in ("F6.", "not_selected_capacity", "REJECT_RANK_CAPACITY"):
        assert forbidden not in src


def test_rank_loss_and_capacity_refusal_are_different_records():
    rank = fr.rank_below_cap_record(candidate=CANDIDATE, rank=2, offer_cap=1,
                                    selection_version="sel-test", **record_kwargs())
    cap = decide(snap(open_count=2)).record_fields()
    assert (rank.stage, rank.reason_code) == ("F6", "F6.rank_below_cap")
    assert (cap["stage"], cap["reason_code"]) == ("F7", "F7.capacity_full")


def test_ladder_labelled_capacity_refusal_is_capacity_full():
    """shared/risk_management.py:L141-L142 labels a slot refusal with the first ladder reason."""
    d = decide(snap(open_count=1, streak=3))
    assert d.risk_decision.reason == "loss_streak_reduce" and not d.risk_decision.allowed
    assert d.reason_code == ca.CODE_CAPACITY_FULL
    assert d.detail["ladder_reasons"] == ("loss_streak_reduce",) and d.detail["limit"] == 1
    cmp = ca.compare_shadow(d, [gate(1), precheck(1)])
    assert "capacity_labelled_by_ladder" in cmp.notes
    assert kinds(cmp) == [("delivery_gate", "mirror_admits_slots_full"),
                          ("tracker_precheck:per_signal", "mirror_admits_slots_full")]


def test_ladder_label_on_admission_is_not_a_refusal():
    d = decide(snap(open_count=0, streak=3))
    assert d.admitted and d.risk_decision.reason == "loss_streak_reduce" and d.reason_code is None


@pytest.mark.parametrize("over,expected", [
    (dict(daily=-16.0), "F7.economic_limit:daily_loss_limit"),
    (dict(weekly=-51.0), "F7.economic_limit:weekly_loss_limit"),
    (dict(realized=-80.0), "F7.economic_limit:max_drawdown_limit"),
    (dict(streak=7), "F7.economic_limit:loss_streak_halt"),
])
def test_economic_limits_in_enforce_mode(over, expected):
    d = decide(snap(**over))
    assert d.reason_code == expected and d.detail["legacy_reason"] == expected.split(":")[1]
    assert d.detail["economic_flags"][0] == expected.split(":")[1]


def test_precedence_pause_over_economic_over_exposure_over_capacity():
    paused = decide(snap(open_count=2, daily=-16.0, paused=True, pause_reason="risk:daily_loss_limit"))
    assert paused.reason_code == ca.CODE_PAUSED and paused.slots == ca.SLOTS_FULL      # masked
    assert paused.detail["legacy_reason"] == "risk:daily_loss_limit"
    assert decide(snap(paused=True)).detail["legacy_reason"] == "manual_pause"
    econ = decide(snap(open_count=2, daily=-16.0))
    assert econ.reason_code == "F7.economic_limit:daily_loss_limit" and econ.slots == ca.SLOTS_FULL
    gross = decide(snap(), cfg(TRADE_AMOUNT_USDT=450.0))
    assert gross.reason_code == ca.CODE_EXPOSURE_GROSS and gross.detail["exposure_slot_bound"] == 0
    assert gross.detail["limit"] == 1 and gross.slots == ca.SLOTS_FREE


def test_observe_mode_attributes_the_stop_that_still_binds():
    enforce = decide(snap(open_count=2, daily=-16.0), mode=ENFORCE)
    observe = decide(snap(open_count=2, daily=-16.0), mode=OBSERVE)
    assert enforce.reason_code == "F7.economic_limit:daily_loss_limit"
    assert observe.reason_code == ca.CODE_CAPACITY_FULL
    assert observe.detail["observed_economic_stop"] == "daily_loss_limit"
    assert observe.detail["risk_policy_version"] == "econ-observe-v1"
    flat = decide(snap(daily=-16.0), mode=OBSERVE)
    assert flat.admitted and flat.risk_decision.reason == "observed:daily_loss_limit"


def test_attribution_never_guesses_an_inconsistent_decision():
    lim = ca.legacy_risk_limits(cfg())
    other = evaluate_with_policy(snap(open_count=0), lim, ENFORCE)
    with pytest.raises(ca.CapacityAttributionError):
        ca.attribute_decision(snap(open_count=2), lim, other, working_orders=None)
    plain = evaluate_new_trade(snap(open_count=2), lim)
    d = ca.attribute_decision(snap(open_count=2), lim, plain, working_orders=None)
    assert d.reason_code == ca.CODE_CAPACITY_FULL and d.risk_decision is plain
    assert d.detail["risk_policy_version"] is None and "economic_halt_mode" not in d.inputs


# ── invalid limits (WP-IT-03 item 3) ─────────────────────────────────────────

@pytest.mark.parametrize("m,c,delivery_kind,tracker_kind", [
    (0, 2, "mirror_unlimited_authority_invalid", "mirror_unlimited_authority_invalid"),
    (10, 0, "mirror_unlimited_authority_invalid", "mirror_admits_authority_invalid"),
    (-1, 2, "mirror_unlimited_authority_invalid", "mirror_unlimited_authority_invalid"),
    (0, 0, "mirror_unlimited_authority_invalid", "mirror_unlimited_authority_invalid"),
])
def test_zero_or_negative_limit_refuses_while_mirrors_read_it_as_unlimited(m, c, delivery_kind,
                                                                           tracker_kind):
    c_ = cfg(MAX_OPEN_TRADES=m, RISK_CANARY_MAX_OPEN_TRADES=c)
    d = decide(snap(), c_)
    assert d.reason_code == ca.CODE_RISK_STATE_INVALID and d.slots == ca.SLOTS_INVALID
    assert d.detail["legacy_reason"] == "invalid_risk_state"
    assert d.detail["invalid_inputs"] == ("max_open_trades",)
    assert gate(0, c_).legacy == (True, "eligible")
    cmp = ca.compare_shadow(d, [gate(0, c_), precheck(0, c_)])
    assert kinds(cmp) == [("delivery_gate", delivery_kind), ("tracker_precheck:per_signal", tracker_kind)]


@pytest.mark.parametrize("limit", [2.5, True, None, "2"])
def test_non_integer_or_missing_limit_is_refused_at_the_boundary(limit):
    lim = RiskLimits(capital_usdt=500.0, trade_amount_usdt=50.0, max_open_trades=limit)
    with pytest.raises(ValueError, match="max_open_trades_not_integer"):
        ca.decide_capacity(snap(), lim, economic_halt_mode=ENFORCE, working_orders=None)
    with pytest.raises(ValueError, match="max_open_trades_not_integer"):
        ca.attribute_decision(snap(), lim, evaluate_new_trade(snap(), ca.legacy_risk_limits(cfg())),
                              working_orders=None)


@pytest.mark.parametrize("name", ["MAX_OPEN_TRADES", "RISK_CANARY_MAX_OPEN_TRADES", "RISK_CAPITAL_USDT",
                                  "STOP_ON_CONSECUTIVE_LOSSES"])
def test_missing_configuration_name_has_no_default(name):
    c = cfg()
    delattr(c, name)
    with pytest.raises(AttributeError):
        ca.legacy_risk_limits(c)


def test_missing_price_fails_closed_as_risk_state_invalid():
    d = decide(snap(open_count=1, unrealized=float("nan")))
    assert d.reason_code == ca.CODE_RISK_STATE_INVALID
    assert d.detail["invalid_inputs"] == ("unrealized_pnl_usdt",)
    assert d.as_dict()["inputs"]["snapshot"]["unrealized_pnl_usdt"] == "nan"


# ── pending reservations (PR-12) ─────────────────────────────────────────────

@pytest.mark.parametrize("working", [None, 0, 1, 3])
def test_working_orders_are_reported_never_counted(working):
    d = decide(snap(open_count=1), working=working)
    ref = decide(snap(open_count=1), working=None)
    assert repr(d.risk_decision) == repr(ref.risk_decision) and d.admitted
    assert d.detail["reserved"] == 0 and d.detail["working_orders"] == working
    notes = ca.compare_shadow(d, [gate(1)]).notes
    assert ("working_orders_uncounted" in notes) is bool(working)


@pytest.mark.parametrize("working", [-1, True, 1.5])
def test_working_orders_must_be_a_count(working):
    with pytest.raises(ValueError, match="working_orders_invalid"):
        decide(snap(), working=working)


# ── duplicate intents and concurrent positions (admission-query mirror) ──────

def P(signal_id, symbol, minute):
    return ca.PendingSignal(signal_id, symbol, 1_700_000_000_000 + minute * 60_000)


def test_admission_queue_supersedes_and_skips_registered():
    q = ca.legacy_admission_queue([P(1, "BBBUSDT", 0), P(2, "AAAUSDT", 1), P(3, "AAAUSDT", 5),
                                   P(4, "CCCUSDT", 2)],
                                  open_symbols=(), registered_signal_ids={4})
    assert [p.signal_id for p in q.queue] == [3, 1]                      # symbol order
    assert [(e.signal_id, e.reason_code, e.legacy_rule) for e in q.excluded] == [
        (2, "F7.superseded", "distinct_on_symbol"), (4, "F7.already_registered",
                                                     "active_trade_exists_for_signal")]
    assert q.excluded[0].detail["superseded_by"] == 3
    for e in q.excluded:
        fr.validate_reason_code(e.reason_code, "F7")


def test_one_open_trade_per_symbol_whatever_its_trade_type():
    q = ca.legacy_admission_queue([P(1, "AAAUSDT", 0), P(2, "BBBUSDT", 0)],
                                  open_symbols={"AAAUSDT"}, registered_signal_ids=())
    assert [p.signal_id for p in q.queue] == [2]
    assert (q.excluded[0].reason_code, q.excluded[0].legacy_rule) == ("F7.exposure_symbol",
                                                                      "one_open_per_symbol")
    assert q.excluded[0].detail["mapping"] == "inferred"
    open_rows = [{"symbol": "AAAUSDT", "trade_type": "momentum", "regime": "flat"}]
    counts = ca.legacy_open_counts(open_rows, "AAAUSDT", "reversion", "flat")
    assert counts == {"open_count": 1, "symbol_open_count": 1, "strategy_open_count": 0,
                      "regime_open_count": 1}
    d = decide(snap(open_count=1, symbol_open=1))
    assert d.reason_code == ca.CODE_EXPOSURE_SYMBOL and d.slots == ca.SLOTS_FREE
    assert d.detail["legacy_reason"] == "symbol_concentration_limit"


def test_strategy_and_regime_concentration_codes():
    c = cfg(MAX_STRATEGY_EXPOSURE_PERCENT=15.0, MAX_REGIME_EXPOSURE_PERCENT=25.0, MAX_OPEN_TRADES=3,
            RISK_CANARY_MAX_OPEN_TRADES=3)
    assert decide(snap(open_count=1, strategy_open=1), c).reason_code == ca.CODE_EXPOSURE_STRATEGY
    assert decide(snap(open_count=2, regime_open=2), c).reason_code == ca.CODE_EXPOSURE_REGIME


def test_open_counts_follow_the_legacy_truthiness():
    rows = [{"symbol": "A", "trade_type": "", "regime": None}, {"symbol": "B", "trade_type": "",
                                                                "regime": None}]
    assert ca.legacy_open_counts(rows, "A", "", None) == {
        "open_count": 2, "symbol_open_count": 1, "strategy_open_count": 0, "regime_open_count": 0}


def test_duplicate_rows_and_unordered_ties_are_refused():
    with pytest.raises(ValueError, match="signal_id_duplicate"):
        ca.legacy_admission_queue([P(1, "A", 0), P(1, "A", 0)], open_symbols=(),
                                  registered_signal_ids=())
    with pytest.raises(ValueError, match="signal_time_tie"):
        ca.legacy_admission_queue([P(1, "A", 0), P(2, "A", 0)], open_symbols=(),
                                  registered_signal_ids=())


# ── mirrors: byte-identical to the REAL service functions ───────────────────

def _telegram():
    from cr1_support import load_telegram_main
    return load_telegram_main()


def _tracker():
    try:
        import trade_tracker.main as tracker
    except ImportError:                                # pragma: no cover
        pytest.skip("trade_tracker service not importable")
    return tracker


def _set_config(monkeypatch, **values):
    from shared.config import config
    for name, value in values.items():
        monkeypatch.setattr(config, name, value)
    return config


DELIVERY_GRID = list(itertools.product((False, True), (None, "manual_pause", "risk:loss_streak_halt"),
                                       (None, 0, 1, 2, 3), (10, 2, 1, 0, -1), (2, 1, 0, 3)))


def test_delivery_gate_mirror_equals_can_deliver_candidate(monkeypatch):
    """telegram/main.py:L364-L382, run for real with a faked database and pause state."""
    tg = _telegram()
    for paused, reason, fetched, m, c in DELIVERY_GRID:
        calls = []

        class DB:
            async def fetchrow(self, sql, *args):
                return None

            async def fetchval(self, sql, *args):
                calls.append(sql)
                return fetched
        monkeypatch.setattr(tg, "Database", DB())
        monkeypatch.setattr(tg, "get_pause_state", AsyncMock(return_value=(paused, reason)))
        _set_config(monkeypatch, MAX_OPEN_TRADES=m, RISK_CANARY_MAX_OPEN_TRADES=c)
        real = asyncio.run(tg.can_deliver_candidate())
        mirror = ca.delivery_gate(paused=paused, pause_reason=reason,
                                  open_count=None if paused else (fetched or 0),
                                  max_open_trades=m, risk_canary_max_open_trades=c)
        assert real == mirror.legacy, (paused, reason, fetched, m, c)
        assert bool(calls) is (not paused)             # the count is read only when not paused
        expected = (ca.CODE_PAUSED if paused else ca.CODE_CAPACITY_FULL if not real[0] else None)
        assert mirror.reason_code == expected


def _tracker_db(counts, signals, log):
    counts = iter(counts)

    class DB:
        async def fetchval(self, sql, *args):
            log.append("count")
            return next(counts)

        async def fetch(self, sql, *args):
            log.append("signals")
            return signals
    return DB()


@pytest.mark.parametrize("m", [10, 2, 1, 0, -1])
@pytest.mark.parametrize("fetched", [None, 0, 1, 2, 3, 10, 11])
def test_tracker_loop_entry_mirror_equals_register_new_signals(monkeypatch, m, fetched):
    """trade_tracker/main.py:L708-L716, run for real; no signal is pending."""
    tracker = _tracker()
    log, emitted = [], []
    monkeypatch.setattr(tracker, "Database", _tracker_db([fetched], [], log))
    monkeypatch.setattr(tracker, "_v2_capacity", lambda *a: emitted.append(a))
    _set_config(monkeypatch, MAX_OPEN_TRADES=m, SIGNAL_INTEGRITY_MODE="off")
    asyncio.run(tracker.register_new_signals())
    pre = ca.tracker_precheck(None if m <= 0 else (fetched or 0), m, site="loop_entry")
    assert ("count" in log) is pre.checked
    assert ("signals" in log) is (not pre.blocked)
    assert emitted == ([(pre.blocked, pre.open_count, m)] if pre.checked else [])


@pytest.mark.parametrize("m", [10, 2, 1, 0])
@pytest.mark.parametrize("second", [0, 1, 2, 3, 10])
def test_tracker_per_signal_mirror_equals_register_new_signals(monkeypatch, m, second):
    """trade_tracker/main.py:L752-L759, run for real with one pending signal and no price."""
    tracker = _tracker()
    log, emitted = [], []
    sig = {"id": 7, "symbol": "AAAUSDT", "features_snapshot": None, "timeframe": "4h"}
    monkeypatch.setattr(tracker, "Database", _tracker_db([0, second], [sig], log))
    monkeypatch.setattr(tracker, "_v2_capacity", lambda *a: emitted.append(a))
    price = AsyncMock(return_value=None)
    monkeypatch.setattr(tracker, "get_current_price", price)
    _set_config(monkeypatch, MAX_OPEN_TRADES=m, SIGNAL_INTEGRITY_MODE="off")
    asyncio.run(tracker.register_new_signals())
    pre = ca.tracker_precheck(None if m <= 0 else second, m, site="per_signal")
    assert price.await_count == (0 if pre.blocked else 1)
    assert log.count("count") == (2 if pre.checked else 0)
    assert emitted[1:] == ([(True, second, m)] if pre.blocked else [])


class _RiskDB:
    def __init__(self, results, open_rows):
        self.results, self.open_rows = results, open_rows

    async def fetch(self, sql, *args):
        if "trade_results" in sql:
            return self.results
        if "active_trades" in sql:
            return self.open_rows
        return []

    async def fetchval(self, sql, *args):
        return None

    async def fetchrow(self, sql, *args):
        return None


CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
RISK_SCENARIOS = [
    # (open rows, symbol, trade_type, regime, losses, price, paused)
    ([], "AAAUSDT", "momentum", "flat", 0, 1.0, False),
    ([("BBBUSDT", "momentum", "flat")], "AAAUSDT", "momentum", "flat", 0, 1.0, False),
    ([("BBBUSDT", "momentum", "flat")], "AAAUSDT", "reversion", "up", 3, 1.0, False),
    ([("AAAUSDT", "momentum", "flat")], "AAAUSDT", "reversion", "flat", 0, 1.0, False),
    ([("BBBUSDT", "momentum", "flat"), ("CCCUSDT", None, None)], "AAAUSDT", None, None, 0, 1.0, False),
    ([("BBBUSDT", "momentum", "flat")], "AAAUSDT", "momentum", "flat", 9, 1.0, False),
    ([("BBBUSDT", "momentum", "flat")], "AAAUSDT", "momentum", "flat", 0, None, False),
    ([], "AAAUSDT", "momentum", "flat", 0, 1.0, True),
]


@pytest.mark.parametrize("mode", [ENFORCE, OBSERVE])
@pytest.mark.parametrize("scenario", RISK_SCENARIOS)
@pytest.mark.parametrize("limits", [(10, 2), (10, 1), (0, 2)])
def test_authority_equals_the_real_tracker_risk_assessment(monkeypatch, mode, scenario, limits):
    """trade_tracker/main.py:L922-L1006, run for real: same RiskLimits, same occupancy counts,
    and the adapter's decision is the tracker's decision."""
    tracker = _tracker()
    rows, symbol, trade_type, regime, losses, price, paused = scenario
    open_rows = [{"symbol": s, "entry_price": 1.0, "trade_type": t, "regime": r} for s, t, r in rows]
    results = [{"profit_usdt": -2.0, "result": "LOSS", "exit_time": CLEAN_START + timedelta(hours=i)}
               for i in range(losses)]
    db = _RiskDB(results, open_rows)
    monkeypatch.setattr(tracker, "Database", db)
    monkeypatch.setattr("shared.risk_epoch.Database", db)
    monkeypatch.setattr(tracker, "get_pause_state",
                        AsyncMock(return_value=(paused, "manual_pause" if paused else None)))
    monkeypatch.setattr(tracker, "_risk_price", AsyncMock(return_value=price))
    config = _set_config(monkeypatch, **dict(RUNTIME, MAX_OPEN_TRADES=limits[0],
                                             RISK_CANARY_MAX_OPEN_TRADES=limits[1]),
                         PAPER_TRADING=True, PAPER_ECONOMIC_HALT_MODE=mode)
    captured = {}
    real_policy = tracker.evaluate_with_policy

    def capture(snapshot, lim, m):
        captured.update(snapshot=snapshot, limits=lim, mode=m)
        return real_policy(snapshot, lim, m)
    monkeypatch.setattr(tracker, "evaluate_with_policy", capture)
    real = asyncio.run(tracker.assess_new_trade_risk(symbol, trade_type=trade_type, regime=regime))
    s, lim = captured["snapshot"], captured["limits"]
    assert lim == ca.legacy_risk_limits(config) and captured["mode"] == mode
    counts = ca.legacy_open_counts(open_rows, symbol, trade_type, regime)
    assert {k: getattr(s, k) for k in counts} == counts
    d = ca.decide_capacity(s, lim, economic_halt_mode=mode, working_orders=None)
    assert repr(d.risk_decision) == repr(real) and d.admitted is bool(real.allowed)


# ── shadow comparison over synthetic sequences (WP-IT-03 item 2) ────────────

SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT")
SEQ_CFGS = [(10, 2), (10, 1), (3, 3), (2, 10), (0, 2), (10, 0)]


def run_cycle(c, mode, streak, open_rows, registered, pending, waits, working):
    """One legacy admission loop (trade_tracker/main.py:L705-L899), capacity parts only."""
    limits, out = ca.legacy_risk_limits(c), []
    entry = precheck(len(open_rows), c, site="loop_entry")
    if entry.blocked:
        return out, working
    queue = ca.legacy_admission_queue(pending, open_symbols={r["symbol"] for r in open_rows},
                                      registered_signal_ids=registered)
    for sig in queue.queue:
        pre = precheck(len(open_rows), c)
        if pre.blocked:
            break
        if sig.signal_id in waits:                     # L806-L810: resting order, no risk check
            working += 1
            continue
        counts = ca.legacy_open_counts(open_rows, sig.symbol, "momentum", "flat")
        s = snap(streak=streak, symbol_open=counts["symbol_open_count"],
                 open_count=counts["open_count"], strategy_open=counts["strategy_open_count"],
                 regime_open=counts["regime_open_count"])
        d = ca.decide_capacity(s, limits, economic_halt_mode=mode, working_orders=working)
        cmp = ca.compare_shadow(d, [gate(len(open_rows), c), pre])
        out.append((cmp, gate(len(open_rows), c), pre))
        if d.admitted:
            open_rows.append({"symbol": sig.symbol, "trade_type": "momentum", "regime": "flat"})
            registered.add(sig.signal_id)
    return out, working


def _sequences():
    rng = random.Random(20261101)
    for (m, c), mode, streak in itertools.product(SEQ_CFGS, (ENFORCE, OBSERVE), (0, 3, 5)):
        conf = cfg(MAX_OPEN_TRADES=m, RISK_CANARY_MAX_OPEN_TRADES=c)
        open_rows, registered, working, next_id, history = [], set(), 0, 1, []
        for cycle in range(6):
            pending = []
            for symbol in rng.sample(SYMBOLS, rng.randint(1, len(SYMBOLS))):
                pending.append(P(next_id, symbol, cycle * 10 + len(pending)))
                next_id += 1
            if registered and rng.random() < 0.5:      # an admitted signal offered again
                sid = min(registered)
                pending.append(ca.PendingSignal(sid, "ZZZUSDT", 0))
            waits = {p.signal_id for p in pending if rng.random() < 0.2}
            out, working = run_cycle(conf, mode, streak, open_rows, registered, pending, waits,
                                     working)
            history.extend(out)
            if open_rows and rng.random() < 0.3:       # a position closes between cycles
                open_rows.pop(0)
        yield conf, mode, streak, history, open_rows


def test_shadow_sequences_record_every_disagreement_and_mirrors_are_never_stricter():
    seen_kinds, n = set(), 0
    for conf, mode, streak, history, open_rows in _sequences():
        slot_limit = min(conf.MAX_OPEN_TRADES, conf.RISK_CANARY_MAX_OPEN_TRADES)
        assert len(open_rows) <= max(slot_limit, 0)
        for cmp, delivery, pre in history:
            n += 1
            a = cmp.authority
            for d in cmp.disagreements:
                assert d.kind in ca.DISAGREEMENT_KINDS
                assert d.kind != "mirror_refuses_slots_free"          # never stricter
                seen_kinds.add(d.kind)
            for mirror, verdict in ((delivery, "refuse" if delivery.reason_code else "pass"),
                                    (pre, "refuse" if pre.blocked else "pass")):
                unchecked = (not delivery.capacity_checked) if mirror is delivery else not pre.checked
                if unchecked:
                    continue
                agrees = (verdict == "refuse") == (a.slots == ca.SLOTS_FULL)
                recorded = [d for d in cmp.disagreements if d.mirror.startswith(
                    "delivery" if mirror is delivery else "tracker")]
                assert bool(recorded) is (not agrees or a.slots == ca.SLOTS_INVALID)
            if slot_limit <= 0:
                assert not a.admitted and a.reason_code == ca.CODE_RISK_STATE_INVALID
    assert n > 100
    assert {"mirror_admits_slots_full", "mirror_unlimited_authority_invalid",
            "mirror_admits_authority_invalid"} <= seen_kinds


def test_runtime_configuration_delivery_agrees_and_tracker_precheck_is_looser():
    """At canary 2 and MAX_OPEN_TRADES 10 with no ladder, the delivery mirror and the authority
    agree; the tracker pre-check (10) never binds where the authority (2) does (PR-14)."""
    full = 0
    for conf, mode, streak, history, _ in _sequences():
        if (conf.MAX_OPEN_TRADES, conf.RISK_CANARY_MAX_OPEN_TRADES, streak) != (10, 2, 0):
            continue
        for cmp, _, _ in history:
            assert [k for k in kinds(cmp) if k[0] == "delivery_gate"] == []
            if cmp.authority.slots == ca.SLOTS_FULL:
                full += 1
                assert ("tracker_precheck:per_signal", "mirror_admits_slots_full") in kinds(cmp)
    assert full > 0


def test_open_count_read_at_another_moment_is_recorded():
    d = decide(snap(open_count=1))
    cmp = ca.compare_shadow(d, [gate(2)])
    assert kinds(cmp) == [("delivery_gate", "mirror_refuses_slots_free"),
                          ("delivery_gate", "open_count_differs")]


def test_paused_delivery_is_not_compared_on_capacity():
    d = decide(snap(open_count=2, paused=True))
    cmp = ca.compare_shadow(d, [gate(None, paused=True)])
    assert cmp.agree and cmp.compared == () and cmp.notes == ("mirror_not_reached:delivery_gate",)
    assert all(n.split(":")[0] in ca.NOTE_KINDS for n in cmp.notes)
    with pytest.raises(ValueError, match="open_count_required"):
        gate(None)
    with pytest.raises(ValueError, match="precheck_site_unknown"):
        ca.tracker_precheck(0, 10, site="elsewhere")


def test_shadow_record_serialises():
    cmp = ca.compare_shadow(decide(snap(open_count=1, streak=3), working=2), [gate(1), precheck(1)])
    text = fr.canonical_json(cmp.as_dict())
    assert '"mirror_admits_slots_full"' in text and '"capacity_labelled_by_ladder"' in text
    free = ca.compare_shadow(decide(snap(open_count=0, streak=3), working=1), [gate(0), precheck(0)])
    assert free.agree and '"working_orders_uncounted"' in fr.canonical_json(free.as_dict())


@pytest.mark.parametrize("raw", ["legacy_v1", " LEGACY_V1 "])
def test_capacity_mode_legacy_v1_is_the_only_mode(raw):
    assert ca.resolve_capacity_mode(raw) == ca.CAPACITY_MODE_LEGACY_V1


@pytest.mark.parametrize("raw", [None, "", "target_v1", "off", "legacy"])
def test_unknown_capacity_mode_refuses(raw):
    with pytest.raises(ValueError, match="unknown capacity mode"):
        ca.resolve_capacity_mode(raw)


# ── module boundary ──────────────────────────────────────────────────────────

def test_module_is_pure_and_imports_no_service_or_experimental_module():
    tree = ast.parse((ROOT / "shared" / "capacity_authority.py").read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
    assert imports == {"__future__", "math", "types", "dataclasses", "typing",
                       "shared.economic_halt_policy", "shared.risk_management"}
