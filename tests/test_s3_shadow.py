"""S3 shadow evaluation (s3-shadow-v1): engineering properties only, synthetic inputs.

Covers: disabled default, operational/replica parity (incl. the REAL live selector), every
classification, NO_TRADE, duplicate symbols/timeframes, non-finite/missing inputs, slippage
sensitivity, determinism and audit stability, error/timeout isolation, no side effects, and
that no production module imports the shadow evaluator."""
import asyncio
import json
import pathlib
import random
import re
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import time

from shared.s3_shadow import (CLASSES, Operational, ShadowConfig, build_snapshot, classify,
                              evaluate_shadow, run_shadow_safely, summarize)
from test_s3_signal_selection import cand

ROOT = pathlib.Path(__file__).resolve().parents[1]
ON = ShadowConfig(enabled=True)


def snap(specs, liq=None, **state):
    rows = [{"symbol": c["symbol"], "timeframe": c["timeframe"], "analysis_data": json.dumps(c)} for c in specs]
    liq = liq if liq is not None else {c["symbol"]: 1e6 for c in specs}
    return build_snapshot(rows, liq, decision_ms=1_800_000_000_000, source="synthetic", **state)


def test_disabled_by_default_and_never_evaluates():
    calls = []
    s = snap([cand("AUSDT")])
    r = run_shadow_safely(s, evaluator=lambda *a, **k: calls.append(1))
    assert r["status"] == "DISABLED" and calls == [] and ShadowConfig().enabled is False


def test_classifications():
    assert classify(None, None) == "AGREE_NO_TRADE"
    assert classify(("A", "4h"), ("A", "4h")) == "AGREE_SELECT"
    assert classify(("A", "4h"), ("B", "1d")) == "DIFFERENT_PICK"
    assert classify(("A", "4h"), None) == "S3_NO_TRADE_ONLY"
    assert classify(None, ("A", "4h")) == "S3_ONLY"
    agree = evaluate_shadow(snap([cand("AUSDT", risk=2.0)]))
    assert agree["classification"] == "AGREE_SELECT" and agree["replica"]["matches_operational"]
    diff = evaluate_shadow(snap([cand("AUSDT", risk=0.3), cand("BUSDT", tf="1d", risk=3.0, spread=0.05)]))
    assert diff["classification"] == "DIFFERENT_PICK" and diff["s3"]["pick"] == ["BUSDT", "1d"]
    none = evaluate_shadow(snap([cand("AUSDT", tt=None)]))
    assert none["classification"] == "AGREE_NO_TRADE"
    s3_only_no = evaluate_shadow(snap([cand("AUSDT", risk=0.15)]))           # T1 path net negative
    assert s3_only_no["classification"] == "S3_NO_TRADE_ONLY"
    assert s3_only_no["s3"]["no_trade_reason"] == "no_eligible_candidate"


def test_supplied_operational_pick_is_compared_and_replica_drift_is_detected():
    s = snap([cand("AUSDT"), cand("BUSDT", spread=0.05)])
    r = evaluate_shadow(s, Operational(("BUSDT", "4h")))
    assert r["operational"]["selector_id"] == "live_fixed_execution_quality_v1"
    assert r["replica"]["pick"] == ["AUSDT", "4h"] and r["replica"]["matches_operational"] is False
    assert evaluate_shadow(s)["operational"]["selector_id"].startswith("replica:")


def test_duplicate_symbols_and_timeframes():
    r = evaluate_shadow(snap([cand("AUSDT", tf="15m", risk=1.0), cand("AUSDT", tf="1d", risk=3.0)]))
    assert r["replica"]["pick"] == ["AUSDT", "15m"]                    # production: string tie-break
    assert r["s3"]["pick"] == ["AUSDT", "1d"] and r["s3"]["reason_counts"]["duplicate_symbol_lower_rank"] == 1


