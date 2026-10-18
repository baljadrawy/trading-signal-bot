"""S3 shadow evaluation (s3-shadow-v1): compare the operational selector with S3. DISABLED.

The operational selector (SignalEngine.find_best_signal_live) stays the sole decision-maker. This
module only *describes* what S3 would have chosen from the same input snapshot. It never emits,
suppresses, delays or duplicates a signal; nothing in production imports it, and wiring it into
the engine is a separate, reviewed step (it would run strictly AFTER the operational decision).

Contracts
  InputSnapshot    rows as the engine reads them + liquidity map + state sets + decision time;
                   ``snapshot_id`` is an order-independent sha256 of all of it.
  Operational      the authoritative pick (symbol, timeframe) or NO_TRADE, with a selector id.
                   ``replica`` re-derives it with candidate_selection's exact production-parity
                   key, so drift between live code and replica is detected, not assumed away.
  S3 result        shared.signal_selection.select_s3 at the baseline policy (slippage 0) plus a
                   declared slippage sensitivity grid; each scenario is an ASSUMPTION.
  Classification   AGREE_SELECT | AGREE_NO_TRADE | DIFFERENT_PICK | S3_NO_TRADE_ONLY |
                   S3_ONLY (operational NO_TRADE but S3 picks: impossible while S3's eligible set
                   is a subset of production's — flagged as an invariant violation)
  Status           OK | DISABLED | INVALID_INPUT | ERROR | TIMEOUT. ``run_shadow_safely`` never
                   raises: every failure becomes a record, so operational selection is unaffected.
  Audit digest     sha256 of the record without timing fields: identical inputs -> identical digest.
Costs: 0.10 %/side (20 bps round trip, no BNB discount) + observed spread + declared slippage.
Nothing here is evidence of profitability.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from typing import Iterable, Mapping, Sequence

from shared.candidate_selection import EligibilityPolicy, normalize, select
from shared.signal_selection import VERSION as S3_VERSION
from shared.signal_selection import S3Policy, select_s3

VERSION = "s3-shadow-v1"
OPERATIONAL_SELECTOR_ID = "live_fixed_execution_quality_v1"   # SignalEngine._fixed_candidate_key
REPLICA_ID = "a43-cs-v1/production_parity"
DEFAULT_SLIPPAGE_SCENARIOS = (0.0, 0.05, 0.10, 0.20)          # % round trip; assumptions only
CLASSES = ("AGREE_SELECT", "AGREE_NO_TRADE", "DIFFERENT_PICK", "S3_NO_TRADE_ONLY", "S3_ONLY")


def _sha(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ShadowConfig:
    enabled: bool = False                      # never enabled automatically
    timeout_s: float = 2.0
    max_candidates: int = 2000                 # bounds CPU and memory per evaluation
    slippage_scenarios_pct: tuple = DEFAULT_SLIPPAGE_SCENARIOS
    include_candidates: bool = True            # per-candidate reasons and metrics in the record


@dataclass(frozen=True)
class InputSnapshot:
    snapshot_id: str
    decision_ms: int | None
    source: str                                # engine_cycle | offline_extract | synthetic
    rows: tuple
    liquidity: Mapping
    open_symbols: frozenset = frozenset()
    cooldown: frozenset = frozenset()
    throttled: frozenset = frozenset()
    emitted_keys: frozenset = frozenset()


def build_snapshot(rows: Iterable[Mapping], liquidity: Mapping, *, decision_ms: int | None,
                   source: str, open_symbols=(), cooldown=(), throttled=(), emitted_keys=()) -> InputSnapshot:
    rows = tuple(dict(r) for r in rows)
    parsed = []
    for r in rows:
        d = r.get("analysis_data", r)
        parsed.append(json.loads(d) if isinstance(d, str) else d)
    ident = {"rows": sorted(_sha(p) for p in parsed),
             "liquidity": {str(k): liquidity[k] for k in sorted(liquidity, key=str)},
             "open": sorted(open_symbols), "cooldown": sorted(cooldown),
             "throttled": sorted(map(list, throttled)), "emitted": sorted(emitted_keys),
             "decision_ms": decision_ms, "source": source}
    return InputSnapshot(_sha(ident), decision_ms, source, rows, dict(liquidity), frozenset(open_symbols),
                         frozenset(cooldown), frozenset(map(tuple, throttled)), frozenset(emitted_keys))


@dataclass(frozen=True)
class Operational:
    pick: tuple | None                         # (symbol, timeframe) or None = NO_TRADE
    selector_id: str = OPERATIONAL_SELECTOR_ID


def classify(operational: tuple | None, s3: tuple | None) -> str:
    if operational is None and s3 is None:
        return "AGREE_NO_TRADE"
    if operational is None:
        return "S3_ONLY"
    if s3 is None:
        return "S3_NO_TRADE_ONLY"
    return "AGREE_SELECT" if operational == s3 else "DIFFERENT_PICK"


def _pick(c):
    return (c.symbol, c.timeframe) if c is not None else None


def _record(status, snapshot, operational, config, policy, *, body=None, error=None, elapsed_ms=None):
    rec = {"version": VERSION, "status": status, "snapshot_id": getattr(snapshot, "snapshot_id", None),
           "decision_ms": getattr(snapshot, "decision_ms", None), "source": getattr(snapshot, "source", None),
           "operational": None if operational is None else {
               "selector_id": operational.selector_id,
               "pick": list(operational.pick) if operational.pick else None},
           "s3_version": S3_VERSION, "policy_id": _sha(asdict(policy)), "policy": asdict(policy),
           "config": {**asdict(config), "slippage_scenarios_pct": list(config.slippage_scenarios_pct)},
           "error": error, **(body or {})}
    rec["audit_digest"] = _sha(rec)
    rec["elapsed_ms"] = elapsed_ms                 # excluded from the digest (timing only)
    return rec


def evaluate_shadow(snapshot: InputSnapshot, operational: Operational | None = None, *,
                    config: ShadowConfig = ShadowConfig(), policy: S3Policy = S3Policy()) -> dict:
    """Pure comparison (raises on programming errors; use ``run_shadow_safely`` operationally).
    ``operational`` None = offline mode: the replica stands in and is labelled as such."""
    if len(snapshot.rows) > config.max_candidates:
        return _record("INVALID_INPUT", snapshot, operational, config, policy,
                       error={"type": "too_many_candidates", "message": f"{len(snapshot.rows)}>{config.max_candidates}"})
    cands = [normalize(r, snapshot.liquidity.get(r.get("symbol") or
                                                 (r.get("analysis_data") or {}).get("symbol")))
             for r in snapshot.rows]
    state = dict(open_symbols=snapshot.open_symbols, cooldown=snapshot.cooldown,
                 throttled=snapshot.throttled)
    replica = select(cands, policy=EligibilityPolicy(max_spread_pct=policy.max_spread_pct),
                     ranker="production_parity", **state)
    op = operational or Operational(_pick(replica.selected), selector_id="replica:" + REPLICA_ID)
    s3_state = dict(state, emitted_keys=snapshot.emitted_keys, decision_ms=snapshot.decision_ms)
    base = select_s3(cands, policy=policy, **s3_state)
    sensitivity = []
    for slip in config.slippage_scenarios_pct:
        d = base if slip == policy.slippage_roundtrip_pct else select_s3(
            cands, policy=replace(policy, slippage_roundtrip_pct=float(slip)), **s3_state)
        sensitivity.append({"slippage_roundtrip_pct": float(slip), "label": "assumption",
                            "outcome": d.outcome, "pick": list(_pick(d.selected)) if d.selected else None,
                            "classification": classify(op.pick, _pick(d.selected)),
                            "eligible": sum(r.stage == "selection" for r in d.records)})
    cls = classify(op.pick, _pick(base.selected))
    body = {
        "replica": {"selector_id": REPLICA_ID, "pick": list(_pick(replica.selected)) if replica.selected else None,
                    "matches_operational": _pick(replica.selected) == op.pick,
                    "eligible": len(replica.ranked)},
        "s3": {"outcome": base.outcome, "pick": list(_pick(base.selected)) if base.selected else None,
               "no_trade_reason": base.no_trade_reason, "reason_counts": base.reason_counts,
               "eligible": sum(r.stage == "selection" for r in base.records), "universe": base.universe},
        "classification": cls, "invariant_violation": cls == "S3_ONLY",
        "costs": {"fee_roundtrip_pct": policy.fee_roundtrip_pct, "spread": "observed per candidate",
                  "slippage_baseline_pct": policy.slippage_roundtrip_pct, "slippage_label": "assumption"},
        "sensitivity": sensitivity,
        # canonical order (not input order) so the audit digest is order-independent
        "candidates": (sorted((r.to_dict() for r in base.records),
                              key=lambda c: (c["symbol"], c["timeframe"], str(c["trade_type"]), _sha(c)))
                       if config.include_candidates else None),
        "candidate_count": len(cands),
    }
    return _record("OK", snapshot, op, config, policy, body=body)


def run_shadow_safely(snapshot, operational: Operational | None = None, *,
                      config: ShadowConfig = ShadowConfig(), policy: S3Policy = S3Policy(),
                      evaluator=evaluate_shadow) -> dict:
    """Operational entry point: never raises, never blocks longer than ``timeout_s``.
    A late result is discarded (the worker cannot be killed, so inputs are bounded instead)."""
    if not config.enabled:
        return _record("DISABLED", snapshot, operational, config, policy)
    start = time.monotonic()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="s3-shadow")
    try:
        fut = pool.submit(evaluator, snapshot, operational, config=config, policy=policy)
        out = fut.result(timeout=config.timeout_s)
        out["elapsed_ms"] = round((time.monotonic() - start) * 1000, 3)
        return out
    except concurrent.futures.TimeoutError:
        return _record("TIMEOUT", snapshot, operational, config, policy,
                       error={"type": "timeout", "message": f">{config.timeout_s}s"},
                       elapsed_ms=round((time.monotonic() - start) * 1000, 3))
    except Exception as exc:                       # isolation: a shadow failure is only a record
        return _record("ERROR", snapshot, operational, config, policy,
                       error={"type": type(exc).__name__, "message": str(exc)[:200]},
                       elapsed_ms=round((time.monotonic() - start) * 1000, 3))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def summarize(records: Sequence[Mapping]) -> dict:
    """Aggregate shadow records (selector behaviour only; no outcomes)."""
    ok = [r for r in records if r.get("status") == "OK"]
    out = {"records": len(records), "ok": len(ok),
           "status": {s: sum(r.get("status") == s for r in records)
                      for s in ("OK", "DISABLED", "INVALID_INPUT", "ERROR", "TIMEOUT")},
           "classification": {c: sum(r["classification"] == c for r in ok) for c in CLASSES},
           "replica_matches_operational": sum(r["replica"]["matches_operational"] for r in ok),
           "candidates": sum(r["candidate_count"] for r in ok),
           "s3_reason_counts": {}, "sensitivity": {}}
    for r in ok:
        for k, v in r["s3"]["reason_counts"].items():
            out["s3_reason_counts"][k] = out["s3_reason_counts"].get(k, 0) + v
        for s in r["sensitivity"]:
            key = f"{s['slippage_roundtrip_pct']:g}"
            agg = out["sensitivity"].setdefault(key, {"s3_selected": 0, "eligible": 0,
                                                      **{c: 0 for c in CLASSES}})
            agg["s3_selected"] += s["outcome"] == "SELECTED"
            agg["eligible"] += s["eligible"]
            agg[s["classification"]] += 1
    out["s3_reason_counts"] = dict(sorted(out["s3_reason_counts"].items()))
    return out


__all__ = ["VERSION", "ShadowConfig", "InputSnapshot", "Operational", "build_snapshot", "classify",
           "evaluate_shadow", "run_shadow_safely", "summarize", "CLASSES", "DEFAULT_SLIPPAGE_SCENARIOS"]
