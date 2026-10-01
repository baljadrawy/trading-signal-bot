"""P2-A coverage index: can each canonical decision be anchored in the certified candle dataset ds-0928?

Reads only the `open_time` column of ds-0928 Parquet files (certified, historical_end 2026-05-31; no holdout data).
Requires pyarrow, which exists only in the pre-existing research venv; nothing is installed. Output is a derived,
reproducible index: no prices, no labels, no outcomes.

  <venv-python> -m research.p2.ds_coverage --dataset <p2 build dir> --ds <ds-0928 snapshot dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from collections import Counter

import pyarrow.parquet as pq

from . import contract as C
from .extract import _write_csv_gz, read_csv_gz

MIN_BARS = 200          # analyzer needs 200 closed candles (CANDLES_TO_FETCH) before the decision candle
MAX_HOLD_H = {"15m": 48, "1h": 48, "4h": 96, "1d": 240}   # timeframe_v1 maximum hold (1h: default policy)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--ds", required=True)
    a = ap.parse_args(argv)
    base, ds = pathlib.Path(a.dataset), pathlib.Path(a.ds)
    man = json.loads((ds / "manifest.json").read_text())
    hist_end_ms = C._ms(man["identity"]["historical_end"].replace(".999999Z", "Z")) + 999
    universe = set(man["identity"]["symbols"])
    decisions = read_csv_gz(base / "canonical" / "decision.csv.gz")
    cache, rows = {}, []
    for d in sorted(decisions, key=lambda r: (r["symbol"], r["timeframe"], r["decision_uid"])):
        sym, tf, w = d["symbol"], d["timeframe"], d["window"]
        o = int(d["inferred_candle_open_ms"]); alt = d["candle_alt_open_ms"]
        horizon_end = int(d["decision_time_ms"]) + MAX_HOLD_H[tf] * 3600_000
        rec = {"decision_uid": d["decision_uid"], "symbol": sym, "timeframe": tf, "window": w,
               "symbol_in_ds0928": "true" if sym in universe else "false"}
        path = ds / "normalized" / tf / f"{sym}.parquet"
        if w != "W1":
            rec.update(status="AWAITING_P2B", candle_present="", alt_candle_present="", bars_before=0,
                       history_ok="", label_horizon_within_ds="false")
        elif sym not in universe or not path.exists():
            rec.update(status="CANNOT_RECONSTRUCT_SYMBOL_NOT_IN_DS0928", candle_present="false", alt_candle_present="",
                       bars_before=0, history_ok="false", label_horizon_within_ds="false")
        else:
            key = (sym, tf)
            if key not in cache:
                col = pq.read_table(path, columns=["open_time"]).column("open_time").cast("int64").to_pylist()
                cache = {key: sorted(v // 1000 for v in col)}          # microseconds -> ms; keep one file in memory
            ot = cache[key]
            import bisect
            i = bisect.bisect_left(ot, o)
            present = i < len(ot) and ot[i] == o
            alt_p = ""
            if alt:
                j = bisect.bisect_left(ot, int(alt)); alt_p = "true" if j < len(ot) and ot[j] == int(alt) else "false"
            rec.update(status="REBUILDABLE_FROM_DS0928" if present and i >= MIN_BARS else
                       ("INSUFFICIENT_HISTORY" if present else "CANDLE_MISSING_IN_DS0928"),
                       candle_present="true" if present else "false", alt_candle_present=alt_p, bars_before=i,
                       history_ok="true" if i >= MIN_BARS else "false",
                       label_horizon_within_ds="true" if horizon_end <= hist_end_ms else "false")
        rows.append(rec)
    rows.sort(key=lambda r: r["decision_uid"])
    cols = ["decision_uid", "symbol", "timeframe", "window", "symbol_in_ds0928", "status", "candle_present",
            "alt_candle_present", "bars_before", "history_ok", "label_horizon_within_ds"]
    info = _write_csv_gz(base / "derived" / "ds0928_coverage.csv.gz", cols, rows)
    summary = {"status_by_window_tf": dict(sorted(Counter(f"{r['window']}|{r['timeframe']}|{r['status']}" for r in rows).items())),
               "w1_label_horizon_within_ds": dict(Counter(r["label_horizon_within_ds"] for r in rows if r["window"] == "W1")),
               "w1_ambiguous_alt_candle_present": dict(Counter(r["alt_candle_present"] for r in rows if r["window"] == "W1" and r["alt_candle_present"])),
               "missing_symbols": sorted({r["symbol"] for r in rows if r["symbol_in_ds0928"] == "false"}),
               "file": info, "ds0928_manifest_sha256": hashlib.sha256((ds / "manifest.json").read_bytes()).hexdigest()}
    (base / "derived" / "ds0928_coverage_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
