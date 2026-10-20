#!/usr/bin/env python3
"""CHG-03: one-shot, gated Collector recovery after a host reboot. HOST side, stdlib only.

  p2f_reboot_recover.py run    --config FILE      one recovery attempt (systemd oneshot at boot, or by hand)
  p2f_reboot_recover.py status --config FILE      read-only: print the classification and gate results
  p2f_reboot_recover.py reset  --config FILE --by WHO --reason TEXT   close the failure circuit (operator)

What it does, in order (each step fails closed and reports why):
  lock -> config -> Docker ready -> storage/resources -> already running? -> recovery ledger (one attempt per
  host boot, failure circuit) -> classify the previous run's end -> drift gates (image id, config, compose,
  restart "no", dataset id) -> incident gate (blocking CRITICAL never bypassed) -> preserve evidence (copy only)
  -> Paper snapshot -> start through p2f_continuous_up.sh (never docker directly) -> re-bind the monitor ->
  verify health and the new run's lineage -> Paper snapshot unchanged -> report + ledger + owner alert.

What it never does: acknowledge an incident, change a restart policy, touch Paper containers, read trading data,
delete or rewrite evidence, retry in a loop, or start the collector without the gated script.

P2F_ACK_PREVIOUS (the runbook's operator confirmation for an unclean previous stop) is NEVER hard-coded. It is
derived from the dataset's latest run record, and it is supplied only when the previous run's end is classified
ORDERLY_REBOOT_UNCLEAN_STOP *and* the config policy ``auto_ack_previous_on_orderly_reboot`` is true. That policy
defaults to false: it needs a separate owner decision (CHG-03 governance proposal).
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2f_ack_binding as AB  # noqa: E402

VERSION = "p2f-reboot-recover-v1"

# outcomes and exit codes
RECOVERED, NOOP_RUNNING, LOCKED = "RECOVERED", "NOOP_ALREADY_RUNNING", "LOCKED"
MANUAL, FAILED = "MANUAL_REQUIRED", "FAILED"
EXIT = {RECOVERED: 0, NOOP_RUNNING: 0, LOCKED: 75, MANUAL: 10, FAILED: 11}

# classifications of the previous run's end
CLEAN_STOP = "CLEAN_STOP_AT_SHUTDOWN"
OPERATOR_STOP = "CLEAN_STOP_BEFORE_SHUTDOWN"        # a deliberate stop: never undone automatically
FAILED_STOP = "FAILED_STOP"
ORDERLY_REBOOT_UNCLEAN = "ORDERLY_REBOOT_UNCLEAN_STOP"
POWER_LOSS_OR_UNVERIFIED = "UNCLEAN_REBOOT_UNVERIFIED"
CRASH_SAME_BOOT = "COLLECTOR_CRASH_SAME_BOOT"
DIED_BEFORE_SHUTDOWN = "COLLECTOR_DIED_BEFORE_SHUTDOWN"
NO_PREVIOUS_RUN = "NO_PREVIOUS_RUN"
UNKNOWN = "UNKNOWN"
AUTO_ELIGIBLE = {CLEAN_STOP, ORDERLY_REBOOT_UNCLEAN}

REQUIRED_CONFIG = ("dataset_dir", "config_file", "config_sha256", "compose_file", "compose_sha256", "image_tag",
                   "image_id", "container", "state_dir", "monitor_dir", "paper_containers")
DEFAULTS = {"min_disk_free_gb": 100, "min_mem_available_mb": 1024, "docker_wait_s": 600, "up_timeout_s": 300,
            "bind_timeout_s": 180, "health_wait_s": 240, "max_consecutive_failures": 2,
            "stopping_window_before_s": 60, "stopping_window_after_s": 300,
            "clean_stop_window_before_s": 120, "clean_stop_window_after_s": 600,
            "max_health_beat_ms": 5000, "policy": {"auto_ack_previous_on_orderly_reboot": False},
            "alert": {"enabled": True, "env_file": "/home/tradmin/trading-signal-bot/.env"}}


class Stop(Exception):
    """A gate refused. ``outcome`` is MANUAL_REQUIRED or FAILED; ``reason`` is a stable code."""

    def __init__(self, outcome, reason, detail=None):
        super().__init__(reason)
        self.outcome, self.reason, self.detail = outcome, reason, detail


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    missing = [k for k in REQUIRED_CONFIG if not cfg.get(k)]
    if missing:
        raise Stop(MANUAL, "config_incomplete", missing)
    for k, v in DEFAULTS.items():
        if isinstance(v, dict):
            cfg[k] = {**v, **cfg.get(k, {})}
        else:
            cfg.setdefault(k, v)
    if cfg["policy"].get("auto_ack_previous_on_orderly_reboot") not in (True, False):
        raise Stop(MANUAL, "config_policy_not_boolean")
    return cfg


# --------------------------------------------------------------------------------------------- host interface

class RealHost:
    """Everything that touches the host. Read-only except run_up / run_bind / send_alert (tests replace it)."""

    def __init__(self, cfg):
        self.cfg = cfg

    def _run(self, args, timeout=30, env=None):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                               env={**os.environ, **(env or {})})
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            return 124, type(e).__name__

    def now_ms(self):
        return int(time.time() * 1000)

    def sleep(self, s):
        time.sleep(s)

    def docker_ready(self):
        return self._run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=15)[0] == 0

    def container_state(self, name):
        rc, out = self._run(["docker", "inspect", "-f",
                             "{{.State.Running}}|{{.State.Status}}|{{.State.ExitCode}}|{{.Id}}|{{.Image}}|"
                             "{{.HostConfig.RestartPolicy.Name}}|{{.HostConfig.RestartPolicy.MaximumRetryCount}}",
                             name])
        if rc != 0:
            return None
        try:
            running, status, code, cid, image, policy, retries = out.strip().split("|")
            return {"running": running == "true", "status": status, "exit_code": int(code), "id": cid,
                    "image": image, "restart_policy": policy, "restart_retries": int(retries)}
        except ValueError:
            return {"unparsable": True}

    def image_id(self, tag):
        rc, out = self._run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"])
        return out.strip() if rc == 0 else None

    def paper_snapshot(self, names):
        snap = []
        for n in names:
            rc, out = self._run(["docker", "inspect", "-f",
                                 "{{.Name}} {{.Id}} {{.Image}} {{.State.StartedAt}} {{.RestartCount}} "
                                 "{{.State.Status}}", n])
            snap.append(out.strip() if rc == 0 else f"/{n} MISSING")
        return snap

    def disk_free_gb(self, path):
        return shutil.disk_usage(path).free / 1e9

    def mem_available_mb(self):
        with open("/proc/meminfo") as fh:
            for ln in fh:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / 1024
        return 0.0

    def _read_proc_boot(self):
        """(kernel boot id, boot time in epoch seconds) from procfs."""
        with open("/proc/sys/kernel/random/boot_id") as fh:
            cur_id = fh.read().strip()
        with open("/proc/stat") as fh:
            btime = next(int(ln.split()[1]) for ln in fh if ln.startswith("btime "))
        return cur_id, btime

    def host_boots(self):
        """Current and previous host boot (Class A, read-only). Fails closed: any missing, unparsable or
        inconsistent evidence yields previous=None or orderly=False, never a guess."""
        try:
            cur_id, btime = self._read_proc_boot()
        except (OSError, StopIteration, ValueError, IndexError):
            return {"current": {"boot_id": None, "start_ms": None}, "previous": None}
        rc, out = self._run(["journalctl", "--user", "--list-boots", "-o", "json", "--no-pager"])
        prev = parse_list_boots(out, btime * 1000) if rc == 0 else None
        res = {"current": {"boot_id": normalize_boot_id(cur_id), "start_ms": btime * 1000}, "previous": prev}
        if prev:
            rc2, tail = self._run(["journalctl", "--user", "-b", prev["boot_id"], "-n", "40", "-o", "cat",
                                   "--no-pager"])
            prev["journal_shutdown_target"] = rc2 == 0 and journal_reached_shutdown(tail)
            prev["wtmp_shutdown"] = False
            for extra in ([], ["-f", "/var/log/wtmp.1"]):          # monthly rotation (minsize 1M) moves it
                rc3, wtmp = self._run(["last", "-x", "--time-format", "iso", *extra, "shutdown"])
                if rc3 == 0 and wtmp_orderly_shutdown(wtmp, prev["end_ms"], btime * 1000):
                    prev["wtmp_shutdown"] = True
                    break
            prev["orderly"] = prev["journal_shutdown_target"] and prev["wtmp_shutdown"]
        return res

    def docker_inspect_json(self, name):
        return self._run(["docker", "inspect", name])[1]

    def docker_logs(self, name):
        return self._run(["docker", "logs", "--tail", "2000", name], timeout=60)[1]

    def run_up(self, env_extra, timeout):
        c = self.cfg
        return self._run([os.path.join(HERE, "p2f_continuous_up.sh"), c["image_tag"], c["image_id"],
                          c["dataset_dir"], c["config_file"], c["compose_file"]], timeout=timeout, env=env_extra)

    def run_bind(self, reason, timeout):
        return self._run([sys.executable, "-B", os.path.join(HERE, "p2f_monitor_bind.py"), "bind",
                          "--reason", reason, "--restart"], timeout=timeout)

    def send_alert(self, text):
        a = self.cfg["alert"]
        if not a.get("enabled"):
            return False, "alert_disabled"
        tok = chat = None
        try:
            with open(a["env_file"]) as fh:
                for ln in fh:
                    ln = ln.strip()
                    if ln.startswith("TELEGRAM_BOT_TOKEN="):
                        tok = ln.split("=", 1)[1].strip().strip("\"'")
                    elif ln.startswith("TELEGRAM_CHAT_ID="):
                        chat = ln.split("=", 1)[1].strip().strip("\"'")
        except OSError as e:
            return False, type(e).__name__
        if not tok or not chat:
            return False, "alert_credentials_missing"
        base = a.get("api_base", "https://api.telegram.org")
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:3500]}).encode()
        try:
            with urllib.request.urlopen(f"{base}/bot{tok}/sendMessage", data=data, timeout=15) as r:
                return json.loads(r.read()).get("ok") is True, None
        except Exception as e:                 # never include the URL: it contains the token
            return False, type(e).__name__


# --------------------------------------------------------------------------------------------- boot evidence

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
ORDERLY_MATCH_S = 300          # journal end vs wtmp shutdown start
BOOT_MATCH_S = 900             # wtmp shutdown end (next boot's utmp record) vs kernel boot time: a slow fsck
#                                can delay systemd-update-utmp by minutes


def normalize_boot_id(v):
    """'71a4d947-99ee-...' (procfs) or '71a4d947...' (journal) -> 32 lowercase hex, else None."""
    v = str(v or "").strip().lower().replace("-", "")
    return v if _HEX32.match(v) else None


def parse_list_boots(text, current_start_ms):
    """``journalctl --user --list-boots -o json`` (systemd 255: a JSON array of objects with ``index``,
    ``boot_id``, ``first_entry``, ``last_entry``, timestamps in microseconds). Returns the latest boot that
    ended before the current kernel boot time, or None when the evidence is missing or malformed."""
    try:
        boots = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(boots, list):
        return None
    best = None
    for b in boots:
        if not isinstance(b, dict):
            return None
        bid = normalize_boot_id(b.get("boot_id"))
        first, last = b.get("first_entry"), b.get("last_entry")
        if bid is None or not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in (first, last)) \
                or last < first:
            return None
        end_ms = last // 1000
        if end_ms < current_start_ms and (best is None or end_ms > best["end_ms"]):
            best = {"boot_id": bid, "start_ms": first // 1000, "end_ms": end_ms}
    return best


def journal_reached_shutdown(text):
    """The previous boot's user manager logged reaching shutdown.target (an orderly shutdown)."""
    return any(ln.startswith("Reached target shutdown.target") for ln in str(text or "").splitlines())


