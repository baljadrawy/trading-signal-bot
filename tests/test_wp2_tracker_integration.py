"""WP2 tracker/telegram integration: before/after parity at every flag default, every flag on and
off, and fail-closed flag parsing.

The BEFORE modules are the service sources at ``wp2_service_fakes.BASE_COMMIT`` (before this
integration), loaded from git. Both modules run the same synthetic scenarios against the same
recording fake database, clock and price feed; their database calls (SQL and arguments, in order),
outbox events and returned decisions must be identical. No network, database or docker.
"""
from __future__ import annotations

import dataclasses
import json
import random
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from shared import accounting_flags as af
from shared import evidence_v2 as ev2
from shared.accounting_flags import AccountingFlags
from shared.config import config
from evidence_v2_fakes import inject_recorder
from wp2_service_fakes import (FIXED_NOW, FakeDB, fixed_datetime, load_after_telegram,
                               load_after_tracker, load_before_telegram, load_before_tracker,
                               patch_many, run)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ALL_SHADOWS = AccountingFlags(ledger_shadow=True, position_state_shadow=True, funnel_recording=True)
RUNTIME = dict(RISK_CAPITAL_USDT=500.0, TRADE_AMOUNT_USDT=50.0, FEE_ROUNDTRIP_PCT=0.3,
               STOP_SLIPPAGE=0.001, MAX_GROSS_EXPOSURE_PERCENT=80.0, MAX_SYMBOL_EXPOSURE_PERCENT=10.0,
               MAX_STRATEGY_EXPOSURE_PERCENT=100.0, MAX_REGIME_EXPOSURE_PERCENT=100.0,
               MAX_DAILY_LOSS_PERCENT=3.0, MAX_WEEKLY_LOSS_PERCENT=6.0, MAX_DRAWDOWN_PERCENT=10.0,
               STOP_ON_CONSECUTIVE_LOSSES=5, RISK_PRICE_FETCH_RETRIES=0, PAPER_TRADING=True,
               SIGNAL_INTEGRITY_MODE="off", PAPER_ENTRY_FILL_MODEL="observed_price_v0",
               MIN_ORDER_NOTIONAL_USDT=5.0, EVIDENCE_V2_ENABLED=False)


@pytest.fixture(scope="module")
def before(tmp_path_factory):
    return load_before_tracker(tmp_path_factory.mktemp("before_tracker"))


@pytest.fixture(scope="module")
def after():
    return load_after_tracker()


@pytest.fixture(autouse=True)
def _runtime(monkeypatch, after):
    for name, value in RUNTIME.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(after, "WP2_FLAGS", af.LEGACY_FLAGS)
    monkeypatch.setattr(after, "_FUNNEL", None)
    ev2.reset_for_tests()
    yield
    ev2.reset_for_tests()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=repr)


class Events:
    """The in-memory evidence-v2 store of one service: ``.events`` flushes and parses it."""

    def __init__(self, service, monkeypatch):
        self.rec, self.sink = inject_recorder(monkeypatch, service)

    @property
    def events(self) -> list:
        self.rec.flush_now()
        return self.sink.records()

    def clear(self) -> None:
        self.rec.flush_now()
        self.sink.lines.clear()


def set_flags(monkeypatch, after, flags):
    """Flags on the AFTER module; the funnel needs the evidence store (in memory here)."""
    store = Events("trade_tracker", monkeypatch)
    monkeypatch.setattr(after, "WP2_FLAGS", flags)
    monkeypatch.setattr(after, "_FUNNEL", after.funnel_service("trade_tracker")
                        if flags.funnel_recording else None)
    return store


# ── fake world ─────────────────────────────────────────────────────────────────────────────

