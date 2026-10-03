"""G3-F4-D1 development harness (importable file; run: python -m tests.dev_certproc_harness). Bounded; diagnostic."""
import glob, json, os, sys, tempfile, time


def main():
    from p2_forward import writer as Wm, record as R
    from p2_forward.certproc import ProcessCertifier, CTX
    t0 = time.monotonic(); ph = lambda m: print(f"{time.monotonic()-t0:7.3f}s {m}", flush=True)
    ph(f"start_method={CTX.get_start_method()} main={sys.modules['__main__'].__file__ if hasattr(sys.modules['__main__'],'__file__') else None}")
    with tempfile.TemporaryDirectory() as d:
        seg = Wm._Segment(d, "lifecycle", "20261003T01", "cccccccc", 1)
        for i in range(200):
            seg.write(R.make(type="lifecycle", obs_id=f"life|{'c'*32}|{i}|x", symbol=None, payload={"i": i}, boot_id="c"*32,
                             endpoint="collector", transport="internal", recv_ts_ns=time.time_ns()))
        seg.finalize(); ph("pending segment created")
        st = Wm.new_stats(); c = ProcessCertifier(d, "c"*32, st, lambda: None)
        c.start(); ph(f"process started pid={c.ident}")
        for _ in range(100):
            if c.is_alive() and (time.time_ns() - c.beat_ns) < 500_000_000 and c.beat_ns: break
            time.sleep(0.05)
        ph(f"alive={c.is_alive()} exitcode={c.proc.exitcode} beat_age_ms={(time.time_ns()-c.beat_ns)//10**6}")
        for _ in range(100):
            if not c.pending(): break
            time.sleep(0.05)
        ph(f"pending_after={len(c.pending())} certified={len(glob.glob(d+'/raw/*/*/*.jsonl.gz'))} failures={st['certification_failures']}")
        ok = c.drain(10); ph(f"drain={ok} alive={c.is_alive()} exitcode={c.proc.exitcode}")


if __name__ == "__main__":
    main()
