"""Resumable Binance Vision 15m downloader with mandatory upstream verification."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import re
import shutil
import urllib.error
import urllib.request


BASE = "https://data.binance.vision/data/spot/monthly/klines"
CHECKSUM = re.compile(r"^([0-9a-fA-F]{64})\s+")
REFERENCE_NAME = re.compile(r"^(?P<symbol>[A-Z0-9]+)-1h-(?P<month>\d{4}-\d{2})\.zip$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jobs_from_reference(reference_root: Path) -> list[tuple[str, str]]:
    jobs = []
    for path in reference_root.glob("*/1h/*-1h-????-??.zip"):
        match = REFERENCE_NAME.match(path.name)
        if match:
            jobs.append((match["symbol"], match["month"]))
    return sorted(set(jobs))


def _fetch(url: str, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(target)


def download_one(output: Path, symbol: str, month: str) -> dict:
    name = f"{symbol}-15m-{month}.zip"
    target = output / symbol / "15m" / name
    check = target.with_name(name + ".CHECKSUM")
    url = f"{BASE}/{symbol}/15m/{name}"
    try:
        if not check.exists():
            _fetch(url + ".CHECKSUM", check)
        match = CHECKSUM.match(check.read_text().strip())
        if not match:
            return {"status": "UPSTREAM_CHECKSUM_MISSING", "symbol": symbol, "month": month}
        expected = match.group(1).lower()
        if not target.exists() or sha256(target) != expected:
            _fetch(url, target)
        actual = sha256(target)
        if actual != expected:
            return {"status": "CHECKSUM_MISMATCH", "symbol": symbol, "month": month,
                    "expected": expected, "actual": actual}
        return {"status": "UPSTREAM_VERIFIED", "symbol": symbol, "month": month,
                "bytes": target.stat().st_size, "sha256": actual}
    except urllib.error.HTTPError as exc:
        for p in (target.with_suffix(target.suffix + ".part"), check.with_suffix(check.suffix + ".part")):
            p.unlink(missing_ok=True)
        return {"status": "NOT_FOUND" if exc.code == 404 else "DOWNLOAD_ERROR",
                "symbol": symbol, "month": month, "detail": str(exc)}
    except Exception as exc:
        return {"status": "DOWNLOAD_ERROR", "symbol": symbol, "month": month, "detail": repr(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--status-log", type=Path, required=True)
    args = parser.parse_args(argv)
    jobs = jobs_from_reference(args.reference_root)
    mismatch = False
    args.status_log.parent.mkdir(parents=True, exist_ok=True)
    with args.status_log.open("w", encoding="utf-8") as log, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, args.output, symbol, month): (symbol, month)
                   for symbol, month in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            log.write("\t".join(str(row.get(k, "")) for k in
                ("status", "symbol", "month", "bytes", "sha256", "detail")) + "\n")
            log.flush()
            mismatch |= row["status"] == "CHECKSUM_MISMATCH"
            if index % 500 == 0:
                print(f"completed={index}/{len(jobs)}", flush=True)
    if mismatch:
        raise SystemExit("checksum mismatch detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