def risk_world(seed: int) -> dict:
    rng = random.Random(seed)
    results = []
    for i in range(rng.randint(0, 8)):
        days = rng.choice([0, 0, 1, 3, 9])
        results.append({"profit_usdt": round(rng.uniform(-3, 3), 4),
                        "result": "WIN", "exit_time": (FIXED_NOW - timedelta(days=days, minutes=i))
                        .replace(tzinfo=None) if rng.random() < 0.5
                        else FIXED_NOW - timedelta(days=days, minutes=i)})
    results.sort(key=lambda r: r["exit_time"].replace(tzinfo=None))
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    open_trades = [{"symbol": s, "entry_price": round(rng.uniform(5, 50), 4),
                    "trade_type": rng.choice(["momentum", "reversion", None]),
                    "regime": rng.choice(["flat", "up", None])}
                   for s in rng.sample(symbols, rng.randint(0, 3))]
    prices = {t["symbol"]: (None if rng.random() < 0.1 else round(t["entry_price"] * rng.uniform(.9, 1.1), 6))
              for t in open_trades}
    return {"results": results, "open": open_trades, "prices": prices,
            "paused": rng.random() < 0.15, "mode": rng.choice(["enforce", "observe"]),
            "max_open": rng.choice([10, 2, 1, 0]), "canary": rng.choice([2, 3, 1]),
            "streak": rng.choice([5, 2, 3]), "symbol": rng.choice(symbols),
            "trade_type": rng.choice(["momentum", "reversion", None]),
            "regime": rng.choice(["flat", "up", None])}


def risk_rules(w):
    return [("fetch", "FROM trade_results", w["results"]),
            ("fetch", "FROM active_trades at\n", w["open"])]


def wire(monkeypatch, modules, w, db, outbox):
    async def price(symbol):
        return w["prices"].get(symbol, 100.0)

    async def enqueue(conn, event_type, aggregate_type, aggregate_id, payload):
        db.log.append(("enqueue", event_type, (aggregate_type, aggregate_id, canon(payload))))
        outbox.append(event_type)
        return 1

    async def risk_start(*a, **k):
        return FIXED_NOW - timedelta(days=30)

    patch_many(monkeypatch, modules, Database=db, get_current_price=price, enqueue=enqueue,
               effective_risk_start=risk_start,
               get_pause_state=AsyncMock(return_value=(w["paused"], "manual_pause" if w["paused"] else None)),
               datetime=fixed_datetime())
    for name, value in (("PAPER_ECONOMIC_HALT_MODE", w["mode"]), ("MAX_OPEN_TRADES", w["max_open"]),
                        ("RISK_CANARY_MAX_OPEN_TRADES", w["canary"]),
                        ("STOP_ON_CONSECUTIVE_LOSSES", w["streak"])):
        monkeypatch.setattr(config, name, value)


def assess(module, monkeypatch, w):
    db, outbox = FakeDB(risk_rules(w)), []
    wire(monkeypatch, [module], w, db, outbox)
    decision = run(module.assess_new_trade_risk(w["symbol"], trade_type=w["trade_type"],
                                                regime=w["regime"]))
    return canon({"type": type(decision).__name__, "decision": dataclasses.asdict(decision),
                  "db": db.log})


# ── 1. capacity + cost booking in the admission snapshot ──────────────────────────────────

@pytest.mark.parametrize("seed", range(160))
def test_assess_new_trade_risk_is_byte_identical(seed, before, after, monkeypatch):
    w = risk_world(seed)
    ref = assess(before, monkeypatch, w)
    assert assess(after, monkeypatch, w) == ref
    set_flags(monkeypatch, after, dataclasses.replace(
        ALL_SHADOWS, cost_label_policy=af.SINGLE_COUNT_LABEL_POLICY,
        break_even_policy=af.SINGLE_COUNT_BREAK_EVEN))
    assert assess(after, monkeypatch, w) == ref        # no flag reaches the risk-guard input (SE-11)


