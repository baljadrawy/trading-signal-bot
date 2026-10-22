"""P1 reference corpus (lab/PARITY_TEST_SPEC.md): seeded synthetic poll paths through PRODUCTION step_barrier.

The lab adapter, once written, must reproduce `decisions()` element for element. Until then the corpus digest is
pinned in tests/test_lab_parity_reference.py, so any behaviour change of the production exit logic is visible.

Synthetic only: a stdlib random walk, no market data, no database, no protected evidence. Deterministic: one
`random.Random(seed)` per path, plain Python float arithmetic, no numpy.
"""
from __future__ import annotations

import hashlib
import json
import random

from shared.triple_barrier import (TripleBarrierConfig, TripleBarrierState, expiry_policy_for_timeframe,
                                   step_barrier)

TIMEFRAMES = ("15m", "4h", "1d")
POLL_H = 5.0 / 60.0                      # one poll every 5 minutes
SUBSTEPS = 4                             # intra-poll extremes -> high / low
ENTRY = 100.0
# (stop distance %, T1/T2/T3 as R multiples)
BRACKETS = ((0.8, (1.0, 2.0, 3.0)), (1.5, (0.5, 1.5, 2.5)), (3.0, (1.0, 1.6, 4.0)))
VOLS = (0.00012, 0.0004, 0.0015, 0.004, 0.009)   # per-substep log-vol (low cells reach the expiries)


def bracket_cfg(b: int, tf: str) -> TripleBarrierConfig:
    stop_pct, (r1, r2, r3) = BRACKETS[b]
    risk = ENTRY * stop_pct / 100.0
    max_h, t1_h, no_t1_h = expiry_policy_for_timeframe(tf)
    cfg = TripleBarrierConfig(symbol="SYNUSDT", entry=ENTRY, target_1=ENTRY + r1 * risk, target_2=ENTRY + r2 * risk,
                              target_3=ENTRY + r3 * risk, stop_loss=ENTRY - risk, expiry_h=max_h, t1_expiry_h=t1_h,
                              no_t1_expiry_h=no_t1_h)
    assert cfg.validate() is None, cfg.validate()
    return cfg


def run_path(seed: int, tf: str, b: int, vol: float) -> dict:
    rng = random.Random(seed)
    cfg = bracket_cfg(b, tf)
    st = TripleBarrierState(peak=cfg.entry)
    price, i = cfg.entry, 0
    drift = rng.uniform(-0.3, 0.3) * vol
    while True:
        hi = lo = price
        for _ in range(SUBSTEPS):
            price *= 1.0 + drift + rng.gauss(0.0, vol)
            hi, lo = max(hi, price), min(lo, price)
        res = step_barrier(cfg, st, hi, lo, price, POLL_H)
        i += 1
        if res is not None:
            return {"seed": seed, "tf": tf, "b": b, "vol": vol, "close_idx": i, "highest_target": res.target_reached,
                    "exit_reason": res.exit_reason, "stop_hit": res.stop_hit, "result": res.result,
                    "exit_price": repr(res.exit_price), "duration_h": repr(res.duration_h)}


def decisions(n_paths: int = 10_035, base_seed: int = 20261022):
    """n_paths split evenly over timeframes x brackets x vols (45 cells); seeds are base_seed + path index."""
    cells = [(tf, b, v) for tf in TIMEFRAMES for b in range(len(BRACKETS)) for v in VOLS]
    out = []
    for k in range(n_paths):
        tf, b, v = cells[k % len(cells)]
        out.append(run_path(base_seed + k, tf, b, v))
    return out


def digest(rows) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return h.hexdigest()
