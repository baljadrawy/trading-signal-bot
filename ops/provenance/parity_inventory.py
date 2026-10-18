#!/usr/bin/env python3
"""Read-only, GitHub-static source/build/runtime parity inventory (R1.4). No Docker, network or production access.

It audits what an external reviewer can verify from the repository alone, and keeps three verification layers apart:
  source  - is the running image's source identified by commit and per-file evidence in the repository?
  build   - can the image be rebuilt canonically from committed inputs (pinned base digest, revision label wiring,
            a committed dependency lock that matches the recorded installed set, a CI build attestation)?
  runtime - is what runs attested by trusted server-origin evidence? NEVER provable from GitHub metadata: always
            reported as not verified here (`runtime_parity_verified: false`).

Inputs (all committed): deploy/DEPLOYED.json (observed baseline), each service's Dockerfile, requirements and optional
lock, docker-compose.yml, and the recorded installed-package inventories of the release record.

Exit: 0 = no blockers (still REVIEW_REQUIRED, never runtime parity), 2 = blockers found, 1 = inputs unreadable.
Usage: parity_inventory.py [--root DIR] [--manifest PATH] [--installed-dir PATH]
"""
import argparse
import json
import pathlib
import re
import sys

SCHEMA = 'tsb-r14-static-audit/2'
DEFAULT_ROOT = pathlib.Path(__file__).resolve().parents[2]
# service -> (directory with Dockerfile/requirements, compose service name or None, installed inventory name)
SERVICES = {
    'scanner': ('scanner', 'scanner', 'scanner'),
    'analyzer': ('analyzer', 'analyzer', 'analyzer'),
    'signal_engine': ('signal_engine', 'signal_engine', 'signal_engine'),
    'trade_tracker': ('trade_tracker', 'trade_tracker', 'trade_tracker'),
    'telegram': ('telegram', 'telegram', 'telegram'),
    'collector': ('p2_forward', None, 'collector'),
}
PIN = re.compile(r'^([A-Za-z0-9_.\[\]-]+)==([^\s;]+)(?:\s*;.*)?$')
BASE_IMAGES = {'pip', 'setuptools', 'wheel'}
LOCK_NAMES = ('requirements.lock', 'requirements.lock.txt', 'constraints.txt')


def norm(name):
    return re.sub(r'[-_.]+', '-', re.sub(r'\[.*\]', '', name)).lower()


def read_requirements(path):
    """Return (pins {name: version}, non-exact lines). Inline and full-line comments are ignored."""
    pins, loose = {}, []
    for raw in path.read_text().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        m = PIN.match(line)
        if m:
            pins[norm(m.group(1))] = m.group(2)
        else:
            loose.append(line)
    return pins, loose


def read_installed(path):
    out = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith('#') and '==' in line:
            n, v = line.split('==', 1)
            out[norm(n)] = v
    return out


def compose_images(path):
    """Minimal parser: top-level `services:` blocks with a two-space service key and an `image:` line."""
    images, svc = {}, None
    for raw in path.read_text().splitlines():
        m = re.match(r'^  ([A-Za-z0-9_-]+):\s*$', raw)
        if m:
            svc = m.group(1)
            continue
        m = re.match(r'^\s{4}image:\s*([^\s#]+)', raw)
        if m and svc:
            images[svc] = m.group(1)
    return images


