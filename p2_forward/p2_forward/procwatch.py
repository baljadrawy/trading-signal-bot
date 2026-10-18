"""In-container process-role self-check (P2-CR Package F, continuous mode only).

The collector is PID 1 of its container PID namespace, so /proc lists exactly the container's processes. Allowed
roles mirror the accepted v8 specification (the verifier's G3 spec v8 `process_roles`; a test pins equality):
  collector (this process), certifier and multiprocessing resource tracker (children of the collector), and the
  pinned Docker HEALTHCHECK chain (`runc init`, `/bin/sh -c <HC_CMD>`, `python -c <probe>`), which is transient.
Anything else is unexpected. An unexpected process seen in `persist` consecutive checks is a role violation (the
caller fails closed); a single sighting is reported as a warning incident. Read-only: /proc reads only; never
signals, kills or inspects another process's memory or environment.

Known limit (P2-E1 closure, NON-BLOCKING TRUST-BOUNDARY LIMITATION): a `docker exec` of the exact pinned
HEALTHCHECK command is indistinguishable from Docker's own probe. Restricting Docker exec access is the mitigation.
"""
from __future__ import annotations

import os

HC_CMD = ("python -c \"import json,time,sys;h=json.load(open('/data/health/collector_health.json'));sys.exit(0 if "
          "time.time()*1000-h['ts_ms']<30000 and h['state'] in ('HEALTHY','STARTING','DISABLED','STOPPING','STOPPED') "
          "else 1)\"")
SHELL_CMDLINE = "/bin/sh -c " + HC_CMD
PROBE_CMDLINE = "python -c " + HC_CMD[len('python -c "'):-1]
CERTIFIER_PREFIX = "/usr/local/bin/python -B -c from multiprocessing.spawn import spawn_main; spawn_main("
TRACKER_PREFIX = "/usr/local/bin/python -B -c from multiprocessing.resource_tracker import main;main("
TRANSIENT = ("runc init",)


def _read(pid: str):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmd = fh.read().rstrip(b"\0").replace(b"\0", b" ").decode("utf-8", "replace")
        with open(f"/proc/{pid}/stat", "rb") as fh:
            st = fh.read().decode("utf-8", "replace")
        ppid = int(st[st.rindex(")") + 2:].split()[1])
        return cmd, ppid
    except (OSError, ValueError, IndexError):
        return None                                           # exited between listdir and read: not a sighting


def classify(pid: int, cmd: str, ppid: int, self_pid: int, self_cmd: str) -> str | None:
    """Role name, or None if unexpected."""
    if pid == self_pid:
        return "collector" if cmd == self_cmd else None
    if ppid == self_pid and cmd.startswith(CERTIFIER_PREFIX):
        return "certifier"
    if ppid == self_pid and cmd.startswith(TRACKER_PREFIX):
        return "tracker"
    if cmd == SHELL_CMDLINE:
        return "healthcheck_shell"
    if cmd == PROBE_CMDLINE:
        return "healthcheck_probe"
    if cmd in TRANSIENT or cmd == "":                          # runc init / zombie or kernel-cleared cmdline
        return "transient"
    return None


class ProcWatch:
    def __init__(self, persist: int = 2):
        self.self_pid = os.getpid()
        self.self_cmd = _read(str(self.self_pid))[0] if _read(str(self.self_pid)) else ""
        self.enabled = self.self_pid == 1                       # only meaningful inside the container PID namespace
        self.persist = persist
        self.seen = {}                                           # (pid, cmd) -> consecutive sightings
        self.checks = 0
        self.last = {}

    def check(self) -> tuple:
        """Returns (violations, transients): lists of {"pid", "ppid", "cmd", "count"} (cmd truncated to 300)."""
        if not self.enabled:
            return [], []
        self.checks += 1
        now, roles = {}, {}
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            r = _read(pid)
            if r is None:
                continue
            cmd, ppid = r
            role = classify(int(pid), cmd, ppid, self.self_pid, self.self_cmd)
            roles[role or "unexpected"] = roles.get(role or "unexpected", 0) + 1
            if role is None:
                key = (int(pid), cmd)
                now[key] = self.seen.get(key, 0) + 1
        self.seen = now
        self.last = roles
        viol, trans = [], []
        for (pid, cmd), n in now.items():
            item = {"pid": pid, "cmd": cmd[:300], "count": n}
            (viol if n >= self.persist else trans).append(item)
        return viol, trans