def test_assessment_returns_the_policy_object_and_keeps_the_authority(after, monkeypatch):
    w = risk_world(3)
    w.update(paused=False, open=[], results=[], max_open=10, canary=2)
    wire(monkeypatch, [after], w, FakeDB(risk_rules(w)), [])
    seen = []
    real = after.evaluate_with_policy

    def spy(*a):
        seen.append(real(*a))
        return seen[-1]
    monkeypatch.setattr(after, "evaluate_with_policy", spy)
    d = run(after.assess_new_trade_risk("AAAUSDT"))
    assert d is seen[0] and len(seen) == 1                       # policy called once, object returned
    authority = after._last_capacity_decision(d)
    assert authority is not None and authority.risk_decision is d and authority.admitted


def test_attribution_failure_never_changes_the_decision(after, monkeypatch):
    w = risk_world(4)
    wire(monkeypatch, [after], w, FakeDB(risk_rules(w)), [])
    odd = type("Odd", (), {"allowed": True, "reason": "made_up", "daily_pnl_pct": 0.0})()
    monkeypatch.setattr(after, "evaluate_with_policy", lambda *a: odd)
    assert run(after.assess_new_trade_risk("AAAUSDT")) is odd
    assert after._last_capacity_decision(odd) is None


def test_tracker_source_keeps_the_capacity_guards(after):
    import inspect
    src = inspect.getsource(after)
    assert "size_multiplier" not in src and "max_positions" not in src
    assert "capacity.legacy_risk_limits(config)" in src
    assert src.count("capacity.tracker_precheck(") == 2


# ── 2. admission loop (pre-checks, F7 records) ─────────────────────────────────────────────

def signal(i, *, price_case, trade_type="reversion"):
    entry = 10.0 + i
    return {"id": 100 + i, "symbol": f"S{i}USDT", "entry_price": entry, "target_1": entry * 1.02,
            "target_2": entry * 1.04, "target_3": entry * 1.06, "stop_loss": entry * 0.97,
            "timeframe": "4h", "is_paper_trade": True, "trade_type": trade_type,
            "features_snapshot": json.dumps({"stop_invalidation": entry * 0.975,
                                             "setup_identity": {"key": f"k{i}",
                                                                "candle_close_time_ms": 1_700_000_000_000}}),
            "_price_case": price_case}


NO_GAIN = 0.0
T1_TRANCHE_GAIN = 0.25 * 50 * (102.0 / 100.0 - 1)          # the T1 tranche of a 50 USDT trade
PRICE = {"fill": 0.995, "wait": 1.01, "reject": 0.9, "none": None}


def admission_world(seed: int) -> dict:
    rng = random.Random(1000 + seed)
    w = risk_world(seed)
    w["paused"] = rng.random() < 0.1
    if rng.random() < 0.7:                                   # a book that admits: few, small results
        w["open"], w["results"] = w["open"][:1], w["results"][:2]
        w["prices"] = {t["symbol"]: t["entry_price"] for t in w["open"]}
        w["max_open"], w["canary"] = rng.choice([10, 3]), rng.choice([2, 3])
    cases = ["fill", "fill", "fill", "wait", "reject", "none"]
    sigs = [signal(i, price_case=rng.choice(cases), trade_type=rng.choice(["momentum", "reversion"]))
            for i in range(rng.randint(0, 4))]
    w["signals"] = sigs
    for s in sigs:
        f = PRICE[s["_price_case"]]
        w["prices"][s["symbol"]] = None if f is None else round(s["entry_price"] * f, 6)
    w["counts"] = [rng.choice([0, 0, 0, 1, 2, 11]) for _ in range(len(sigs) + 1)]
    w["inserted"] = [rng.choice([900 + i, None]) for i in range(len(sigs))]
    w["streak_halt"] = rng.random() < 0.2
    return w


