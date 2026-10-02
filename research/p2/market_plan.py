"""P2-B acquisition plan: the exact (symbol, timeframe, kind, period) request set, computed BEFORE any download.

Universe = symbols of P2-A W2 decisions + W1 decisions whose label horizon runs past ds-0928 + BTCUSDT/ETHUSDT
(market context). All four timeframes per symbol (the analyzer evaluates every TIMEFRAME per symbol; HTF context).
Window = [2026-06-01, freeze). Lookback before 2026-06-01 is taken from certified ds-0928 when the symbol exists
there; only symbols absent from ds-0928 get pre-June monthly archives planned (never redownload certified data).

  <venv-python> -m research.p2.market_plan --p2a-canonical <dir> --p2a-derived <dir> --ds <ds-0928 dir> --out plan.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from collections import Counter

import pyarrow.parquet as pq

from . import contract as C
from . import market_contract as M
from .extract import read_csv_gz


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--p2a-canonical", required=True)
    ap.add_argument("--p2a-derived", required=True)
    ap.add_argument("--ds", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    dec = read_csv_gz(pathlib.Path(a.p2a_canonical) / "decision.csv.gz")
    cov = {r["decision_uid"]: r for r in read_csv_gz(pathlib.Path(a.p2a_derived) / "ds0928_coverage.csv.gz")}
    ds = pathlib.Path(a.ds)
    man = json.loads((ds / "manifest.json").read_text())
    universe_ds = set(man["identity"]["symbols"])
    w2 = [r for r in dec if r["window"] == "W2"]
    w1_tail = [r for r in dec if r["window"] == "W1" and cov[r["decision_uid"]]["label_horizon_within_ds"] == "false"]
    symbols = sorted({r["symbol"] for r in w2} | {r["symbol"] for r in w1_tail} | {"BTCUSDT", "ETHUSDT"})
    first_dec = {}
    for r in w2:
        first_dec[r["symbol"]] = min(first_dec.get(r["symbol"], 10**15), int(r["inferred_candle_open_ms"]))
    reqs, ds_ranges = [], {}
    for s in symbols:
        for tf in M.TIMEFRAMES:
            for kind, period in M.w2_requests(s, tf):
                reqs.append({"symbol": s, "timeframe": tf, "kind": kind, "period": period, "purpose": "w2_window"})
            if s not in first_dec:
                continue                                     # W1-tail / context symbol: no W2 lookback needed
            need = first_dec[s] - (M.LOOKBACK_BARS + M.LOOKBACK_MARGIN_BARS) * M.TF_MS[tf]
            if need >= M.W2_START_MS:
                continue
            p = ds / "normalized" / tf / f"{s}.parquet"
            if s in universe_ds and p.exists():
                col = pq.read_table(p, columns=["open_time"]).column("open_time").cast("int64").to_pylist()
                ds_ranges[f"{s}|{tf}"] = [min(col) // 1000, max(col) // 1000, len(col)]
                continue                                     # certified history reused, not redownloaded
            for period in M.month_starts(need, M.W2_START_MS):
                reqs.append({"symbol": s, "timeframe": tf, "kind": "monthly", "period": period,
                             "purpose": "lookback_symbol_absent_from_ds0928"})
    reqs.sort(key=lambda r: (r["symbol"], r["timeframe"], r["kind"], r["period"]))
    body = json.dumps(reqs, sort_keys=True, separators=(",", ":"))
    plan = {"contract": M.MARKET_CONTRACT_VERSION, "freeze_ms": M.FREEZE_MS, "w2_start_ms": M.W2_START_MS,
            "plan_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "symbols": symbols, "n_symbols": len(symbols),
            "w2_decision_symbols": len({r['symbol'] for r in w2}), "w1_tail_symbols": sorted({r['symbol'] for r in w1_tail}),
            "symbols_absent_from_ds0928": sorted(set(symbols) - universe_ds),
            "w2_decisions_on_freeze_day": sum(1 for r in w2 if int(r["decision_time_ms"]) >= (M.FREEZE_MS // 86_400_000) * 86_400_000),
            "counts": {"by_kind": dict(Counter(r["kind"] for r in reqs)), "by_purpose": dict(Counter(r["purpose"] for r in reqs)),
                       "by_tf": dict(Counter(r["timeframe"] for r in reqs)), "total": len(reqs)},
            "never_planned": ["monthly 2026-08 (contains post-freeze)", "daily 2026-08-19 (contains post-freeze)", "1d 2026-08-19 (not closed)"],
            "ds0928_ranges_reused": ds_ranges, "requests": reqs}
    pathlib.Path(a.out).write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: plan[k] for k in ("plan_sha256", "n_symbols", "w2_decision_symbols", "w1_tail_symbols",
                                           "symbols_absent_from_ds0928", "w2_decisions_on_freeze_day", "counts")}, sort_keys=True))


if __name__ == "__main__":
    main()
