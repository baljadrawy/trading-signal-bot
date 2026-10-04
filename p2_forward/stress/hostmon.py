"""HOST-side stress monitor / load injector (stdlib only; runs OUTSIDE the capped container, so none of its work is
charged to the collector's cgroup).

* cgroup sampler (1 s): cpu.stat (usage / nr_periods / nr_throttled / throttled_usec), memory.current/peak,
  pids.current of the collector container's own cgroup; identity: cpu.max, memory.max, pids.max, cgroup.procs and
  /proc/<pid>/cgroup + cmdline of every process in it (re-captured every 30 s).
* lifecycle poller (100 ms): first-seen time of every segment's .partial / .pending / .certifying / certified state.
* injector: at every virtual-hour boundary (+1 s) from cycle --inject-from on, hard-links `mult` x one real G3-v6
  hour of finalized segments (data + idx) into raw/zl<type>/2099-01-01/ as *.pending (fresh mtime). The real
  certifier process certifies them with the unchanged writer.certify() (full decode/validate/sha/rename/manifest).
* archiver: removes injected segments ONLY after their manifest entry exists (certification's last step), so the
  raw/ tree stays representative and nothing is removed mid-certification.
"""
import argparse
import json
import os
import subprocess
import time

LOAD_DAY = "2099-01-01"
TYPES = ("book", "depth", "market", "candle", "clock", "health")


def rd(p):
    try:
        with open(p) as fh:
            return fh.read().strip()
    except OSError:
        return None


def kv(text):
    out = {}
    for line in (text or "").splitlines():
        k, _, v = line.partition(" ")
        out[k] = int(v) if v.isdigit() else v
    return out


