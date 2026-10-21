"""_telemetry.json write-amplification control (research/null_a/recorder.py, telemetry_min_interval_s).
Default 0 keeps the previous behaviour exactly; > 0 rate-limits only the file write, never the snapshots."""
import json
import os
import sys
import tempfile

sys.path.insert(0, '.')
from research.null_a.recorder import EvidenceRecorder
from research.null_a.sinks import NullSink


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def rec(d, interval, clock, hist=500):
    return EvidenceRecorder(sink=NullSink(), enabled=True, telemetry_path=os.path.join(d, "_telemetry.json"),
                            telemetry_history_size=hist, telemetry_min_interval_s=interval, clock=clock)


def run_cycles(r, clock, n, step=5.0, path=None, on_write=None):
    """Simulate the flusher: one dump per flush cycle; returns (writes, bytes written, max write gap s)."""
    writes, bytes_, last_w, max_gap = 0, 0, None, 0.0
    for _ in range(n):
        before = r.telemetry_writes
        r.dump_telemetry()
        if r.telemetry_writes > before:
            writes += 1; bytes_ += os.path.getsize(path)
            if last_w is not None: max_gap = max(max_gap, clock.t - last_w)
            last_w = clock.t
        clock.t += step
    return writes, bytes_, max_gap


def test_default_rewrites_every_cycle_unchanged():
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 0.0, c); p = os.path.join(d, "_telemetry.json")
        w, _, _ = run_cycles(r, c, 30, path=p)
        assert w == 30
        data = json.load(open(p))
        assert isinstance(data, list) and len(data) == 30 and {"ts", "phase_id", "evidence_dropped_records"} <= set(data[-1])


def test_interval_limits_writes_but_keeps_every_snapshot_and_freshness():
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 60.0, c); p = os.path.join(d, "_telemetry.json")
        w, _, gap = run_cycles(r, c, 720, path=p)                          # one hour of 5 s cycles
        assert 60 <= w <= 62, w                                             # ~1 write per minute (+ first)
        assert gap <= 60.0 + 5.0 and gap < 600                              # canary STALE_SECONDS = 600
        assert len(r._tel_history) == 500                                    # ring buffer filled as before
        r.dump_telemetry(force=True)
        assert len(json.load(open(p))) == 500                                # same schema, full window on disk


def test_alarm_counter_change_writes_immediately():
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 600.0, c); p = os.path.join(d, "_telemetry.json")
        r.dump_telemetry(); c.t += 5; r.dump_telemetry(); assert r.telemetry_writes == 1
        r.dropped += 1; c.t += 5; r.dump_telemetry()
        assert r.telemetry_writes == 2 and json.load(open(p))[-1]["evidence_dropped_records"] == 1
        r.flush_failures += 1; c.t += 5; r.dump_telemetry(); assert r.telemetry_writes == 3
        r.capture_errors += 1; c.t += 5; r.dump_telemetry(); assert r.telemetry_writes == 4


def test_shutdown_forces_final_write():
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 600.0, c); p = os.path.join(d, "_telemetry.json")
        r.dump_telemetry(); c.t += 5; r.dump_telemetry(); n = len(json.load(open(p)))
        r.shutdown(timeout_ms=10)
        assert len(json.load(open(p))) == n + 2                               # skipped snapshot + shutdown one


def test_atomic_replace_and_buried_failure():
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 0.0, c); p = os.path.join(d, "_telemetry.json")
        r.dump_telemetry()
        assert not os.path.exists(p + ".tmp") and json.load(open(p))
        bad = EvidenceRecorder(sink=NullSink(), enabled=True, telemetry_path=os.path.join(p, "x", "t.json"),
                               telemetry_min_interval_s=60.0, clock=c)
        bad.dump_telemetry()                                                  # parent is a file: buried, no raise
        assert bad.telemetry_writes == 0 and len(bad._tel_history) == 1


def test_write_amplification_benchmark():
    """One simulated hour (720 cycles of 5 s) with a full 500-snapshot window: bytes written, current vs 60 s."""
    out = {}
    for interval in (0.0, 60.0):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(); r = rec(d, interval, c); p = os.path.join(d, "_telemetry.json")
            run_cycles(r, c, 500, path=p)                                    # warm up: full window
            w, b, _ = run_cycles(r, c, 720, path=p)
            out[interval] = (w, b)
    (w0, b0), (w1, b1) = out[0.0], out[60.0]
    print(f"\nbenchmark/hour: current writes={w0} bytes={b0}; 60s writes={w1} bytes={b1}; reduction={b0 / b1:.1f}x")
    assert w0 == 720 and w1 <= 62 and b0 / b1 >= 11


def test_abrupt_termination_leaves_last_complete_file():
    """No shutdown (process killed): the file on disk is the last complete atomic write, valid JSON, never torn."""
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 60.0, c); p = os.path.join(d, "_telemetry.json")
        run_cycles(r, c, 30, path=p)                                         # 150 s: writes at 0, 60, 120 s
        data = json.load(open(p))
        assert isinstance(data, list) and data and not os.path.exists(p + ".tmp")
        assert len(data) <= len(r._tel_history)                              # unwritten tail is the only loss


def test_failed_replace_keeps_old_file_and_retries_next_cycle(monkeypatch=None):
    import research.null_a.recorder as M
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 60.0, c); p = os.path.join(d, "_telemetry.json")
        r.dump_telemetry(); good = open(p).read()
        real = M.os.replace
        def boom(a, b): raise OSError("disk full")
        M.os.replace = boom
        try:
            c.t += 61; r.dump_telemetry()                                     # due, but replace fails: buried
        finally:
            M.os.replace = real
        assert open(p).read() == good and r.telemetry_writes == 1            # old file intact
        c.t += 5; r.dump_telemetry()                                          # not marked written => retried now
        assert r.telemetry_writes == 2 and len(json.load(open(p))) == 3


def test_canary_watchdog_fields_and_freshness():
    """Fields read by ~/canary_watchdog.py worst()/status and its STALE rule (latest ts older than 600 s)."""
    import time
    with tempfile.TemporaryDirectory() as d:
        c = Clock(); r = rec(d, 60.0, c); p = os.path.join(d, "_telemetry.json")
        r.dump_telemetry()
        latest = json.load(open(p))[-1]
        for k in ("ts", "evidence_capture_latency_ms_p95", "evidence_dropped_records", "evidence_write_success_rate",
                  "evidence_pending_records_on_shutdown", "evidence_captured_total"):
            assert k in latest, k
        assert time.time() - latest["ts"] < 600
