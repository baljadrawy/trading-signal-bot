"""Synthetic CPU-bound workload for validating the research execution layer.

Each unit runs a seeded Monte-Carlo loop (pure Python, single-threaded) and returns small JSON.
Touches no real data. Example (inside a runner job, workers come from $RESEARCH_WORKERS):
  python3 synthetic_cpu.py --units 16 --iters 3000000 --checkpoint /tmp/x/ckpt --out /tmp/x/merged.json
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from research_exec.detpool import make_units, run_units  # noqa: E402
from research_exec.record import atomic_write_bytes  # noqa: E402


def mc_unit(unit):
    rng = unit.rng()
    n = int(unit.params["iters"])
    # Completion-order perturbation for tests: from the environment and a SEPARATE rng, so it
    # changes only when units finish, never what they compute (and is not part of the plan).
    jitter = float(os.environ.get("SYNTH_JITTER_S", "0") or 0)
    if jitter:
        time.sleep(random.Random(unit.seed ^ 0x5EED).random() * jitter)
    hits = 0
    acc = 0.0
    for _ in range(n):
        x, y = rng.random(), rng.random()
        if x * x + y * y <= 1.0:
            hits += 1
        acc += x * y
    return {"hits": hits, "n": n, "pi_est": 4.0 * hits / n, "mean_xy": acc / n,
            "first_draw": rng.random()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", type=int, default=16)
    ap.add_argument("--iters", type=int, default=1_000_000)
    ap.add_argument("--base-seed", type=int, default=20261006)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--checkpoint")
    ap.add_argument("--out")
    ap.add_argument("--jitter-s", type=float, default=0.0)
    ap.add_argument("--shuffle-seed", type=int)
    a = ap.parse_args(argv)
    units = make_units([f"u{i:04d}" for i in range(a.units)], a.base_seed,
                       params={"iters": a.iters})
    if a.jitter_s:
        os.environ["SYNTH_JITTER_S"] = str(a.jitter_s)   # inherited by spawned workers
    t0 = time.monotonic()
    res = run_units(mc_unit, units, workers=a.workers, checkpoint_dir=a.checkpoint,
                    fn_id="synthetic_cpu.mc_unit", meta={"iters": a.iters},
                    _test_shuffle_seed=a.shuffle_seed)
    if a.out:
        atomic_write_bytes(a.out, res.merged_bytes)
    print(f"result_sha256={res.result_sha256} workers={res.workers} reused={res.reused} "
          f"computed={res.computed} rejected={len(res.rejected)} wall_s={time.monotonic() - t0:.2f}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
