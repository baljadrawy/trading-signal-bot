#!/usr/bin/env python3
"""Continuous collector monitor — OBSERVE ONLY (P2-CR Package D4/D5). HOST side, stdlib only.

  p2f_cont_monitor.py --dataset <dataset_dir> (--binding-file <binding.json> | --cid <full container id>) --out <monitor_dir> [--once]
  p2f_cont_monitor.py --record-exit --out <monitor_dir>          (systemd ExecStopPost hook; G4)

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

G4 supervision (additive; the four files above keep their formats):
  .monitor.lock          exclusive flock held for the whole process lifetime: a second lock-honouring instance on
                         the same --out refuses BEFORE writing anything (exit 75). A process that does not honour the
                         lock (a legacy monitor on the same --out, seen in two consecutive /proc scans) makes this
                         monitor stop writing and exit 75: never two concurrent writers.
  monitor_lifecycle.jsonl  start / exit records (pid, unit, invocation, binding, previous status age = the gap).
  status.json "monitor"  writer identity (pid, systemd unit + invocation, container binding, Docker-free binding check)
                         so a consumer (G2 admission/watchdog) can verify WHO wrote the status and against WHICH container.
  Binding: --binding-file names the container explicitly (written by p2f_monitor_bind.py from `docker inspect` of the
  container NAME). The monitor itself stays Docker-free: each full sample proves the bound scope still runs the
  collector with this dataset mounted at /data (same device+inode); a stale binding (bound scope gone while another
  scope runs a collector on this dataset) is CRITICAL `binding_stale`, a wrong dataset is CRITICAL
  `binding_dataset_mismatch`. It never silently follows a new container: re-binding is an explicit step.
  systemd: Type=notify READY after the first status write, WATCHDOG=1 every loop (a hung loop is killed and restarted).

G3 readiness (additive): the collector's limits are read from its cgroup scope (cpu.max, memory.max, memory.swap.max,
  pids.max) at every sample instead of a hard-coded 384 MiB. status.json "limits" = raw + parsed values, the expectation
  (binding "limits" recorded by p2f_monitor_bind.py, else this process's first observation) and any mismatch.
  mem_pct_of_limit uses the observed memory.max (None when unlimited / unreadable -> WARNING memory_limit_unknown);
  samples gain mem_limit_bytes, cpu_quota_cores, cpu_pct_of_quota and swap_current. A limit that differs from the
  expectation is WARNING limit_mismatch:<file>; an unreadable / malformed / unlimited limit is WARNING limit_<file>_*.

Health-episode coalescing (optional, --coalesce-health-episodes; OFF by default = the behaviour above, byte for byte):
  a collector `health:DEGRADED` no longer produces entry / recovery lines of its own. Instead alerts.jsonl gets ONE
  `health_episode` line when the episode ends: start_ms, end_ms, duration_s, samples, streams, causes, reasons, end
  state. An episode still open after --episode-open-alert-s (default 300 s) also gets one `health_episode_open` line at
  that point, so a long degradation is never silent. Resolution is the full-sample interval (60 s): start = first
  sample that saw DEGRADED, end = first sample that did not. Every other reason (incidents, DEGRADED_DISK, BANNED_418,
  FAILED, stale health file, memory, binding ...) alerts exactly as before; status.json and samples are unchanged.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SEV = ["INFO", "WARNING", "DEGRADED", "CRITICAL", "STOPPED"]
EX_DUPLICATE, EX_CONFIG = 75, 78          # never restarted by systemd (RestartPreventExitStatus): a config/ownership fault
BINDING_SCHEMA = "p2f-monitor-binding-v1"
CID_RE = re.compile(r"^[0-9a-f]{64}$")
LOCK_NAME, LIFECYCLE = ".monitor.lock", "monitor_lifecycle.jsonl"
CGROOT = "/sys/fs/cgroup/system.slice"
# G3 readiness: the collector's limits are READ from its cgroup scope at every sample (no hard-coded copy of the
# compose limits). The binding file may carry the limits recorded at bind time (p2f_monitor_bind.py); without one the
# first observation of this process is the baseline. A difference is a WARNING `limit_mismatch:<file>`; an unreadable
# or unlimited ("max") memory limit is a WARNING and the memory thresholds are then not evaluated (None, not a guess).
LIMIT_FILES = ("cpu.max", "memory.max", "memory.swap.max", "pids.max")
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


def read_limits(scope):
    """Effective limits of a cgroup v2 scope, Docker-free. Raw strings as the kernel shows them plus parsed values:
    memory_max_bytes / pids_max (int, or None for "max" / unreadable), cpu quota and period (us) and quota in cores.
    `problems` lists what is unreadable, malformed or unlimited."""
    raw = {f: (rd(os.path.join(scope, f)) or "").strip() or None for f in LIMIT_FILES}
    out = {"source": "cgroup", "scope": os.path.basename(scope), "cpu_max_raw": raw["cpu.max"],
           "memory_max_raw": raw["memory.max"], "memory_swap_max_raw": raw["memory.swap.max"],
           "pids_max_raw": raw["pids.max"], "memory_max_bytes": None, "memory_swap_max_bytes": None, "pids_max": None,
           "cpu_quota_us": None, "cpu_period_us": None, "cpu_quota_cores": None, "problems": []}
    for f, key in (("memory.max", "memory_max_bytes"), ("memory.swap.max", "memory_swap_max_bytes"), ("pids.max", "pids_max")):
        v = raw[f]
        if v is None:
            out["problems"].append(f"{f}_unreadable")
        elif v == "max":
            out["problems"].append(f"{f}_unlimited")
        elif v.isdigit() and int(v) > 0 or (v == "0" and f == "memory.swap.max"):
            out[key] = int(v)
        else:
            out["problems"].append(f"{f}_malformed")
    v = (raw["cpu.max"] or "").split()
    if not v:
        out["problems"].append("cpu.max_unreadable")
    elif len(v) == 2 and v[1].isdigit() and int(v[1]) > 0 and (v[0] == "max" or v[0].isdigit() and int(v[0]) > 0):
        out["cpu_period_us"] = int(v[1])
        if v[0] == "max":
            out["problems"].append("cpu.max_unlimited")
        else:
            out["cpu_quota_us"] = int(v[0])
            out["cpu_quota_cores"] = round(int(v[0]) / int(v[1]), 4)
    else:
        out["problems"].append("cpu.max_malformed")
    return out


def limit_expectation(binding):
    """Bound expectation {file: raw string} from the binding file (p2f_monitor_bind.py >= G3 readiness), else None."""
    lim = (binding or {}).get("limits") if isinstance(binding, dict) else None
    if not isinstance(lim, dict):
        return None
    exp = {f: lim.get(f) for f in LIMIT_FILES if isinstance(lim.get(f), str)}
    return exp or None


def role(p):
    c = p.get("cmdline") or ""
    if c in ROLE_EXACT:
        return ROLE_EXACT[c]
    for pre, r in ROLE_PREFIX.items():
        if c.startswith(pre):
            return r
    return None if p.get("complete") else "incomplete"


def sd_notify(msg):
    """systemd notify protocol, stdlib only; a no-op outside a Type=notify unit."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sk:
            sk.connect("\0" + addr[1:] if addr.startswith("@") else addr)
            sk.sendall(msg.encode())
    except OSError:
        pass