def audit_service(name, cfg, runtime, root, installed_dir, compose):
    src_dir, compose_svc, inv_name = cfg
    issues = []          # (layer, message)

    def gap(layer, msg):
        issues.append({'layer': layer, 'issue': msg})

    if runtime is None:
        gap('runtime', 'service absent from deploy/DEPLOYED.json')
        return {'service': name, 'status': 'BLOCKED', 'source_verified': False, 'build_verified': False,
                'runtime_verified': False, 'issues': issues}
    prov, repro = runtime.get('provenance', {}), runtime.get('reproducibility', {})
    # --- source layer
    evidence_ok = all((root / e).exists() for e in prov.get('evidence', []))
    if prov.get('source_kind') != 'commit':
        gap('source', f"image source is not a single commit (source_kind={prov.get('source_kind')})")
    if not prov.get('evidence') or not evidence_ok:
        gap('source', 'per-file source evidence missing from the repository')
    source_ok = prov.get('source_kind') == 'commit' and bool(prov.get('evidence')) and evidence_ok
    # --- build layer
    dockerfile = root / src_dir / 'Dockerfile'
    if not dockerfile.is_file():
        gap('build', 'missing versioned Dockerfile')
    else:
        text = dockerfile.read_text()
        froms = re.findall(r'^FROM\s+(\S+)', text, re.M)
        if not froms or any(not re.search(r'@sha256:[0-9a-f]{64}$', f) for f in froms):
            gap('build', 'base image not pinned by immutable digest')
        if 'org.opencontainers.image.revision' not in text:
            gap('build', 'no OCI revision label in Dockerfile')
        elif re.search(r'ARG\s+BUILD_REVISION=unknown', text):
            gap('build', "revision label defaults to 'unknown' (a release build must pass BUILD_REVISION)")
    req = root / src_dir / 'requirements.txt'
    installed_path = installed_dir / f'{inv_name}.txt'
    installed = read_installed(installed_path) if installed_path.is_file() else None
    if not req.is_file():
        gap('build', 'missing requirements.txt')
    else:
        pins, loose = read_requirements(req)
        if loose or not pins:
            gap('build', 'requirements are not all exact pins')
        if installed is None:
            gap('build', 'no recorded installed-package inventory to compare with')
        else:
            mism = sorted(f'{k} pinned {v}, installed {installed.get(k, "absent")}'
                          for k, v in pins.items() if installed.get(k) != v)
            if mism:
                gap('build', 'requirements pins differ from the installed runtime set: ' + '; '.join(mism))
            unpinned = sorted(set(installed) - set(pins) - BASE_IMAGES)
            lock = next((root / src_dir / n for n in LOCK_NAMES if (root / src_dir / n).is_file()), None)
            if lock is None and unpinned:
                gap('build', f'no committed dependency lock: {len(unpinned)} installed distributions are not pinned')
    if repro.get('level') != 'L2-canonical-rebuild' or not repro.get('canonical_rebuild'):
        gap('build', 'no verified canonical rebuild (no CI build attestation)')
    if not any(a.get('role') == 'running image' and re.fullmatch(r'[0-9a-f]{64}', str(a.get('sha256', '')))
               for a in runtime.get('archives', [])):
        gap('build', 'no checksummed archive of the running image referenced')
    # --- deployment reference (static)
    if compose_svc is not None:
        ref = compose.get(compose_svc)
        if ref is None:
            gap('runtime', f'compose has no image: for service {compose_svc}')
        elif ref != runtime.get('observed', {}).get('image_ref'):
            gap('runtime', f'compose image ({ref}) differs from the observed image reference')
    # --- runtime layer: never provable from GitHub
    gap('runtime', 'runtime parity requires trusted server-origin attestation (not verifiable from GitHub)')
    blocking = [i for i in issues if i['layer'] != 'runtime' or 'requires trusted' not in i['issue']]
    return {'service': name, 'status': 'BLOCKED' if blocking else 'REVIEW_REQUIRED',
            'source_verified': source_ok, 'build_verified': False if blocking else None,
            'runtime_verified': False, 'issues': issues}


def audit(root=DEFAULT_ROOT, manifest_path=None, installed_dir=None):
    root = pathlib.Path(root)
    manifest_path = pathlib.Path(manifest_path or root / 'deploy' / 'DEPLOYED.json')
    installed_dir = pathlib.Path(installed_dir or root / 'deploy' / 'a561-rel-ea8ae4f' / 'installed-packages')
    manifest = json.loads(manifest_path.read_text())
    compose_path = root / 'docker-compose.yml'
    compose = compose_images(compose_path) if compose_path.is_file() else {}
    results = [audit_service(n, c, manifest.get('services', {}).get(n), root, installed_dir, compose)
               for n, c in SERVICES.items()]
    blockers = [f"{r['service']}: [{i['layer']}] {i['issue']}" for r in results for i in r['issues']
                if not (i['layer'] == 'runtime' and 'requires trusted' in i['issue'])]
    return {'schema': SCHEMA, 'scope': 'GITHUB_STATIC_ONLY', 'runtime_observed_at': manifest.get('observed_at'),
            'runtime_parity_verified': False,
            'layers': {'source': 'identified by commit and per-file evidence in the repository',
                       'build': 'canonical rebuild from committed inputs; requires a CI build attestation',
                       'runtime': 'requires trusted server-origin attestation; never verified by this tool'},
            'services': results, 'blockers': blockers}


def main(argv=None):
    ap = argparse.ArgumentParser(description='GitHub-static R1.4 parity inventory (read-only)')
    ap.add_argument('--root', default=str(DEFAULT_ROOT))
    ap.add_argument('--manifest')
    ap.add_argument('--installed-dir')
    a = ap.parse_args(argv)
    try:
        out = audit(a.root, a.manifest, a.installed_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'schema': SCHEMA, 'error': f'inputs unreadable: {type(exc).__name__}',
                          'runtime_parity_verified': False}))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if not out['blockers'] else 2


if __name__ == '__main__':
    sys.exit(main())
