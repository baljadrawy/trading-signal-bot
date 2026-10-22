import sys, json, gzip, os, importlib.util
sys.path.insert(0, '/w')
from tests.test_verify_independent import segs_of
spec = importlib.util.spec_from_file_location('reader', '/r/p2_research/reader.py'); RD = importlib.util.module_from_spec(spec); sys.path.insert(0, '/r'); spec.loader.exec_module(RD)
out = {}
for ds in sys.argv[1:]:
    B = RD.Bundle(); B.range_start_ms, B.range_end_ms = 0, 1 << 62
    n, ctrl, boots, err = 0, [], set(), None
    try:
        for t in ("book", "depth", "market", "gap", "lifecycle", "health", "clock", "universe"):
            for seg in segs_of(ds, t):
                for line in gzip.open(seg, "rt"):
                    r = json.loads(line); RD.validate_record(r); n += 1
                    if t in ("gap", "lifecycle", "health", "clock"):
                        ctrl.append(r)
                        if t == "lifecycle": boots.add(r["obs_id"].split("|")[1][:8])
        ctrl.sort(key=lambda r: (r["available_at_ms"], r["obs_id"]))
        RD.process_control(B, ctrl, boots)
        ev = sorted({e for _, e, _, _ in B.lifecycle})
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]; ev = None
    out[os.path.basename(ds)] = {"records": n, "error": err, "new_events_ingested": [e for e in (ev or []) if 'flap' in e or 'session_end' in e]}
print(json.dumps(out))
