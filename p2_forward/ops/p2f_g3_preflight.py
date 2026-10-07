#!/usr/bin/env python3
"""G3 (collector resize 0.5 CPU / 384 MiB -> 1.5 CPU / 768 MiB) precondition gate. READ-ONLY, fail closed. Stdlib only.

  p2f_g3_preflight.py check --expect EXPECT.json [--json OUT.json] [--op-minutes 25] [--now-ms MS]
  p2f_g3_preflight.py watch --expect EXPECT.json --max-s N [--interval-s 30] [--until pass|never] [--jsonl OUT.jsonl]

`check` evaluates every precondition immediately before the gated stop and exits 0 ONLY when all of them PASS.
Any missing, unreadable, malformed or uncertain input is a FAIL of that check (never a silent pass). Exit 1 = at least
one FAIL, 2 = usage / internal error (also "do not proceed").

`watch` is the bounded G3 waiter (see docs/p2/P2F_G3_RESIZE_READINESS.md section 2): it records a baseline (incident
ids, monitor alerts.jsonl offset, health boot, lifecycle segment set) and polls health, incidents, monitor status AND
alerts, and the day-lifecycle files every --interval-s until --max-s (hard deadline, exit 4). STOP (exit 3) on any new
incident id, any new monitor alert line >= DEGRADED, a monitor severity >= DEGRADED, health not HEALTHY, a new
seq_reset / unresolved hand-off, or a collector identity change. With --until pass it exits 0 at the first poll where
the full `check` passes. It never uses pgrep, never signals anything and writes only --jsonl.

What this tool never does: start / stop / restart / recreate the collector or the monitor; write the dataset, the
monitor directory, the binding or compose.yml; acknowledge incidents; call `docker` for anything but `inspect` /
`image inspect` (Class A). It writes only the --json / --jsonl file given, which must be outside the dataset and the
monitor output directory.

Sources of truth (one per check; docs/p2/P2F_G3_RESIZE_READINESS.md section 1 has the full table):
  identity    docker inspect <name> (Id, Image, Config.Image, RestartCount, State, Mounts) + docker image inspect
              <tag> + runs/run-<boot>.json (build, config_hash, collector_version) + health (boot_id, config_hash)
              + the cgroup scope (collector process, /data inode, cpu.max / memory.max before the change)
  health      <dataset>/health/collector_health.json (state, reasons, ts_ms) + owner-signed classification list
  incidents   <dataset>/incidents/state.json + p2f_ack_binding.gate() (the exact start gate of p2f_continuous_up.sh)
  rotation    health counters (handoffs, handoff_classes, seq_reset, seq_reset_causes) + health.rotation.events +
              lifecycle ws_handoff / ws_rotation / seq_reset records of the CURRENT boot in finalized raw/lifecycle
              segments
  lifecycle   days/*.json, seals/D.json (+ report sha), backup BACKUP.json + SHA256SUMS, the restore-test PASS line
              in logs/daily_seal_backup.log (the only durable restore-test record today), or an owner disposition
  monitor     systemctl --user show <unit> + <monitor out>/status.json (+ mtime) + the binding file
  run chain   verifier/verify_continuous.py <dataset> --run-chain (deployed verifier, O(runs))
  windows     wall clock + health (connection_age_s, rotation_after_s, universe_epoch) + the fixed protected windows
  rollback    docker image inspect (1.5.0 and 1.4.0 tags), rollback tar + its .sha256, compose backup file
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True                  # never leave __pycache__ in the deployed ops directory
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "p2f-g3-preflight-v1"
EXPECT_SCHEMA = "p2f-g3-expect-v1"
OK_MONITOR = ("INFO", "WARNING")
HANDOFF_OK_REASONS = ("caught_up", "old_closed")
ROTATION_INCIDENT_PREFIXES = ("seq_reset", "rotation_handoff_incomplete", "rotation_overlap_failed")
H_MS, MIN_MS = 3_600_000, 60_000


# ------------------------------------------------------------------ small readers (all fail closed by raising)
def now_ms() -> int:
    return time.time_ns() // 1_000_000


def fsha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def jload(p: str):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def utc(ms) -> str:
    if not isinstance(ms, (int, float)):
        return str(ms)
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def day_of(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def version_tuple(v):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)$", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


class Env:
    """Every external read the gate makes. Tests replace the methods; production uses Docker (inspect only),
    systemctl --user show, the filesystem and the deployed verifier."""

    def __init__(self, x: dict):
        self.x = x

    def docker_inspect(self, name: str) -> dict:
        r = subprocess.run(["docker", "inspect", "--type", "container", name], capture_output=True, text=True,
                           timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"docker inspect {name}: rc={r.returncode} {r.stderr.strip()[:200]}")
        return json.loads(r.stdout)[0]

    def image_id(self, tag: str):
        r = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], capture_output=True,
                           text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None

    def unit_show(self, unit: str) -> dict:
        r = subprocess.run(["systemctl", "--user", "show", unit, "-p",
                            "ActiveState,SubState,MainPID,InvocationID,NRestarts"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            raise RuntimeError(f"systemctl --user show {unit}: rc={r.returncode}")
        return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)

    def run_chain(self) -> dict:
        import tempfile
        v = self.x["verifier"]
        with tempfile.TemporaryDirectory(prefix="g3pf-") as td:    # private temp, removed on exit
            jp = os.path.join(td, "run_chain.json")
            r = subprocess.run(["nice", "-n", "19", sys.executable, "-B", v, self.x["dataset"], "--run-chain",
                                "--json", jp], capture_output=True, text=True, timeout=120)
            try:
                out = jload(jp)
            except (OSError, ValueError):
                out = {"PASS": False, "unparsable": (r.stdout + r.stderr)[-300:]}
        out["_rc"] = r.returncode
        return out

    def ack_gate(self, data: str) -> dict:
        sys.path.insert(0, self.x.get("ops_dir") or HERE)
        try:
            import p2f_ack_binding as AB                   # the exact module p2f_continuous_up.sh uses
        finally:
            sys.path.pop(0)
        return AB.gate(data)

    def cgroup_root(self) -> str:
        return self.x.get("cgroup_root", "/sys/fs/cgroup/system.slice")

    def read(self, p: str):
        try:
            with open(p, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None


def res(cid, ok, source, **detail):
    return {"check": cid, "result": "PASS" if ok else "FAIL", "source": source, **detail}


# ------------------------------------------------------------------ checks
def c_identity(env: Env, x: dict, st: dict) -> dict:
    src = "docker inspect + docker image inspect + runs/run-<boot>.json + health + cgroup scope"
    p = []
    d = env.docker_inspect(x["container_name"])
    st["container"] = d
    cid, img = d.get("Id"), d.get("Image")
    if cid != x["cid"]:
        p.append(f"cid {str(cid)[:12]} != expected {x['cid'][:12]}")
    if not (d.get("State") or {}).get("Running"):
        p.append("container_not_running")
    if d.get("RestartCount") != 0:
        p.append(f"restart_count={d.get('RestartCount')}")
    if (d.get("Config") or {}).get("Image") != x["image_tag"]:
        p.append(f"image_tag={(d.get('Config') or {}).get('Image')}")
    if img != x["image_id"]:
        p.append(f"image_id={img}")
    if env.image_id(x["image_tag"]) != x["image_id"]:
        p.append("tag_does_not_resolve_to_expected_image_id")
    mounts = {(m.get("Destination")): m for m in d.get("Mounts") or []}
    md = mounts.get("/data") or {}
    if os.path.realpath(md.get("Source") or "") != os.path.realpath(x["dataset"]) or md.get("RW") is not True:
        p.append(f"/data mount={md.get('Source')} rw={md.get('RW')}")
    mc = mounts.get("/config/collector.json") or {}
    if os.path.realpath(mc.get("Source") or "") != os.path.realpath(x["config_file"]) or mc.get("RW") is not False:
        p.append(f"/config mount={mc.get('Source')} rw={mc.get('RW')}")
    h = jload(os.path.join(x["dataset"], "health", "collector_health.json"))
    st["health"] = h
    boot = h.get("boot_id")
    if h.get("config_hash") != x["config_hash"]:
        p.append(f"health.config_hash={str(h.get('config_hash'))[:12]}")
    run = jload(os.path.join(x["dataset"], "runs", f"run-{boot}.json"))
    st["run"] = run
    b = run.get("build") or {}
    if run.get("config_hash") != x["config_hash"]:
        p.append(f"run.config_hash={str(run.get('config_hash'))[:12]}")
    if b.get("image_id_runtime_claim") != x["image_id"] or b.get("image_tag") != x["image_tag"]:
        p.append("run.build image claim/tag mismatch")
    if x.get("git_commit") and b.get("git_commit") != x["git_commit"]:
        p.append(f"run.build.git_commit={b.get('git_commit')}")
    vt, vmin = version_tuple(run.get("collector_version")), version_tuple(x["min_collector_version"])
    if vt is None or vmin is None or vt < vmin or h.get("version") != run.get("collector_version"):
        p.append(f"collector_version={run.get('collector_version')} (health {h.get('version')}) < {x['min_collector_version']}")
    if x.get("config_file_sha256") and fsha(x["config_file"]) != x["config_file_sha256"]:
        p.append("config_file_sha256 changed")
    scope = os.path.join(env.cgroup_root(), f"docker-{cid}.scope")
    lim = {f: (env.read(os.path.join(scope, f)) or "").strip() or None for f in ("cpu.max", "memory.max", "memory.swap.max", "pids.max")}
    st["limits_now"] = lim
    for f, want in (x.get("limits_before") or {}).items():
        if lim.get(f) != want:
            p.append(f"cgroup {f}={lim.get(f)} != expected-before {want}")
    if not x.get("limits_before"):
        p.append("expect.limits_before missing (cannot prove the pre-change state)")
    pid = None
    for q in (env.read(os.path.join(scope, "cgroup.procs")) or "").split():
        cmd = (env.read(f"/proc/{q}/cmdline") or "").replace("\0", " ").strip()
        if cmd == "python -m p2_forward":
            pid = q
    if pid is None:
        p.append("no collector process in the cgroup scope")
    elif x.get("verify_data_inode", True):
        try:
            a, bb = os.stat(f"/proc/{pid}/root/data"), os.stat(x["dataset"])
            if (a.st_dev, a.st_ino) != (bb.st_dev, bb.st_ino):
                p.append("collector /data is not the dataset (inode)")
        except OSError as e:
            p.append(f"/data inode unreadable: {e}")
    return res("identity", not p, src, problems=p, cid12=str(cid)[:12], image_id=img, boot8=str(boot)[:8],
               config_hash=h.get("config_hash"), collector_version=run.get("collector_version"), limits=lim,
               started_at=(d.get("State") or {}).get("StartedAt"), restart_count=d.get("RestartCount"))


def load_classification(x: dict):
    """Owner-signed list of hard health reasons that may be present at G3 (empty by default). Fail closed: an
    unsigned, malformed or sha-mismatched list counts as no list."""
    p = x.get("hard_reason_classification")
    if not p:
        return [], None
    c = jload(p)
    if c.get("schema") != "p2f-g3-hard-reason-classification-v1" or not c.get("signed_by") or not c.get("signed_at"):
        raise ValueError("classification list unsigned or wrong schema")
    if x.get("hard_reason_classification_sha256") and fsha(p) != x["hard_reason_classification_sha256"]:
        raise ValueError("classification list sha256 != expected")
    return [e for e in c.get("entries", []) if e.get("reason") and e.get("evidence")], fsha(p)


def c_health(env: Env, x: dict, st: dict, now: int) -> dict:
    src = "health/collector_health.json + owner-signed classification list"
    h = st.get("health") or jload(os.path.join(x["dataset"], "health", "collector_health.json"))
    p = []
    age = (now - h["ts_ms"]) / 1000 if isinstance(h.get("ts_ms"), int) else None
    if age is None or age > x.get("health_max_age_s", 30) or age < -5:
        p.append(f"health_age_s={age}")
    entries, csha = load_classification(x)
    allowed = {e["reason"] for e in entries}
    reasons = h.get("reasons")
    if not isinstance(reasons, list):
        p.append("reasons missing")
        reasons = []
    unclassified = [r for r in reasons if r not in allowed]
    if h.get("state") != "HEALTHY":
        if not reasons or unclassified:
            p.append(f"state={h.get('state')}")
    if unclassified:
        p.append(f"unclassified hard reasons: {unclassified[:10]}")
    return res("health", not p, src, problems=p, state=h.get("state"), reasons=reasons,
               warnings=(h.get("warnings") or [])[:10], age_s=None if age is None else round(age, 1),
               classification_sha256=csha)


def c_incidents(env: Env, x: dict, st: dict) -> dict:
    src = "incidents/state.json + p2f_ack_binding.gate()"
    s = jload(os.path.join(x["dataset"], "incidents", "state.json"))
    st["incidents"] = s
    p, boot8 = [], str((st.get("health") or {}).get("boot_id", ""))[:8]
    inc = s.get("incidents")
    if not isinstance(inc, list):
        return res("incidents", False, src, problems=["state.json has no incidents list"])
    blocking = [i for i in inc if i.get("active") and i.get("ack") is None and i.get("severity") in ("DEGRADED", "CRITICAL")]
    for i in blocking:
        p.append(f"active unacked {i.get('severity')} {i.get('id')} {i.get('key')}")
    unknown = [i for i in inc if i.get("severity") not in ("INFO", "WARNING", "DEGRADED", "CRITICAL")]
    for i in unknown:
        p.append(f"unknown severity {i.get('id')}={i.get('severity')}")
    rot = [i for i in inc if i.get("active") and str(i.get("key", "")).startswith(ROTATION_INCIDENT_PREFIXES)
           and f"-{boot8}-" in str(i.get("id"))]
    for i in rot:
        p.append(f"rotation/sequence incident in the current run: {i.get('id')} {i.get('key')} ack={bool(i.get('ack'))}")
    g = env.ack_gate(x["dataset"])
    if g:
        p.append(f"AB.gate() not clean: {sorted(g)[:5]}")
    warn = [f"{i.get('id')} {i.get('key')}" for i in inc if i.get("active") and i.get("ack") is None and i.get("severity") == "WARNING"]
    return res("incidents", not p, src, problems=p, ab_gate=g, unacked_warnings=warn,
               state_sha256=fsha(os.path.join(x["dataset"], "incidents", "state.json")),
               ids=sorted(i.get("id") for i in inc))


def lifecycle_records(data: str, boot: str, start_ms: int, end_ms: int, events: tuple):
    """Records of `events` from the current boot's FINALIZED lifecycle segments (the open .partial is excluded: it
    is being written). Only the day directories from the boot's start to today are read."""
    out, b8 = [], boot[:8]
    d0 = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc).date()
    d1 = dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc).date()
    import gzip
    while d0 <= d1:
        dd = os.path.join(data, "raw", "lifecycle", d0.isoformat())
        for f in sorted(os.listdir(dd)) if os.path.isdir(dd) else []:
            if f.endswith(".jsonl.gz") and f"-{b8}-" in f:
                with gzip.open(os.path.join(dd, f), "rt", encoding="utf-8") as fh:
                    for line in fh:
                        r = json.loads(line)
                        ev = (r.get("payload") or {}).get("event")
                        if r.get("boot_id") == boot and ev in events:
                            out.append(r)
        d0 += dt.timedelta(days=1)
    return out


