#!/usr/bin/env python3
"""Read-only runtime provenance manifest for released images.

`generate` reads each image with `docker image inspect` and `docker save` (both read-only: no container is created,
started or changed) and compares every file under the image's app root with the git tree of its declared source
commit. `verify` regenerates and diffs against a committed manifest.

Per file it records the sha256, the git blob id, the size and a classification:
  match      blob equals the source-commit blob at the mapped path
  assembled  blob differs from the source commit but exists in git history (first commit containing it is recorded)
  unknown    blob is in no reachable commit
  dormant    path is in the Dockerfile COPY scope at the source commit but absent from the image (listed separately)
Installed Python distributions are read from *.dist-info directory names in the merged layers.

Usage:
  runtime_manifest.py generate SPEC.json OUT.json [--repo PATH]
  runtime_manifest.py verify   SPEC.json MANIFEST.json [--repo PATH]
"""
import argparse
import fnmatch
import hashlib
import io
import json
import posixpath
import re
import subprocess
import sys
import tarfile

DIST = re.compile(r'(\.wh\.)?([A-Za-z0-9_.]+)-([0-9][^-/]*)\.dist-info$')


def run(*cmd, repo=None, text=True):
    full = (['git', '-C', repo] + list(cmd)) if repo else list(cmd)
    r = subprocess.run(full, capture_output=True, text=text)
    if r.returncode != 0:
        raise SystemExit(f'command failed: {" ".join(full)}: {r.stderr.strip()[:300]}')
    return r.stdout


def image_layers(image):
    """Yield (layer_tarfile) in order, streaming `docker save`."""
    p = subprocess.Popen(['docker', 'save', image], stdout=subprocess.PIPE)
    outer = tarfile.open(fileobj=p.stdout, mode='r|')
    blobs, manifest = {}, None
    for m in outer:
        f = outer.extractfile(m) if m.isfile() else None
        if f is None:
            continue
        data = f.read()
        if m.name == 'manifest.json':
            manifest = json.loads(data)
        else:
            blobs[m.name] = data
    if p.wait() != 0:
        raise SystemExit(f'docker save failed for {image}')
    for name in manifest[0]['Layers']:
        try:
            yield tarfile.open(fileobj=io.BytesIO(blobs[name]), mode='r:*')
        except tarfile.ReadError:
            continue


def merged_view(image, root):
    """Merged file view under `root` (whiteouts applied) plus installed distributions."""
    root = root.strip('/') + '/'
    files, dists = {}, {}
    for t in image_layers(image):
        for m in t:
            n = m.name.lstrip('./')
            base = posixpath.basename(n.rstrip('/'))
            dm = DIST.match(base)
            if dm:
                key = (dm.group(2).lower().replace('_', '-'), dm.group(3))
                if dm.group(1):
                    dists.pop(key, None)
                else:
                    dists[key] = True
            if not n.startswith(root):
                continue
            rel = n[len(root):]
            d = posixpath.dirname(rel)
            if base == '.wh..wh..opq':
                for k in [k for k in files if k.startswith(d + '/')]:
                    del files[k]
                continue
            if base.startswith('.wh.'):
                tgt = posixpath.join(d, base[4:])
                files.pop(tgt, None)
                for k in [k for k in files if k.startswith(tgt + '/')]:
                    del files[k]
                continue
            if m.isfile():
                b = t.extractfile(m).read()
                files[rel] = {'sha256': hashlib.sha256(b).hexdigest(),
                              'git_blob': hashlib.sha1(b'blob %d\0' % len(b) + b).hexdigest(), 'bytes': len(b)}
            elif m.issym():
                files[rel] = {'symlink': m.linkname}
    return files, sorted(f'{n}=={v}' for n, v in dists)