def admit(module, monkeypatch, w):
    counts, inserted = iter(w["counts"]), iter(w["inserted"])
    rows = [{k: v for k, v in s.items() if not k.startswith("_")} for s in w["signals"]]
    rules = [
        ("fetch", "SELECT DISTINCT ON (s.symbol)", rows),
        ("fetchval", "SELECT COUNT(*) FROM active_trades", lambda *a: next(counts, 0)),
        ("fetchval", "macro_snapshot->>'usdtd_trend', market_condition) FROM signals", "flat"),
        ("fetchval", "SELECT trade_type FROM signals", lambda sid: next(
            (s["trade_type"] for s in w["signals"] if s["id"] == sid), None)),
        ("fetchval", "INSERT INTO active_trades", lambda *a: next(inserted, None)),
        ("fetchval", "INSERT INTO risk_management", 1),
    ] + risk_rules(w)
    db, outbox = FakeDB(rules), []
    wire(monkeypatch, [module], w, db, outbox)
    monkeypatch.setattr(module, "get_min_notional", AsyncMock(return_value=5.0))
    monkeypatch.setattr(module, "loss_streak_halt_active", AsyncMock(return_value=w["streak_halt"]))
    run(module.register_new_signals())
    return canon(db.log)


@pytest.mark.parametrize("seed", range(120))
def test_register_new_signals_is_byte_identical(seed, before, after, monkeypatch):
    w = admission_world(seed)
    ref = admit(before, monkeypatch, w)
    assert admit(after, monkeypatch, w) == ref
    sink = set_flags(monkeypatch, after, ALL_SHADOWS)
    assert admit(after, monkeypatch, w) == ref                   # recording never touches the DB
    cycles = [e for e in sink.events if e["event_type"] == "funnel.cycle"]
    assert len(cycles) == 1 and cycles[0]["payload"]["valid"], cycles


def _funnel_codes(sink):
    return sorted(e["payload"]["reason_code"] for e in sink.events
                  if e["event_type"] == "funnel.rejection")


def test_f7_records_name_the_canonical_codes(after, monkeypatch):
    w = admission_world(0)
    w.update(paused=False, open=[], results=[], max_open=10, canary=2, streak_halt=False, mode="enforce")
    w["signals"] = [signal(0, price_case="none"), signal(1, price_case="reject"),
                    signal(2, price_case="wait"), signal(3, price_case="fill"), signal(4, price_case="fill")]
    for s in w["signals"]:
        f = PRICE[s["_price_case"]]
        w["prices"][s["symbol"]] = None if f is None else round(s["entry_price"] * f, 6)
    w["counts"] = [0, 0, 0, 0, 0, 10]          # loop entry, then one per signal; the last is full
    w["inserted"] = [None]
    sink = set_flags(monkeypatch, after, ALL_SHADOWS)
    admit(after, monkeypatch, w)
    assert _funnel_codes(sink) == ["F7.already_registered", "F7.capacity_full", "F7.entry_rejected",
                                   "F7.no_price"]
    env = [e for e in sink.events if e["event_type"] == "funnel.cycle"][0]["payload"]
    assert env["valid"] and env["report"]["stage_counts"] == [
        {"stage": "F7", "n_in": 5, "passed": 0, "held": 1, "expanded_from": None}]


def test_f7_risk_refusal_uses_the_authority_code(after, monkeypatch):
    w = admission_world(1)
    w.update(paused=True, open=[], results=[], max_open=10, canary=2, streak_halt=False)
    w["signals"] = [signal(0, price_case="fill")]
    w["prices"]["S0USDT"] = round(10.0 * 0.995, 6)
    w["counts"] = [0, 0]
    sink = set_flags(monkeypatch, after, ALL_SHADOWS)
    admit(after, monkeypatch, w)
    assert _funnel_codes(sink) == ["F7.paused"]


def test_loop_entry_capacity_is_a_cycle_record_of_zero_subjects(after, monkeypatch):
    w = admission_world(2)
    w.update(max_open=2, canary=2)
    w["counts"] = [2]
    sink = set_flags(monkeypatch, after, ALL_SHADOWS)
    admit(after, monkeypatch, w)
    recs = [e["payload"] for e in sink.events if e["event_type"] == "funnel.rejection"]
    assert [(r["scope"], r["reason_code"], r["detail"]["subject_count"]) for r in recs] == [
        ("cycle", "F7.capacity_full", 0)]


