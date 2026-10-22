import json, sys, sysconfig, platform, hashlib, importlib.metadata as md
out = {"python": sys.version.split()[0], "machine": platform.machine(),
       "platform_tag": sysconfig.get_platform(), "libc": platform.libc_ver(), "dists": []}
for d in md.distributions():
    p = d._path
    wheel = d.read_text("WHEEL") or ""
    tags = [l.split(":",1)[1].strip() for l in wheel.splitlines() if l.startswith("Tag:")]
    gen = [l.split(":",1)[1].strip() for l in wheel.splitlines() if l.startswith("Generator:")]
    rec = d.read_text("RECORD")
    direct = d.read_text("direct_url.json")
    out["dists"].append({
        "name": d.metadata["Name"], "version": d.version,
        "dist_info": p.name, "location": str(p.parent),
        "installer": (d.read_text("INSTALLER") or "").strip(),
        "wheel_tags": tags, "wheel_generator": gen,
        "root_is_purelib": "Root-Is-Purelib: true" in wheel,
        "record_sha256": hashlib.sha256(rec.encode()).hexdigest() if rec else None,
        "record_files": len(rec.splitlines()) if rec else 0,
        "direct_url": json.loads(direct) if direct else None,
        "requested": d.read_text("REQUESTED") is not None,
        "requires_dist": d.requires or [],
        "requires_python": d.metadata.get("Requires-Python"),
    })
json.dump(out, sys.stdout, indent=1, sort_keys=True)
