"""CLI for the MI CPU guard (design artifact; NOT installed or started by anything).

python -m mi_cpuguard.guard_main --campaign C --reservation-cpu-s X --ledger PATH --cgroup-dir DIR --kill-unit UNIT
       [--done-units u1,u2]   # DONE when every listed unit is inactive
Exit codes: 0 DONE (charged as measured), 2 KILL (campaign must STOP), 3 refused (no budget / ledger tamper).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import ledger as L
from .guard import Guard, read_usage_usec, systemd_kill


def _inactive(units):
    for u in units:
        r = subprocess.run(["systemctl", "--user", "show", "-p", "ActiveState", "--value", u],
                           capture_output=True, text=True, timeout=10)
        if r.stdout.strip() not in ("inactive", "failed", ""):
            return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--reservation-cpu-s", type=float, required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--cgroup-dir", required=True)
    ap.add_argument("--kill-unit", required=True)
    ap.add_argument("--done-units", default="")
    ap.add_argument("--margin-cpu-s", type=float, default=None)
    ap.add_argument("--poll-s", type=float, default=None)
    a = ap.parse_args(argv)
    kw = {}
    if a.margin_cpu_s is not None:
        kw["margin_cpu_s"] = a.margin_cpu_s
    if a.poll_s is not None:
        kw["poll_s"] = a.poll_s
    done_units = [u for u in a.done_units.split(",") if u]
    g = Guard(reader=lambda: read_usage_usec(a.cgroup_dir), killer=lambda: systemd_kill(a.kill_unit),
              ledger=L.BudgetLedger(a.ledger), campaign=a.campaign, reservation_cpu_s=a.reservation_cpu_s,
              done=(lambda: _inactive(done_units)) if done_units else (lambda: False),
              log=lambda o: print(json.dumps(o), flush=True), **kw)
    try:
        if not g.start():
            return 2
    except (L.BudgetExceeded, L.LedgerTamper) as e:
        print(json.dumps({"verdict": "REFUSED", "reason": str(e)}), flush=True)
        return 3
    out = g.run()
    return 0 if out["verdict"] == "DONE" and not out["stop_campaign"] else 2


if __name__ == "__main__":
    sys.exit(main())