_WTMP = re.compile(r"^shutdown\s+system down\s+\S+\s+(\S+)\s+-\s+(\S+)\s")


def _iso_ms(v):
    try:
        t = datetime.datetime.fromisoformat(v)
    except ValueError:
        return None
    return int(t.timestamp() * 1000) if t.tzinfo else None


def wtmp_orderly_shutdown(text, prev_end_ms, current_start_ms):
    """``last -x --time-format iso shutdown``: an orderly shutdown writes a 'shutdown system down <start> - <end>'
    record (end = next boot). True only if one record starts within ORDERLY_MATCH_S of the previous boot's last
    journal entry and ends within ORDERLY_MATCH_S of the current kernel boot time. A power loss writes none."""
    w = ORDERLY_MATCH_S * 1000
    for ln in str(text or "").splitlines():
        m = _WTMP.match(ln)
        if not m:
            continue
        a, b = _iso_ms(m.group(1)), _iso_ms(m.group(2))
        if a is not None and b is not None and abs(a - prev_end_ms) <= w \
                and abs(b - current_start_ms) <= BOOT_MATCH_S * 1000:
            return True
    return False


def compose_restart_policy(text):
    """The collector service's restart policy from the compose text: exactly one uncommented ``restart:`` key
    inside ``services: collector:``, and no ``restart_policy`` anywhere. Returns the unquoted value or raises."""
    lines = str(text).splitlines()
    in_services = in_collector = False
    coll_indent = None
    found = []
    for ln in lines:
        code = ln.split("#", 1)[0].rstrip()
        if not code.strip():
            continue
        indent = len(code) - len(code.lstrip())
        key = code.strip()
        if "restart_policy" in key:
            raise Stop(MANUAL, "compose_has_restart_policy_block")
        if indent == 0:
            in_services, in_collector = key == "services:", False
            continue
        if in_services and key == "collector:":
            in_collector, coll_indent = True, indent
            continue
        if in_collector and indent <= coll_indent:
            in_collector = False
        if in_collector and key.startswith("restart:"):
            found.append(key.split(":", 1)[1].strip().strip("\"'"))
    if len(found) != 1:
        raise Stop(MANUAL, "compose_restart_key_not_unique", {"count": len(found)})
    return found[0]


