"""A43: signal identity, failure safety, selection integrity and diagnostics.

Deterministic synthetic sequences only. They demonstrate engineering
properties (identity, idempotency, determinism, parity); they say nothing
about market profitability. No database, market data or outcome is read.
"""
import asyncio
import json
import math
import random
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'signal_engine')

import pytest

import signal_logic
from shared import evidence_v2
from shared.candidate_diagnostics import FIELDS, build_record, deserialize, serialize, validate_record
from shared.candidate_selection import (EligibilityPolicy, bounded_universe, eligibility_reasons,
                                        execution_quality_v2_key, normalize, production_parity_key,
                                        production_query_window, select)
from shared.config import config
from shared.database import Database
from shared.dependency_safety import (DEPENDENCIES, Criticality, ReadOutcome, classify_error,
                                      cycle_gate, guarded_read)
from shared.signal_identity import (EmissionLedger, IdentityError, bracket_hash, freshness,
                                    identity_from_candidate, integrity_check)
from shared.signal_quality import CorrelatedExposurePolicy, Exposure

DAY = 86_400_000
T0 = 20_720 * DAY                     # aligned to 1d, 4h and 15m
TF_MS = {"15m": 900_000, "4h": 14_400_000, "1d": DAY}
SV = "sb-2026.08"


def cand(symbol="AAAUSDT", tf="4h", candle_open=T0, tt="momentum", spread=0.01, entry=100.0,
         policy="fixed_execution_quality_v1", **extra):
    d = {"symbol": symbol, "timeframe": tf, "trade_type": tt, "selection_policy": policy,
         "order_book": {"valid": True, "spread_pct": spread},
         "entry_price": entry, "stop_loss": entry * 0.98, "target_1": entry * 1.02,
         "target_2": entry * 1.036, "target_3": entry * 1.044, "atr": entry * 0.01,
         "stop_policy": "momentum_breakout", "stop_valid": True,
         "pit": {"candle_open_time_ms": candle_open,
                 "candle_close_time_ms": None if candle_open is None else candle_open + TF_MS[tf] - 1}}
    d.update(extra)
    return d


