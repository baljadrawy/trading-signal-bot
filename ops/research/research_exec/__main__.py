"""CLI: python3 -m research_exec <command> ...   (or ops/research/bin/research-run)

  run      --job-id ID --owner TAG [--profile R1] [--workers N] [--max-runtime-s S]
           [--allow-elevated] [--attended] [--cwd DIR] [--setenv K=V ...] [--config F] [--wait] -- CMD...
  admit    [--profile R1] [--config F]          dry admission check, prints the decision (exit 0/3)
  status   --job-id ID                          unit states
  freeze | thaw | kill  --job-id ID             manual control of the job unit (kill = group SIGKILL)
  record   --job-id ID [--config F]             print (re)built job_record.json
  profiles [--config F]                          print effective profiles and thresholds
Internal (used inside units): _jobwrap, _watchdog.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import admission, config, launcher


def _cfg(args):
    return config.load_config(getattr(args, "config", None))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_jobwrap":
        from . import jobwrap
        job_dir, lock = argv[1], argv[2]
        cmd = argv[4:] if len(argv) > 3 and argv[3] == "--" else argv[3:]
        return jobwrap.main(job_dir, lock, cmd)
    if argv and argv[0] == "_watchdog":
        from . import watchdog
        ap = argparse.ArgumentParser(prog="_watchdog")
        ap.add_argument("job_dir")
        ap.add_argument("unit")
        ap.add_argument("--config")
        a = ap.parse_args(argv[1:])
        return watchdog.main(config.load_config(a.config), a.job_dir, a.unit)

    cmd = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="research-run")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--job-id", required=True)
    r.add_argument("--owner", required=True)
    r.add_argument("--profile", default="R1")
    r.add_argument("--workers", type=int)
    r.add_argument("--max-runtime-s", type=int)
    r.add_argument("--allow-elevated", action="store_true")
    r.add_argument("--attended", action="store_true")
    r.add_argument("--cwd")
    r.add_argument("--setenv", action="append", default=[])
    r.add_argument("--config")
    r.add_argument("--wait", action="store_true")
    r.add_argument("--mi-campaign", help="opt-in MI Phase 1S campaign (requires config mi.enabled)")
    mi = sub.add_parser("mi", help="MI campaign lifecycle (opt-in; config mi.enabled)")
    mi.add_argument("action", choices=["init", "open", "close", "recover", "status", "ledger-check",
                                       "ledger-recover"])
    mi.add_argument("--campaign")
    mi.add_argument("--reservation-cpu-s", type=float)
    mi.add_argument("--approve-genesis", action="store_true", help="init only: first-ever genesis (owner)")
    mi.add_argument("--recover-action", choices=["rebuild-checkpoints", "torn-tail", "restore-backup", "carry-forward"])
    mi.add_argument("--approve", help="owner approval token printed by `mi ledger-check`")
    mi.add_argument("--by", default=os.environ.get("USER", "owner"))
    mi.add_argument("--backup")
    mi.add_argument("--declared-consumed-cpu-s", type=float)
    mi.add_argument("--declared-campaigns", default="")
    mi.add_argument("--config")
    ad = sub.add_parser("admit")
    ad.add_argument("--profile", default="R1")
    ad.add_argument("--config")
    for name in ("status", "freeze", "thaw", "kill"):
        s = sub.add_parser(name)
        s.add_argument("--job-id", required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--job-id", required=True)
    rc.add_argument("--config")
    pf = sub.add_parser("profiles")
    pf.add_argument("--config")
    a = ap.parse_args(argv)

    if a.command == "run":
        cfg = _cfg(a)
        try:
            prof = config.resolve_profile(cfg, a.profile, workers=a.workers,
                                          allow_elevated=a.allow_elevated, attended=a.attended,
                                          max_runtime_s=a.max_runtime_s)
            return launcher.launch(cfg, job_id=a.job_id, owner=a.owner, profile=prof, cmd=cmd,
                                   cwd=a.cwd, setenv=a.setenv, config_path=a.config, wait=a.wait,
                                   mi_campaign=a.mi_campaign)
        except (ValueError, PermissionError, FileExistsError, RuntimeError) as exc:
            print(f"research-run: {exc}", file=sys.stderr)
            return 2
    if a.command == "mi":
        from . import mi_campaign as MIC
        cfg = _cfg(a)
        try:
            if a.action == "init":
                out = MIC.init_ledger(cfg, approve_genesis=a.approve_genesis, by=a.by)
            elif a.action == "ledger-check":
                out = MIC.ledger_check(cfg)
            elif a.action == "ledger-recover":
                out = MIC.ledger_recover(cfg, a.recover_action, approve=a.approve or "", by=a.by, backup=a.backup,
                                         declared_consumed_cpu_s=a.declared_consumed_cpu_s,
                                         declared_campaigns=[c for c in a.declared_campaigns.split(",") if c])
            elif a.action == "open":
                if not a.campaign or a.reservation_cpu_s is None:
                    raise MIC.MIError("open needs --campaign and --reservation-cpu-s")
                out = MIC.open_campaign(cfg, a.campaign, a.reservation_cpu_s, ensure_parent=launcher.ensure_slice)
            elif a.action == "close":
                out = MIC.close_campaign(cfg, a.campaign)
            elif a.action == "recover":
                out = MIC.recover_campaign(cfg, a.campaign)
            else:
                out = MIC.status(cfg)
        except Exception as exc:                     # incl. LedgerTamper / BudgetExceeded: fail closed, exit 2
            print(f"research-run mi: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return 0
    if a.command == "admit":
        cfg = _cfg(a)
        prof = config.resolve_profile(cfg, a.profile, workers=None, allow_elevated=True,
                                      attended=True, max_runtime_s=None)
        d = admission.evaluate(cfg, prof)
        print(json.dumps(d, indent=2, sort_keys=True, default=str))
        return 0 if d["admit"] else 3
    if a.command in ("status", "freeze", "thaw", "kill"):
        return launcher.control(a.job_id, a.command)
    if a.command == "record":
        from .watchdog import build_job_record
        cfg = _cfg(a)
        rec = build_job_record(os.path.join(cfg["state_dir"], "jobs", a.job_id))
        print(json.dumps(rec, indent=2, sort_keys=True, default=str))
        return 0
    if a.command == "profiles":
        cfg = _cfg(a)
        print(json.dumps({k: cfg[k] for k in ("profiles", "slice", "admission", "watchdog",
                                               "windows_utc", "health_path", "state_dir")},
                         indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