# --------------------------------------------------------------------------------------------- ledger

def ledger_path(cfg):
    return os.path.join(cfg["state_dir"], "ledger.jsonl")


def read_ledger(cfg):
    p = ledger_path(cfg)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                out.append(json.loads(ln))
    return out


def append_ledger(cfg, rec):
    """Append-only, hash-chained (each record carries the sha256 of the file before it)."""
    os.makedirs(cfg["state_dir"], mode=0o700, exist_ok=True)
    p = ledger_path(cfg)
    rec = {**rec, "prev_sha256": sha256_file(p) if os.path.exists(p) else None, "version": VERSION}
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rec


def verify_ledger_chain(cfg):
    p = ledger_path(cfg)
    if not os.path.exists(p):
        return True
    data = open(p, "rb").read().splitlines(keepends=True)
    prefix = b""
    for ln in data:
        if not ln.strip():
            continue
        rec = json.loads(ln)
        want = hashlib.sha256(prefix).hexdigest() if prefix else None
        if rec.get("prev_sha256") != want:
            return False
        prefix += ln
    return True


def ledger_gate(cfg, ledger, host_boot_id, previous_run_boot):
    """One automatic attempt per host boot; failure circuit; previous run consistent with the ledger."""
    if not verify_ledger_chain(cfg):
        raise Stop(MANUAL, "ledger_chain_broken")
    if any(r.get("kind") == "ATTEMPT" and r.get("host_boot_id") == host_boot_id for r in ledger):
        raise Stop(MANUAL, "already_attempted_this_host_boot")
    fails = 0
    for r in reversed([r for r in ledger if r.get("kind") in ("OUTCOME", "RESET")]):
        if r.get("kind") == "RESET" or r.get("outcome") == RECOVERED:
            break
        if r.get("outcome") == FAILED:
            fails += 1
    if fails >= cfg["max_consecutive_failures"]:
        raise Stop(MANUAL, "failure_circuit_open", {"consecutive_failures": fails})
    recovered = [r for r in ledger if r.get("kind") == "OUTCOME" and r.get("outcome") == RECOVERED]
    if previous_run_boot and any(r.get("previous_run") == previous_run_boot for r in recovered):
        raise Stop(MANUAL, "previous_run_already_recovered_once")
    return fails