def identity(cg):
    procs = (rd(os.path.join(cg, "cgroup.procs")) or "").split()
    pinfo = []
    for p in procs:
        cmd = (rd(f"/proc/{p}/cmdline") or "").replace("\x00", " ").strip()
        pinfo.append({"host_pid": int(p), "cgroup": rd(f"/proc/{p}/cgroup"), "cmdline": cmd,
                      "ns_pid": (kv((rd(f"/proc/{p}/status") or "").replace(":\t", " ")).get("NSpid") or "")})
    return {"t_ms": int(time.time() * 1000), "cgroup_dir": cg, "cpu.max": rd(os.path.join(cg, "cpu.max")),
            "memory.max": rd(os.path.join(cg, "memory.max")), "memory.swap.max": rd(os.path.join(cg, "memory.swap.max")),
            "pids.max": rd(os.path.join(cg, "pids.max")), "procs": pinfo}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cid", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--load", required=True)
    ap.add_argument("--hour-s", type=int, default=180)
    ap.add_argument("--mult", default="1", help="comma list: multiplier per injected cycle (last repeats)")
    ap.add_argument("--inject-from", type=int, default=2, help="first boundary index (from start) that gets load")
    ap.add_argument("--hours", default="h12,h11,h10,h09,h13")
    ap.add_argument("--kill", default="", help="confirmation only: 'offset_s:idle|busy,...' SIGKILL the certifier")
    a = ap.parse_args()
    cg = f"/sys/fs/cgroup/system.slice/docker-{a.cid}.scope"
    mult = [int(x) for x in a.mult.split(",")]
    hours = a.hours.split(",")
    fcg = open(os.path.join(a.out, "cgroup.tsv"), "a", buffering=1)
    fcg.write("t_ms\tusage_usec\tuser_usec\tsystem_usec\tnr_periods\tnr_throttled\tthrottled_usec\tmem_current\t"
              "mem_peak\tpids_current\tcpu_pressure_some_total\n")
    fid = open(os.path.join(a.out, "cgroup_identity.jsonl"), "a", buffering=1)
    fth = open(os.path.join(a.out, "threads.jsonl"), "a", buffering=1)
    last_th = 0.0
    flc = open(os.path.join(a.out, "lifecycle.jsonl"), "a", buffering=1)
    finj = open(os.path.join(a.out, "inject.jsonl"), "a", buffering=1)
    seen = {}
    start = time.time()
    first_boundary = (int(start) // a.hour_s + 1) * a.hour_s
    boundary_idx, next_b = 0, first_boundary
    last_cg = last_id = last_arch = 0.0
    archived, mpos = 0, 0
    raw = os.path.join(a.data, "raw")
    kills = sorted((int(x.split(":")[0]), x.split(":")[1]) for x in a.kill.split(",") if x)
    fk = open(os.path.join(a.out, "kills.jsonl"), "a", buffering=1)

    def certifier_pids():
        out = []
        for pid in (rd(os.path.join(cg, "cgroup.procs")) or "").split():
            if "spawn_main" in (rd(f"/proc/{pid}/cmdline") or ""):
                out.append(int(pid))
        return out

    def certifying_now():
        for root, _, files in os.walk(raw):
            if any(f.endswith(".certifying") for f in files):
                return True
        return False
    while True:
        now = time.time()
        alive = os.path.isdir(cg)
        if now - last_cg >= 1.0 and alive:
            last_cg = now
            st = kv(rd(os.path.join(cg, "cpu.stat")))
            pr = rd(os.path.join(cg, "cpu.pressure")) or ""
            some = [x for x in pr.split() if x.startswith("total=")]
            fcg.write("\t".join(str(x) for x in (int(now * 1000), st.get("usage_usec"), st.get("user_usec"),
                                                 st.get("system_usec"), st.get("nr_periods"), st.get("nr_throttled"),
                                                 st.get("throttled_usec"), rd(os.path.join(cg, "memory.current")),
                                                 rd(os.path.join(cg, "memory.peak")), rd(os.path.join(cg, "pids.current")),
                                                 some[0][6:] if some else "")) + "\n")
        if now - last_th >= 0.25 and alive:                  # per-process / per-thread CPU ticks (host /proc)
            last_th = now
            row = {"t_ms": int(now * 1000), "p": {}}
            for pid in (rd(os.path.join(cg, "cgroup.procs")) or "").split():
                try:
                    for tid in os.listdir(f"/proc/{pid}/task"):
                        f = (rd(f"/proc/{pid}/task/{tid}/stat") or "").rsplit(")", 1)
                        if len(f) == 2:
                            v = f[1].split()
                            row["p"][f"{pid}/{tid}"] = [f[0].split("(", 1)[1], int(v[11]) + int(v[12])]
                except OSError:
                    pass
            fth.write(json.dumps(row, separators=(",", ":")) + "\n")
        if now - last_id >= 30.0 and alive:
            last_id = now
            fid.write(json.dumps(identity(cg)) + "\n")
        # lifecycle poller
        if os.path.isdir(raw):
            for root, _, files in os.walk(raw):
                for f in files:
                    if ".jsonl.gz" not in f or f.endswith(".sha256") or ".tmp" in f:
                        continue
                    stem, _, suf = f.partition(".jsonl.gz")
                    state = {"": "certified", ".partial": "active", ".pending": "pending",
                             ".certifying": "certifying"}.get(suf)
                    if state and (stem, state) not in seen:
                        seen[(stem, state)] = now
                        flc.write(json.dumps({"t_ms": int(now * 1000), "seg": stem, "state": state,
                                              "dir": os.path.relpath(root, raw)}) + "\n")
        # confirmation kills (host SIGKILL of the certifier process; never the collector)
        if kills and alive and now - start >= kills[0][0] and (kills[0][1] == "idle" or certifying_now()
                                                                or now - start >= kills[0][0] + 200):
            off, mode = kills.pop(0)
            pids = certifier_pids()
            busy = certifying_now()
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            fk.write(json.dumps({"t_ms": int(time.time() * 1000), "offset_s": off, "mode": mode, "pids": pids,
                                 "certifying_at_kill": busy}) + "\n")
        # injector
        if now >= next_b + 1.0:
            if boundary_idx >= a.inject_from:
                cyc = boundary_idx - a.inject_from
                m = mult[min(cyc, len(mult) - 1)]
                t0 = time.time(); n = 0
                for j in range(m):
                    h = hours[j % len(hours)]
                    for typ in TYPES:
                        src = os.path.join(a.load, h, typ)
                        if not os.path.exists(src + ".jsonl.gz"):
                            continue
                        d = os.path.join(raw, f"zl{typ}", LOAD_DAY)
                        os.makedirs(d, exist_ok=True)
                        name = f"zl{typ}-C{cyc:04d}{j:02d}Z-ld{h}load-0001"
                        os.link(src + ".idx", os.path.join(d, name + ".idx.pending"))
                        os.link(src + ".jsonl.gz", os.path.join(d, name + ".jsonl.gz.pending"))
                        for p in (name + ".idx.pending", name + ".jsonl.gz.pending"):
                            os.utime(os.path.join(d, p))
                        n += 1
                finj.write(json.dumps({"t_ms": int(t0 * 1000), "boundary_ms": next_b * 1000, "cycle": cyc, "mult": m,
                                       "segments": n, "inject_ms": round((time.time() - t0) * 1000, 2)}) + "\n")
            boundary_idx += 1
            next_b += a.hour_s
        # archiver (manifest entry = certification complete)
        if now - last_arch >= 2.0:
            last_arch = now
            mp = os.path.join(a.data, "manifests", LOAD_DAY + ".jsonl")
            if os.path.exists(mp):
                with open(mp) as fh:
                    fh.seek(mpos)
                    for line in fh:
                        if not line.endswith("\n"):
                            break
                        mpos += len(line.encode())
                        rel = json.loads(line)["segment"]
                        p = os.path.join(a.data, rel)
                        for q in (p, p + ".sha256", p[:-9] + ".idx"):
                            try:
                                os.unlink(q)
                            except FileNotFoundError:
                                pass
                        archived += 1
        if not alive and now - start > 60:
            st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", a.cid], capture_output=True, text=True)
            if st.stdout.strip() != "true":
                break
        time.sleep(0.1 - (time.time() - now) % 0.1)
    with open(os.path.join(a.out, "hostmon_done.json"), "w") as fh:
        json.dump({"end_ms": int(time.time() * 1000), "boundaries": boundary_idx, "archived": archived}, fh)


if __name__ == "__main__":
    main()
