#!/usr/bin/env python3
"""P2-CR bounded OFFLINE validation driver (HOST side). Dev/test only: fake exchange, no Binance, no external network,
no credentials, no production resources. Every container: unique `tsb-p2f-v-*` name, label tsb.purpose=p2cr-offline-
validation, `--network none` (collector joins the fake exchange's empty netns), read-only rootfs, cap-drop ALL,
no-new-privileges, uid 1000, collector limits 0.5 CPU / 384 MiB / 64 PIDs (as production), scratch dataset only.

  cont_v.py v1 <root>      crash / restart matrix (accelerated calendar)
  cont_v.py v2 <root> <dataset> <label> <seconds>   timed continuous run on a given dataset (production calendar)
  cont_v.py v3 <root>      accelerated daily lifecycle (universe drift, rotation, day close) for ~3.3 days
"""
import json
import os
import subprocess
import sys
import time

WT = os.environ.get("V_WT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # code (read-only)
IMAGE = os.environ.get("V_IMAGE", "tsb-p2-forward:p2e1-2707df91-20261003T2142Z")
MON = os.path.join(WT, "ops", "p2f_cont_monitor.py")


def sh(*a, check=True, capture=True):
    r = subprocess.run(list(a), capture_output=capture, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{a}: {r.stderr[-500:]}")
    return r.stdout.strip() if capture else ""


def log(root, msg, **kw):
    line = {"t_ms": int(time.time() * 1000), "msg": msg, **kw}
    with open(os.path.join(root, "driver.jsonl"), "a") as fh:
        fh.write(json.dumps(line, default=str) + "\n")
    print(json.dumps(line, default=str), flush=True)


def tls(root):
    d = os.path.join(root, "tls")
    if os.path.exists(os.path.join(d, "server.pem")):
        return d
    os.makedirs(d, exist_ok=True)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=p2cr-offline-test-ca",
       "-keyout", f"{d}/ca.key", "-out", f"{d}/ca.pem")
    sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=fakex", "-keyout", f"{d}/server.key", "-out", f"{d}/server.csr")
    with open(f"{d}/ext.cnf", "w") as fh:
        fh.write("subjectAltName=DNS:data-api.binance.vision,DNS:data-stream.binance.vision,IP:127.0.0.1\n")
    sh("openssl", "x509", "-req", "-in", f"{d}/server.csr", "-CA", f"{d}/ca.pem", "-CAkey", f"{d}/ca.key", "-CAcreateserial",
       "-days", "30", "-extfile", f"{d}/ext.cnf", "-out", f"{d}/server.pem")
    for f in os.listdir(d):
        os.chmod(os.path.join(d, f), 0o644)
    return d


def common(root, out):
    return ["--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--user", "1000:1000",
            "--label", "tsb.purpose=p2cr-offline-validation", "-v", f"{WT}:/work:ro", "-v", f"{tls(root)}:/tls:ro",
            "-v", f"{out}:/out", "-w", "/work", "--entrypoint", "python", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "STRESS_OUT=/out"]


def fakex(root, name, shift):
    out = os.path.join(root, "out", name); os.makedirs(out, exist_ok=True)
    sh("docker", "rm", "-f", name, check=False)
    sh("docker", "run", "-d", "--name", name, "--network", "none", "--cpus", "1.0", "--memory", "256m", "--pids-limit", "32",
       *common(root, out), "-e", "STRESS_TLS_CERT=/tls/server.pem", "-e", "STRESS_TLS_KEY=/tls/server.key",
       "-e", f"STRESS_UNIVERSE_SHIFT={1 if shift else 0}", IMAGE, "-m", "stress", "fakex")
    time.sleep(2)


def collector(root, name, fx, data, env):
    out = os.path.join(root, "out", name); os.makedirs(out, exist_ok=True)
    sh("docker", "rm", "-f", name, check=False)
    head = sh("git", "-C", WT, "rev-parse", "HEAD")
    envs = []
    for k, v in {**env, "STRESS_TLS_CA": "/tls/ca.pem", "P2F_GIT_COMMIT": f"{head}-offline-validation",
                 "P2F_IMAGE_ID": "offline-validation:" + IMAGE}.items():
        envs += ["-e", f"{k}={v}"]
    sh("docker", "run", "-d", "--name", name, "--network", f"container:{fx}", "--cpus", "0.5", "--memory", "384m",
       "--memory-swap", "384m", "--pids-limit", "64", "--tmpfs", "/tmp:size=16m,mode=1777", *common(root, out),
       "-v", f"{data}:/data", *envs, IMAGE, "-m", "stress", os.environ.get("V_ENTRY", "ccollector"))
    cid = sh("docker", "inspect", "-f", "{{.Id}}", name)
    return cid, out


def health(data):
    try:
        with open(os.path.join(data, "health", "collector_health.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def wait(pred, s, step=0.05):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def files(data, suffixes):
    out = []
    for r, _, fs in os.walk(os.path.join(data, "raw")):
        out += [os.path.join(r, f) for f in fs if f.endswith(suffixes)]
    return out


def monitor(root, cid, data, name):
    out = os.path.join(root, "monitor", name); os.makedirs(out, exist_ok=True)
    return subprocess.Popen([sys.executable, MON, "--dataset", data, "--cid", cid, "--out", out,
                             "--collector-cmdline", "python -m stress ccollector"],
                            stdout=subprocess.DEVNULL, stderr=open(os.path.join(out, "monitor.err"), "w"))


def state_of(name):
    return sh("docker", "inspect", "-f", "{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}", name, check=False)


def cal_env(hour_ms):
    h = int(time.time() * 1000) // hour_ms
    return {"STRESS_CAL_HOUR_MS": str(hour_ms), "STRESS_CAL_EPOCH_HOUR": str(h - 20), "STRESS_CAL_BASE": "2030-01-01T00:00:00+00:00"}


def v1(root):
    """Crash / restart matrix on ONE logical dataset (hour = 20 s, day = 8 min)."""
    data = os.path.join(root, "data"); os.makedirs(data, exist_ok=True)
    fx = "tsb-p2f-v-v1-fakex"; fakex(root, fx, shift=False)
    env = {**cal_env(20_000), "STRESS_DATASET_ID": "v1-crash-matrix",
           "STRESS_CFG": json.dumps({"universe_refresh_at_s": 30, "day_close_after_s": 20, "ws_rotation_s": 400})}
    n = [0]

    def start(tag):
        n[0] += 1
        name = f"tsb-p2f-v-v1-c{n[0]:02d}"
        cid, out = collector(root, name, fx, data, env)
        log(root, "start", name=name, tag=tag, cid=cid[:12])
        return name

    def kill(name, tag, **kw):
        sh("docker", "kill", "-s", "KILL", name, check=False)
        st = state_of(name)
        log(root, "SIGKILL", name=name, tag=tag, state=st, partial=len(files(data, (".partial",))),
            pending=len(files(data, (".pending",))), certifying=len(files(data, (".certifying",))), **kw)
        sh("docker", "rm", "-f", name, check=False)

    def healthy(s=90):
        return wait(lambda: health(data).get("state") == "HEALTHY", s, 0.2)

    c = start("K1 active write"); log(root, "healthy", ok=healthy()); time.sleep(25)
    ok = wait(lambda: files(data, (".partial",)), 10); kill(c, "K1 kill during active write", partials_seen=ok)
    for delay in (0.8, 1.5, 3.0):                                    # K5: kill during startup recovery
        c = start("K5 recovery"); time.sleep(delay); kill(c, f"K5 kill during recovery after {delay}s")
    c = start("K3 certification"); log(root, "healthy", ok=healthy())
    ok = wait(lambda: files(data, (".certifying",)), 120, 0.01); kill(c, "K3 kill during certification", certifying_seen=ok)
    c = start("K2 rotation"); log(root, "healthy", ok=healthy())
    ok = wait(lambda: files(data, (".pending",)), 120, 0.005); kill(c, "K2 kill at hourly rotation (finalized, pending)", pending_seen=ok)
    c = start("K4 manifest append"); log(root, "healthy", ok=healthy())
    md = os.path.join(data, "manifests")
    sizes = {f: os.path.getsize(os.path.join(md, f)) for f in os.listdir(md)}
    ok = wait(lambda: any(os.path.getsize(os.path.join(md, f)) != sizes.get(f) for f in os.listdir(md)), 120, 0.002)
    kill(c, "K4 kill immediately after a manifest append was observed", manifest_change_seen=ok)
    c = start("K6 graceful host-style shutdown"); log(root, "healthy", ok=healthy()); time.sleep(30)
    t0 = time.time(); sh("docker", "stop", "-t", "90", c)
    log(root, "docker stop -t 90", name=c, state=state_of(c), elapsed_s=round(time.time() - t0, 1)); sh("docker", "rm", c)
    c = start("K7 stop with 1 s grace during certification"); log(root, "healthy", ok=healthy())
    ok = wait(lambda: files(data, (".certifying", ".pending")), 120, 0.01)
    t0 = time.time(); sh("docker", "stop", "-t", "1", c)
    log(root, "docker stop -t 1 (SIGKILL after 1 s mid-drain)", name=c, state=state_of(c), seen=ok, elapsed_s=round(time.time() - t0, 1))
    sh("docker", "rm", c)
    c = start("final: run past the next day ends so affected days close")
    cid = sh("docker", "inspect", "-f", "{{.Id}}", c)
    mon = monitor(root, cid, data, "v1-final")
    log(root, "healthy", ok=healthy())
    time.sleep(int(os.environ.get("V1_FINAL_S", "620")))
    sh("docker", "stop", "-t", "90", c); log(root, "final stop", state=state_of(c)); sh("docker", "rm", c)
    mon.terminate()
    sh("docker", "rm", "-f", fx, check=False)
    log(root, "v1 done")


def v2(root, data, label, seconds):
    fx = f"tsb-p2f-v-v2-{label}-fakex"; fakex(root, fx, shift=False)
    env = {"STRESS_DATASET_ID": os.environ.get("V2_DATASET_ID", "v2-scale"), "STRESS_CFG": os.environ.get("V2_CFG", "{}")}
    if os.environ.get("V_ENTRY") == "collector":                     # pre-P2-CR code: bounded harness entry
        env.update({"STRESS_RUNTIME_S": str(seconds + 600), "STRESS_HOUR_S": "180", "STRESS_PREFILL": "0"})
    name = f"tsb-p2f-v-v2-{label}"
    t0 = time.time()
    cid, out = collector(root, name, fx, data, env)
    mon = monitor(root, cid, data, f"v2-{label}")
    ok = wait(lambda: health(data).get("state") == "HEALTHY", 600, 0.2)
    log(root, "v2 healthy", label=label, ok=ok, startup_to_healthy_s=round(time.time() - t0, 1))
    time.sleep(seconds)
    sh("docker", "stop", "-t", "450", name)
    log(root, "v2 stop", label=label, state=state_of(name), cid=cid)
    sh("docker", "rm", name); mon.terminate()
    sh("docker", "rm", "-f", fx, check=False)


def v3(root):
    data = os.path.join(root, "data"); os.makedirs(data, exist_ok=True)
    fx = "tsb-p2f-v-v3-fakex"; fakex(root, fx, shift=True)
    env = {**cal_env(30_000), "STRESS_DATASET_ID": "v3-daily-lifecycle",
           "STRESS_CFG": json.dumps({"universe_refresh_at_s": 20, "day_close_after_s": 30, "ws_rotation_s": 690})}
    name = "tsb-p2f-v-v3-c01"
    cid, out = collector(root, name, fx, data, env)
    mon = monitor(root, cid, data, "v3")
    log(root, "v3 start", cid=cid[:12], calendar=env)
    log(root, "healthy", ok=wait(lambda: health(data).get("state") == "HEALTHY", 120, 0.2))
    time.sleep(int(os.environ.get("V3_S", "2400")))
    sh("docker", "stop", "-t", "450", name)
    log(root, "v3 stop", state=state_of(name)); sh("docker", "rm", name); mon.terminate()
    sh("docker", "rm", "-f", fx, check=False)


if __name__ == "__main__":
    cmd, root = sys.argv[1], sys.argv[2]
    os.makedirs(root, exist_ok=True)
    {"v1": lambda: v1(root), "v3": lambda: v3(root),
     "v2": lambda: v2(root, sys.argv[3], sys.argv[4], int(sys.argv[5]))}[cmd]()
