"""A34 before/after latency evidence (loopback only): the ignore-CLOSE peer scenario, N trials per transport.
    <venv>/bin/python -m tests.a34_recovery_latency <out.json> [N]"""
import asyncio
import json
import statistics
import sys

from p2_forward import transport as T
from tests.test_p2f_recovery_a34 import BeforeAfter, load_deployed_transport


def main():
    out_path, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5
    old = load_deployed_transport()
    case = BeforeAfter()
    res = {"trials": n, "fixed": [], "deployed": []}
    for _ in range(n):
        res["fixed"].append(asyncio.run(case._scenario(T)))
    for _ in range(2):
        res["deployed"].append(asyncio.run(case._scenario(old)))
    secs = [r["secs"] for r in res["fixed"] if r["recovered"]]
    res["fixed_summary"] = {"recovered": sum(r["recovered"] for r in res["fixed"]), "min_s": min(secs),
                            "median_s": statistics.median(secs), "max_s": max(secs)}
    res["deployed_summary"] = {"recovered": sum(r["recovered"] for r in res["deployed"]),
                               "observed_s": [round(r["secs"], 1) for r in res["deployed"]]}
    with open(out_path, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    print(json.dumps({k: res[k] for k in ("fixed_summary", "deployed_summary")}))


if __name__ == "__main__":
    main()