def last_closed_open(t_ms, tf):
    step = TF_MS[tf]
    return (t_ms // step) * step - step


# ── A43-B: identity, freshness, duplicates ─────────────────────────────────

def _simulate(tf, hours, *, integrity):
    """Engine cycles every 60 s; analysis refreshed every 5 min and read up to 30 min old.

    Production model: emit unless the symbol emitted in the last 2 h (cooldown).
    A43 model: emit only a fresh, never-emitted setup key."""
    ledger, last_emit, per_candle, stale = EmissionLedger(), None, {}, 0
    for minute in range(0, hours * 60):
        now = T0 + 10 * DAY + minute * 60_000
        analysed = now - (minute % 30) * 60_000           # worst case inside the 30-min window
        row = cand(tf=tf, candle_open=last_closed_open(analysed, tf))
        if integrity:
            v = integrity_check(row, decision_ms=now, strategy_version=SV, emitted_keys=ledger.snapshot())
            if not v.eligible:
                continue
            ledger.claim_sync(identity_from_candidate(row, strategy_version=SV), bracket_hash(row))
        else:
            if last_emit is not None and now - last_emit < 2 * 3_600_000:
                continue
            last_emit = now
        key = row["pit"]["candle_open_time_ms"]
        per_candle[key] = per_candle.get(key, 0) + 1
        if now - (key + TF_MS[tf]) >= TF_MS[tf]:
            stale += 1
    return per_candle, stale


@pytest.mark.parametrize("tf", ["4h", "1d"])
def test_same_candle_evaluated_repeatedly(tf):                         # scenarios 1, 2, 10
    prod, prod_stale = _simulate(tf, 72, integrity=False)
    a43, a43_stale = _simulate(tf, 72, integrity=True)
    assert max(prod.values()) >= 2                    # production re-emits one candle
    assert set(a43.values()) == {1} and a43_stale == 0                # once per candle, never superseded


def test_15m_has_no_repeat_under_either_model():
    prod, _ = _simulate("15m", 24, integrity=False)
    a43, _ = _simulate("15m", 24, integrity=True)
    assert set(prod.values()) == {1} and set(a43.values()) == {1}


def test_new_candle_with_identical_bracket_is_a_new_setup():           # scenario 3
    a, b = cand(candle_open=T0), cand(candle_open=T0 + TF_MS["4h"])
    assert bracket_hash(a) == bracket_hash(b)
    ia, ib = (identity_from_candidate(x, strategy_version=SV) for x in (a, b))
    assert ia.key != ib.key
    led = EmissionLedger()
    assert [led.claim_sync(i, bracket_hash(a)).status for i in (ia, ib)] == ["claimed", "claimed"]


def test_distinct_setups_on_one_candle_do_not_block_each_other():      # scenario 4
    keys = {identity_from_candidate(c, strategy_version=SV).key for c in (
        cand(tt="momentum"), cand(tt="reversion"), cand(tf="1d"), cand(symbol="BBBUSDT"),
        cand(policy="fixed_execution_quality_v2"))}
    assert len(keys) == 5


def test_restart_before_reevaluation_still_detects_duplicate():         # scenario 5
    c = cand()
    ident = identity_from_candidate(c, strategy_version=SV)
    before = EmissionLedger()
    assert before.claim_sync(ident, bracket_hash(c)).status == "claimed"
    after = EmissionLedger.restore(before.snapshot())                  # new process, persisted keys
    assert after.claim_sync(ident, bracket_hash(c)).status == "duplicate"


def test_concurrent_selection_workers_claim_once():                    # scenario 6
    c = cand()
    ident, bh = identity_from_candidate(c, strategy_version=SV), bracket_hash(c)

    async def race():
        led = EmissionLedger()
        return await asyncio.gather(*[led.claim(ident, bh) for _ in range(25)])
    statuses = [r.status for r in asyncio.run(race())]
    assert statuses.count("claimed") == 1 and statuses.count("duplicate") == 24


def test_duplicate_persistence_attempt_and_bracket_conflict():         # scenario 16
    c = cand()
    ident = identity_from_candidate(c, strategy_version=SV)
    led = EmissionLedger()
    led.claim_sync(ident, bracket_hash(c))
    assert led.claim_sync(ident, bracket_hash(c)).status == "duplicate"
    assert led.claim_sync(ident, bracket_hash({**c, "stop_loss": 97.5})).status == "conflict"


@pytest.mark.parametrize("pit,error", [
    ({}, "candle_open_time_missing"),
    ({"candle_open_time_ms": T0}, "candle_close_time_missing"),
    ({"candle_open_time_ms": "abc", "candle_close_time_ms": T0}, "candle_open_time_malformed"),
    ({"candle_open_time_ms": True, "candle_close_time_ms": T0}, "candle_open_time_malformed"),
    ({"candle_open_time_ms": T0 + 1, "candle_close_time_ms": T0 + TF_MS["4h"]}, "candle_open_not_aligned"),
    ({"candle_open_time_ms": T0, "candle_close_time_ms": T0 + TF_MS["4h"]}, "candle_close_inconsistent"),
])
def test_missing_or_malformed_candle_timestamp_fails_closed(pit, error):   # scenario 9
    c = {**cand(), "pit": pit}
    with pytest.raises(IdentityError, match=error):
        identity_from_candidate(c, strategy_version=SV)
    assert integrity_check(c, decision_ms=T0 + DAY, strategy_version=SV).reasons == (f"identity:{error}",)
    assert identity_from_candidate({**cand(), "pit": {"candle_open_time_ms": str(T0),
                                    "candle_close_time_ms": float(T0 + TF_MS['4h'] - 1)}},
                                   strategy_version=SV).candle_open_ms == T0


def test_stale_market_data_and_the_observed_244_minute_case():         # scenario 10
    ident = identity_from_candidate(cand(), strategy_version=SV)
    end = ident.candle_end_ms
    assert freshness(ident, end + 60_000).admissible
    assert freshness(ident, end + 244.6 * 60_000).reason == "superseded_by_newer_candle"
    assert freshness(ident, end - 1).reason == "decision_before_candle_close"
    assert freshness(ident, end + 30 * 60_000, max_age_bars=0.1).reason == "superseded_by_newer_candle"
    with pytest.raises(ValueError):
        freshness(ident, end, max_age_bars=2)


def test_strategy_version_change_creates_a_new_identity():             # scenario 19
    c = cand()
    k1 = identity_from_candidate(c, strategy_version="sb-2026.08").key
    k2 = identity_from_candidate(c, strategy_version="sb-2026.09").key
    assert k1 != k2 and k1 == identity_from_candidate(dict(c), strategy_version="sb-2026.08").key
    cid = evidence_v2.candle_id("AAAUSDT", "4h", T0)                   # existing P1 lineage differs too
    assert evidence_v2.candidate_id(cid, "momentum", "sb-2026.08") != \
        evidence_v2.candidate_id(cid, "momentum", "sb-2026.09")
    with pytest.raises(IdentityError, match="strategy_version_missing"):
        identity_from_candidate(c, strategy_version="")


# ── A43-C: failure safety ──────────────────────────────────────────────────

class FakeMacro:
    async def should_block_now(self): return False
    def macro_state_key(self): return "usdtd_flat"
    def snapshot(self): return {}
    def state(self): return {}


def _engine(monkeypatch, fetch, volumes=None):
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", False)
    monkeypatch.setattr(config, "LEARNING_GATES_ENABLED", False)
    monkeypatch.setattr(Database, "fetch", fetch)
    engine = signal_logic.SignalEngine()

    async def volume(symbol):
        return (volumes or {}).get(symbol)
    monkeypatch.setattr(engine, "_get_volume_usdt", volume)
    return engine


def _row(c):
    return {"symbol": c["symbol"], "timeframe": c["timeframe"], "analysis_data": c}


def test_production_cooldown_fails_open_on_db_error(monkeypatch):      # scenario 7 (current code)
    async def fetch(sql, *a):
        if "INTERVAL '2 hours'" in sql:
            raise asyncio.TimeoutError()
        return []                                     # no open trades
    engine = _engine(monkeypatch, fetch)
    assert asyncio.run(engine._get_symbol_cooldown_set()) == set()     # error → "no cooldown"
    out = asyncio.run(engine.find_best_signal_live([_row(cand())], FakeMacro()))
    assert out is not None                            # a signal is emitted with cooldown unverified


def test_production_open_position_error_aborts_cycle(monkeypatch):     # scenario 8 (current code)
    async def fetch(sql, *a):
        if "active_trades" in sql:
            raise ConnectionResetError("db gone")
        return []
    engine = _engine(monkeypatch, fetch)
    with pytest.raises(ConnectionResetError):
        asyncio.run(engine.find_best_signal_live([_row(cand())], FakeMacro()))


def test_guarded_reads_block_new_exposure_on_safety_timeouts():        # scenarios 7, 8 (A43)
    async def slow():
        await asyncio.sleep(1)

    async def ok():
        return {"BTCUSDT"}

    async def run():
        sleeps = []

        async def fake_sleep(s):
            sleeps.append(s)
        cd = await guarded_read("symbol_cooldown", slow, timeout_s=0.01, max_attempts=2,
                                backoff_s=0.05, sleep=fake_sleep)
        op = await guarded_read("open_positions", ok, timeout_s=0.5)
        return cd, op, sleeps
    cd, op, sleeps = asyncio.run(run())
    assert (cd.ok, cd.error_class, cd.attempts) == (False, "timeout", 2) and sleeps == [0.05]
    assert op.ok and op.value == {"BTCUSDT"}
    gate = cycle_gate({"symbol_cooldown": cd, "open_positions": op})
    assert not gate.allow_new_exposure and gate.blocked_by == ("symbol_cooldown",)
    assert gate.reason == "safety_state_unverified:symbol_cooldown"
    assert gate.events[0]["error_class"] == "timeout"


def test_ranking_and_diagnostic_failures_degrade_without_blocking():
    fail = lambda n: ReadOutcome(n, DEPENDENCIES[n], False, error_class="query", attempts=1)
    gate = cycle_gate({"selection_volume": fail("selection_volume"),
                       "truncation_measure": fail("truncation_measure")})
    assert gate.allow_new_exposure and gate.degraded == ("selection_volume",) and gate.blocked_by == ()


def test_retry_policy_is_bounded_and_query_errors_are_not_retried():
    calls = []

    class PostgresError(Exception):
        pass

    async def bad_query():
        calls.append(1)
        raise PostgresError("syntax")

    async def always_down():
        calls.append(1)
        raise ConnectionRefusedError()

    async def run():
        async def nosleep(_): pass
        q = await guarded_read("open_positions", bad_query, max_attempts=5, sleep=nosleep)
        n_q = len(calls)
        c = await guarded_read("open_positions", always_down, max_attempts=3, sleep=nosleep)
        return q, n_q, c
    q, n_q, c = asyncio.run(run())
    assert (q.error_class, q.attempts, n_q) == ("query", 1, 1)
    assert (c.error_class, c.attempts, len(calls)) == ("connection", 3, 4)
    with pytest.raises(ValueError, match="unclassified_dependency"):
        asyncio.run(guarded_read("mystery", always_down))
    with pytest.raises(ValueError, match="invalid_retry_bounds"):
        asyncio.run(guarded_read("open_positions", always_down, max_attempts=50))
    assert classify_error(ValueError()) == "unknown"
    assert DEPENDENCIES["selection_volume"] is Criticality.RANKING


def test_budget_exhaustion_stops_retries():
    t = [0.0]

    async def down():
        t[0] += 3.0
        raise ConnectionError()

    async def run():
        async def nosleep(_): pass
        return await guarded_read("open_positions", down, max_attempts=5, budget_s=5.0,
                                  sleep=nosleep, clock=lambda: t[0])
    out = asyncio.run(run())
    assert not out.ok and out.attempts == 2                            # 3 s + 3 s > 5 s budget


# ── A43-D: candidate selection integrity ───────────────────────────────────

def _universe(n, seed=7, best_symbol=None):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        sym = f"S{i:03d}USDT"
        for tf in ("15m", "4h", "1d"):
            c = cand(symbol=sym, tf=tf, candle_open=last_closed_open(T0 + 30 * DAY, tf),
                     spread=round(rng.uniform(0.02, 0.14), 4), total_score=rng.uniform(0, 8))
            rows.append({"symbol": sym, "timeframe": tf, "analysis_data": c})
    if best_symbol:
        c = cand(symbol=best_symbol, tf="4h", candle_open=last_closed_open(T0 + 30 * DAY, "4h"),
                 spread=0.001, total_score=0.0)
        rows.append({"symbol": best_symbol, "timeframe": "4h", "analysis_data": c})
    return rows


def test_universe_larger_than_200_truncates_alphabetically_in_production():   # scenarios 11, 15
    rows = _universe(120, best_symbol="ZZZUSDT")                       # 361 rows
    window = production_query_window(rows)
    assert len(window) == 200 and max(r["symbol"] for r in window) < "S067USDT"
    assert "ZZZUSDT" not in {r["symbol"] for r in window}
    prod = select([normalize(r) for r in window])
    full = bounded_universe(rows)
    a43 = select([normalize(r) for r in full.rows], ranker="execution_quality_v2")
    assert prod.selected.symbol != "ZZZUSDT" and a43.selected.symbol == "ZZZUSDT"
    assert full.total == 361 and not full.capped
    capped = bounded_universe(rows, max_rows=300)
    assert capped.capped and len(capped.rows) == 300 and len(capped.dropped) == 61
    dropped_syms = sorted(s for s, _ in capped.dropped)
    assert dropped_syms[0] < "S010USDT" and dropped_syms[-1] > "S100USDT"   # spread across the alphabet


def test_selection_is_invariant_to_input_order():                      # scenario 12
    rows = _universe(40)
    base = [normalize(r) for r in rows]
    for ranker in ("production_parity", "execution_quality_v2"):
        picks = set()
        for seed in range(10):
            shuffled = base[:]
            random.Random(seed).shuffle(shuffled)
            r = select(shuffled, ranker=ranker)
            picks.add((r.selected.symbol, r.selected.timeframe))
        assert len(picks) == 1


def test_equal_spread_and_liquidity_ties():                            # scenario 13
    groups, prod_first, v2_first, prod_tf = 300, 0, 0, set()
    for g in range(groups):
        names = sorted(f"G{g:03d}{x}USDT" for x in "ABCD")
        cs = [normalize(cand(symbol=s, spread=0.02)) for s in names]
        prod_first += select(cs).selected.symbol == names[0]
        v2_first += select(cs, ranker="execution_quality_v2").selected.symbol == names[0]
    assert prod_first == groups                                        # production: always alphabetical
    assert 0.15 < v2_first / groups < 0.35                             # v2: ≈ 1/4, no alphabet preference
    multi_tf = [normalize(cand(tf=tf)) for tf in ("4h", "1d", "15m")]
    assert select(multi_tf).selected.timeframe == "15m"                # lexical '15m' < '1d' < '4h'
    picks = {select([normalize(cand(symbol=f"T{i}USDT", tf=tf)) for tf in ("4h", "1d", "15m")],
                    ranker="execution_quality_v2").selected.timeframe for i in range(30)}
    assert picks == {"15m", "1d", "4h"}


def test_invalid_or_missing_liquidity():                               # scenario 14
    a = normalize(cand(symbol="AAAUSDT"), liquidity_usdt=float("nan"))
    b = normalize(cand(symbol="BBBUSDT"), liquidity_usdt=5e6)
    c = normalize(cand(symbol="CCCUSDT"), liquidity_usdt=None)
    d = normalize(cand(symbol="DDDUSDT"), liquidity_usdt=-1)
    assert a.liquidity_usdt is None and d.liquidity_usdt is None
    for order in ([a, b, c, d], [d, c, b, a], [c, a, d, b]):
        assert select(order, ranker="execution_quality_v2").selected.symbol == "BBBUSDT"
    # the production key with a NaN volume: -nan breaks tuple ordering → winner depends on input order
    k = signal_logic.SignalEngine._fixed_candidate_key
    x = {"symbol": "XUSDT", "timeframe": "4h", "order_book": {"spread_pct": 0.02}, "_selection_volume_usdt": float("nan")}
    y = {"symbol": "YUSDT", "timeframe": "4h", "order_book": {"spread_pct": 0.02}, "_selection_volume_usdt": 1e6}
    assert min([x, y], key=k)["symbol"] != min([y, x], key=k)["symbol"]


def test_nan_spread_passes_production_filter(monkeypatch):
    async def fetch(sql, *a): return []
    engine = _engine(monkeypatch, fetch)
    async def no_cd(): return set()
    monkeypatch.setattr(engine, "_get_symbol_cooldown_set", no_cd)
    out = asyncio.run(engine.find_best_signal_live([_row(cand(spread=float("nan")))], FakeMacro()))
    assert out is not None                                             # NaN > 0.15 is False
    c = normalize(cand(spread=float("nan")))
    assert eligibility_reasons(c, EligibilityPolicy()) == ()           # parity
    assert eligibility_reasons(c, EligibilityPolicy(reject_non_finite_spread=True)) == ("spread_invalid",)


def test_live_decision_path_parity(monkeypatch):                       # scenario 20
    """The real find_best_signal_live and select(production_parity) agree on 300 random sets."""
    async def fetch(sql, *a):
        if "active_trades" in sql:
            return [{"symbol": s} for s in fetch.open]
        return []
    fetch.open = set()
    vols = {}
    engine = _engine(monkeypatch, fetch, vols)
    rng = random.Random(43)
    agree = 0
    for trial in range(300):
        cooldown = set()

        async def cd():
            return set(cooldown)
        monkeypatch.setattr(engine, "_get_symbol_cooldown_set", cd)
        cs = []
        vols.clear()
        for j in range(rng.randint(1, 8)):
            sym = f"P{rng.randint(0, 5)}USDT"
            tf = rng.choice(["15m", "4h", "1d"])
            if any(c["symbol"] == sym and c["timeframe"] == tf for c in cs):
                continue
            c = cand(symbol=sym, tf=tf, tt=rng.choice(["momentum", "reversion", None]),
                     spread=rng.choice([0.01, 0.02, 0.02, 0.2, None]),
                     stop_valid=rng.choice([True, True, False, None]))
            if rng.random() < 0.1:
                c["order_book"]["valid"] = False
            cs.append(c)
            vols[sym] = rng.choice([1e6, 2e6, 2e6, None])
        fetch.open = {s for s in {c["symbol"] for c in cs} if rng.random() < 0.15}
        cooldown.update(s for s in {c["symbol"] for c in cs} if rng.random() < 0.15)
        rows = [_row(json.loads(json.dumps(c))) for c in cs]
        live = asyncio.run(engine.find_best_signal_live(rows, FakeMacro()))
        res = select([normalize(c, vols.get(c["symbol"])) for c in cs],
                     open_symbols=frozenset(fetch.open), cooldown=frozenset(cooldown))
        got = (res.selected.symbol, res.selected.timeframe) if res.selected else None
        want = (live["symbol"], live["timeframe"]) if live else None
        assert got == want, (trial, cs)
        agree += 1
    assert agree == 300


# ── A43-E: diagnostics, correlated exposure ────────────────────────────────

def test_diagnostic_record_serialization_and_exposure_context():       # scenarios 17, 18
    cs = [normalize(cand(symbol="AAAUSDT"), 3e6), normalize(cand(symbol="BBBUSDT", spread=0.05), 9e6)]
    sel = select(cs, ranker="execution_quality_v2")
    policy = CorrelatedExposurePolicy(enabled=True)
    open_ = [Exposure("ETHUSDT", 50, 1.1)]
    verdict = policy.evaluate(open_, Exposure("AAAUSDT", 50, 1.3))
    exposure = {"policy": policy.version, "beta_weighted_open_usdt": policy.beta_weighted(open_),
                "would_allow": verdict.would_allow, "reasons": list(verdict.reasons)}
    decision = T0 + TF_MS["4h"] + 60_000
    rec = build_record(cs[0], strategy_version=SV, decision_ms=decision, selection=sel,
                       exposure=exposure)
    line = serialize(rec)
    assert line == serialize(build_record(cs[0], strategy_version=SV, decision_ms=decision,
                                          selection=sel, exposure=exposure))     # deterministic bytes
    assert deserialize(line) == rec and len(line) < 2048 and "NaN" not in line
    assert rec["selected"] is True and rec["rank"] == 1 and rec["fresh"] is True
    assert rec["exposure"]["would_allow"] is False and rec["exposure"]["beta_weighted_open_usdt"] == pytest.approx(55.0)
    assert rec["setup_key"] == identity_from_candidate(cs[0].data, strategy_version=SV).key
    assert rec["cost_over_risk"] == pytest.approx(0.2 / 2.0)
    with pytest.raises(ValueError, match="diag_fields_mismatch"):
        validate_record({**rec, "api_key": "x"})
    with pytest.raises(ValueError, match="diag_eligibility_inconsistent"):
        validate_record({**rec, "eligible": False})
    broken = build_record(normalize({**cand(), "pit": {}}), strategy_version=SV, decision_ms=decision,
                          reasons=("identity:candle_open_time_missing",))
    assert broken["setup_key"] is None and broken["identity_error"] == "candle_open_time_missing"
    assert set(json.loads(serialize(broken))) == set(FIELDS)


def test_no_production_module_imports_a43_components():
    """A44: identity and failure safety are wired (in exactly these files); selection v2 and
    diagnostics stay experimental and unimported by production code."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    # Registered experimental modules may import each other (tests/experimental_modules.py
    # contract, A46); every production file is still checked.
    sys.path.insert(0, str(root / "tests"))
    from experimental_modules import EXPERIMENTAL_SHARED
    EXPERIMENTAL = tuple(dict.fromkeys(("candidate_selection", "candidate_diagnostics",
                                        "signal_quality", "counterfactual_barrier")
                                       + tuple(EXPERIMENTAL_SHARED)))

    def importers(names):
        pattern = re.compile(r"(from\s+shared(\.|\s+import\s+[^\n]*\b)|import\s+shared\.)("
                             + "|".join(names) + r")\b")
        return sorted(str(p.relative_to(root)) for p in root.rglob("*.py")
                      if "tests" not in p.parts and p.stem not in names + EXPERIMENTAL
                      and pattern.search(p.read_text(errors="ignore")))
    assert importers(("candidate_selection", "candidate_diagnostics")) == []
    assert importers(("signal_identity", "dependency_safety")) == [
        "analyzer/main.py", "analyzer/technical_analyzer.py", "signal_engine/main.py",
        "signal_engine/signal_logic.py", "trade_tracker/main.py"]
