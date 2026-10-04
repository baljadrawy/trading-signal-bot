#!/usr/bin/env python3
"""Continuous collector monitor — OBSERVE ONLY (P2-CR Package D4/D5). HOST side, stdlib only.

  p2f_cont_monitor.py --dataset <dataset_dir> --cid <full container id> --out <monitor_dir> [--once]

Authority (owner decision D5): this program NEVER starts, stops or restarts the collector, never signals any process,
never calls Docker, never writes into the dataset, never deletes anything, never touches trading, Paper, credentials
or W3. It only reads: the container's cgroup files, /proc (process identity, v8 roles), the dataset's health file,
incident state, day-close and seal records, and host free space. It writes only under --out:
  status.json            latest evaluated status (atomic)
  alerts.jsonl           local alert log: one line on entry / escalation / recovery; CRITICAL and STOPPED repeat
                         every 6 h while unresolved (no storms)
  <day>/samples.jsonl    one compact sample every 60 s (memory / CPU / throttling / PIDs / OOM / health / disk)
  <day>/procs.jsonl      v8 process-identity samples every 5 s (same sampler as the accepted v8 gate monitor)
Severity model (P2-CR audit section 3): INFO < WARNING < DEGRADED < CRITICAL < STOPPED.
External delivery (Telegram / email) is deliberately absent (owner D4: not required for the initial start gate).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SEV = ["INFO", "WARNING", "DEGRADED", "CRITICAL", "STOPPED"]
MEM_LIMIT = 402653184
HC = ("python -c \"import json,time,sys;h=json.load(open('/data/health/collector_health.json'));sys.exit(0 if "
      "time.time()*1000-h['ts_ms']<30000 and h['state'] in ('HEALTHY','STARTING','DISABLED','STOPPING','STOPPED') "
      "else 1)\"")
ROLE_EXACT = {"/bin/sh -c " + HC: "healthcheck_shell", "python -c " + HC[len('python -c "'):-1]: "healthcheck_probe",
              "runc init": "healthcheck_runc", "python -m p2_forward": "collector"}
ROLE_PREFIX = {"/usr/local/bin/python -B -c from multiprocessing.spawn import spawn_main; spawn_main(": "certifier",
               "/usr/local/bin/python -B -c from multiprocessing.resource_tracker import main;main(": "tracker"}


def rd(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def jrd(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def kv(text):
    out = {}
    for line in (text or "").splitlines():
        k, _, v = line.partition(" ")
        if v.strip().lstrip("-").isdigit():
            out[k] = int(v)
    return out


def role(p):
    c = p.get("cmdline") or ""
    if c in ROLE_EXACT:
        return ROLE_EXACT[c]
    for pre, r in ROLE_PREFIX.items():
        if c.startswith(pre):
            return r
    return None if p.get("complete") else "incomplete"


class Monitor:
    def __init__(self, a):
        self.a, self.last_sev, self.last_alert, self.unknown = a, None, {}, {}
        self.prev_cpu = None
        os.makedirs(a.out, exist_ok=True)

    def day_dir(self):
        d = os.path.join(self.a.out, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"))
        os.makedirs(d, exist_ok=True)
        return d

    def append(self, name, obj, day=True):
        p = os.path.join(self.day_dir() if day else self.a.out, name)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str) + "\n")

    def procs(self):
        """v8 identity sample via the accepted host sampler (read-only /proc + cgroup)."""
        try:
            out = subprocess.run([sys.executable, os.path.join(HERE, "p2f_proc_sample.py"), self.a.cid],
                                 capture_output=True, text=True, timeout=10).stdout
            detail = json.loads(out.split("\t", 1)[1])
        except (subprocess.SubprocessError, ValueError, IndexError):
            return None, []
        now, bad = {}, []
        for p in detail["procs"]:
            r = role(p)
            if r is None:
                key = (p["pid"], p.get("cmdline"))
                now[key] = self.unknown.get(key, 0) + 1
                if now[key] >= 2:
                    bad.append({"pid": p["pid"], "cmd": (p.get("cmdline") or "")[:200], "samples": now[key]})
        self.unknown = now
        if detail.get("escaped"):
            bad.append({"escaped": [e.get("pid") for e in detail["escaped"]]})
        return detail, bad

    def sample(self):
        a, m = self.a, int(time.time() * 1000)
        scope = f"/sys/fs/cgroup/system.slice/docker-{a.cid}.scope"
        alive = os.path.exists(scope) and bool((rd(scope + "/cgroup.procs") or "").split())
        cpu, mem_ev = kv(rd(scope + "/cpu.stat")), kv(rd(scope + "/memory.events"))
        memst = kv(rd(scope + "/memory.stat"))
        cur = int((rd(scope + "/memory.current") or "0").strip() or 0)
        anon = memst.get("anon")
        h = jrd(os.path.join(a.dataset, "health", "collector_health.json")) or {}
        inc = (jrd(os.path.join(a.dataset, "incidents", "state.json")) or {}).get("incidents", [])
        act = [i for i in inc if i.get("active") and i.get("ack") is None]
        du = shutil.disk_usage(a.dataset)
        days = sorted(f[:-5] for f in os.listdir(os.path.join(a.dataset, "days"))) if os.path.isdir(os.path.join(a.dataset, "days")) else []
        seals = sorted(f[:-5] for f in os.listdir(os.path.join(a.dataset, "seals"))
                       if f.endswith(".json") and not f.endswith(".report.json") and "FAILED" not in f) \
            if os.path.isdir(os.path.join(a.dataset, "seals")) else []
        thr = None
        if self.prev_cpu and cpu.get("nr_periods", 0) > self.prev_cpu.get("nr_periods", 0):
            thr = (cpu.get("nr_throttled", 0) - self.prev_cpu.get("nr_throttled", 0)) / \
                (cpu["nr_periods"] - self.prev_cpu["nr_periods"])
            cpu_cores = (cpu.get("usage_usec", 0) - self.prev_cpu.get("usage_usec", 0)) / 1e6 / max(1e-3, (m - self.prev_cpu["_t"]) / 1000)
        else:
            cpu_cores = None
        self.prev_cpu = {**cpu, "_t": m}
        ins = h.get("instrumentation") or {}
        s = {"t_ms": m, "alive": alive, "health_state": h.get("state"), "health_age_s": None if not h else round((m - h.get("ts_ms", 0)) / 1000, 1),
             "reasons": (h.get("reasons") or [])[:10], "warnings": (h.get("warnings") or [])[:10],
             "mem_current": cur, "mem_anon": anon, "mem_pct_of_limit": round(100 * (anon if anon is not None else cur) / MEM_LIMIT, 1),
             "oom_kill": mem_ev.get("oom_kill"), "pids": int((rd(scope + "/pids.current") or "0").strip() or 0),
             "cpu_cores_60s": None if cpu_cores is None else round(cpu_cores, 3), "throttled_frac_60s": None if thr is None else round(thr, 4),
             "sampler_lateness_max_60s_ms": ins.get("sampler_lateness_max_60s_ms"), "loop_lag_max_60s_ms": ins.get("loop_lag_max_60s_ms"),
             "gc_pause_max_ms": ins.get("gc_pause_max_ms"), "certifier": {k: (h.get("certifier") or {}).get(k) for k in ("alive", "pending", "oldest_pending_age_ms", "failures")},
             "writer": {k: (h.get("writer") or {}).get(k) for k in ("beat_age_ms", "durable_lag_ms", "write_errors")},
             "rest": {k: (h.get("rest") or {}).get(k) for k in ("ip_used_weight_1m_max", "events")},
             "disk_free_gb": round(du.free / 1e9, 1), "dataset_gb": (h.get("disk") or {}).get("collector_dir_gb"),
             "incidents_active": [{k: i.get(k) for k in ("id", "key", "severity", "count")} for i in act][:20],
             "last_closed_day": days[-1] if days else None, "last_sealed_day": seals[-1] if seals else None,
             "universe_epoch": h.get("universe_epoch"), "connection_age_s": h.get("connection_age_s")}
        return s

    def evaluate(self, s, proc_bad):
        r = []
        if not s["alive"]:
            r.append(("STOPPED", "collector_not_running"))
        if s["health_age_s"] is None or s["health_age_s"] > 60:
            r.append(("STOPPED" if not s["alive"] else "CRITICAL", "health_file_stale"))
        for i in s["incidents_active"]:
            r.append((i["severity"] if i["severity"] in SEV else "CRITICAL", f"incident:{i['key']}"))
        if s["health_state"] in ("DEGRADED", "DEGRADED_DISK", "BANNED_418"):
            r.append(("DEGRADED", f"health:{s['health_state']}"))
        if s["health_state"] in ("FAILED", "STOPPED_INCOMPLETE"):
            r.append(("CRITICAL", f"health:{s['health_state']}"))
        if s["mem_pct_of_limit"] >= 90:
            r.append(("CRITICAL", "memory_ge_90pct"))
        elif s["mem_pct_of_limit"] >= 75:
            r.append(("WARNING", "memory_ge_75pct"))
        if s["oom_kill"]:
            r.append(("CRITICAL", f"oom_kill:{s['oom_kill']}"))
        if s["throttled_frac_60s"] is not None and s["throttled_frac_60s"] > 0.10:
            r.append(("WARNING", "cpu_throttled_gt_10pct"))
        if s["disk_free_gb"] < 60:
            r.append(("CRITICAL", "disk_free_lt_60gb"))
        elif s["disk_free_gb"] < 100:
            r.append(("WARNING", "disk_free_lt_100gb"))
        if proc_bad:
            r.append(("CRITICAL", "process_role_violation"))
        sev = max((SEV.index(x) for x, _ in r), default=0)
        return SEV[sev], sorted({why for _, why in r})

    def alert(self, sev, reasons, s):
        m = s["t_ms"]
        key = (sev, tuple(reasons))
        repeat = sev in ("CRITICAL", "STOPPED") and m - self.last_alert.get(key, 0) >= 6 * 3600 * 1000
        if sev != self.last_sev or repeat:
            kind = "recovery" if self.last_sev and SEV.index(sev) < SEV.index(self.last_sev) else ("repeat" if sev == self.last_sev else "entry")
            self.append("alerts.jsonl", {"t_ms": m, "severity": sev, "kind": kind, "reasons": reasons}, day=False)
            self.last_alert[key] = m
        self.last_sev = sev

    def run(self):
        last_full = 0
        while True:
            detail, bad = self.procs()
            if detail is not None:
                self.append("procs.jsonl", {"t_ms": int(time.time() * 1000), "procs": [{k: p.get(k) for k in ("pid", "ppid", "nspid", "cmdline", "complete")}
                                                                                  for p in detail["procs"]], "escaped": detail.get("escaped"), "violations": bad})
            if time.time() - last_full >= 60 or self.a.once:
                s = self.sample()
                sev, reasons = self.evaluate(s, bad)
                s.update(severity=sev, severity_reasons=reasons)
                self.append("samples.jsonl", s)
                tmp = os.path.join(self.a.out, "status.json.tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(s, fh, sort_keys=True, indent=1, default=str)
                os.replace(tmp, os.path.join(self.a.out, "status.json"))
                self.alert(sev, reasons, s)
                last_full = time.time()
            if self.a.once:
                return 0
            time.sleep(5)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True); ap.add_argument("--cid", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--collector-cmdline", default="python -m p2_forward", help="offline harness only")
    a = ap.parse_args(argv)
    ROLE_EXACT[a.collector_cmdline] = "collector"
    if os.path.abspath(a.out).startswith(os.path.abspath(a.dataset) + os.sep):
        sys.exit("monitor output must be outside the dataset (observe only)")
    return Monitor(a).run()


if __name__ == "__main__":
    sys.exit(main())
