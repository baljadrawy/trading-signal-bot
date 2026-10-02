"""P2-B acquisition: download exactly the planned public Binance spot klines (no key), verify, record provenance.

- Archives (data.binance.vision): the `.CHECKSUM` is fetched first; the zip must match it (SHA-256) or the file is
  rejected. HTTP 404 on both is recorded as SOURCE_UNAVAILABLE (not listed / delisted / no archive). URLs are
  built only through market_contract.archive_url, which refuses any archive able to contain a post-freeze candle.
- Freeze day (2026-08-19): public REST /api/v3/klines with endTime = last admissible open, so no post-freeze candle
  can be returned. The response is validated BEFORE it is written; a violation aborts (nothing stored).
  An overlap request for 2026-08-18 cross-validates REST against the checksummed daily archive.
- Polite and bounded: few workers, rate limiting, REST used-weight watch, nice/ionice by the caller.

  python3 -m research.p2.market_acquire --plan plan.json --raw <raw dir> --log acquisition.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import market_contract as M

UA = {"User-Agent": "tsb-p2b-research/1 (public data, no key)"}
CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+")
_rest_lock = threading.Lock()
_last_rest = [0.0]


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _get(url: str, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


def _safe(sym: str) -> str:
    return urllib.parse.quote(sym, safe="")


def fetch_archive(raw: pathlib.Path, rq: dict) -> dict:
    s, tf, kind, period = rq["symbol"], rq["timeframe"], rq["kind"], rq["period"]
    url = M.archive_url(kind, _safe(s), tf, period)               # raises FreezeViolation for post-freeze archives
    rel = pathlib.Path("binance_vision/spot") / kind / "klines" / _safe(s) / tf / f"{_safe(s)}-{tf}-{period}.zip"
    target = raw / rel
    rec = {**rq, "source": "BINANCE_VISION_SPOT_ARCHIVE", "url": url, "path": str(rel), "retrieved_utc": _now()}
    for attempt in range(3):
        try:
            _, ck, _ = _get(url + ".CHECKSUM")
            m = CHECKSUM_RE.match(ck.decode().strip())
            if not m:
                return {**rec, "status": "UPSTREAM_CHECKSUM_UNPARSEABLE"}
            expected = m.group(1).lower()
            _, body, _ = _get(url)
            actual = hashlib.sha256(body).hexdigest()
            if actual != expected:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1)); continue
                return {**rec, "status": "CHECKSUM_MISMATCH", "upstream_sha256": expected, "local_sha256": actual}
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".zip.part")
            tmp.write_bytes(body); tmp.replace(target)
            target.with_name(target.name + ".CHECKSUM").write_bytes(ck)
            return {**rec, "status": "UPSTREAM_VERIFIED", "upstream_sha256": expected, "local_sha256": actual,
                    "bytes": len(body)}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {**rec, "status": "SOURCE_UNAVAILABLE", "http": 404}
            if attempt == 2:
                return {**rec, "status": "DOWNLOAD_ERROR", "http": e.code}
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # network
            if attempt == 2:
                return {**rec, "status": "DOWNLOAD_ERROR", "detail": type(e).__name__}
            time.sleep(3 * (attempt + 1))


def fetch_rest(raw: pathlib.Path, rq: dict, start_ms: int, end_open_ms: int, purpose: str) -> dict:
    s, tf = rq["symbol"], rq["timeframe"]
    if end_open_ms > M.last_admissible_open_ms(tf):
        raise M.FreezeViolation("REST endTime beyond last admissible open")
    q = urllib.parse.urlencode({"symbol": s, "interval": tf, "startTime": start_ms, "endTime": end_open_ms, "limit": 1000})
    url = f"{M.REST_URL}?{q}"
    day = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
    rel = pathlib.Path("binance_rest/spot/klines") / _safe(s) / tf / f"{_safe(s)}-{tf}-{day}-{purpose}.json"
    rec = {**rq, "kind": "rest", "purpose": purpose, "source": "BINANCE_SPOT_REST_PUBLIC", "url": url,
           "path": str(rel), "start_ms": start_ms, "end_open_ms": end_open_ms}
    for attempt in range(3):
        with _rest_lock:
            wait = 0.35 - (time.time() - _last_rest[0])
            if wait > 0: time.sleep(wait)
            _last_rest[0] = time.time()
            try:
                status, body, hdr = _get(url, timeout=30)
            except urllib.error.HTTPError as e:
                if e.code in (418, 429):
                    raise SystemExit(f"REST rate limit signalled ({e.code}); aborting acquisition")
                if e.code == 400:
                    return {**rec, "retrieved_utc": _now(), "status": "SOURCE_UNAVAILABLE", "http": 400}
                if attempt == 2: return {**rec, "retrieved_utc": _now(), "status": "DOWNLOAD_ERROR", "http": e.code}
                time.sleep(3); continue
            except Exception as e:
                if attempt == 2: return {**rec, "retrieved_utc": _now(), "status": "DOWNLOAD_ERROR", "detail": type(e).__name__}
                time.sleep(3); continue
        used = int(hdr.get("x-mbx-used-weight-1m") or hdr.get("X-MBX-USED-WEIGHT-1M") or 0)
        if used > 1200: time.sleep(30)
        rows = json.loads(body)
        for k in rows:                                           # validate BEFORE writing anything
            o, c = int(k[0]), int(k[6])
            o_ms, c_ms = (o // 1000, c // 1000) if o >= 10**15 else (o, c)
            M.assert_closed_before_freeze(c_ms, o_ms, tf)        # FreezeViolation aborts the whole run
            if not (start_ms <= o_ms <= end_open_ms):
                raise ValueError("REST row outside requested window")
        target = raw / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return {**rec, "retrieved_utc": _now(), "status": "REST_VALIDATED_NO_UPSTREAM_CHECKSUM", "rows": len(rows),
                "local_sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "used_weight_1m": used}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
    raw = pathlib.Path(a.raw); raw.mkdir(parents=True, exist_ok=True)
    reqs = plan["requests"]
    archives = [r for r in reqs if r["kind"] in ("monthly", "daily")]
    rests = [r for r in reqs if r["kind"] == "rest"]
    out = open(a.log, "w", encoding="utf-8")
    lock = threading.Lock()

    def log(rec):
        with lock:
            out.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n"); out.flush()

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for n, rec in enumerate(pool.map(lambda r: fetch_archive(raw, r), archives), 1):
            log(rec)
            if n % 1000 == 0: print(f"archives {n}/{len(archives)}", flush=True)
    for r in rests:
        start, end_open = (int(x) for x in r["period"].split(":"))
        log(fetch_rest(raw, r, start, end_open, "freeze_day_partial"))
        prev = start - 86_400_000                                    # 2026-08-18: cross-check day
        log(fetch_rest(raw, {**r, "period": f"{prev}:{start - M.TF_MS[r['timeframe']]}"}, prev,
                       start - M.TF_MS[r["timeframe"]], "crosscheck_prev_day"))
    out.close()
    print("done")


if __name__ == "__main__":
    sys.exit(main())