def test_funnel_off_builds_nothing(after, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("funnel touched while FUNNEL_RECORDING=off")
    monkeypatch.setattr(after.TrackerAdmissionFunnel, "begin", boom)
    w = admission_world(5)
    admit(after, monkeypatch, w)


# ── 3. exits and the close (cost booking, shadows) ─────────────────────────────────────────

def trade_row(seed: int) -> tuple:
    rng = random.Random(5000 + seed)
    entry = 100.0
    highest = rng.choice([0, 0, 1, 2])
    policy = rng.choice(["partial_25_50_25_v1", "partial_25_50_25_v1", None])
    min_notional = rng.choice([5.0, 5.0, 20.0])
    dist = {1: 0.25, 2: 0.5, 3: 0.25}
    if min_notional == 20.0:
        dist = {1: 0.0, 2: 1.0, 3: 0.0}
    sold = sum(dist[t] for t in range(1, highest + 1)) if policy else 0.0
    targets = {1: 102.0, 2: 104.0, 3: 106.0}
    fills = [{"fill_price": targets[t], "quantity_fraction": dist[t]}
             for t in range(1, highest + 1) if policy and dist[t] > 0]
    trade = {"id": 40 + seed, "signal_id": 700 + seed, "symbol": "TTTUSDT", "entry_price": entry,
             "target_1": 102.0, "target_2": 104.0, "target_3": 106.0, "stop_loss": 97.0,
             "stop_invalidation": rng.choice([None, 97.5]), "timeframe": "4h",
             "highest_target_hit": highest, "remaining_fraction": 1.0 - sold,
             "realized_profit_percent": sum((targets[t] / entry - 1) * 100 * dist[t]
                                            for t in range(1, highest + 1)) if policy else 0.0,
             "realized_profit_usdt": sum((targets[t] / entry - 1) * 50 * dist[t]
                                         for t in range(1, highest + 1)) if policy else 0.0,
             "peak_price": rng.choice([None, 103.0, 105.0]) if highest else rng.choice([None, 101.0]),
             "opened_at": (FIXED_NOW - timedelta(hours=rng.choice([1, 13, 30, 60, 130]))).replace(tzinfo=None),
             "exit_policy_version": policy, "min_order_notional_usdt": min_notional,
             "expiry_h": 96.0, "t1_expiry_h": 48.0, "no_t1_expiry_h": 24.0}
    price = rng.choice([95.0, 99.0, 100.2, 100.35, 101.0, 102.5, 104.5, 106.5, 103.0])
    return trade, fills, price


def exit_rules(trade, fills, w):
    """The tracker's own writes update the fake row and fills, as the database would."""
    row, fills = dict(trade), list(fills)

    def update(highest, sold, pct, usdt, _tid):
        row.update(highest_target_hit=highest,
                   remaining_fraction=max(0.0, float(row["remaining_fraction"]) - sold),
                   realized_profit_percent=row["realized_profit_percent"] + pct,
                   realized_profit_usdt=row["realized_profit_usdt"] + usdt)

    def add_fill(_tid, _sid, _sym, _target, price, fraction, *rest):
        fills.append({"fill_price": price, "quantity_fraction": fraction})

    return [
        ("execute", "SET\n                        highest_target_hit=$1", update),
        ("execute", "INSERT INTO trade_target_fills", add_fill),
        ("fetchrow", "SELECT * FROM active_trades WHERE id=$1", lambda *a: dict(row)),
        ("fetch", "FROM trade_target_fills", lambda *a: list(fills)),
        ("fetchval", "INSERT INTO trade_results", 555),
        ("fetchval", "INSERT INTO risk_management", 1),
    ] + risk_rules(w)


def evaluate(module, monkeypatch, seed):
    trade, fills, price = trade_row(seed)
    w = risk_world(seed)
    db, outbox = FakeDB(exit_rules(trade, fills, w)), []
    wire(monkeypatch, [module], w, db, outbox)
    module._closing.clear()
    run(module.evaluate_trade(dict(trade), price))
    return db


@pytest.mark.parametrize("seed", range(200))
def test_evaluate_and_close_are_byte_identical(seed, before, after, monkeypatch):
    ref = canon(evaluate(before, monkeypatch, seed).log)
    assert canon(evaluate(after, monkeypatch, seed).log) == ref
    set_flags(monkeypatch, after, ALL_SHADOWS)
    assert canon(evaluate(after, monkeypatch, seed).log) == ref


def _result_insert(log):
    rows = [entry for entry in log if entry[0] == "fetchval" and "INSERT INTO trade_results" in entry[1]]
    return rows[0][2] if rows else None


@pytest.mark.parametrize("seed", range(200))
def test_single_count_label_policy_changes_only_the_economic_fields(seed, before, after, monkeypatch):
    ref = evaluate(before, monkeypatch, seed).log
    set_flags(monkeypatch, after, AccountingFlags(cost_label_policy=af.SINGLE_COUNT_LABEL_POLICY))
    got = evaluate(after, monkeypatch, seed).log
    a, b = _result_insert(ref), _result_insert(got)
    assert (a is None) == (b is None)
    if a is None:
        assert canon(got) == canon(ref)
        return
    assert a[:11] == b[:11]                                  # legacy columns byte-identical
    assert b[14] == af.SINGLE_COUNT_LABEL_POLICY and a[14] == "net_after_modeled_cost_v1"
    assert b[11] <= a[11]                                    # slippage booked once, never added
    strip = [e for e in got if e is not None and "INSERT INTO trade_results" not in e[1]]
    assert canon(strip) == canon([e for e in ref if "INSERT INTO trade_results" not in e[1]])


def test_single_count_full_stop_exit_charges_fee_per_side_and_slippage_once(after, monkeypatch):
    trade, fills, _ = trade_row(0)
    trade.update(highest_target_hit=0, remaining_fraction=1.0, realized_profit_percent=0.0,
                 realized_profit_usdt=NO_GAIN, exit_policy_version="partial_25_50_25_v1",
                 opened_at=(FIXED_NOW - timedelta(hours=1)).replace(tzinfo=None))
    w = risk_world(0)
    set_flags(monkeypatch, after, AccountingFlags(cost_label_policy=af.SINGLE_COUNT_LABEL_POLICY))
    db = FakeDB(exit_rules(trade, [], w))
    wire(monkeypatch, [after], w, db, [])
    run(after.evaluate_trade(dict(trade), 96.0))
    row = _result_insert(db.log)
    fill = 96.0 * (1 - 0.001)    # stop reference min(stop, observation); slippage in price, once
    assert row[3] == pytest.approx(fill)
    assert row[11] == pytest.approx(0.001 * (50 + 50 * fill / 100), abs=1e-6)


def test_break_even_flag_moves_only_the_post_t1_stop(before, after, monkeypatch):
    trade, _, _ = trade_row(1)
    trade.update(highest_target_hit=1, remaining_fraction=0.75, exit_policy_version="partial_25_50_25_v1",
                 realized_profit_percent=0.5, realized_profit_usdt=T1_TRANCHE_GAIN, peak_price=102.0,
                 min_order_notional_usdt=5.0,
                 opened_at=(FIXED_NOW - timedelta(hours=2)).replace(tzinfo=None))
    fills = [{"fill_price": 102.0, "quantity_fraction": 0.25}]
    w = risk_world(1)

    def go(module):
        db = FakeDB(exit_rules(trade, fills, w))
        wire(monkeypatch, [module], w, db, [])
        module._closing.clear()
        run(module.evaluate_trade(dict(trade), 100.35))
        return db.log
    legacy = go(before)
    assert _result_insert(legacy)[10] is False and "break_even" in _result_insert(legacy)[7]
    assert canon(go(after)) == canon(legacy)
    set_flags(monkeypatch, after, AccountingFlags(break_even_policy=af.SINGLE_COUNT_BREAK_EVEN))
    assert _result_insert(go(after)) is None                 # 100.35 is above the single-count level
    from shared.cost_label_policy import barrier_cost_kwargs, bound_costs
    from shared.triple_barrier import TripleBarrierConfig
    kw = barrier_cost_kwargs(bound_costs(config), af.SINGLE_COUNT_BREAK_EVEN)
    level = TripleBarrierConfig("X", 100.0, 102.0, 104.0, 106.0, 97.0, **kw).net_break_even_stop()
    assert level == pytest.approx(100.0 * 1.001 / ((1 - 0.001) * (1 - 0.001)))


def test_shadows_record_without_changing_anything(after, monkeypatch):
    sink = set_flags(monkeypatch, after, AccountingFlags(ledger_shadow=True, position_state_shadow=True))
    seen = {"ledger": 0, "position": 0}
    for seed in range(200):
        evaluate(after, monkeypatch, seed)
    for e in sink.events:
        if e["event_type"] == "ledger.reconciliation":
            seen["ledger"] += 1
            assert e["payload"]["ok"], e["payload"]
        if e["event_type"] == "position_state.shadow":
            seen["position"] += 1
            for refusal in e["payload"]["refusals"]:          # only the documented merge difference
                row, _, _ = trade_row(e["payload"]["trade_id"] - 40)
                assert refusal["reason"] == "close_with_no_open_quantity", e["payload"]
                assert row["min_order_notional_usdt"] == 20.0
    assert seen["ledger"] > 20 and seen["position"] > 20
    assert after.WP2_SHADOW_STATS["ledger_mismatches"] == 0


def test_shadows_off_make_zero_calls(after, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("shadow called while its flag is off")
    for mod, names in ((after.ledger_legacy_adapter, ("reconcile",)),
                       (after.position_state_shadow, ("validate_target_hits", "validate_close"))):
        for name in names:
            monkeypatch.setattr(mod, name, boom)
    monkeypatch.setattr(after, "_shadow_emit", boom)
    for seed in range(60):
        evaluate(after, monkeypatch, seed)


# ── 4. telegram delivery gate ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tg_before(tmp_path_factory):
    return load_before_telegram(tmp_path_factory.mktemp("before_telegram"))


@pytest.fixture(scope="module")
def tg_after():
    return load_after_telegram()


GRID = [(p, r, f, m, c) for p in (False, True) for r in (None, "manual_pause", "risk_state_missing")
        for f in (None, 0, 1, 2, 3) for m in (10, 2, 1, 0, -1) for c in (2, 1, 0, 3)]


def gate(module, monkeypatch, case):
    paused, reason, fetched, m, c = case
    db = FakeDB([("fetchval", "COUNT(*)", fetched), ("fetchrow", "service_heartbeats", None)])
    monkeypatch.setattr(module, "Database", db)
    monkeypatch.setattr(module, "get_pause_state", AsyncMock(return_value=(paused, reason)))
    monkeypatch.setattr(config, "MAX_OPEN_TRADES", m)
    monkeypatch.setattr(config, "RISK_CANARY_MAX_OPEN_TRADES", c)
    return canon({"out": run(module.can_deliver_candidate()), "db": db.log})


def test_delivery_gate_is_byte_identical(tg_before, tg_after, monkeypatch):
    for case in GRID:
        assert gate(tg_after, monkeypatch, case) == gate(tg_before, monkeypatch, case), case
    monkeypatch.setattr(tg_after, "_FUNNEL", object())                 # recording on: same answers
    for case in GRID:
        assert gate(tg_after, monkeypatch, case) == gate(tg_before, monkeypatch, case), case


def test_delivery_refusal_is_an_f7_record(tg_after, monkeypatch):
    sink = Events("telegram", monkeypatch)
    monkeypatch.setattr(tg_after, "_FUNNEL", tg_after.funnel_service("telegram"))
    sig = {"id": 9, "symbol": "DDDUSDT", "timeframe": "4h", "trade_type": "momentum",
           "telegram_sent": False, "decision_source": "policy_ready", "features_snapshot": None}
    for paused, count, code in ((True, 0, "F7.paused"), (False, 2, "F7.capacity_full")):
        sink.clear()
        db = FakeDB([("fetchrow", "FROM signals WHERE id", sig), ("fetchval", "COUNT(*)", count),
                     ("fetchrow", "service_heartbeats", None)])
        monkeypatch.setattr(tg_after, "Database", db)
        monkeypatch.setattr(tg_after, "get_pause_state", AsyncMock(return_value=(paused, "manual_pause")))
        monkeypatch.setattr(tg_after, "ack", AsyncMock())
        monkeypatch.setattr(config, "MAX_OPEN_TRADES", 10)
        monkeypatch.setattr(config, "RISK_CANARY_MAX_OPEN_TRADES", 2)
        from shared.signal_readiness import SIGNAL_READY_EVENT
        ok = run(tg_after.handle_candidate_event(None, None, "o", SIGNAL_READY_EVENT,
                                                 {"id": 1, "aggregate_id": 9}))
        assert ok is False
        assert _funnel_codes(sink) == [code]
        env = [e for e in sink.events if e["event_type"] == "funnel.cycle"][0]["payload"]
        assert env["valid"]


def test_telegram_funnel_flag_fails_closed(tg_after, monkeypatch):
    with pytest.raises(RuntimeError):
        tg_after.configure_funnel({"FUNNEL_RECORDING": "maybe"})
    assert tg_after.configure_funnel({}) is False


# ── 5. fail-closed start-up ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env", [
    {"PAPER_COST_LABEL_POLICY": "research_baseline_v1"}, {"PAPER_COST_LABEL_POLICY": ""},
    {"PAPER_BREAK_EVEN_POLICY": "research_stress_v1"}, {"LEDGER_SHADOW": "1"},
    {"POSITION_STATE_SHADOW": "enforce"}, {"FUNNEL_RECORDING": "true"},
    {"FUNNEL_RECORDING": "on"},                         # on needs the evidence-v2 store
])
def test_unknown_flag_values_refuse_to_start(env, after):
    with pytest.raises(RuntimeError):
        after.configure_wp2(env)
    assert after.WP2_FLAGS == af.LEGACY_FLAGS


