"""Resource-safe benchmark on SYNTHETIC data only (1 day, 37 symbols, production cadences).

  python -m p2_research.bench gen   <scratch_dir>            # writes a sealed synthetic day (not measured)
  python -m p2_research.bench build <scratch_dir> <out_dir>  # measured: reader + features + labels + manifest

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


def bench_spec():
    D = ms(f"{DAY}T00:00:00Z")
    tiers = {"BTCUSDT": 0, "ETHUSDT": 0}
    tiers.update({f"T1S{i:02d}USDT": 1 for i in range(6)})
    tiers.update({f"T2S{i:02d}USDT": 2 for i in range(29)})
    return {"dataset_id": "synthetic-bench", "cadences": REAL_CAD,
            "runs": [{"boot": "c3" * 16, "ws": D + 30_000, "stop": None}],
            "span_end": D + 86_400_000 + 3_600_000 + 60_000,
            "epochs": [{"effective_ms": D, "stamp": "20261005T000000000000Z", "tiers": tiers}],
            "gaps": [], "candle_misses": [], "close_days": [DAY], "seal_days": [DAY]}


def main(argv):
    if argv[0] == "gen":
        t = time.time()
        Synth(argv[1], bench_spec()).generate()
        print(json.dumps({"gen_wall_s": round(time.time() - t, 1)}))
        return 0
    from .builder import build
    t0, c0 = time.time(), time.process_time()
    m = build(argv[1], [DAY], argv[2], code_commit=os.environ.get("P2C_COMMIT", "bench"), write=True)
    ru = resource.getrusage(resource.RUSAGE_SELF)
    out = {"rows": m["row_count"], "excluded": m["excluded_count"], "logical_hash": m["logical_hash"],
           "book_records": sum(s["records"] for s in m["source"]["segments"] if "/book/" in s["path"]),
           "depth_records": sum(s["records"] for s in m["source"]["segments"] if "/depth/" in s["path"]),
           "segments": len(m["source"]["segments"]), "wall_s": round(time.time() - t0, 2),
           "cpu_s": round(time.process_time() - c0, 2), "user_s": round(ru.ru_utime, 2), "sys_s": round(ru.ru_stime, 2),
           "peak_rss_mb": round(ru.ru_maxrss / 1024, 1)}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