def test_non_finite_and_missing_inputs_are_records_not_crashes():
    r = evaluate_shadow(snap([cand("AUSDT", spread=float("nan")), cand("BUSDT", entry_price=None)], liq={}))
    assert r["status"] == "OK" and r["s3"]["outcome"] == "NO_TRADE"
    assert {"spread_invalid", "bracket_missing", "liquidity_unknown"} <= set(r["s3"]["reason_counts"])
    big = snap([cand(f"S{i}USDT") for i in range(5)])
    assert evaluate_shadow(big, config=ShadowConfig(max_candidates=3))["status"] == "INVALID_INPUT"


def test_slippage_sensitivity_is_monotone_and_labelled_as_assumption():
    # cost/R at 0 slippage: 0.22/1.2 = 0.18 and 0.22/1.0 = 0.22 (both under the 0.25 cap)
    r = evaluate_shadow(snap([cand("AUSDT", risk=1.2), cand("BUSDT", risk=1.0)]),
                        config=ShadowConfig(slippage_scenarios_pct=(0.0, 0.05, 0.1, 0.2, 0.4)))
    elig = [s["eligible"] for s in r["sensitivity"]]
    assert elig == sorted(elig, reverse=True) and elig[0] == 2 and elig[-1] == 0
    assert {s["label"] for s in r["sensitivity"]} == {"assumption"}
    assert r["costs"]["fee_roundtrip_pct"] == 0.2 and r["costs"]["slippage_label"] == "assumption"


def test_determinism_and_audit_stability():
    specs = [cand("AUSDT"), cand("BUSDT", risk=3.0), cand("CUSDT", spread=0.03)]
    a = evaluate_shadow(snap(specs))
    assert evaluate_shadow(snap(specs))["audit_digest"] == a["audit_digest"]          # identical input
    b = evaluate_shadow(snap(list(reversed(specs))))
    assert a["snapshot_id"] == b["snapshot_id"] and a["audit_digest"] == b["audit_digest"]
    assert json.loads(json.dumps(a)) == a
    c = evaluate_shadow(snap([cand("AUSDT"), cand("BUSDT", risk=2.9), cand("CUSDT", spread=0.03)]))
    assert c["audit_digest"] != a["audit_digest"]


def test_nan_spread_makes_the_production_pick_order_dependent_but_not_s3():
    """Documented production quirk (A43): min() over a NaN key depends on input order, so a
    NaN-spread candidate can even be SELECTED. The shadow records it; S3 rejects NaN."""
    specs = [cand("AUSDT"), cand("BUSDT", risk=3.0), cand("CUSDT", spread=float("nan"))]
    from shared.candidate_selection import EligibilityPolicy
    a, b = evaluate_shadow(snap(specs)), evaluate_shadow(snap(list(reversed(specs))))
    assert a["snapshot_id"] == b["snapshot_id"]
    if EligibilityPolicy().reject_non_finite_spread:        # live selector fixed (#34): replica follows
        assert a["replica"]["pick"] == b["replica"]["pick"] != ["CUSDT", "4h"]
    else:                                                   # pre-fix production quirk
        assert a["replica"]["pick"] != b["replica"]["pick"] and ["CUSDT", "4h"] in (a["replica"]["pick"],
                                                                                   b["replica"]["pick"])
    assert a["s3"] == b["s3"] and a["s3"]["pick"] == ["BUSDT", "4h"]


def test_shadow_exceptions_and_timeouts_are_isolated():
    s = snap([cand("AUSDT")])

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")

    def slow(*a, **k):
        time.sleep(0.5)
        return {"status": "OK"}
    err = run_shadow_safely(s, config=ON, evaluator=boom)
    assert err["status"] == "ERROR" and err["error"]["type"] == "RuntimeError"
    t0 = time.monotonic()
    to = run_shadow_safely(s, config=ShadowConfig(enabled=True, timeout_s=0.05), evaluator=slow)
    assert to["status"] == "TIMEOUT" and time.monotonic() - t0 < 0.4
    assert run_shadow_safely(s, config=ON)["status"] == "OK"


