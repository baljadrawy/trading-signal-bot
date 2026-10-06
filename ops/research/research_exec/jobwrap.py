"""Main process of the job unit (rj-<id>.service).

1. Takes the authoritative flock for the profile's lock class (held for the job's whole life,
   including frozen periods). Busy -> exit 75 without running anything.
2. Runs the command as a child, stdout/stderr to files in the job dir.
3. After the child exits, records wall time, rusage (child + its waited descendants) and the
   unit's own cgroup accounting (cpu.stat, memory.peak, pids.peak, memory.events) while the
   cgroup still exists, then exits with the child's code.
If the unit is SIGKILLed (escalation, OOM group kill) this record is never written; the
watchdog then builds the job record from its own periodic cgroup samples.
"""
from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import time

from . import hostsignals as hs
from .record import atomic_write_json, utc_now

EX_LOCK_BUSY = 75


def main(job_dir: str, lock: str, cmd: list[str]) -> int:
    os.makedirs(job_dir, exist_ok=True)
    out = os.path.join(job_dir, "jobwrap.json")
    with open("/proc/self/oom_score_adj") as fh:
        adj = fh.read().strip()
    rec = {"started_at": utc_now(), "pid": os.getpid(), "cmd": cmd, "lock": lock,
           "oom_score_adj": adj, "cgroup": hs.own_cgroup_dir()}
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    lfd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lfd)
        rec.update(status="lock_busy", finished_at=utc_now(), exit_code=EX_LOCK_BUSY)
        atomic_write_json(out, rec)
        return EX_LOCK_BUSY
    os.ftruncate(lfd, 0)
    os.write(lfd, f"{os.getpid()} {os.environ.get('RESEARCH_JOB_ID', '?')} {utc_now()}\n".encode())
    rec["status"] = "running"
    atomic_write_json(out, rec)

    # systemd stop sends SIGTERM to every process in the cgroup; the child gets it directly.
    # We only note it and keep waiting so the measurement is still written.
    got = {"sig": None}

    def _note(signum, _frame):
        got["sig"] = signum
    signal.signal(signal.SIGTERM, _note)

    t0w, t0 = time.time(), time.monotonic()
    with open(os.path.join(job_dir, "stdout.log"), "ab") as so, \
            open(os.path.join(job_dir, "stderr.log"), "ab") as se:
        child = subprocess.Popen(cmd, stdout=so, stderr=se, stdin=subprocess.DEVNULL)
        rec["child_pid"] = child.pid
        while True:
            try:
                _pid, status, ru = os.wait4(child.pid, 0)
                break
            except InterruptedError:
                continue
    wall = time.monotonic() - t0
    code = os.waitstatus_to_exitcode(status)
    child.returncode = code          # reaped via wait4 (for rusage); tell Popen
    cg = hs.cgroup_stats(rec["cgroup"]) if rec["cgroup"] else {}
    rec.update(
        status="finished", finished_at=utc_now(), exit_code=code, wall_s=round(wall, 3),
        start_epoch=t0w, signal_received=got["sig"],
        rusage_children={"utime_s": ru.ru_utime, "stime_s": ru.ru_stime,
                         "maxrss_kib_largest_process": ru.ru_maxrss},
        cgroup_at_exit=cg,
    )
    atomic_write_json(out, rec)
    return code if code >= 0 else 128 - code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