# --------------------------------------------------------------------------------------------- classification

def latest_run_record(data):
    rd = os.path.join(data, "runs")
    if not os.path.isdir(rd):
        return None
    runs = []
    for f in os.listdir(rd):
        if f.startswith("run-") and f.endswith(".json"):
            with open(os.path.join(rd, f), encoding="utf-8") as fh:
                runs.append(json.load(fh))
    return max(runs, key=lambda r: r["created_ms"]) if runs else None


def read_health(data):
    p = os.path.join(data, "health", "collector_health.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def classify(cfg, boots, ledger):
    """Classify how the previous run ended. Returns (classification, facts)."""
    data = cfg["dataset_dir"]
    run = latest_run_record(data)
    if run is None:
        return NO_PREVIOUS_RUN, {}
    b = run["boot_id"]
    facts = {"previous_run": b, "previous_run_created_ms": run["created_ms"]}
    lineage = AB.latest_run(data)
    if not lineage or lineage.get("boot_id") != b:
        return UNKNOWN, {**facts, "why": "run_lineage_mismatch"}
    rec = [r for r in ledger if r.get("kind") == "OUTCOME" and r.get("new_run")]
    if rec and rec[-1].get("new_run_created_ms") and run["created_ms"] < rec[-1]["new_run_created_ms"]:
        return UNKNOWN, {**facts, "why": "latest_run_older_than_ledger"}
    cur, prev = boots.get("current") or {}, boots.get("previous")
    mk = os.path.join(data, "control", f"stop-{b[:8]}.json")
    if os.path.exists(mk):
        with open(mk, encoding="utf-8") as fh:
            m = json.load(fh)
        facts["stop_marker"] = {k: m.get(k) for k in ("state", "exit_code", "reason", "ts_ms")}
        if m.get("state") != "STOPPED":
            return FAILED_STOP, facts
        ts = m.get("ts_ms")
        # automatic only for a clean stop caused by the shutdown; a deliberate earlier stop is respected
        if (prev and prev.get("orderly") and cur.get("start_ms") and isinstance(ts, int)
                and run["created_ms"] < cur["start_ms"]
                and prev["end_ms"] - cfg["clean_stop_window_before_s"] * 1000 <= ts
                <= prev["end_ms"] + cfg["clean_stop_window_after_s"] * 1000):
            return CLEAN_STOP, facts
        return OPERATOR_STOP, facts
    facts["stop_marker"] = None
    if not cur.get("start_ms"):
        return UNKNOWN, {**facts, "why": "current_boot_unknown"}
    if run["created_ms"] >= cur["start_ms"]:
        return CRASH_SAME_BOOT, facts
    h = read_health(data)
    if not prev or not h or h.get("boot_id") != b or not isinstance(h.get("ts_ms"), int):
        return POWER_LOSS_OR_UNVERIFIED, {**facts, "why": "no_previous_boot_or_health_evidence"}
    facts.update(last_health_ms=h["ts_ms"], last_health_state=h.get("state"),
                 previous_boot_end_ms=prev["end_ms"], orderly=prev["orderly"])
    # The collector writes state STOPPING (and its health) the moment its stop event fires (a signal), and
    # FAILED on fail-closed paths. A crash (OOM, SIGKILL, segfault) leaves the last periodic state instead.
    # So an unclean end caused by the shutdown shows STOPPING at about the shutdown time.
    if h.get("state") != "STOPPING" or h["ts_ms"] < prev["end_ms"] - cfg["stopping_window_before_s"] * 1000:
        return DIED_BEFORE_SHUTDOWN, facts
    if h["ts_ms"] > prev["end_ms"] + cfg["stopping_window_after_s"] * 1000:
        return UNKNOWN, {**facts, "why": "health_after_previous_boot_end"}
    return (ORDERLY_REBOOT_UNCLEAN if prev["orderly"] else POWER_LOSS_OR_UNVERIFIED), facts


# --------------------------------------------------------------------------------------------- gates

def drift_gates(cfg, host):
    tag_id = host.image_id(cfg["image_tag"])
    if tag_id != cfg["image_id"]:
        raise Stop(MANUAL, "image_id_mismatch", {"actual": tag_id})
    for key, path in (("config_sha256", cfg["config_file"]), ("compose_sha256", cfg["compose_file"])):
        if not os.path.isfile(path):
            raise Stop(MANUAL, f"{key.split('_')[0]}_missing")
        if sha256_file(path) != cfg[key]:
            raise Stop(MANUAL, f"{key.split('_')[0]}_drift")
    with open(cfg["compose_file"], encoding="utf-8") as fh:
        compose = fh.read()
    if compose_restart_policy(compose) != "no":
        raise Stop(MANUAL, "compose_restart_policy_not_no")
    st = host.container_state(cfg["container"])
    if st is not None and not restart_policy_is_no(st):
        raise Stop(MANUAL, "container_restart_policy_not_no", {k: st.get(k) for k in ("restart_policy",
                                                                                     "restart_retries")})
    with open(cfg["config_file"], encoding="utf-8") as fh:
        ccfg = json.load(fh)
    with open(os.path.join(cfg["dataset_dir"], "dataset.json"), encoding="utf-8") as fh:
        ds = json.load(fh)
    if ccfg.get("dataset_id") != ds.get("dataset_id"):
        raise Stop(MANUAL, "dataset_id_mismatch")


def restart_policy_is_no(st):
    """Docker's actual HostConfig for the container: policy 'no' with no retries ('' is Docker's spelling of
    'no' on some versions). Anything unparsable is treated as not 'no'."""
    return (not st.get("unparsable") and st.get("restart_policy") in ("no", "")
            and st.get("restart_retries") == 0)


def incident_gate(cfg):
    blocking = AB.gate(cfg["dataset_dir"])
    if blocking:
        raise Stop(MANUAL, "blocking_critical_incident", sorted(blocking)[:10])


def preserve_evidence(cfg, host, rdir):
    """Copy (never move) the runbook's evidence set; verify every copied file against its source."""
    ev = os.path.join(rdir, "evidence")
    data = cfg["dataset_dir"]
    try:
        os.makedirs(ev, mode=0o700)
        for d in ("control", "incidents", "quarantine", "health"):
            src = os.path.join(data, d)
            if not os.path.isdir(src):
                raise Stop(MANUAL, "evidence_source_missing", d)
            shutil.copytree(src, os.path.join(ev, d), symlinks=True)
        if os.path.isdir(cfg["monitor_dir"]):
            shutil.copytree(cfg["monitor_dir"], os.path.join(ev, "monitor"), symlinks=True)   # runbook: whole dir
        with open(os.path.join(ev, "collector_inspect.json"), "w") as fh:
            fh.write(host.docker_inspect_json(cfg["container"]))
        with open(os.path.join(ev, "collector_logs.txt"), "w") as fh:
            fh.write(host.docker_logs(cfg["container"]))
        sums = []
        for d in ("control", "incidents", "quarantine", "health"):
            for root, _, files in os.walk(os.path.join(ev, d)):
                for f in files:
                    cp = os.path.join(root, f)
                    rel = os.path.relpath(cp, ev)
                    src = os.path.join(data, rel)
                    h = sha256_file(cp)
                    if not os.path.exists(src) or sha256_file(src) != h:
                        raise Stop(MANUAL, "evidence_copy_mismatch", rel)
                    sums.append(f"{h}  {rel}")
        with open(os.path.join(ev, "SHA256SUMS"), "w") as fh:
            fh.write("\n".join(sorted(sums, key=lambda s: s[66:])) + "\n")
    except Stop:
        raise
    except OSError as e:
        raise Stop(MANUAL, "evidence_preservation_failed", type(e).__name__)
    return len(sums)


def wait_docker(cfg, host):
    deadline = host.now_ms() + cfg["docker_wait_s"] * 1000
    while True:
        if host.docker_ready():
            return
        if host.now_ms() >= deadline:
            raise Stop(MANUAL, "docker_not_ready")
        host.sleep(5)


def storage_gates(cfg, host):
    data = cfg["dataset_dir"]
    if not os.path.isfile(os.path.join(data, "dataset.json")):
        raise Stop(MANUAL, "dataset_unavailable")
    free = host.disk_free_gb(data)
    if free < cfg["min_disk_free_gb"]:
        raise Stop(MANUAL, "insufficient_disk", {"free_gb": round(free, 1)})
    mem = host.mem_available_mb()
    if mem < cfg["min_mem_available_mb"]:
        raise Stop(MANUAL, "insufficient_memory", {"available_mb": round(mem)})


def verify_started(cfg, host, prev_boot):
    """Poll (bounded) until the new run is live and healthy enough; never restarts anything."""
    data = cfg["dataset_dir"]
    deadline = host.now_ms() + cfg["health_wait_s"] * 1000
    last = None
    while True:
        st = host.container_state(cfg["container"])
        run = latest_run_record(data)
        h = read_health(data)
        if st and st.get("running") and not restart_policy_is_no(st):
            raise Stop(FAILED, "running_restart_policy_not_no", {k: st.get(k) for k in ("restart_policy",
                                                                                       "restart_retries")})
        ok = (st and st.get("running") and st["image"] == cfg["image_id"]
              and run and run["boot_id"] != prev_boot
              and (prev_boot is None or (run.get("previous_run") or {}).get("boot_id") == prev_boot)
              and h and h.get("boot_id") == run["boot_id"] and h.get("write_errors") == 0
              and (h.get("writer") or {}).get("alive") is True
              and (h.get("writer") or {}).get("beat_age_ms", 1e12) <= cfg["max_health_beat_ms"]
              and (h.get("certifier") or {}).get("alive") is True)
        if ok:
            return run, h, st
        last = {"container": st, "run": run and run["boot_id"], "health_boot": h and h.get("boot_id")}
        if st and not st.get("running"):
            raise Stop(FAILED, "collector_exited_after_start", last)
        if host.now_ms() >= deadline:
            raise Stop(FAILED, "health_not_verified", last)
        host.sleep(10)


# --------------------------------------------------------------------------------------------- orchestration

def alert_text(rep):
    lines = [f"[TSB P2 collector recovery] {rep['outcome']}: {rep['reason']}",
             f"host boot {str(rep.get('host_boot_id') or '?')[:8]}  class {rep.get('classification')}",
             f"previous run {str(rep.get('previous_run'))[:8]}  new run {str(rep.get('new_run'))[:8]}"]
    if rep["outcome"] != RECOVERED:
        lines.append("Manual action needed: see " + rep.get("report_file", "the recovery ledger"))
    return "\n".join(lines)


def report_dir(cfg, rep):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(rep["started_ms"] / 1000))
    return os.path.join(cfg["state_dir"], f"{stamp}-{str(rep.get('host_boot_id') or 'unknown')[:8]}")


