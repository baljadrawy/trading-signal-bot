"""P2-B independent verification (separate from the downloader/normalizer filters).

1. W3 proof: scan (a) every raw record selected for certification, (b) every normalized candle, (c) the coverage
   index and parity sample, and count candles closing at/after the freeze (must be 0 everywhere).
2. REST cross-check: REST rows for 2026-08-18 vs the checksummed daily archive for the same candles (field equality).
3. Determinism: compare two independent normalization outputs (file bytes + content identity).

  <venv-python> -m research.p2.market_verify --raw <raw> --log acquisition.jsonl --norm <dir> [--norm2 <dir>]
      --coverage <reports dir> --out verify.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import pathlib
import zipfile
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq

from . import market_contract as M


def _ms(v: int) -> int:
    return v // 1000 if v >= 10**15 else v


def raw_rows(path: pathlib.Path):
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".csv")]
            for line in z.open(names[0]).read().decode().splitlines():
                f = line.split(",")
                if f and f[0].strip().lstrip("-").isdigit():
                    yield [_ms(int(f[0]))] + f[1:6] + [_ms(int(f[6]))] + f[7:9]
    else:
        for k in json.loads(path.read_bytes()):
            yield [_ms(int(k[0]))] + list(k[1:6]) + [_ms(int(k[6]))] + list(k[7:9])


def main(argv=None):
    ap = argparse.ArgumentParser()
    for k in ("--raw", "--log", "--norm", "--coverage", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--norm2")
    a = ap.parse_args(argv)
    raw, norm, cov = pathlib.Path(a.raw), pathlib.Path(a.norm), pathlib.Path(a.coverage)
    recs = [json.loads(l) for l in open(a.log, encoding="utf-8")]
    res = {"freeze_ms": M.FREEZE_MS, "acquisition_status": dict(Counter(r["status"] for r in recs))}

    # (a) raw selected records
    raw_scan = Counter(); raw_max = 0; cross = {}
    for r in recs:
        if r["status"] not in ("UPSTREAM_VERIFIED", "REST_VALIDATED_NO_UPSTREAM_CHECKSUM"):
            continue
        p = raw / r["path"]
        if hashlib.sha256(p.read_bytes()).hexdigest() != r["local_sha256"]:
            raise SystemExit(f"raw file changed after acquisition: {r['path']}")
        for row in raw_rows(p):
            raw_scan["rows"] += 1; raw_max = max(raw_max, row[6])
            if row[6] >= M.FREEZE_MS: raw_scan["at_or_after_freeze"] += 1
            if r.get("purpose") == "crosscheck_prev_day":
                cross[(r["symbol"], r["timeframe"], row[0])] = row
    res["raw_scan"] = {"files": sum(1 for r in recs if r["status"] in ("UPSTREAM_VERIFIED", "REST_VALIDATED_NO_UPSTREAM_CHECKSUM")),
                       "rows": raw_scan["rows"], "max_close_ms": raw_max,
                       "at_or_after_freeze": raw_scan["at_or_after_freeze"]}

    # (b) normalized candles + REST cross-check against archive rows in the normalized set
    n_rows = n_bad = 0; n_max = 0; cmp = Counter()
    for f in sorted(norm.glob("*/*.parquet")):
        t = pq.read_table(f)
        o = t.column("open_time").cast(pa.timestamp("us", tz="UTC")).cast("int64").to_pylist()
        c = t.column("close_time").cast(pa.timestamp("us", tz="UTC")).cast("int64").to_pylist()
        n_rows += len(c); n_max = max([n_max] + [x // 1000 for x in c])
        n_bad += sum(1 for x in c if x // 1000 >= M.FREEZE_MS)
        sym, tf = f.stem, f.parent.name
        if any(k[0] == sym and k[1] == tf for k in cross):
            d = t.to_pydict()
            for i, om in enumerate(o):
                key = (sym, tf, om // 1000)
                if key in cross and d["source_kind"][i].startswith("vision_"):
                    rr = cross[key]
                    same = all(float(rr[j]) == float(d[n][i]) for j, n in ((1, "open"), (2, "high"), (3, "low"), (4, "close"),
                                                                         (5, "volume"), (7, "quote_volume"))) and int(rr[8]) == int(d["trade_count"][i])
                    cmp["match" if same else "mismatch"] += 1
    res["normalized_scan"] = {"files": len(list(norm.glob('*/*.parquet'))), "rows": n_rows, "max_close_ms": n_max,
                              "at_or_after_freeze": n_bad}
    res["rest_vs_archive_crosscheck_2026_08_18"] = {**dict(cmp), "rest_rows_available": len(cross)}

    # (c) coverage index + parity sample
    cv = list(csv.DictReader(gzip.open(cov / "w2_decision_coverage.csv.gz", "rt")))
    res["coverage_scan"] = {"rows": len(cv), "max_decision_ms": max(int(r["decision_time_ms"]) for r in cv),
                            "decisions_at_or_after_freeze": sum(1 for r in cv if int(r["decision_time_ms"]) >= M.FREEZE_MS)}
    pr = list(csv.DictReader(gzip.open(cov / "snapshot_parity.csv.gz", "rt")))
    pu = {r["decision_uid"] for r in pr}; dm = {r["decision_uid"]: int(r["decision_time_ms"]) for r in cv}
    res["parity_scan"] = {"rows": len(pr), "decisions": len(pu),
                          "decisions_at_or_after_freeze": sum(1 for u in pu if dm[u] >= M.FREEZE_MS)}

    if a.norm2:
        n2 = pathlib.Path(a.norm2)
        fa = sorted(str(p.relative_to(norm)) for p in norm.rglob("*") if p.is_file())
        fb = sorted(str(p.relative_to(n2)) for p in n2.rglob("*") if p.is_file())
        diff = [f for f in fa if f in fb and hashlib.sha256((norm / f).read_bytes()).digest() != hashlib.sha256((n2 / f).read_bytes()).digest()]
        s1 = json.loads((norm / "_normalize_summary.json").read_text()); s2 = json.loads((n2 / "_normalize_summary.json").read_text())
        res["determinism"] = {"same_file_set": fa == fb, "files": len(fa), "byte_differing": diff,
                              "content_identity_1": s1["content_identity"], "content_identity_2": s2["content_identity"],
                              "content_identity_equal": s1["content_identity"] == s2["content_identity"]}
    res["W3_PROOF"] = "PASS" if (res["raw_scan"]["at_or_after_freeze"] == 0 and n_bad == 0 and
                                 res["coverage_scan"]["decisions_at_or_after_freeze"] == 0 and
                                 res["parity_scan"]["decisions_at_or_after_freeze"] == 0 and
                                 raw_max < M.FREEZE_MS and n_max < M.FREEZE_MS) else "FAIL"
    pathlib.Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    print(json.dumps(res, sort_keys=True))


if __name__ == "__main__":
    main()