def test_single_count_flags_refuse_a_non_default_cost_basis(after, monkeypatch):
    monkeypatch.setattr(config, "FEE_ROUNDTRIP_PCT", 0.4)
    after.configure_wp2({})                                         # legacy accepts any valid cost
    for env in ({"PAPER_COST_LABEL_POLICY": "net_single_count_legacy_v1"},
                {"PAPER_BREAK_EVEN_POLICY": "single_count_legacy_v1"}):
        with pytest.raises(RuntimeError):
            after.configure_wp2(env)


@pytest.mark.parametrize("name,value", [("TRADE_AMOUNT_USDT", 0.0), ("STOP_SLIPPAGE", 1.0),
                                        ("FEE_ROUNDTRIP_PCT", -0.1), ("FEE_ROUNDTRIP_PCT", float("nan"))])
def test_invalid_cost_config_refuses_to_start(name, value, after, monkeypatch):
    monkeypatch.setattr(config, name, value)
    with pytest.raises(ValueError):
        after.configure_wp2({})


def test_all_flags_resolve(after, monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_V2_ENABLED", True)
    flags = after.configure_wp2({"PAPER_COST_LABEL_POLICY": " NET_SINGLE_COUNT_LEGACY_V1 ",
                                 "PAPER_BREAK_EVEN_POLICY": "single_count_legacy_v1",
                                 "LEDGER_SHADOW": "on", "POSITION_STATE_SHADOW": "On",
                                 "FUNNEL_RECORDING": "on"})
    assert flags == AccountingFlags(af.SINGLE_COUNT_LABEL_POLICY, af.SINGLE_COUNT_BREAK_EVEN,
                                    True, True, True)
    assert after._FUNNEL is not None