def c_rotation(env: Env, x: dict, st: dict, now: int) -> dict:
    src = "health counters + health.rotation.events + lifecycle ws_handoff/ws_rotation/seq_reset (current boot)"
    h, run = st.get("health") or {}, st.get("run") or {}
    p = []
    vt, vmin = version_tuple(run.get("collector_version")), version_tuple(x["min_collector_version"])
    if vt is None or vmin is None or vt < vmin:
        p.append("current run is not collector >= min version")
    c = h.get("counters") or {}
    hc = c.get("handoff_classes")
    if not isinstance(c.get("handoffs"), int) or not isinstance(hc, dict) or not isinstance(c.get("seq_reset"), int):
        return res("rotation", False, src, problems=["health counters handoffs/handoff_classes/seq_reset missing"])
    need = x.get("min_observed_handoffs", 1)
    if c["handoffs"] < need:
        p.append(f"handoffs={c['handoffs']} < {need} (no observed 1.5.0 rotation yet)")
    if hc.get("unresolved"):
        p.append(f"handoff_classes.unresolved={hc.get('unresolved')}")
    if c["seq_reset"] != 0 or c.get("seq_reset_causes"):
        p.append(f"seq_reset={c['seq_reset']} causes={c.get('seq_reset_causes')}")
    evs = (h.get("rotation") or {}).get("events")
    if not isinstance(evs, list):
        p.append("health.rotation.events missing")
        evs = []
    for e in evs:
        ho = e.get("handoff") or {}
        if not e.get("overlap_ok") or not ho.get("complete") or ho.get("reason") not in HANDOFF_OK_REASONS:
            p.append(f"rotation {e.get('conn')} at {utc(e.get('started_ms'))}: overlap_ok={e.get('overlap_ok')} "
                     f"complete={ho.get('complete')} reason={ho.get('reason')}")
    boot = h.get("boot_id")
    lc = lifecycle_records(x["dataset"], boot, run.get("created_ms") or 0, now,
                           ("ws_handoff", "ws_rotation", "seq_reset")) if boot else []
    hand = [r["payload"] for r in lc if r["payload"]["event"] == "ws_handoff"]
    rots = [r["payload"] for r in lc if r["payload"]["event"] == "ws_rotation"]
    resets = [r["payload"] for r in lc if r["payload"]["event"] == "seq_reset"]
    if len(hand) < need:
        p.append(f"finalized lifecycle ws_handoff records={len(hand)} < {need}")
    for a in hand:
        ho = a.get("handoff") or {}
        if a.get("unresolved") or (a.get("classes") or {}).get("unresolved") or not ho.get("complete") \
                or ho.get("reason") not in HANDOFF_OK_REASONS:
            p.append(f"ws_handoff {a.get('conn')} close={utc(a.get('close_ms'))}: complete={ho.get('complete')} "
                     f"reason={ho.get('reason')} unresolved={(a.get('unresolved') or [])[:5]}")
    for r in rots:
        if not r.get("overlap_ok"):
            p.append(f"ws_rotation {r.get('conn')} overlap_ok=False")
    if resets:
        p.append(f"lifecycle seq_reset records in the current run: {len(resets)}")
    if len(hand) > c["handoffs"]:
        p.append(f"lifecycle ws_handoff ({len(hand)}) > health counter ({c['handoffs']}): inconsistent")
    return res("rotation", not p, src, problems=p, handoffs=c["handoffs"], handoff_classes=hc,
               seq_reset=c["seq_reset"], seq_stale=c.get("seq_stale"), lifecycle_ws_handoff=len(hand),
               lifecycle_ws_rotation=len(rots), lifecycle_seq_reset=len(resets),
               handoff_records=[{"conn": a.get("conn"), "close": utc(a.get("close_ms")), "classes": a.get("classes"),
                                 "reason": (a.get("handoff") or {}).get("reason")} for a in hand][:10])


