#!/usr/bin/env python3
"""V2 microbenchmark: hot-path cost on a dataset, for the code tree on sys.path[0] (old 19b8bbb or new P2-CR).
usage: bench_hotpaths.py <code_dir> <dataset> <label>  -> one JSON line (CPU ms per call, median of 3)."""
import json, os, statistics, sys, time
sys.path.insert(0, sys.argv[1])
from p2_forward import writer as W
base, label = sys.argv[2], sys.argv[3]
new = hasattr(W, "open_days")
def t(fn, n=3):
    xs = []
    for _ in range(n):
        c = time.process_time(); fn(); xs.append((time.process_time() - c) * 1000)
    return round(statistics.median(xs), 1)
def old_disk_walk():
    s = 0
    for r, _, fs in os.walk(base):
        for f in fs:
            try: s += os.path.getsize(os.path.join(r, f))
            except OSError: pass
    return s
out = {"label": label, "code": "p2cr" if new else "19b8bbb", "raw_files": sum(len(f) for _, _, f in os.walk(os.path.join(base, "raw")))}
out["certifier_scan_ms"] = t(lambda: W.scan_lifecycle(base))                    # certifier ~1 Hz; health every 10 s
if new:
    cache = {}
    out["disk_accounting_ms_cold"] = t(lambda: W.dataset_bytes(base, {}), 1)
    W.dataset_bytes(base, cache)
    out["disk_accounting_ms_warm"] = t(lambda: W.dataset_bytes(base, cache))   # disk task every 60 s (worker thread)
    out["closed_day_integrity_ms_startup"] = t(lambda: W.check_closed_days(base), 1)
    out["open_days"] = len(W.open_days(base))
else:
    out["disk_walk_ms"] = t(old_disk_walk)                                       # old disk task: event loop, every 60 s
st = W.new_stats()
out["complete_manifests_ms_startup_and_certifier_restart"] = t(lambda: W.complete_manifests(base, "b" * 32, st), 1)
print(json.dumps(out))
