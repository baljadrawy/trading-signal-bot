#!/usr/bin/env python3
"""Read-only source/runtime parity inventory. No Docker or production access."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVICES = ("scanner", "analyzer", "signal_engine", "trade_tracker", "telegram")
DEPLOYED = ROOT / "deploy" / "DEPLOYED.json"

def audit():
    manifest = json.loads(DEPLOYED.read_text())
    issues = []
    results = []
    for service in SERVICES:
        runtime = manifest["services"][service]
        dockerfile = ROOT / service / "Dockerfile"
        req = ROOT / service / "requirements.txt"
        source = runtime["provenance"]
        problems = []
        if not dockerfile.is_file():
            problems.append("missing versioned Dockerfile")
        if not req.is_file():
            problems.append("missing requirements.txt")
        else:
            lines = [s.split("#", 1)[0].strip() for s in req.read_text().splitlines() if s.split("#", 1)[0].strip()]
            if not lines or any(not re.match(r"^[A-Za-z0-9_.-]+==[^\s;]+(?:\s*;.*)?$", s) for s in lines):
                problems.append("requirements are not all exact pins (not a validated transitive lock)")
        if source["source_kind"] != "commit":
            problems.append("image source is not a single commit")
        if runtime["reproducibility"]["level"] != "L2-canonical-rebuild":
            problems.append("no verified canonical rebuild")
        if not runtime["reproducibility"]["canonical_rebuild"]:
            problems.append("canonical rebuild not attested")
        results.append({"service": service, "status": "BLOCKED" if problems else "REVIEW_REQUIRED", "issues": problems})
        issues.extend(f"{service}: {problem}" for problem in problems)
    collector = manifest["services"]["collector"]
    if not collector["archives"]:
        issues.append("collector: no archive of running image")
    output = {"schema": "tsb-r14-static-audit/1", "runtime_observed_at": manifest["observed_at"], "scope": "GITHUB_STATIC_ONLY", "runtime_parity_verified": False, "services": results, "blockers": issues}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if not issues else 2

if __name__ == "__main__":
    sys.exit(audit())
