"""Fetch official checksum sidecars and verify an existing Binance archive tree."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import urllib.error
import urllib.request

from .download_binance_15m import BASE, CHECKSUM, sha256, _fetch


NAME = re.compile(r"^(?P<symbol>[A-Z0-9]+)-(?P<tf>15m|1h|4h|1d)-(?P<month>\d{4}-\d{2})\.zip$")


def verify_one(root: Path, path: Path) -> dict:
    match = NAME.match(path.name)
    if not match:
        return {"status": "MALFORMED_NAME", "path": str(path.relative_to(root))}
    check = path.with_name(path.name + ".CHECKSUM")
    url = f"{BASE}/{match['symbol']}/{match['tf']}/{path.name}.CHECKSUM"
    try:
        if not check.exists():
            _fetch(url, check)
        parsed = CHECKSUM.match(check.read_text().strip())
        if not parsed:
            return {"status": "UPSTREAM_CHECKSUM_MISSING", "path": str(path.relative_to(root))}
        expected = parsed.group(1).lower()
        actual = sha256(path)
        return {"status": "UPSTREAM_VERIFIED" if actual == expected else "CHECKSUM_MISMATCH",
                "path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                "sha256": actual, "expected": expected}
    except urllib.error.HTTPError as exc:
        return {"status": "UPSTREAM_CHECKSUM_MISSING" if exc.code == 404 else "DOWNLOAD_ERROR",
                "path": str(path.relative_to(root)), "detail": str(exc)}
    except Exception as exc:
        return {"status": "DOWNLOAD_ERROR", "path": str(path.relative_to(root)), "detail": repr(exc)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--status-log", type=Path, required=True)
    a = p.parse_args(argv)
    paths = sorted(path for tf in ("1h", "4h", "1d") for path in a.root.glob(f"*/{tf}/*.zip"))
    a.status_log.parent.mkdir(parents=True, exist_ok=True)
    mismatch = False
    with a.status_log.open("w", encoding="utf-8") as log, ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(verify_one, a.root, path) for path in paths]
        for n, future in enumerate(as_completed(futures), 1):
            row = future.result(); mismatch |= row["status"] == "CHECKSUM_MISMATCH"
            log.write("\t".join(str(row.get(k, "")) for k in
                ("status", "path", "bytes", "sha256", "expected", "detail")) + "\n")
            log.flush()
            if n % 1000 == 0: print(f"verified={n}/{len(paths)}", flush=True)
    if mismatch: raise SystemExit("checksum mismatch detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
