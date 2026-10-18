#!/usr/bin/env python3
"""Offline verifier for proposed pip freeze locks. Never resolves or installs packages."""
import argparse
import hashlib
import json
from pathlib import Path
import re

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)$")
NORMALIZE = re.compile(r"[-_.]+")


def parse(text):
    result = {}
    errors = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        if not match:
            errors.append(f"line {number}: unsupported or non-exact requirement")
            continue
        name, version = match.groups()
        key = NORMALIZE.sub("-", name).lower()
        if key in result:
            errors.append(f"line {number}: duplicate distribution {key}")
        result[key] = version
    if not result:
        errors.append("no distributions")
    return result, errors


def verify(direct_text, lock_text):
    direct, errors = parse(direct_text)
    lock, lock_errors = parse(lock_text)
    errors += lock_errors
    for name, version in sorted(direct.items()):
        if name not in lock:
            errors.append(f"missing direct distribution {name}")
        elif lock[name] != version:
            errors.append(f"direct version mismatch {name}: declared {version}, locked {lock[name]}")
    return sorted(set(errors)), len(direct), len(lock)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--lock", type=Path, required=True)
    a = p.parse_args()
    direct = a.requirements.read_text()
    lock = a.lock.read_text()
    errors, direct_count, lock_count = verify(direct, lock)
    print(json.dumps({"schema": "tsb-r14-lock-review/1", "verified": not errors,
                      "direct_count": direct_count, "lock_count": lock_count,
                      "requirements_sha256": hashlib.sha256(direct.encode()).hexdigest(),
                      "lock_sha256": hashlib.sha256(lock.encode()).hexdigest(),
                      "issues": errors}, sort_keys=True))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