def run(cfg, host):
    rep = {"version": VERSION, "started_ms": host.now_ms(), "outcome": None, "reason": None}
    os.makedirs(cfg["state_dir"], mode=0o700, exist_ok=True)
    lock = open(os.path.join(cfg["state_dir"], ".recover.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {**rep, "outcome": LOCKED, "reason": "another_recovery_running"}
    attempted = False
    try:
        wait_docker(cfg, host)
        st = host.container_state(cfg["container"])
        if st and st["running"]:
            return {**rep, "outcome": NOOP_RUNNING, "reason": "collector_already_running"}
        if os.path.exists(os.path.join(cfg["state_dir"], "HOLD")):
            raise Stop(MANUAL, "operator_hold")
        storage_gates(cfg, host)
        boots = host.host_boots()
        rep["host_boot_id"] = boots["current"]["boot_id"]
        rep["boot_evidence"] = boots.get("previous")
        if not rep["host_boot_id"] or not boots["current"].get("start_ms"):
            raise Stop(MANUAL, "current_boot_unverifiable")
        ledger = read_ledger(cfg)
        cls, facts = classify(cfg, boots, ledger)
        rep.update(classification=cls, facts=facts, previous_run=facts.get("previous_run"))
        ledger_gate(cfg, ledger, rep["host_boot_id"], rep["previous_run"])
        if cls not in AUTO_ELIGIBLE:
            raise Stop(MANUAL, f"not_auto_eligible:{cls}")
        ack_env = {}
        if cls == ORDERLY_REBOOT_UNCLEAN:
            if not cfg["policy"]["auto_ack_previous_on_orderly_reboot"]:
                raise Stop(MANUAL, "unclean_stop_needs_operator_ack")
            ack_env = {"P2F_ACK_PREVIOUS": rep["previous_run"][:8]}
        drift_gates(cfg, host)
        incident_gate(cfg)
        rdir = report_dir(cfg, rep)
        rep["report_dir"] = rdir
        rep["evidence_files"] = preserve_evidence(cfg, host, rdir)
        rep["evidence_sums_sha256"] = sha256_file(os.path.join(rdir, "evidence", "SHA256SUMS"))
        rep["paper_before"] = host.paper_snapshot(cfg["paper_containers"])
        append_ledger(cfg, {"kind": "ATTEMPT", "at_ms": host.now_ms(), "host_boot_id": rep["host_boot_id"],
                            "classification": cls, "previous_run": rep["previous_run"],
                            "auto_ack": bool(ack_env), "evidence_sums_sha256": rep["evidence_sums_sha256"]})
        attempted = True
        rc, out = host.run_up(ack_env, cfg["up_timeout_s"])
        rep["up_rc"], rep["up_tail"] = rc, out.strip().splitlines()[-3:]
        if rc != 0 or "UP OK" not in out:
            raise Stop(FAILED, "gated_start_refused_or_failed", {"rc": rc})
        if not re.search(r"\brestart=no\b", out):
            raise Stop(FAILED, "gated_start_restart_policy_unconfirmed")
        newrun, health, cst = verify_started(cfg, host, rep["previous_run"])
        rep.update(new_run=newrun["boot_id"], new_run_created_ms=newrun["created_ms"], container_id=cst["id"])
        brc, bout = host.run_bind(f"CHG-03 automatic recovery after host boot {rep['host_boot_id'][:8]}",
                                  cfg["bind_timeout_s"])
        rep["bind_rc"] = brc
        if brc != 0:
            raise Stop(FAILED, "monitor_rebind_failed", {"rc": brc})
        down = os.path.join(cfg["dataset_dir"], "runs", f"downtime-{newrun['boot_id']}.json")
        rep["downtime_record"] = os.path.exists(down)
        if not rep["downtime_record"]:
            raise Stop(FAILED, "downtime_not_recorded")
        rep["health_state"], rep["health_reasons"] = health.get("state"), health.get("reasons")
        rep["paper_after"] = host.paper_snapshot(cfg["paper_containers"])
        if rep["paper_after"] != rep["paper_before"]:
            raise Stop(FAILED, "paper_containers_changed")
        rep.update(outcome=RECOVERED, reason="recovered")
    except Stop as s:
        rep.update(outcome=s.outcome, reason=s.reason, detail=s.detail)
    finally:
        rep["finished_ms"] = host.now_ms()
        if rep["outcome"] not in (NOOP_RUNNING, LOCKED, None):
            if rep.get("report_dir") is None:
                rep["report_dir"] = report_dir(cfg, rep)
            os.makedirs(rep["report_dir"], mode=0o700, exist_ok=True)
            rep["report_file"] = os.path.join(rep["report_dir"], "report.json")
            with open(rep["report_file"], "w") as fh:
                json.dump(rep, fh, indent=1, sort_keys=True, default=str)
            if attempted or rep["outcome"] in (MANUAL, FAILED):
                append_ledger(cfg, {"kind": "OUTCOME", "at_ms": rep["finished_ms"],
                                    "host_boot_id": rep.get("host_boot_id"), "outcome": rep["outcome"],
                                    "reason": rep["reason"], "previous_run": rep.get("previous_run"),
                                    "new_run": rep.get("new_run"),
                                    "new_run_created_ms": rep.get("new_run_created_ms"),
                                    "attempted": attempted, "report": rep["report_file"]})
            ok, err = host.send_alert(alert_text(rep))
            rep["alert_sent"], rep["alert_error"] = ok, err
            if not ok:
                with open(os.path.join(cfg["state_dir"], "alert_errors.log"), "a") as fh:
                    fh.write(f"{rep['finished_ms']} {rep['outcome']} {rep['reason']} alert_failed {err}\n")
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return rep


def status(cfg, host):
    """Read-only preview: classification and gate results, no lock, no ledger write, no start."""
    out = {"docker_ready": host.docker_ready()}
    st = host.container_state(cfg["container"])
    out["collector"] = st
    boots = host.host_boots()
    ledger = read_ledger(cfg)
    out["classification"], out["facts"] = classify(cfg, boots, ledger)
    for name, fn in (("ledger", lambda: ledger_gate(cfg, ledger, boots["current"]["boot_id"],
                                                    out["facts"].get("previous_run"))),
                     ("drift", lambda: drift_gates(cfg, host)), ("incidents", lambda: incident_gate(cfg)),
                     ("storage", lambda: storage_gates(cfg, host))):
        try:
            fn()
            out[name] = "PASS"
        except Stop as s:
            out[name] = f"{s.outcome}:{s.reason}"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "status", "reset"))
    ap.add_argument("--config", required=True)
    ap.add_argument("--by")
    ap.add_argument("--reason")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
    except Stop as s:
        print(json.dumps({"outcome": s.outcome, "reason": s.reason, "detail": s.detail}))
        return EXIT[MANUAL]
    host = RealHost(cfg)
    if a.cmd == "status":
        print(json.dumps(status(cfg, host), indent=1, sort_keys=True, default=str))
        return 0
    if a.cmd == "reset":
        if not (a.by and a.reason):
            print("reset needs --by and --reason")
            return 2
        append_ledger(cfg, {"kind": "RESET", "at_ms": host.now_ms(), "by": a.by, "reason": a.reason})
        print("failure circuit reset recorded")
        return 0
    rep = run(cfg, host)
    print(json.dumps({k: rep.get(k) for k in ("outcome", "reason", "classification", "previous_run", "new_run",
                                              "report_file")}, sort_keys=True))
    return EXIT[rep["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