def sha256_file(p):
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def own_unit():
    """(supervisor, unit) from this process's cgroup: a systemd user service, or none (manual / tmux / test)."""
    leaf = (rd("/proc/self/cgroup") or "").strip().rsplit("/", 1)[-1]
    if os.environ.get("INVOCATION_ID") and leaf.endswith(".service") and "/user@" in (rd("/proc/self/cgroup") or ""):
        return "systemd-user", leaf
    return "none", None


def acquire_lock(out):
    """Exclusive single-writer lock on <out>/.monitor.lock (kept open for the process lifetime; never deleted)."""
    fd = os.open(os.path.join(out, LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o664)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def proc_argv(pid):
    raw = rd_bytes(f"/proc/{pid}/cmdline")
    return [x.decode(errors="replace") for x in raw.split(b"\0")[:-1]] if raw else []


def rd_bytes(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def starttime(pid):
    st = rd(f"/proc/{pid}/stat")
    return st[st.rindex(")") + 2:].split()[19] if st and ")" in st else None


def monitors_on(out, exclude=()):
    """Other processes running this monitor (not the exit hook) with the same --out (resolved like they resolve it)."""
    real, found = os.path.realpath(out), []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in exclude:
            continue
        argv = proc_argv(d)
        if not any(x.endswith("p2f_cont_monitor.py") for x in argv) or "--record-exit" in argv:
            continue
        o = next((argv[i + 1] for i, x in enumerate(argv[:-1]) if x == "--out"), None) or \
            next((x.split("=", 1)[1] for x in argv if x.startswith("--out=")), None)
        if o is None:
            continue
        try:
            cwd = os.readlink(f"/proc/{d}/cwd")
        except OSError:
            continue
        if os.path.realpath(os.path.join(cwd, o)) == real:
            found.append((int(d), starttime(d)))
    return found


def same_inode(a, b):
    try:
        x, y = os.stat(a), os.stat(b)
    except OSError:
        return None
    return (x.st_dev, x.st_ino) == (y.st_dev, y.st_ino)


def collector_in_scope(scope, dataset, collector_cmd):
    """Docker-free proof: pid of the collector process in this cgroup scope, and whether its /data IS this dataset."""
    for pid in (rd(scope + "/cgroup.procs") or "").split():
        if " ".join(proc_argv(pid)) == collector_cmd:
            return int(pid), same_inode(f"/proc/{pid}/root/data", dataset)
    return None, None


def load_binding(path, dataset):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        b = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"binding file unreadable: {exc}") from None
    if b.get("schema") != BINDING_SCHEMA or not CID_RE.match(str(b.get("cid"))) or not b.get("container_name"):
        raise SystemExit(f"binding file invalid (schema/cid/container_name): {path}")
    if os.path.realpath(b.get("dataset") or "") != os.path.realpath(dataset):
        raise SystemExit(f"binding dataset {b.get('dataset')!r} != --dataset {dataset!r}")
    b["_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    return b


def episode_reason(reason):
    """(stream or None, cause) of a collector health reason, for episode summaries. `gap_*:<stream>:<cause>` gives
    the gap cause, `stale:` / `not_ready:` / `awaiting_post_reconnect:` / `stream_failed:` the reason kind, and any
    other reason (connection, writer, task, incident ...) is its own cause."""
    kind, _, rest = reason.partition(":")
    if kind in ("gap_short", "gap_open"):
        stream, sep, cause = rest.rpartition(":")
        return (stream, f"{kind}:{cause}") if sep and stream else (None, reason)
    if kind in ("stale", "not_ready", "awaiting_post_reconnect") and rest:
        return rest, kind
    if kind == "stream_failed" and rest:
        return rest.rsplit(":", 1)[0], kind
    return None, reason


class Monitor:
    def __init__(self, a):
        self.a, self.last_sev, self.last_alert, self.unknown = a, None, {}, {}
        self.prev_cpu = None
        self.t0 = time.time()
        self.foreign_seen = set()
        self.ident = getattr(a, "ident", None) or {}
        self.limit_expect = getattr(a, "limit_expect", None)      # from the binding file (or None)
        self.limit_baseline = None                                # first observation (no binding limits)
        self.coalesce = bool(getattr(a, "coalesce_health_episodes", False))   # optional, OFF by default
        self.episode_open_alert_ms = 1000 * int(getattr(a, "episode_open_alert_s", 300) or 300)
        self.episode = None
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
        scope = f"{CGROOT}/docker-{a.cid}.scope"
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
        lim = self.limits(scope) if alive else dict(read_limits(scope), problems=[], not_alive=True)
        ins = h.get("instrumentation") or {}
        s = {"t_ms": m, "alive": alive, "health_state": h.get("state"), "health_age_s": None if not h else round((m - h.get("ts_ms", 0)) / 1000, 1),
             "reasons": (h.get("reasons") or [])[:10], "warnings": (h.get("warnings") or [])[:10],
             "mem_current": cur, "mem_anon": anon, "mem_limit_bytes": lim["memory_max_bytes"],
             "mem_pct_of_limit": None if not lim["memory_max_bytes"] else
             round(100 * (anon if anon is not None else cur) / lim["memory_max_bytes"], 1),
             "cpu_quota_cores": lim["cpu_quota_cores"],
             "cpu_pct_of_quota": None if cpu_cores is None or not lim["cpu_quota_cores"] else
             round(100 * cpu_cores / lim["cpu_quota_cores"], 1),
             "swap_current": int((rd(scope + "/memory.swap.current") or "0").strip() or 0) if alive else None,
             "oom_kill": mem_ev.get("oom_kill"), "pids": int((rd(scope + "/pids.current") or "0").strip() or 0),
             "cpu_cores_60s": None if cpu_cores is None else round(cpu_cores, 3), "throttled_frac_60s": None if thr is None else round(thr, 4),
             "sampler_lateness_max_60s_ms": ins.get("sampler_lateness_max_60s_ms"), "loop_lag_max_60s_ms": ins.get("loop_lag_max_60s_ms"),
             "gc_pause_max_ms": ins.get("gc_pause_max_ms"), "certifier": {k: (h.get("certifier") or {}).get(k) for k in ("alive", "pending", "oldest_pending_age_ms", "failures")},
             "writer": {k: (h.get("writer") or {}).get(k) for k in ("beat_age_ms", "durable_lag_ms", "write_errors")},
             "rest": {k: (h.get("rest") or {}).get(k) for k in ("ip_used_weight_1m_max", "events")},
             "disk_free_gb": round(du.free / 1e9, 1), "dataset_gb": (h.get("disk") or {}).get("collector_dir_gb"),
             "incidents_active": [{k: i.get(k) for k in ("id", "key", "severity", "count")} for i in act][:20],
             "last_closed_day": days[-1] if days else None, "last_sealed_day": seals[-1] if seals else None,
             "universe_epoch": h.get("universe_epoch"), "connection_age_s": h.get("connection_age_s"),
             "_limits": lim}
        if self.coalesce:
            s["_health_reasons"] = list(h.get("reasons") or [])   # full list (episode detail); never written as is
        return s

    def limits(self, scope):
        """Observed limits + comparison with the expectation (binding) or the first observation of this process."""
        lim = read_limits(scope)
        obs = {f: lim[k] for f, k in (("cpu.max", "cpu_max_raw"), ("memory.max", "memory_max_raw"),
                                       ("memory.swap.max", "memory_swap_max_raw"), ("pids.max", "pids_max_raw"))}
        if self.limit_expect:
            exp, src = self.limit_expect, "binding"
        else:
            if self.limit_baseline is None and all(obs.values()):
                self.limit_baseline = dict(obs)
            exp, src = self.limit_baseline, "first_observation"
        lim["expected"], lim["expected_source"] = exp, src if exp else "none"
        lim["mismatch"] = sorted(f for f, v in (exp or {}).items() if obs.get(f) != v)
        return lim

    def binding_check(self, s):
        """Docker-free validation that the bound container is the collector of THIS dataset (each full sample)."""
        a = self.a
        scope = f"{CGROOT}/docker-{a.cid}.scope"
        pid, mount_ok = collector_in_scope(scope, a.dataset, a.collector_cmdline) if s["alive"] else (None, None)
        bc = {"cid12": a.cid[:12], "scope_alive": s["alive"], "collector_pid": pid, "dataset_mount_ok": mount_ok,
              "other_collectors": []}
        if not s["alive"]:
            try:
                scopes = [x for x in os.listdir(CGROOT) if x.startswith("docker-") and x.endswith(".scope")]
            except OSError:
                scopes = []
            for x in scopes:
                p, ok = collector_in_scope(os.path.join(CGROOT, x), a.dataset, a.collector_cmdline)
                if p is not None and ok:
                    bc["other_collectors"].append(x[len("docker-"):len("docker-") + 12])
        return bc

    def foreign_writers(self):
        """Confirmed (seen in two consecutive scans, same pid+starttime) non-lock-honouring writers on this --out."""
        now = set(monitors_on(self.a.out, exclude={os.getpid()}))
        confirmed = now & self.foreign_seen
        self.foreign_seen = now
        return sorted(confirmed)

    def lifecycle(self, obj):
        self.append(LIFECYCLE, dict(obj, t_ms=int(time.time() * 1000)), day=False)

    def evaluate(self, s, proc_bad):
        r = self.severity_reasons(s, proc_bad)
        sev = max((SEV.index(x) for x, _ in r), default=0)
        return SEV[sev], sorted({why for _, why in r})

    def severity_reasons(self, s, proc_bad):
        """[(severity, reason)] for one full sample (evaluate() reduces it to the overall severity)."""
        r = []
        if not s["alive"]:
            r.append(("STOPPED", "collector_not_running"))
        if s["health_age_s"] is None or s["health_age_s"] > 60:
            starting = s["alive"] and s["health_age_s"] is None and time.time() - self.t0 < 120
            r.append(("WARNING" if starting else "STOPPED" if not s["alive"] else "CRITICAL",
                      "health_file_not_yet_written" if starting else "health_file_stale"))
        for i in s["incidents_active"]:
            r.append((i["severity"] if i["severity"] in SEV else "CRITICAL", f"incident:{i['key']}"))
        if s["health_state"] in ("DEGRADED", "DEGRADED_DISK", "BANNED_418"):
            r.append(("DEGRADED", f"health:{s['health_state']}"))
        if s["health_state"] in ("FAILED", "STOPPED_INCOMPLETE"):
            r.append(("CRITICAL", f"health:{s['health_state']}"))
        lim = s.get("_limits") or {}
        if s["mem_pct_of_limit"] is None:
            if s["alive"]:
                r.append(("WARNING", "memory_limit_unknown"))                  # thresholds not evaluable: visible
        elif s["mem_pct_of_limit"] >= 90:
            r.append(("CRITICAL", "memory_ge_90pct"))
        elif s["mem_pct_of_limit"] >= 75:
            r.append(("WARNING", "memory_ge_75pct"))
        if s["alive"]:
            for pr in lim.get("problems") or []:
                if pr != "memory.max_unlimited":                               # already memory_limit_unknown
                    r.append(("WARNING", f"limit_{pr}"))
            for f in lim.get("mismatch") or []:
                r.append(("WARNING", f"limit_mismatch:{f}"))
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
        bc = s.get("_binding") or {}
        if bc.get("scope_alive") and bc.get("collector_pid") and bc.get("dataset_mount_ok") is False:
            r.append(("CRITICAL", "binding_dataset_mismatch"))
        for o in bc.get("other_collectors") or []:
            r.append(("CRITICAL", f"binding_stale:collector_now={o}"))
        return r

    def episode_step(self, s, health_reasons):
        """Coalescing mode: track one collector health:DEGRADED episode; write one line when it ends (and one
        `health_episode_open` line once it has lasted episode_open_alert_ms)."""
        m, deg = s["t_ms"], s.get("health_state") == "DEGRADED"
        ep = self.episode
        if deg:
            if ep is None:
                ep = self.episode = {"start_ms": m, "samples": 0, "streams": set(), "causes": set(), "reasons": set(),
                                     "open_alerted": False}
            ep["samples"] += 1
            for r in health_reasons:
                stream, cause = episode_reason(r)
                ep["reasons"].add(r)
                ep["causes"].add(cause)
                if stream:
                    ep["streams"].add(stream)
            if not ep["open_alerted"] and m - ep["start_ms"] >= self.episode_open_alert_ms:
                ep["open_alerted"] = True
                self.append("alerts.jsonl", dict(self.episode_summary(ep, m), kind="health_episode_open"), day=False)
        elif ep is not None:
            self.append("alerts.jsonl", dict(self.episode_summary(ep, m), kind="health_episode", end_ms=m,
                                             end_state=s.get("health_state")), day=False)
            self.episode = None

    @staticmethod
    def episode_summary(ep, m):
        return {"t_ms": m, "severity": "DEGRADED", "reasons": sorted(ep["reasons"])[:50], "start_ms": ep["start_ms"],
                "duration_s": round((m - ep["start_ms"]) / 1000, 1), "samples": ep["samples"],
                "streams": sorted(ep["streams"])[:50], "streams_total": len(ep["streams"]), "causes": sorted(ep["causes"])}

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
        last_full, ready = 0, False
        while True:
            detail, bad = self.procs()
            if detail is not None:
                self.append("procs.jsonl", {"t_ms": int(time.time() * 1000), "procs": [{k: p.get(k) for k in ("pid", "ppid", "nspid", "cmdline", "complete")}
                                                                                  for p in detail["procs"]], "escaped": detail.get("escaped"), "violations": bad})
            if time.time() - last_full >= 60 or self.a.once:
                fw = self.foreign_writers()
                if fw:
                    # A writer that does not honour the lock shares --out: stop writing (single writer), fail visibly.
                    why = [f"duplicate_monitor_writer:pid={p}" for p, _ in fw]
                    self.append("alerts.jsonl", {"t_ms": int(time.time() * 1000), "severity": "CRITICAL",
                                                 "kind": "monitor_yield", "reasons": why}, day=False)
                    self.lifecycle({"event": "yield", "pid": os.getpid(), "reasons": why})
                    sd_notify("STATUS=yielded to a non-lock-honouring writer; exiting 75")
                    return EX_DUPLICATE
                s = self.sample()
                bc = self.binding_check(s)
                sev, reasons = self.evaluate(dict(s, _binding=bc), bad)
                s.update(severity=sev, severity_reasons=reasons)
                lim = s.pop("_limits", None)
                health_reasons = s.pop("_health_reasons", None)
                self.append("samples.jsonl", s)
                tmp = os.path.join(self.a.out, "status.json.tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(dict(s, limits=lim, monitor=dict(self.ident, binding_check=bc, status_written_ms=s["t_ms"])), fh,
                              sort_keys=True, indent=1, default=str)
                os.replace(tmp, os.path.join(self.a.out, "status.json"))
                if self.coalesce:                    # health:DEGRADED -> one line per episode; all else as before
                    rest = [x for x in self.severity_reasons(dict(s, _limits=lim, _binding=bc), bad)
                            if x[1] != "health:DEGRADED"]
                    self.alert(SEV[max((SEV.index(x) for x, _ in rest), default=0)], sorted({w for _, w in rest}), s)
                    self.episode_step(s, health_reasons or [])
                else:
                    self.alert(sev, reasons, s)
                last_full = time.time()
                if not ready:
                    sd_notify("READY=1")
                    ready = True
                sd_notify(f"STATUS=severity={sev} cid={self.a.cid[:12]} reasons={','.join(reasons)[:200]}")
            if self.a.once:
                return 0
            sd_notify("WATCHDOG=1")
            time.sleep(5)


def record_exit(out):
    """systemd ExecStopPost hook: record how the monitor process ended (it has exited; its lock is free).
    A non-success result also becomes a CRITICAL alert line, so a crash or crash loop is never silent."""
    env = {k: os.environ.get(k) for k in ("SERVICE_RESULT", "EXIT_CODE", "EXIT_STATUS", "INVOCATION_ID")}
    os.makedirs(out, exist_ok=True)
    fd = None
    for _ in range(50):                      # the exited monitor's lock is released by the kernel; bounded wait
        fd = acquire_lock(out)
        if fd is not None:
            break
        time.sleep(0.1)
    if fd is None:
        print("record-exit: lock still held by a live monitor; nothing recorded", file=sys.stderr)
        return 0
    t = int(time.time() * 1000)
    rec = {"t_ms": t, "event": "exit", "service_result": env["SERVICE_RESULT"], "exit_code": env["EXIT_CODE"],
           "exit_status": env["EXIT_STATUS"], "invocation_id": env["INVOCATION_ID"]}
    foreign = monitors_on(out, exclude={os.getpid()})
    with open(os.path.join(out, LIFECYCLE), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(rec, foreign_writers=[p for p, _ in foreign]), sort_keys=True, separators=(",", ":")) + "\n")
    if env["SERVICE_RESULT"] not in (None, "success") and not foreign:
        with open(os.path.join(out, "alerts.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t_ms": t, "severity": "CRITICAL", "kind": "monitor_exit",
                                 "reasons": [f"monitor_exit:result={env['SERVICE_RESULT']},code={env['EXIT_CODE']},"
                                             f"status={env['EXIT_STATUS']}"]},
                                sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset"); ap.add_argument("--out", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--cid", help="explicit full container id (tests / manual)")
    g.add_argument("--binding-file", help="binding JSON written by p2f_monitor_bind.py (supervised service)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--record-exit", action="store_true", help="systemd ExecStopPost hook")
    ap.add_argument("--collector-cmdline", default="python -m p2_forward", help="offline harness only")
    ap.add_argument("--coalesce-health-episodes", action="store_true",
                    help="optional (OFF by default): one alert line per collector health:DEGRADED episode")
    ap.add_argument("--episode-open-alert-s", type=int, default=300,
                    help="with --coalesce-health-episodes: an episode open this long alerts once (candidate value)")
    a = ap.parse_args(argv)
    if a.record_exit:
        return record_exit(a.out)
    if not a.dataset or not (a.cid or a.binding_file):
        ap.error("--dataset and one of --cid / --binding-file are required")
    if a.episode_open_alert_s <= 0:
        ap.error("--episode-open-alert-s must be > 0")
    ROLE_EXACT[a.collector_cmdline] = "collector"
    if os.path.abspath(a.out).startswith(os.path.abspath(a.dataset) + os.sep):
        sys.exit("monitor output must be outside the dataset (observe only)")
    try:
        binding = load_binding(a.binding_file, a.dataset) if a.binding_file else None
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return EX_CONFIG
    if binding:
        a.cid = binding["cid"]
    elif not CID_RE.match(a.cid or ""):
        print(f"--cid must be a full 64-hex container id, got {a.cid!r}", file=sys.stderr)
        return EX_CONFIG
    a.limit_expect = limit_expectation(binding)
    os.makedirs(a.out, exist_ok=True)
    lock_fd = acquire_lock(a.out)                       # BEFORE any write under --out
    if lock_fd is None:
        print(f"another monitor holds {os.path.join(a.out, LOCK_NAME)}; refusing (nothing written)", file=sys.stderr)
        return EX_DUPLICATE
    legacy = monitors_on(a.out, exclude={os.getpid()})
    if legacy:
        print(f"a monitor that does not honour the lock writes {a.out}: pids {[p for p, _ in legacy]}; refusing "
              "(nothing written)", file=sys.stderr)
        return EX_DUPLICATE
    supervisor, unit = own_unit()
    prev = jrd(os.path.join(a.out, "status.json")) or {}
    now_ms = int(time.time() * 1000)
    a.ident = {"schema": "p2f-monitor-ident-v1", "pid": os.getpid(), "started_ms": now_ms, "supervisor": supervisor,
               "unit": unit, "invocation_id": os.environ.get("INVOCATION_ID"), "cid": a.cid,
               "binding": {"source": "file" if binding else "argv", "path": a.binding_file,
                           "sha256": binding and binding["_sha256"],
                           "container_name": binding and binding["container_name"],
                           "bound_at": binding and binding.get("bound_at"),
                           "limits": a.limit_expect},
               "lock": os.path.join(a.out, LOCK_NAME), "code_sha256": sha256_file(os.path.abspath(__file__))}
    m = Monitor(a)
    if not a.once:
        pt = prev.get("t_ms")
        m.lifecycle({"event": "start", "pid": os.getpid(), "supervisor": supervisor, "unit": unit,
                     "invocation_id": a.ident["invocation_id"], "cid": a.cid, "binding_sha256": a.ident["binding"]["sha256"],
                     "code_sha256": a.ident["code_sha256"], "prev_status_t_ms": pt,
                     "prev_writer_pid": (prev.get("monitor") or {}).get("pid"),
                     "status_gap_s": round((now_ms - pt) / 1000, 1) if isinstance(pt, (int, float)) else None})
    return m.run()


if __name__ == "__main__":
    sys.exit(main())
