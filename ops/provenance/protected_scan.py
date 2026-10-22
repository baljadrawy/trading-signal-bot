#!/usr/bin/env python3
"""Blocking protected-information scan of a git diff (added lines only). Standard library only.

Patterns: second-precision times (HH:MM:SS), market stream names, secret-looking words, and protected
scientific quantities. Any match blocks (exit 1).

ONE narrow exception (owner decision 2026-10-22): a container start time in the runtime baseline. It applies only when ALL hold:
  - file is exactly `deploy/DEPLOYED.json`;
  - the added line is exactly `"started_at": "<value>"` (optional trailing comma), nothing else on the line;
  - the only pattern the line matches is the HH:MM:SS time pattern;
  - in the head version of the file, the value is a strict ISO-8601 UTC timestamp
    (YYYY-MM-DDTHH:MM:SS[.fraction 1-9 digits]Z, a real calendar date) located at one of the explicitly enumerated
    JSON paths services.<service>.observed.started_at (no wildcard);
  - the value occurs nowhere else in that head file: no other path, no key, no substring of another string
    (no smuggled copy). continuous_learner is deliberately NOT enumerated: a learner start time must always block.
With --verify-docker (host gate only) each exempted value must also equal `docker inspect` StartedAt of the
container named in the same service entry.

usage: protected_scan.py --base REF --head REF [--repo DIR] [--verify-docker]
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys

TIME = r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
# Written so that this source file never matches itself: each word is split by a non-capturing group.
PATTERNS = [TIME, r"@book(?:Ticker)", r"@depth[0-9]", r"mini(?:Ticker)@", r"missing(?:_samples)", r"pass(?:word)",
            r"tok(?:en)", r"api[_-]?key", r"BEGIN [A-Z ]*KEY", r"holdout_look_count *[=:] *[1-9]",
            r"profit_usdt *[=:] *-?[0-9]", r"sharpe *= *-?[0-9]"]
PROTECTED = re.compile("|".join(PATTERNS), re.I)
TIME_RE = re.compile(TIME)
OTHER_RE = re.compile("|".join(PATTERNS[1:]), re.I)
ALLOW = re.compile(r"no secrets|not .*secret|approval token|\b(ack|acknowledg|STOPPING|deployed|reboot|healthy|opened|filed)\b",
                   re.I)

EXEMPT_FILE = "deploy/DEPLOYED.json"
EXEMPT_SERVICES = ("analyzer", "collector", "postgres", "scanner", "signal_engine", "telegram", "trade_tracker")
EXEMPT_PATHS = frozenset(("services", s, "observed", "started_at") for s in EXEMPT_SERVICES)
ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?Z$")
LINE = re.compile(r'^\s*"started_at": "([^"\\]*)",?\s*$')


def strict_iso(v) -> bool:
    if not isinstance(v, str):
        return False
    m = ISO.match(v)
    if not m:
        return False
    try:
        dt.datetime(*(int(m.group(i)) for i in range(1, 7)), tzinfo=dt.timezone.utc)
    except ValueError:
        return False
    return True


def _walk(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + (k,), k, None                     # keys are scanned too
            yield from _walk(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, path + (i,))
    else:
        yield path, None, o


def exempt_values(head_text: str):
    """Set of started_at values that may pass: strict ISO-8601, found at an enumerated exempt path, and never found
    anywhere else in the file (no other path, no key). None if the file is not valid JSON."""
    try:
        doc = json.loads(head_text)
    except ValueError:
        return None
    at_exempt, elsewhere = set(), set()
    for path, key, val in _walk(doc):
        if key is not None:
            elsewhere.add(key)
        elif isinstance(val, str):
            (at_exempt if path in EXEMPT_PATHS else elsewhere).add(val)
    return {v for v in at_exempt if strict_iso(v) and v not in elsewhere
            and not any(v in other for other in elsewhere)}


def parse_diff(diff_text: str):
    """Yield (path, added_line) for every added line of a unified diff."""
    cur = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            cur = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
        elif line.startswith("+") and not line.startswith("+++") and cur is not None:
            yield cur, line[1:]


def scan(diff_text: str, read_head):
    """read_head(path) -> head file text or None. Returns a list of findings (path, line)."""
    findings, cache = [], {}
    for path, line in parse_diff(diff_text):
        if not PROTECTED.search(line) or ALLOW.search(line):
            continue
        if path == EXEMPT_FILE and not OTHER_RE.search(line):
            m = LINE.match(line)
            if m:
                if path not in cache:
                    cache[path] = exempt_values(read_head(path) or "")
                vals = cache[path]
                if vals is not None and m.group(1) in vals and strict_iso(m.group(1)):
                    continue
        findings.append((path, line.strip()[:200]))
    return findings


def exempted_started_at(head_text: str) -> dict:
    """{service: (container, started_at)} for every exempt path present in the manifest."""
    doc = json.loads(head_text)
    out = {}
    for s in EXEMPT_SERVICES:
        e = (doc.get("services") or {}).get(s) or {}
        v = (e.get("observed") or {}).get("started_at")
        if v is not None:
            out[s] = (e.get("container"), v)
    return out


def verify_docker(head_text: str, inspect) -> list:
    """inspect(container) -> StartedAt string or None. Returns mismatches for the changed values only."""
    bad = []
    for s, (container, v) in exempted_started_at(head_text).items():
        live = inspect(container) if container else None
        if live != v:
            bad.append((s, container, v, live))
    return bad


def _docker_started_at(container):
    try:
        r = subprocess.run(["docker", "inspect", container, "--format", "{{.State.StartedAt}}"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--base", required=True)
    a.add_argument("--head", required=True)
    a.add_argument("--repo", default=".")
    a.add_argument("--verify-docker", action="store_true")
    a.add_argument("--only-changed-services", action="store_true",
                   help="with --verify-docker: check only services whose started_at changed in this diff")
    o = a.parse_args(argv)
    git = lambda *x: subprocess.run(["git", "-C", o.repo, *x], capture_output=True, text=True)
    diff = git("diff", f"{o.base}...{o.head}").stdout

    def read_head(p):
        r = git("show", f"{o.head}:{p}")
        return r.stdout if r.returncode == 0 else None

    findings = scan(diff, read_head)
    for p, l in findings:
        print(f"SCAN MATCH {p}: {l}")
    rc = 1 if findings else 0
    if o.verify_docker:
        head = read_head(EXEMPT_FILE)
        if head:
            changed = {m.group(1) for p, l in parse_diff(diff) if p == EXEMPT_FILE for m in [LINE.match(l)] if m}
            insp = _docker_started_at
            for s, c, v, live in verify_docker(head, insp):
                if o.only_changed_services and v not in changed:
                    continue
                print(f"STARTED_AT MISMATCH {s} container={c} manifest={v} live={live}")
                rc = 1
    print("SCAN CLEAN" if rc == 0 else "SCAN BLOCKED")
    return rc


if __name__ == "__main__":
    sys.exit(main())