def restore_pass_days(log_path: str) -> set:
    out = set()
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("{") and '"restore_test"' in line:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("restore_test") == "PASS" and (r.get("totals") or {}).get("unexplained") == 0:
                    out.add(r.get("day"))
    return out


def check_disposition(x: dict, day: str, d: dict) -> list:
    p = []
    if d.get("status") != "FAILED" or not d.get("doc") or not d.get("doc_sha256"):
        return [f"{day}: disposition incomplete"]
    if not os.path.isfile(d["doc"]) or fsha(d["doc"]) != d["doc_sha256"]:
        p.append(f"{day}: disposition doc missing or sha256 changed")
    for rel, want in (d.get("pinned_files") or {}).items():
        q = os.path.join(x["dataset"], rel)
        if not os.path.isfile(q) or fsha(q) != want:
            p.append(f"{day}: pinned {rel} missing or changed")
    if not d.get("pinned_files"):
        p.append(f"{day}: disposition pins no lifecycle file")
    if os.path.exists(os.path.join(x["dataset"], "seals", f"{day}.json")):
        p.append(f"{day}: a PASS seal now exists next to a FAILED disposition (owner review)")
    return p


def c_lifecycle(env: Env, x: dict, st: dict, now: int) -> dict:
    src = "days/ + seals/ + backup BACKUP.json/SHA256SUMS + restore-test PASS log line, or owner disposition"
    data, p, rows = x["dataset"], [], {}
    days = sorted(f[:-5] for f in os.listdir(os.path.join(data, "days")) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", f))
    today = day_of(now)
    yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    first = jload(os.path.join(data, "dataset.json")).get("created_utc") or (days[0] if days else None)
    if yesterday not in days and (not days or days[0] <= yesterday):
        p.append(f"yesterday {yesterday} is not closed yet (days/{yesterday}.json missing)")
    disp = x.get("day_dispositions") or {}
    restored = restore_pass_days(x["seal_log"])
    bk_root = os.path.join(x["backup_root"], x["dataset_id"])
    for d in days:
        if d >= today:
            continue
        if d in disp:
            q = check_disposition(x, d, disp[d])
            rows[d] = "disposition:FAILED" if not q else "disposition:INVALID"
            p += q
            continue
        q = []
        sp = os.path.join(data, "seals", f"{d}.json")
        try:
            seal = jload(sp)
            if seal.get("result") != "PASS" or fsha(os.path.join(data, "seals", f"{d}.report.json")) != seal.get("report_sha256"):
                q.append("seal not PASS / report sha mismatch")
            bkj = jload(os.path.join(bk_root, d, "BACKUP.json"))
            if bkj.get("seal_sha256") != fsha(sp) or bkj.get("day") != d:
                q.append("backup BACKUP.json does not match the seal")
            if not os.path.isfile(os.path.join(bk_root, d, "SHA256SUMS")):
                q.append("backup SHA256SUMS missing")
        except (OSError, ValueError) as e:
            q.append(f"{type(e).__name__}: {str(e)[:120]}")
        if d not in restored:
            q.append("no restore-test PASS record")
        rows[d] = "sealed+backup+restore" if not q else "INCOMPLETE"
        p += [f"{d}: {m}" for m in q]
    pend = [os.path.basename(f) for f in os.listdir(os.path.join(data, "seals")) if f.endswith(".partial")]
    if pend:
        p.append(f"seal in progress: {pend}")
    return res("day_lifecycle", not p, src, problems=p, days=rows, first_day=first,
               restore_test_source=x["seal_log"])


def c_monitor(env: Env, x: dict, st: dict, now: int) -> dict:
    src = "systemctl --user show <unit> + <monitor out>/status.json (+mtime) + binding file"
    p = []
    u = env.unit_show(x["monitor_unit"])
    sp = os.path.join(x["monitor_out"], "status.json")
    s = jload(sp)
    ages = [now / 1000 - os.stat(sp).st_mtime]
    if isinstance(s.get("t_ms"), (int, float)):
        ages.append((now - s["t_ms"]) / 1000)
    else:
        p.append("status.t_ms missing")
    age = max(ages)
    if age > x.get("monitor_max_age_s", 120):
        p.append(f"status age_s={round(age, 1)}")
    m = s.get("monitor") or {}
    if u.get("ActiveState") != "active" or u.get("SubState") != "running":
        p.append(f"unit {u.get('ActiveState')}/{u.get('SubState')}")
    if m.get("supervisor") != "systemd-user" or m.get("unit") != x["monitor_unit"]:
        p.append(f"writer {m.get('supervisor')}/{m.get('unit')} is not the supervised unit")
    if str(m.get("pid")) != u.get("MainPID") or m.get("invocation_id") != u.get("InvocationID"):
        p.append("status writer is not the unit's MainPID/InvocationID")
    live = (st.get("container") or {}).get("Id")
    b = jload(x["binding_file"])
    if not (m.get("cid") == b.get("cid") == x["cid"] == live):
        p.append(f"binding cid {str(b.get('cid'))[:12]} / status cid {str(m.get('cid'))[:12]} / live {str(live)[:12]}")
    bc = m.get("binding_check") or {}
    if not (bc.get("scope_alive") and bc.get("collector_pid") and bc.get("dataset_mount_ok") is True):
        p.append(f"binding_check not proven: {bc}")
    if s.get("severity") not in OK_MONITOR:
        p.append(f"monitor severity={s.get('severity')} reasons={s.get('severity_reasons')}")
    if x.get("monitor_code_sha256") and m.get("code_sha256") != x["monitor_code_sha256"]:
        p.append("monitor code_sha256 != expected")
    lim = s.get("limits")
    if x.get("require_limit_aware_monitor", True):
        # G3 precondition: the deployed monitor derives the limit from the cgroup (P2F_G3_RESIZE_READINESS.md s.3)
        cg = st.get("limits_now") or {}
        if not isinstance(lim, dict):
            p.append("monitor is not limit-aware (status.json has no 'limits'): deploy the monitor-limit change first")
        elif lim.get("memory_max_raw") != cg.get("memory.max") or lim.get("cpu_max_raw") != cg.get("cpu.max"):
            p.append(f"monitor limits {lim.get('memory_max_raw')}/{lim.get('cpu_max_raw')} != cgroup "
                     f"{cg.get('memory.max')}/{cg.get('cpu.max')}")
    return res("monitor", not p, src, problems=p, unit=u, severity=s.get("severity"),
               reasons=s.get("severity_reasons"), age_s=round(age, 1), writer_cid12=str(m.get("cid"))[:12],
               binding_sha256=fsha(x["binding_file"]), limits=lim)


def c_run_chain(env: Env, x: dict, st: dict) -> dict:
    r = env.run_chain()
    p = [] if r.get("PASS") is True and r.get("_rc") == 0 and not r.get("failures") else [str(r)[:400]]
    runs = r.get("runs") or []
    boot = (st.get("health") or {}).get("boot_id")
    if not runs or runs[-1].get("boot_id") != boot or runs[-1].get("state") is not None:
        p.append(f"last run in the chain is not the running boot {str(boot)[:8]} (no stop marker yet)")
    ok = not p
    return res("run_chain", ok, "verifier/verify_continuous.py --run-chain --json <private tmp>", problems=p,
               runs=[(str(q.get("boot_id"))[:8], q.get("cause"), q.get("state")) for q in r.get("runs") or []])


def rotation_times(h: dict) -> list:
    """Scheduled rotations from live health: proactive (each connection's last up + rotation_after_s), the next
    universe refresh / pending transition. Unknown inputs raise (fail closed)."""
    t, out = h["ts_ms"], []
    lim = h["rotation_after_s"] * 1000
    for name, age in sorted((h.get("connection_age_s") or {}).items()):
        if not isinstance(age, (int, float)):
            raise ValueError(f"connection {name} age unknown")
        out.append(("proactive:" + name, t - int(age * 1000) + lim))
    if not h.get("connection_age_s"):
        raise ValueError("no connection ages in health")
    ue = h["universe_epoch"]
    if ue.get("refresh_degraded"):
        raise ValueError(f"universe refresh degraded (30-min retries): {ue.get('refresh_degraded')}")
    if ue.get("pending_effective_ms"):
        out.append(("universe_transition_pending", ue["pending_effective_ms"]))
    if not isinstance(ue.get("next_refresh_ms"), int):
        raise ValueError("universe next_refresh_ms unknown")
    out.append(("universe_refresh_transition", ue["next_refresh_ms"]))
    return out


def protected_windows(day_start_ms: int) -> list:
    """Fixed daily windows (UTC) for one calendar day starting at day_start_ms."""
    w = [(f"hourly_seal_backup_{hh:02d}:12-:25", day_start_ms + hh * H_MS + 12 * MIN_MS, day_start_ms + hh * H_MS + 25 * MIN_MS)
         for hh in range(24)]
    w.append(("day_end_23:30-00:00", day_start_ms + 23 * H_MS + 30 * MIN_MS, day_start_ms + 24 * H_MS))
    w.append(("seal_universe_01:10-01:45", day_start_ms + H_MS + 10 * MIN_MS, day_start_ms + H_MS + 45 * MIN_MS))
    return w


def c_windows(env: Env, x: dict, st: dict, now: int, lifecycle_ok: bool) -> dict:
    src = "wall clock + health (connection_age_s, rotation_after_s, universe_epoch) + fixed windows"
    h = st.get("health") or {}
    p, op = [], x.get("op_minutes", 25) * MIN_MS
    lo, hi = now, now + op
    margin = x.get("rotation_margin_min", 30) * MIN_MS
    try:
        rots = rotation_times(h)
    except (KeyError, TypeError, ValueError) as e:
        return res("windows", False, src, problems=[f"rotation schedule uncertain: {e}"])
    for name, t in rots:
        if lo < t + margin and hi > t - margin:
            p.append(f"within +-{margin // MIN_MS} min of {name} at {utc(t)}")
    d0 = (now // (24 * H_MS)) * 24 * H_MS
    for dd in (d0 - 24 * H_MS, d0, d0 + 24 * H_MS):
        for name, a, b in protected_windows(dd):
            if lo < b and hi > a:
                p.append(f"overlaps {name} {utc(a)}..{utc(b)}")
    # 00:00Z -> end of yesterday's seal/backup/restore-test: open-ended; it ends only when the lifecycle check passes
    if (now - d0) < 2 * H_MS and not lifecycle_ok:
        p.append("after 00:00Z and yesterday's seal/backup/restore-test is not complete")
    return res("windows", not p, src, problems=p, op_interval=[utc(lo), utc(hi)],
               scheduled_rotations=[(n, utc(t)) for n, t in rots])


def c_rollback(env: Env, x: dict) -> dict:
    src = "docker image inspect + rollback tar sha256 + compose backup"
    p = []
    rb = x["rollback"]
    if env.image_id(x["image_tag"]) != x["image_id"]:
        p.append("1.5.0 image tag missing or moved (needed for the post-resize start)")
    if env.image_id(rb["previous_image_tag"]) != rb["previous_image_id"]:
        p.append("previous (1.4.0) image tag missing or moved")
    tar = rb["tar"]
    try:
        with open(tar + ".sha256", encoding="utf-8") as fh:
            side = fh.read().split()[0]
        if side != rb["tar_sha256"]:
            p.append("rollback tar .sha256 sidecar != pinned")
        if x.get("verify_tar_sha", True) and fsha(tar) != rb["tar_sha256"]:
            p.append("rollback tar content sha256 != pinned")
    except (OSError, IndexError) as e:
        p.append(f"rollback tar: {type(e).__name__}: {e}")
    cur = fsha(x["compose_file"])
    if cur != x["compose_sha256_before"]:
        p.append(f"deployed compose.yml sha256 {cur[:12]} != expected pre-G3 {x['compose_sha256_before'][:12]}")
    bk = rb.get("compose_backup")
    if not bk or not os.path.isfile(bk) or fsha(bk) != x["compose_sha256_before"]:
        p.append(f"compose backup {bk} missing or not the pre-G3 compose")
    elif os.access(bk, os.W_OK):
        p.append("compose backup is writable (must be read-only)")
    with open(x["compose_file"], encoding="utf-8") as fh:
        txt = fh.read()
    want = x.get("compose_limits_before") or {}
    for k, v in want.items():
        if not re.search(rf"^\s*{re.escape(k)}:\s*{re.escape(str(v))}\s*(#.*)?$", txt, re.M):
            p.append(f"compose {k} is not {v}")
    if not want:
        p.append("expect.compose_limits_before missing")
    return res("rollback", not p, src, problems=p, compose_sha256=cur)


def c_host(env: Env, x: dict) -> dict:
    """Report-only host context + one fail-closed floor (MemAvailable)."""
    mi = {}
    for line in (env.read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        if v.strip().split()[0:1]:
            mi[k] = int(v.strip().split()[0])
    psi = (env.read("/proc/pressure/memory") or "").strip().splitlines()
    p = []
    avail = mi.get("MemAvailable")
    if avail is None or avail / 1048576 < x.get("min_mem_available_gib", 4):
        p.append(f"MemAvailable={None if avail is None else round(avail / 1048576, 2)} GiB")
    return res("host", not p, "/proc/meminfo + /proc/pressure/memory (report-only besides MemAvailable floor)",
               problems=p, mem_available_gib=None if avail is None else round(avail / 1048576, 2),
               swap_total_kib=mi.get("SwapTotal"), swap_free_kib=mi.get("SwapFree"), psi_memory=psi)


def evaluate(env: Env, x: dict, now=None) -> dict:
    now = now_ms() if now is None else now
    st, out = {}, []

    def run(fn, *a):
        try:
            r = fn(*a)
        except Exception as e:                                       # noqa: BLE001  (fail closed on anything)
            r = res(fn.__name__[2:], False, "exception", problems=[f"{type(e).__name__}: {str(e)[:300]}"])
        out.append(r)
        return r

    run(c_identity, env, x, st)
    run(c_health, env, x, st, now)
    run(c_incidents, env, x, st)
    run(c_rotation, env, x, st, now)
    lc = run(c_lifecycle, env, x, st, now)
    run(c_monitor, env, x, st, now)
    run(c_run_chain, env, x, st)
    run(c_windows, env, x, st, now, lc["result"] == "PASS")
    run(c_rollback, env, x)
    run(c_host, env, x)
    names = [r["check"] for r in out]
    verdict = "PASS" if all(r["result"] == "PASS" for r in out) and len(names) == 10 else "FAIL"
    return {"schema": SCHEMA, "verdict": verdict, "evaluated_ms": now, "evaluated_utc": utc(now),
            "expect_sha256": x.get("_sha256"), "failed": [r["check"] for r in out if r["result"] != "PASS"],
            "checks": out}


def load_expect(p: str) -> dict:
    x = jload(p)
    if x.get("schema") != EXPECT_SCHEMA:
        raise SystemExit(f"expect file schema != {EXPECT_SCHEMA}")
    for k in ("cid", "container_name", "image_tag", "image_id", "config_hash", "dataset", "dataset_id", "config_file",
              "min_collector_version", "monitor_unit", "monitor_out", "binding_file", "verifier", "seal_log",
              "backup_root", "compose_file", "compose_sha256_before", "rollback"):
        if not x.get(k):
            raise SystemExit(f"expect file lacks {k}")
    x["_sha256"] = fsha(p)
    return x


def guard_out(x: dict, path: str):
    if not path:
        return
    rp = os.path.realpath(path)
    for d in (x["dataset"], x["monitor_out"], os.path.dirname(x["compose_file"])):
        if rp.startswith(os.path.realpath(d) + os.sep):
            raise SystemExit(f"output {path} must be outside {d} (read-only tool)")


# ------------------------------------------------------------------ bounded waiter
def watch_snapshot(env: Env, x: dict) -> dict:
    h = jload(os.path.join(x["dataset"], "health", "collector_health.json"))
    s = jload(os.path.join(x["dataset"], "incidents", "state.json"))
    ms = jload(os.path.join(x["monitor_out"], "status.json"))
    ap = os.path.join(x["monitor_out"], "alerts.jsonl")
    c = h.get("counters") or {}
    return {"boot": h.get("boot_id"), "state": h.get("state"), "reasons": h.get("reasons"), "ts_ms": h.get("ts_ms"),
            "incident_ids": sorted(i["id"] for i in s.get("incidents", [])),
            "incidents": {i["id"]: (i.get("severity"), i.get("active"), i.get("ack") is not None, i.get("count"))
                          for i in s.get("incidents", [])},
            "alerts_size": os.path.getsize(ap) if os.path.exists(ap) else 0, "monitor_sev": ms.get("severity"),
            "monitor_t_ms": ms.get("t_ms"), "monitor_reasons": ms.get("severity_reasons"),
            "seq_reset": c.get("seq_reset"), "unresolved": (c.get("handoff_classes") or {}).get("unresolved", 0),
            "handoffs": c.get("handoffs"),
            "seals": sorted(os.listdir(os.path.join(x["dataset"], "seals"))),
            "days": sorted(os.listdir(os.path.join(x["dataset"], "days"))),
            "external": sorted(os.listdir(os.path.join(x["dataset"], "incidents", "external")))}


def watch_stop_reasons(base: dict, cur: dict, x: dict, now: int) -> list:
    r = []
    if cur["boot"] != base["boot"]:
        r.append(f"collector boot changed {str(base['boot'])[:8]}->{str(cur['boot'])[:8]}")
    if cur["state"] != "HEALTHY":
        r.append(f"health {cur['state']} {cur['reasons']}")
    if not isinstance(cur["ts_ms"], int) or now - cur["ts_ms"] > 60_000:
        r.append("health file stale")
    new = sorted(set(cur["incident_ids"]) - set(base["incident_ids"]))
    if new:
        r.append(f"new incident ids {new[:5]}")
    for i, (sev, act, ack, cnt) in cur["incidents"].items():
        b = base["incidents"].get(i)
        if b and act and not ack and sev in ("DEGRADED", "CRITICAL") and (b[3] != cnt or not b[1] or b[2]):
            r.append(f"incident {i} recurred / reopened")
    if cur["monitor_sev"] not in OK_MONITOR:
        r.append(f"monitor {cur['monitor_sev']} {cur['monitor_reasons']}")
    if not isinstance(cur["monitor_t_ms"], (int, float)) or now - cur["monitor_t_ms"] > 180_000:
        r.append("monitor status stale")
    if (cur["seq_reset"] or 0) > (base["seq_reset"] or 0) or (cur["unresolved"] or 0) > (base["unresolved"] or 0):
        r.append(f"seq_reset {base['seq_reset']}->{cur['seq_reset']} unresolved {base['unresolved']}->{cur['unresolved']}")
    if [f for f in cur["seals"] if "FAILED" in f and f not in base["seals"]]:
        r.append("new FAILED seal report")
    if [f for f in cur["external"] if f not in base["external"]]:
        r.append(f"new external incident file(s) {[f for f in cur['external'] if f not in base['external']][:3]}")
    return r


def new_alert_lines(x: dict, offset: int):
    ap = os.path.join(x["monitor_out"], "alerts.jsonl")
    out = []
    with open(ap, "rb") as fh:
        fh.seek(offset)
        for line in fh.read().decode("utf-8", "replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"severity": "CRITICAL", "kind": "unparsable_alert_line"})
    return out


def watch(env: Env, x: dict, max_s: float, interval_s: float, until: str, jsonl: str | None, sleep=time.sleep,
          clock=now_ms) -> int:
    t0 = clock()
    deadline = t0 + int(max_s * 1000)

    def log(rec):
        if jsonl:
            with open(jsonl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(dict(rec, t_utc=utc(clock())), sort_keys=True, default=str) + "\n")

    try:
        base = watch_snapshot(env, x)
    except Exception as e:                                           # noqa: BLE001
        log({"event": "stop", "why": [f"baseline unreadable: {e}"]})
        return 3
    log({"event": "baseline", "pid": os.getpid(), "max_s": max_s, "interval_s": interval_s, "until": until, **base})
    seen = base["alerts_size"]
    while True:
        now = clock()
        try:
            cur = watch_snapshot(env, x)
            why = watch_stop_reasons(base, cur, x, now)
            alerts = new_alert_lines(x, seen)
            seen = cur["alerts_size"]
            for a in alerts:
                if a.get("severity") not in OK_MONITOR or a.get("kind") in ("monitor_exit", "monitor_yield"):
                    why.append(f"monitor alert {a.get('severity')} {a.get('kind')} {a.get('reasons')}")
        except Exception as e:                                       # noqa: BLE001  (unreadable = stop)
            why, cur = [f"poll unreadable: {type(e).__name__}: {e}"], {}
        if why:
            log({"event": "stop", "why": why})
            return 3
        if until == "pass":
            v = evaluate(env, x, now)
            log({"event": "poll", "verdict": v["verdict"], "failed": v["failed"]})
            if v["verdict"] == "PASS":
                log({"event": "pass"})
                return 0
        else:
            log({"event": "poll", "state": cur.get("state"), "monitor": cur.get("monitor_sev")})
        if clock() + interval_s * 1000 > deadline:
            log({"event": "timeout", "elapsed_s": round((clock() - t0) / 1000, 1)})
            return 4
        sleep(interval_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "watch"])
    ap.add_argument("--expect", required=True)
    ap.add_argument("--json")
    ap.add_argument("--jsonl")
    ap.add_argument("--op-minutes", type=int)
    ap.add_argument("--now-ms", type=int, help="tests only")
    ap.add_argument("--max-s", type=float)
    ap.add_argument("--interval-s", type=float, default=30.0)
    ap.add_argument("--until", choices=["pass", "never"], default="never")
    a = ap.parse_args(argv)
    try:
        x = load_expect(a.expect)
        if a.op_minutes:
            x["op_minutes"] = a.op_minutes
        guard_out(x, a.json)
        guard_out(x, a.jsonl)
    except (SystemExit, OSError, ValueError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    env = Env(x)
    if a.cmd == "watch":
        if not a.max_s or a.max_s <= 0 or a.max_s > 6 * 3600:
            print("REFUSED: watch needs --max-s in (0, 21600]", file=sys.stderr)
            return 2
        return watch(env, x, a.max_s, max(5.0, a.interval_s), a.until, a.jsonl)
    v = evaluate(env, x, a.now_ms)
    txt = json.dumps(v, indent=1, sort_keys=True, default=str)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(txt + "\n")
    for r in v["checks"]:
        print(f"{r['result']:4}  {r['check']:13}  {'; '.join(r.get('problems') or [])[:300]}")
    print(f"VERDICT {v['verdict']}  failed={v['failed']}")
    return 0 if v["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
