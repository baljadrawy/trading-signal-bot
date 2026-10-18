#!/usr/bin/env python3
"""Render host-specific operational templates and compare them with what is installed. READ-ONLY on the host.

Only `${NAME}` tokens whose NAME is defined in the values file are substituted. Any other `${UPPER_CASE}` token is an
error (no silent gaps). Shell syntax such as `$D`, `$(...)` or `$o` is left untouched.

  render.py render  VALUES OUTDIR     write rendered files under OUTDIR (never into the installed locations)
  render.py compare VALUES            byte-compare each rendered template with its installed counterpart;
                                      crontab fragments must appear verbatim, in order, in `crontab -l`;
                                      a template with a verbatim repo copy must also render to that copy (drift guard)
Exit status 0 = everything identical, 1 = a difference, 2 = usage or template error. It never installs anything.
"""
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOKEN = re.compile(r'\$\{([A-Z][A-Z0-9_]*)\}')


def load_values(path):
    vals = {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#'):
            k, v = line.split('=', 1)
            vals[k.strip()] = v.strip()
    return vals


def render_text(text, vals, where):
    missing = sorted({m.group(1) for m in TOKEN.finditer(text) if m.group(1) not in vals})
    if missing:
        raise SystemExit(f'{where}: undefined template values {missing}')
    return TOKEN.sub(lambda m: vals[m.group(1)], text)


def entries(vals):
    for line in open(os.path.join(ROOT, 'ops/host/INSTALL_MAP.tsv'), encoding='utf-8'):
        if line.strip() and not line.startswith('#'):
            tpl, dst, kind, copy = (line.rstrip('\n').split('\t') + ['-'])[:4]
            yield tpl, render_text(dst, vals, 'INSTALL_MAP'), kind, copy


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main(argv):
    if len(argv) < 3 or argv[1] not in ('render', 'compare'):
        print(__doc__)
        return 2
    vals = load_values(argv[2])
    bad = 0
    for tpl, dst, kind, copy in entries(vals):
        src = os.path.join(ROOT, tpl)
        if not os.path.exists(src):
            print(f'SOURCE-MISSING {tpl} (provided by the collector runtime-import PR)')
            bad += 1
            continue
        out = render_text(open(src, encoding='utf-8').read(), vals, tpl).encode()
        if argv[1] == 'render':
            target = os.path.join(argv[3], os.path.basename(tpl).removesuffix('.tmpl'))
            with open(target, 'wb') as f:
                f.write(out)
            print(f'rendered {tpl} -> {target} sha256={sha(out)[:16]}')
            continue
        if kind == 'file':
            try:
                inst = open(dst, 'rb').read()
            except OSError as e:
                print(f'MISSING  {dst} ({e.strerror})')
                bad += 1
                continue
            same = inst == out
            print(f'{"IDENTICAL" if same else "DIFFERENT"} {tpl} vs {dst} sha256={sha(out)[:16]}/{sha(inst)[:16]}')
            bad += not same
            if copy != '-' and os.path.exists(os.path.join(ROOT, copy)):
                rc = open(os.path.join(ROOT, copy), 'rb').read() == out
                print(f'{"IDENTICAL" if rc else "DIFFERENT"} {tpl} vs repo copy {copy}')
                bad += not rc
        elif kind == 'crontab-fragment':
            live = subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout.splitlines()
            want = [l for l in out.decode().splitlines() if l and not l.startswith('#')]
            pos, ok = 0, True
            for w in want:
                try:
                    pos = live.index(w, pos) + 1
                except ValueError:
                    ok = False
            print(f'{"PRESENT  " if ok else "ABSENT   "} {tpl}: {len(want)} job lines verbatim in crontab -l')
            bad += not ok
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
