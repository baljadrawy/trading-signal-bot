#!/usr/bin/env python3
"""R1.4-B fail-closed canonical-build preflight; no Docker/network/server access."""
import argparse
import json
from pathlib import Path
import re

SERVICES = ("scanner", "analyzer", "signal_engine", "trade_tracker", "telegram")
BASE = re.compile(r"^FROM\s+[^\s]+@sha256:[0-9a-f]{64}(?:\s+AS\s+\w+)?\s*$", re.I | re.M)
PIN = re.compile(r"^[A-Za-z0-9_.-]+==[^\s;#]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def check(root, service, revision):
    issues = []
    if service not in SERVICES:
        return ["unknown service"]
    if not SHA.fullmatch(revision):
        issues.append("revision must be a full 40-character commit SHA")
    dockerfile = root / service / "Dockerfile"
    lock = root / service / "requirements.lock"
    if not dockerfile.is_file():
        issues.append("missing Dockerfile")
    else:
        content = dockerfile.read_text()
        from_lines = re.findall(r"^FROM\s+.*$", content, re.M)
        if not from_lines or any(not BASE.fullmatch(line) for line in from_lines):
            issues.append("every FROM must use an immutable sha256 digest")
        if "org.opencontainers.image.revision" not in content:
            issues.append("missing OCI revision label")
        if not re.search(r"\bARG\s+BUILD_REVISION\b", content):
            issues.append("missing BUILD_REVISION build argument")
    if not lock.is_file():
        issues.append("missing committed requirements.lock")
    else:
        pins = {}
        for line in lock.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if not PIN.fullmatch(line):
                issues.append("lock contains non-exact or unsupported entry")
                continue
            name, version = line.split("==", 1)
            key = re.sub(r"[-_.]+", "-", name).lower()
            if key in pins and pins[key] != version:
                issues.append("conflicting duplicate lock entry")
            pins[key] = version
        if not pins:
            issues.append("lock has no pinned distributions")
    return sorted(set(issues))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--service", required=True, choices=SERVICES)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    issues = check(args.root, args.service, args.revision)
    print(json.dumps({"schema": "tsb-r14-build-preflight/1", "service": args.service,
                      "ready": not issues, "issues": issues}, sort_keys=True))
    return 2 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
