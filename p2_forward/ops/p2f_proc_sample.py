#!/usr/bin/env python3
"""v8 gate-monitor process sampler (HOST side, read-only, stdlib). One call = one sample of the collector container's
OWN cgroup scope. Prints one line: '<role hints>\\t<json detail>'.

detail = {"cid", "procs": [{pid, ppid, nspid, comm, cmdline, exe, cgroup, parent_cmdline}], "follow": [...],
          "escaped": [...]}
- every process in the scope's cgroup.procs, with its own identity read immediately from /proc;
- follow-up: a process whose identity is incomplete (gone, empty command line, mid-exec) is re-read every 50 ms for
  up to 2 s so a transient can be reconciled from LATER command information (never trusted on its own);
- escape check: every host process descended from the collector (container PID 1) that is NOT in the scope.
"""
import json, os, sys, time

def rd(p, b=False):
    try:
        with open(p, "rb") as fh:
            d = fh.read()
        return d if b else d.decode(errors="replace")
    except OSError:
        return None

def ident(pid):
    st = rd(f"/proc/{pid}/stat")
    o = {"pid": int(pid)}
    if st and ")" in st:
        comm, rest = st[st.index("(") + 1:st.rindex(")")], st[st.rindex(")") + 2:].split()
        o["comm"], o["ppid"] = comm, int(rest[1])
        pc = rd(f"/proc/{rest[1]}/cmdline", True)
        o["parent_cmdline"] = (pc or b"").replace(b"\0", b" ").decode(errors="replace").strip()[:400]
    cl = rd(f"/proc/{pid}/cmdline", True)
    o["cmdline"] = (cl or b"").replace(b"\0", b" ").decode(errors="replace").strip()[:1024]
    cg = rd(f"/proc/{pid}/cgroup"); o["cgroup"] = (cg or "").strip()
    status = rd(f"/proc/{pid}/status") or ""
    for line in status.splitlines():
        if line.startswith("NSpid:"):
            ns = line.split()[1:]; o["nspid"] = int(ns[-1]) if ns else None
    try:
        o["exe"] = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        o["exe"] = None
    o["complete"] = bool(o.get("comm")) and bool(o["cmdline"])
    return o

def hint(o):
    c = o.get("cmdline") or ""
    if c == "python -m p2_forward": return "collector"
    if "multiprocessing.spawn" in c: return "certifier"
    if "multiprocessing.resource_tracker" in c: return "tracker"
    if "collector_health.json" in c or c == "runc init": return "healthcheck?"
    return "other"

def main():
    cid = sys.argv[1]
    scope = f"/sys/fs/cgroup/system.slice/docker-{cid}.scope"
    pids = (rd(scope + "/cgroup.procs") or "").split()
    procs = [ident(p) for p in pids]
    follow, pending = [], [o["pid"] for o in procs if not o["complete"]]
    end = time.time() + 2.0
    while pending and time.time() < end:
        time.sleep(0.05)
        nxt = []
        for p in pending:
            o = ident(p); o["t_ms"] = int(time.time() * 1000)
            if o.get("comm") or o["cmdline"]:
                follow.append(o)
            if not o["complete"] and os.path.exists(f"/proc/{p}"):
                nxt.append(p)
        pending = nxt
    escaped = []
    col = [o for o in procs if o.get("nspid") == 1 and o.get("cmdline") == "python -m p2_forward"]
    if col:
        root, kids = col[0]["pid"], {}
        for d in os.listdir("/proc"):
            if d.isdigit():
                s = rd(f"/proc/{d}/stat")
                if s and ")" in s:
                    kids.setdefault(int(s[s.rindex(")") + 2:].split()[1]), []).append(int(d))
        inscope, stack = {int(p) for p in pids}, [root]
        while stack:
            for k in kids.get(stack.pop(), []):
                stack.append(k)
                if k not in inscope:
                    escaped.append(ident(k))
    detail = {"cid": cid, "procs": procs, "follow": follow, "escaped": escaped}
    print(",".join(f"{o['pid']}={hint(o)}" for o in procs) + "\t" + json.dumps(detail, separators=(",", ":")))

if __name__ == "__main__":
    main()
