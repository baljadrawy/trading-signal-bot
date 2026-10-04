"""Resource-safe benchmark on SYNTHETIC data only (N days, default 1; 37 symbols, production cadences).

  python -m p2_research.bench gen   <scratch_dir> [N]                    # writes N sealed synthetic days (not measured)
  python -m p2_research.bench build <scratch_dir> <out_dir> [N] [--streaming]  # measured: reader+features+labels+manifest

Run under explicit limits, e.g. ``nice -n 15 ionice -c3 prlimit --as=2147483648 python -m p2_research.bench build ...``.
Reports CPU time (user+sys), wall time and peak RSS of this process (getrusage).
"""
from __future__ import annotations

import json
import os
import resource
import sys
import time

from .tests.synth import REAL_CAD, Synth, ms

DAY = "2026-10-05"


def bench_days(n: int = 1) -> list:
    D = ms(f"{DAY}T00:00:00Z")
    return [time.strftime("%Y-%m-%d", time.gmtime((D + i * 86_400_000) / 1000)) for i in range(n)]


def bench_spec(n: int = 1):
    D = ms(f"{DAY}T00:00:00Z")
    tiers = {"BTCUSDT": 0, "ETHUSDT": 0}
    tiers.update({f"T1S{i:02d}USDT": 1 for i in range(6)})
    tiers.update({f"T2S{i:02d}USDT": 2 for i in range(29)})
    return {"dataset_id": "synthetic-bench", "cadences": REAL_CAD,
            "runs": [{"boot": "c3" * 16, "ws": D + 30_000, "stop": None}],
            "span_end": D + n * 86_400_000 + 3_600_000 + 60_000,
            "epochs": [{"effective_ms": D, "stamp": "20261005T000000000000Z", "tiers": tiers}],
            "gaps": [], "candle_misses": [], "close_days": bench_days(n), "seal_days": bench_days(n)}


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if argv[0] == "gen":
        t = time.time()
        Synth(argv[1], bench_spec(int(args[2]) if len(args) > 2 else 1)).generate()
        print(json.dumps({"gen_wall_s": round(time.time() - t, 1)}))
        return 0
    from .builder import build
    t0, c0 = time.time(), time.process_time()
    n = int(args[3]) if len(args) > 3 else 1
    m = build(argv[1], bench_days(n), argv[2], code_commit=os.environ.get("P2C_COMMIT", "bench"), write=True,
              streaming="--streaming" in argv)
    ru = resource.getrusage(resource.RUSAGE_SELF)
    out = {"rows": m["row_count"], "excluded": m["excluded_count"], "logical_hash": m["logical_hash"],
           "book_records": sum(s["records"] for s in m["source"]["segments"] if "/book/" in s["path"]),
           "depth_records": sum(s["records"] for s in m["source"]["segments"] if "/depth/" in s["path"]),
           "segments": len(m["source"]["segments"]), "wall_s": round(time.time() - t0, 2),
           "cpu_s": round(time.process_time() - c0, 2), "user_s": round(ru.ru_utime, 2), "sys_s": round(ru.ru_stime, 2),
           "peak_rss_mb": round(ru.ru_maxrss / 1024, 1), "days": n, "streaming": "--streaming" in argv,
           "build_execution": m.get("build_execution")}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