def expected_tree(repo, commit, copy_map, excludes=()):
    """{image_rel_path: git_blob} for the Dockerfile COPY scope at `commit` (.dockerignore patterns applied)."""
    out = run('ls-tree', '-r', commit, repo=repo)
    tree = {l.split('\t', 1)[1]: l.split()[2] for l in out.splitlines()
            if not any(fnmatch.fnmatch(l.split('\t', 1)[1], g) or fnmatch.fnmatch(posixpath.basename(l.split('\t', 1)[1]), g)
                       for g in excludes)}
    exp = {}
    for src, dst in copy_map:
        for p, b in tree.items():
            if src.endswith('/') and p.startswith(src):
                exp[dst + p[len(src):]] = b
            elif p == src:
                exp[dst] = b
    return exp


def first_commit_with(repo, blob, cache={}):
    if blob not in cache:
        out = run('log', '--all', '--reverse', '--format=%H', f'--find-object={blob}', repo=repo).split()
        cache[blob] = out[0] if out else None
    return cache[blob]


def inspect(image):
    d = json.loads(run('docker', 'image', 'inspect', image))[0]
    cfg = d.get('Config') or {}
    env = [e for e in (cfg.get('Env') or []) if e.split('=', 1)[0].startswith(('P2F_GIT_COMMIT', 'P2F_IMAGE_TAG',
                                                                              'P2F_BUILD_TIME', 'PYTHON_VERSION'))]
    return {'image_id': d['Id'], 'repo_digests': sorted(d.get('RepoDigests') or []), 'repo_tags': sorted(d.get('RepoTags') or []),
            'created': d.get('Created'), 'architecture': d.get('Architecture'),
            'rootfs_layers': (d.get('RootFS') or {}).get('Layers') or [],
            'labels': {k: v for k, v in (cfg.get('Labels') or {}).items() if k.startswith('org.opencontainers')},
            'provenance_env': env, 'workdir': cfg.get('WorkingDir'),
            'entrypoint': cfg.get('Entrypoint'), 'cmd': cfg.get('Cmd')}


def generate(spec, repo):
    out = {'schema': 'tsb-runtime-manifest/1', 'release': spec['release'], 'generated_from': 'docker save + git (read-only)',
           'services': {}}
    for s in spec['services']:
        entry = {'image': s['image'], 'container': s.get('container'), 'source_reference': s.get('source_reference'),
                 'inspect': inspect(s['image'])}
        if s.get('app_root'):
            files, dists = merged_view(s['image'], s['app_root'])
            files = {k: v for k, v in files.items() if '__pycache__' not in k and not k.endswith('.pyc')}
            exp = (expected_tree(repo, s['source_commit'], s['copy_map'], spec.get('dockerignore_excludes', ()))
                   if s.get('source_commit') else {})
            cls = {}
            for k, v in sorted(files.items()):
                b = v.get('git_blob')
                if b and exp.get(k) == b:
                    c = 'match'
                elif b and first_commit_with(repo, b):
                    c = 'assembled'
                else:
                    c = 'unknown'
                rec = dict(v, classification=c)
                if c == 'assembled':
                    rec['first_commit_containing_blob'] = first_commit_with(repo, b)
                cls[k] = rec
            entry.update({'source_commit': s.get('source_commit'), 'app_root': s['app_root'], 'copy_map': s['copy_map'],
                          'files': cls, 'dormant': sorted(k for k in exp if k not in files),
                          'installed_distributions': dists,
                          'summary': {c: sum(1 for r in cls.values() if r['classification'] == c)
                                      for c in ('match', 'assembled', 'unknown')}})
            entry['summary']['dormant'] = len(entry['dormant'])
        out['services'][s['service']] = entry
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['generate', 'verify'])
    ap.add_argument('spec')
    ap.add_argument('manifest')
    ap.add_argument('--repo', default='.')
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    new = generate(spec, a.repo)
    if a.mode == 'generate':
        with open(a.manifest, 'w') as f:
            json.dump(new, f, indent=1, sort_keys=True)
            f.write('\n')
        for k, v in new['services'].items():
            print(k, v['inspect']['image_id'][:19], v.get('summary', '-'))
        return 0
    old = json.load(open(a.manifest))
    bad = 0
    for k, v in old['services'].items():
        n = new['services'].get(k)
        same = n is not None and json.dumps(n, sort_keys=True) == json.dumps(v, sort_keys=True)
        print(('OK   ' if same else 'DIFF ') + k)
        bad += not same
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
