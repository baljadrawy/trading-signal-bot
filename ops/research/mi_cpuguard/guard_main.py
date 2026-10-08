"""CLI for the MI CPU guard (runs inside the mi-cpuguard-<campaign> unit; started only by research_exec.mi_campaign).

python -m mi_cpuguard.guard_main --campaign C --reservation-cpu-s X --ledger PATH --cgroup-dir DIR --kill-unit UNIT
       --ready-file F --close-file F [--wait-cgroup-s 30] [--margin-cpu-s 12] [--poll-s 1] [--max-gap-s 3]
       [--anchor-pids 1]
Sequence: wait (bounded) for the MI slice cgroup -> reserve (ledger) -> baseline -> write ready file -> poll.
DONE when the close file exists and the slice holds only the anchor (pids.current <= anchor_pids).
Exit: 0 DONE charged as measured; 2 KILL (campaign must STOP); 3 refused before reserving (no budget, ledger
tamper, cgroup never appeared, bad kill target); 4 STOP after the kill (ledger error while charging; the
reservation stays open and counts as consumed until `research-run mi recover`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time

from . import MARGIN_CPU_S, MAX_POLL_GAP_S, POLL_S
from . import ledger as L
from .guard import Guard, read_usage_usec, systemd_kill

# Only an MI child slice of research.slice may ever be killed: never research.slice itself, never a service,
# scope or container (Collector / Paper / Postgres live in the SYSTEM manager and are unreachable via --user anyway).
KILL_UNIT_RE = re.compile(r"^research-[a-z0-9][a-z0-9-]{0,40}\.slice$")


def valid_kill_target(unit: str, cgroup_dir: str) -> bool:
    if not KILL_UNIT_RE.match(unit or ""):
        return False
    parts = os.path.normpath(cgroup_dir).split(os.sep)
    return len(parts) >= 2 and parts[-1] == unit and parts[-2] == "research.slice"


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _pids(cgroup_dir):
    with open(os.path.join(cgroup_dir, "pids.current"), encoding="ascii") as fh:
        return int(fh.read().strip())


def main(argv=None, *, killer=None, sleep=time.sleep, clock=time.monotonic) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--reservation-cpu-s", type=float, required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--cgroup-dir", required=True)
    ap.add_argument("--kill-unit", required=True)
    ap.add_argument("--ready-file", required=True)
    ap.add_argument("--close-file", required=True)
    ap.add_argument("--wait-cgroup-s", type=float, default=30.0)
    ap.add_argument("--margin-cpu-s", type=float, default=MARGIN_CPU_S)
    ap.add_argument("--poll-s", type=float, default=POLL_S)
    ap.add_argument("--max-gap-s", type=float, default=MAX_POLL_GAP_S)
    ap.add_argument("--anchor-pids", type=int, default=1)
    a = ap.parse_args(argv)

    def say(o):
        print(json.dumps(o, sort_keys=True), flush=True)

    if not valid_kill_target(a.kill_unit, a.cgroup_dir):
        say({"verdict": "REFUSED", "reason": f"kill target not an MI child slice: {a.kill_unit} / {a.cgroup_dir}"})
        return 3
    t_end = clock() + a.wait_cgroup_s
    while not os.path.exists(os.path.join(a.cgroup_dir, "cpu.stat")):
        if clock() > t_end:
            say({"verdict": "REFUSED", "reason": "MI slice cgroup never appeared (no reservation taken)"})
            return 3
        sleep(0.2)
    kill = killer or (lambda: systemd_kill(a.kill_unit))

    def done():
        if not os.path.exists(a.close_file):
            return False
        try:
            return _pids(a.cgroup_dir) <= a.anchor_pids
        except Exception:
            return False                      # unreadable pids -> not done; the counter read decides faults

    g = Guard(reader=lambda: read_usage_usec(a.cgroup_dir), killer=kill, ledger=L.BudgetLedger(a.ledger),
              campaign=a.campaign, reservation_cpu_s=a.reservation_cpu_s, margin_cpu_s=a.margin_cpu_s,
              poll_s=a.poll_s, max_gap_s=a.max_gap_s, done=done, log=say, sleep=sleep, clock=clock)

    def on_signal(signum, _frame):
        g.stop_requested = signal.Signals(signum).name

    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, on_signal)
        except ValueError:                    # not in the main thread (tests)
            pass
    try:
        if not g.start():
            return 2
    except (L.BudgetExceeded, L.LedgerTamper) as e:
        say({"verdict": "REFUSED", "reason": f"{type(e).__name__}: {e}"})
        return 3
    try:
        _atomic_json(a.ready_file, {"campaign": a.campaign, "baseline_usec": g.baseline, "pid": os.getpid(),
                                    "invocation_id": os.environ.get("INVOCATION_ID"),
                                    "reservation_cpu_s": a.reservation_cpu_s, "limit_cpu_s": g.limit})
        out = g.run()
    except Exception as e:                     # e.g. LedgerTamper while charging: the kill already happened
        try:
            kill()
        finally:
            say({"verdict": "STOP", "reason": f"{type(e).__name__}: {e}", "reservation_left_open": True})
        return 4
    return 0 if out["verdict"] == "DONE" and not out["stop_campaign"] else 2


if __name__ == "__main__":
    sys.exit(main())
