#!/usr/bin/env python3
"""Convert a disposable pip --dry-run --report resolution to REVIEW-ONLY lock evidence.

Never install, commit, deploy, or certify the resolved environment.
"""
import argparse
import hashlib
import json
from pathlib import Path

from lock_review import verify


def convert(requirements: str, report: dict):
    if report.get("version") != "1":
        raise ValueError("unsupported pip report version")
    entries = report.get("install")
    if not isinstance(entries, list) or not entries:
        raise ValueError("empty or invalid pip resolution")
    pins = {}
    for entry in entries:
        meta = entry.get("metadata") or {}
        name, version = meta.get("name"), meta.get("version")
        download = entry.get("download_info") or {}
        url = download.get("url", "")
        if not name or not version or not url.startswith("https://"):
            raise ValueError("missing metadata or non-HTTPS distribution")
        # Wheel-only CI resolver must not silently accept source archives.
        if not url.split("?", 1)[0].lower().endswith(".whl"):
            raise ValueError("non-wheel distribution in resolution")
        normalized = name.lower().replace("_", "-").replace(".", "-")
        if normalized in pins:
            raise ValueError(f"duplicate distribution: {normalized}")
        pins[normalized] = version
    lock = "".join(f"{name}=={pins[name]}\n" for name in sorted(pins))
    issues, _, _ = verify(requirements, lock)
    if issues:
        raise ValueError("; ".join(issues))
    return lock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--service", required=True)
    args = parser.parse_args()
    requirements = args.requirements.read_text()
    report = json.loads(args.report.read_text())
    lock = convert(requirements, report)
    args.output.write_text(lock)
    args.provenance.write_text(json.dumps({
        "schema": "tsb-r14-disposable-lock-candidate/1",
        "status": "REVIEW_ONLY_NOT_CERTIFIED",
        "service": args.service,
        "requirements_sha256": hashlib.sha256(requirements.encode()).hexdigest(),
        "lock_sha256": hashlib.sha256(lock.encode()).hexdigest(),
        "distribution_count": len(lock.splitlines()),
        "pip_report_version": report["version"],
        "source": "pip install --dry-run --ignore-installed --only-binary=:all: --report",
        "limitations": [
            "pip resolution report is not an installed environment",
            "no pip check or service smoke tests",
            "no distribution hashes or platform attestation",
            "not a canonical build or runtime parity certificate"
        ]
    }, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