def test_no_operational_side_effects():
    specs = [cand("AUSDT"), cand("BUSDT", risk=3.0)]
    s = snap(specs, open_symbols={"ZUSDT"})
    before = json.dumps([dict(r) for r in s.rows], sort_keys=True), dict(s.liquidity), set(s.open_symbols)
    op = Operational(("AUSDT", "4h"))
    run_shadow_safely(s, op, config=ON)
    assert (json.dumps([dict(r) for r in s.rows], sort_keys=True), dict(s.liquidity), set(s.open_symbols)) == before
    assert op.pick == ("AUSDT", "4h")


def test_summary_and_s3_subset_invariant_on_random_sets():
    rng = random.Random(31)
    recs = []
    for _ in range(150):
        specs = []
        for _ in range(rng.randint(0, 6)):
            c = cand(f"R{rng.randint(0, 6)}USDT", tf=rng.choice(["15m", "4h", "1d"]),
                     spread=rng.choice([0.01, 0.05, 0.2]), risk=rng.choice([0.2, 0.6, 1.5, 3.0]),
                     tt=rng.choice(["momentum", "reversion", None]))
            if not any((x["symbol"], x["timeframe"]) == (c["symbol"], c["timeframe"]) for x in specs):
                specs.append(c)
        recs.append(run_shadow_safely(snap(specs), config=ON))
    s = summarize(recs)
    assert s["ok"] == 150 and s["classification"]["S3_ONLY"] == 0
    assert sum(s["classification"].values()) == 150 and set(s["classification"]) == set(CLASSES)
    assert s["replica_matches_operational"] == 150


def test_no_production_module_imports_the_shadow_evaluator():
    from experimental_modules import EXPERIMENTAL_SHARED
    assert "s3_shadow" in EXPERIMENTAL_SHARED
    for path in ROOT.glob("*/*.py"):
        if path.parts[-2] in ("tests", "research", "docs", "colab") or (
                path.parent.name == "shared" and path.stem in EXPERIMENTAL_SHARED):
            continue
        assert not re.search(r"\bs3_shadow\b", path.read_text(encoding="utf-8", errors="ignore")), path


def test_offline_operational_column_equals_the_real_live_selector(monkeypatch):
    sys.path.insert(0, 'signal_engine')
    import signal_logic
    from shared.config import config
    from shared.database import Database

    class Macro:
        async def should_block_now(self): return False
        def macro_state_key(self): return 'usdtd_flat'
        def snapshot(self): return {}
        def state(self): return {}

    async def fetch(sql, *a):
        return []
    monkeypatch.setattr(Database, 'fetch', fetch)
    monkeypatch.setattr(config, 'ENABLE_EVIDENCE_RECORDER', False)
    monkeypatch.setattr(config, 'LEARNING_GATES_ENABLED', False)
    monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off', raising=False)
    rng = random.Random(77)
    compared = 0
    for _ in range(150):
        specs, vols = [], {}
        for _ in range(rng.randint(1, 6)):
            c = cand(f"E{rng.randint(0, 4)}USDT", tf=rng.choice(['15m', '4h', '1d']),
                     spread=rng.choice([0.01, 0.02, 0.2]), risk=rng.choice([0.3, 1.0, 2.5]),
                     tt=rng.choice(['momentum', 'reversion', None]))
            if not any((x["symbol"], x["timeframe"]) == (c["symbol"], c["timeframe"]) for x in specs):
                specs.append(c)
                vols.setdefault(c["symbol"], rng.choice([1e6, 2e6, None]))
        s = snap(specs, liq=vols)
        eng = signal_logic.SignalEngine()

        async def vol(sym):
            return vols.get(sym)

        async def no_cd():
            return set()
        monkeypatch.setattr(eng, '_get_volume_usdt', vol)
        monkeypatch.setattr(eng, '_get_symbol_cooldown_set', no_cd)
        live = asyncio.run(eng.find_best_signal_live([dict(r) for r in s.rows], Macro()))
        live_pick = [live['symbol'], live['timeframe']] if live else None
        rec = evaluate_shadow(s, Operational(tuple(live_pick) if live_pick else None))
        assert rec["replica"]["matches_operational"], (live_pick, rec["replica"]["pick"])
        compared += live is not None
    assert compared > 80
