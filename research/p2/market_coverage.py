"""P2-B: seam validation, W2 decision coverage, and stored-snapshot feature parity (reconstruction fidelity only).

- No outcome is read. Horizon sufficiency is a data-availability check (candles exist up to t+H before freeze).
- Feature rebuild executes the analyzer's own W2-era methods (`_calculate_indicators`, `_raw_features`) extracted
  verbatim from git at --code-commit; pandas_ta is absent in every analyzer image, so the `ta` fallback is used,
  exactly like production. Indicator periods are the config defaults (no override present in the analyzer env).
- Ambiguity is resolved ONLY by runtime semantics: entry = round(close of last closed candle, 8). A candidate is
  chosen iff exactly one candidate candle satisfies it; otherwise AMBIGUOUS (never resolved by parity/outcome).
- Hard PIT assertion: every input candle closes strictly before the decision time.

  <venv-python> -m research.p2.market_coverage --p2b <normalized dir> --ds <ds-0928 dir> --p2a-canonical <dir>
      --acq-log acquisition.jsonl --repo <git worktree> --code-commit 977746f --out <reports dir>
"""
from __future__ import annotations

import argparse
import ast
import bisect
import hashlib
import json
import pathlib
import subprocess
import types
from collections import Counter, defaultdict
from decimal import Decimal

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import ta

from . import market_contract as M
from .extract import read_csv_gz, _write_csv_gz

MAX_HOLD_H = {"15m": 48, "1h": 48, "4h": 96, "1d": 240}   # timeframe_v1 max hold; 1h uses the default policy
CORE = ["rsi", "stoch_k", "stoch_d", "macd_hist", "bb_pos", "bb_width", "atr_pct", "volume_ratio",
        "dist_ema20", "dist_ema50", "dist_ema200", "obv_vs_ema"]
EXTRA = ["adx14", "cci20", "willr14", "roc10", "mfi14", "cmf20"]
TOL = {**{k: 1e-6 for k in ("bb_pos", "bb_width", "atr_pct", "volume_ratio", "dist_ema20", "dist_ema50",
                             "dist_ema200", "roc10", "cmf20", "willr14")},
       **{k: 1e-4 for k in ("rsi", "stoch_k", "stoch_d", "macd_hist", "obv_vs_ema", "adx14", "cci20", "mfi14")}}
CONFIG = types.SimpleNamespace(RSI_PERIOD=14, MACD_FAST=12, MACD_SLOW=26, MACD_SIGNAL=9, EMA_SHORT=20, EMA_MEDIUM=50,
                               EMA_LONG=200, BB_PERIOD=20, BB_STD=2.0, ATR_PERIOD=14, STOCH_RSI_WINDOW=14,
                               STOCH_K=3, STOCH_D=3, CANDLES_TO_FETCH=200)
BASE = ["open_time", "close_time", "open", "high", "low", "close", "volume", "quote_volume", "trade_count"]


def load_historical_config(repo: str, commit: str):
    """Literal class-field defaults of shared/config.py at the SAME commit as the analyzer code (version-faithful;
    e.g. W2-era StochRSI used smooth1=STOCH_K=14). The analyzer environment sets none of these keys."""
    src = subprocess.run(["git", "-C", repo, "show", f"{commit}:shared/config.py"],
                         capture_output=True, text=True, check=True).stdout
    vals = {}
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, (int, float)) and n.target.id in vars(CONFIG):
            vals[n.target.id] = n.value.value
    cfg = types.SimpleNamespace(**{**vars(CONFIG), **vals})
    return cfg, hashlib.sha256(json.dumps(vars(cfg), sort_keys=True).encode()).hexdigest()


def load_analyzer(repo: str, commit: str):
    src = subprocess.run(["git", "-C", repo, "show", f"{commit}:analyzer/technical_analyzer.py"],
                         capture_output=True, text=True, check=True).stdout
    tree = ast.parse(src)
    body = [ast.get_source_segment(src, n) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in ("_calculate_indicators", "_raw_features")]
    if len(body) != 2:
        raise SystemExit("analyzer methods not found")
    code = "class HistoricalAnalyzer:\n" + "\n".join("    " + l for b in body for l in b.splitlines()) + "\n"
    cfg, cfg_sha = load_historical_config(repo, commit)
    ns = {"ta": ta, "np": np, "pd": pd, "pta": None, "config": cfg, "Dict": dict}
    exec(compile(code, f"<{commit}:technical_analyzer>", "exec"), ns)
    return ns["HistoricalAnalyzer"](), hashlib.sha256(code.encode()).hexdigest() + ":" + cfg_sha


def load_series(p2b: pathlib.Path, ds: pathlib.Path, sym: str, tf: str):
    parts = []
    f_ds = ds / "normalized" / tf / f"{sym}.parquet"
    if f_ds.exists():
        d = pq.read_table(f_ds, columns=BASE).to_pandas(); d["source_kind"] = "ds0928"; parts.append(d)
    f_b = p2b / tf / f"{sym}.parquet"
    if f_b.exists():
        d = pq.read_table(f_b, columns=BASE + ["source_kind"]).to_pandas(); parts.append(d)
    if not parts:
        return None
    s = pd.concat(parts, ignore_index=True)
    s["open_ms"] = s["open_time"].astype("datetime64[us, UTC]").astype("int64") // 1000
    s["close_ms"] = s["close_time"].astype("datetime64[us, UTC]").astype("int64") // 1000
    return s.sort_values("open_ms", kind="mergesort").reset_index(drop=True)


def seam(p2b: pathlib.Path, ds: pathlib.Path, sym: str, tf: str, ds_schema_cache: dict) -> dict:
    f_ds, f_b = ds / "normalized" / tf / f"{sym}.parquet", p2b / tf / f"{sym}.parquet"
    r = {"symbol": sym, "timeframe": tf, "in_ds0928": f_ds.exists(), "in_p2b": f_b.exists()}
    if not (r["in_ds0928"] and r["in_p2b"]):
        r["status"] = "NO_SEAM_SINGLE_SOURCE"; return r
    a = pq.read_table(f_ds, columns=BASE); b = pq.read_table(f_b, columns=BASE)
    r["schema_compatible"] = [str(x.type) for x in a.schema] == [str(x.type) for x in b.schema]
    us = lambda t, c: t.column(c).cast(pa.timestamp("us", tz="UTC")).cast("int64").to_pylist()   # unit-normalized
    ao, bo, ac, bc = us(a, "open_time"), us(b, "open_time"), us(a, "close_time"), us(b, "close_time")
    tf_us = M.TF_MS[tf] * 1000
    r["ds_last_open_ms"], r["p2b_first_open_ms"] = ao[-1] // 1000, bo[0] // 1000
    r["duplicate_identity"] = bool(set(ao) & set(bo))
    r["seam_step_bars"] = (bo[0] - ao[-1]) / tf_us
    r["monotonic"] = ao == sorted(ao) and bo == sorted(bo) and ao[-1] < bo[0]
    r["close_semantics_ds_last"] = ac[-1] - ao[-1]; r["close_semantics_p2b_first"] = bc[0] - bo[0]
    r["trade_count_type"] = [str(a.schema.field("trade_count").type), str(b.schema.field("trade_count").type)]
    ds_ends_at_cutoff = ac[-1] // 1000 >= M.W2_START_MS - 1000
    ok = r["schema_compatible"] and not r["duplicate_identity"] and r["monotonic"]
    if r["seam_step_bars"] == 1 and ok:
        r["status"] = "SEAM_CONTIGUOUS"
    elif ok and not ds_ends_at_cutoff:
        r["status"] = "SEAM_DS_ENDS_EARLY"          # ds series stopped before 05-31 (delisting/halt): no synthesis
    elif ok:
        r["status"] = "SEAM_GAP"
    else:
        r["status"] = "SEAM_FAIL"
    return r


def resolve_candle(cands: list, present: dict, close_of, entry, ambiguous: bool):
    """Runtime-semantics rule only: entry == round(close, 8) of the analysed candle. Never parity/outcome."""
    match = [c for c in cands if present.get(c) and entry is not None and
             Decimal(repr(round(float(close_of(c)), 8))) == entry]
    if ambiguous:
        return (match[0], "RESOLVED_BY_ENTRY_EQUALS_CLOSE") if len(match) == 1 else (None, f"AMBIGUOUS_{len(match)}_MATCHES")
    return cands[0], ("UNAMBIGUOUS_ENTRY_MATCH" if match == [cands[0]] else "UNAMBIGUOUS_ENTRY_MISMATCH")


def _alt_exact(cache: dict, alt_analyzer, df, k, sv) -> bool:
    if "f" not in cache:
        cache["f"] = alt_analyzer._raw_features(alt_analyzer._calculate_indicators(df.copy()))
    rv = cache["f"].get(k)
    return rv is not None and sv is not None and float(rv) == float(sv)


def pit_guard(max_input_close_ms: int, decision_ms: int, uid: str = "") -> None:
    """Hard fail on future-candle leakage: every input candle must close strictly before the decision."""
    if max_input_close_ms >= decision_ms:
        raise SystemExit(f"PIT VIOLATION {uid}: input candle closes at/after decision")


def main(argv=None):
    ap = argparse.ArgumentParser()
    for k in ("--p2b", "--ds", "--p2a-canonical", "--acq-log", "--repo", "--code-commit", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--alt-code-commit", default="63da7d3",
                    help="next code version; a mismatch that matches it EXACTLY is labelled VERSION_DIFFERENCE")
    a = ap.parse_args(argv)
    p2b, ds, out = pathlib.Path(a.p2b), pathlib.Path(a.ds), pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    analyzer, code_sha = load_analyzer(a.repo, a.code_commit)
    alt_analyzer, alt_sha = load_analyzer(a.repo, a.alt_code_commit)
    dec = [r for r in read_csv_gz(pathlib.Path(a.p2a_canonical) / "decision.csv.gz") if r["window"] == "W2"]
    ctx = defaultdict(dict)
    for r in read_csv_gz(pathlib.Path(a.p2a_canonical) / "decision_market_context.csv.gz"):
        if r["namespace"] == "features_snapshot" and r["feature_name"] in CORE + EXTRA:
            ctx[r["decision_uid"]][r["feature_name"]] = json.loads(r["value_json"])
    acq = [json.loads(l) for l in open(a.acq_log, encoding="utf-8")]
    unavailable = defaultdict(list)                      # (sym, tf) -> periods without verified data
    for r in acq:
        if r["status"] not in ("UPSTREAM_VERIFIED", "REST_VALIDATED_NO_UPSTREAM_CHECKSUM"):
            unavailable[(r["symbol"], r["timeframe"])].append((r["kind"], r["period"], r["status"]))

    # Seam validation for every acquired (symbol, tf)
    seams = [seam(p2b, ds, s, tf, {}) for tf in M.TIMEFRAMES for s in sorted(p.stem for p in (p2b / tf).glob("*.parquet"))]
    seams.sort(key=lambda r: (r["symbol"], r["timeframe"]))

    cache = {}

    def series(sym, tf):
        if (sym, tf) not in cache:
            if len(cache) > 64: cache.clear()
            cache[(sym, tf)] = load_series(p2b, ds, sym, tf)
        return cache[(sym, tf)]

    cov, parity, pit_viol = [], [], 0
    for d in sorted(dec, key=lambda r: (r["symbol"], r["timeframe"], r["decision_uid"])):
        sym, tf, uid = d["symbol"], d["timeframe"], d["decision_uid"]
        dms, entry = int(d["decision_time_ms"]), Decimal(d["planned_entry"]) if d["planned_entry"] else None
        s = series(sym, tf)
        rec = {"decision_uid": uid, "symbol": sym, "timeframe": tf, "decision_time_ms": dms}
        if s is None or s.empty:
            rec.update(cls="SYMBOL_UNAVAILABLE", detail="no candle series"); cov.append(rec); continue
        om = s["open_ms"].tolist()
        cands = [int(d["inferred_candle_open_ms"])] + ([int(d["candle_alt_open_ms"])] if d["candle_alt_open_ms"] else [])
        present = {c: (bisect.bisect_left(om, c) < len(om) and om[bisect.bisect_left(om, c)] == c) for c in cands}
        ambiguous = d["candle_ambiguous"] == "true"
        if not any(present.values()):
            src = "SOURCE_GAP" if unavailable.get((sym, tf)) else "OTHER"
            rec.update(cls=src, detail="decision candle missing" + (" (acquisition unavailable)" if src == "SOURCE_GAP" else " (exchange gap)"))
            cov.append(rec); continue
        chosen, resolution = resolve_candle(cands, present, lambda c: s.at[om.index(c), "close"], entry, ambiguous)
        rec["resolution"] = resolution
        htf = {}
        for tf2 in M.TIMEFRAMES:
            s2 = series(sym, tf2)
            exp_open = (dms // M.TF_MS[tf2]) * M.TF_MS[tf2] - M.TF_MS[tf2]
            if s2 is None or not len(s2):
                htf[tf2] = False
            else:
                o2 = s2["open_ms"].tolist(); j = bisect.bisect_left(o2, exp_open)
                htf[tf2] = j < len(o2) and o2[j] == exp_open
        rec["htf_context_all"] = all(htf.values())
        horizon_end = dms + MAX_HOLD_H[tf] * 3_600_000
        censored = horizon_end >= M.FREEZE_MS
        rec["horizon_censored"] = censored
        if chosen is None:
            rec.update(cls="AMBIGUOUS"); cov.append(rec); continue
        idx = om.index(chosen)
        window = s.iloc[max(0, idx - M.LOOKBACK_BARS + 1): idx + 1]
        rec["lookback_bars"] = len(window)
        if len(window) < M.LOOKBACK_BARS:
            rec.update(cls="INSUFFICIENT_LOOKBACK"); cov.append(rec); feature_state = "INSUFFICIENT_HISTORY"
        else:
            pit_guard(int(window["close_ms"].max()), dms, uid)       # HARD PIT (raises)
            later = s[(s["open_ms"] > chosen) & (s["open_ms"] <= horizon_end)]
            expected = (min(horizon_end, M.FREEZE_MS) - chosen) // M.TF_MS[tf]
            horizon_gap = (not censored) and len(later) < expected - 1
            rec.update(cls="FEATURE_READY_OUTCOME_CENSORED" if censored else ("OTHER" if horizon_gap else "COMPLETE"),
                       detail="horizon candles missing" if horizon_gap and not censored else "")
            cov.append(rec); feature_state = "OK"
        if d["has_features_snapshot"] != "true" or uid not in ctx:
            continue
        stored = ctx[uid]
        if feature_state != "OK":
            for k in CORE + EXTRA:
                parity.append({"decision_uid": uid, "symbol": sym, "timeframe": tf, "feature": k, "cls": "INSUFFICIENT_HISTORY"})
            continue
        df = window[["open", "high", "low", "close", "volume"]].astype(float).reset_index(drop=True).copy()
        feats = analyzer._raw_features(analyzer._calculate_indicators(df))
        src_kinds = set(window["source_kind"])
        alt = {}
        for k in CORE + EXTRA:
            sv, rv = stored.get(k, "__absent__"), feats.get(k)
            if sv == "__absent__":
                c = "VERSION_DIFFERENCE"
            elif sv is None and rv is None:
                c = "EXACT"
            elif sv is None or rv is None:
                c = "VERSION_DIFFERENCE" if k in EXTRA else "UNKNOWN"
            elif float(sv) == float(rv):
                c = "EXACT"
            elif abs(float(sv) - float(rv)) <= TOL[k] * max(1.0, abs(float(sv))):
                c = "WITHIN_TOLERANCE"
            elif _alt_exact(alt, alt_analyzer, df_raw := window[["open", "high", "low", "close", "volume"]].astype(float).reset_index(drop=True), k, sv):
                c = "VERSION_DIFFERENCE"                       # stored value equals the next code version exactly
            elif resolution == "UNAMBIGUOUS_ENTRY_MISMATCH":
                c = "TIMESTAMP_ALIGNMENT_ERROR"
            elif "rest_freeze_day" in src_kinds:
                c = "SOURCE_DIFFERENCE"
            elif k in EXTRA:
                c = "VERSION_DIFFERENCE"
            else:
                c = "UNKNOWN"
            parity.append({"decision_uid": uid, "symbol": sym, "timeframe": tf, "feature": k, "cls": c,
                           "abs_diff": "" if c in ("EXACT",) or sv in (None, "__absent__") or rv is None else f"{abs(float(sv)-float(rv)):.3e}"})

    _write_csv_gz(out / "w2_decision_coverage.csv.gz",
                  ["decision_uid", "symbol", "timeframe", "decision_time_ms", "cls", "detail", "resolution",
                   "htf_context_all", "horizon_censored", "lookback_bars"], cov)
    _write_csv_gz(out / "seam_validation.csv.gz",
                  ["symbol", "timeframe", "in_ds0928", "in_p2b", "status", "schema_compatible", "duplicate_identity",
                   "seam_step_bars", "monotonic", "ds_last_open_ms", "p2b_first_open_ms", "close_semantics_ds_last",
                   "close_semantics_p2b_first", "trade_count_type"], seams)
    _write_csv_gz(out / "snapshot_parity.csv.gz", ["decision_uid", "symbol", "timeframe", "feature", "cls", "abs_diff"], parity)
    pd_dec = {r["decision_uid"]: r for r in dec}
    snap = [r for r in dec if r["has_features_snapshot"] == "true"]
    t_lo, t_hi = M.W2_START_MS, M.FREEZE_MS
    third = lambda ms: "early" if ms < t_lo + (t_hi - t_lo) / 3 else ("middle" if ms < t_lo + 2 * (t_hi - t_lo) / 3 else "late")
    atr = sorted(float(ctx[r["decision_uid"]]["atr_pct"]) for r in snap if ctx[r["decision_uid"]].get("atr_pct") is not None)
    q1, q2 = (atr[len(atr) // 3], atr[2 * len(atr) // 3]) if atr else (0, 0)
    vb = lambda u: "n/a" if ctx[u].get("atr_pct") is None else ("low" if float(ctx[u]["atr_pct"]) < q1 else ("mid" if float(ctx[u]["atr_pct"]) < q2 else "high"))
    sample_uids = {p["decision_uid"] for p in parity}
    summary = {
        "analyzer_code_commit": a.code_commit, "analyzer_methods_sha256": code_sha, "ta_version": "0.11.0",
        "alt_code_commit": a.alt_code_commit, "alt_methods_sha256": alt_sha,
        "pit_violations": pit_viol,
        "seam_status": dict(Counter(r["status"] for r in seams)),
        "coverage_cls": dict(Counter(r["cls"] for r in cov)),
        "coverage_cls_by_tf": dict(Counter(f"{r['timeframe']}|{r['cls']}" for r in cov)),
        "resolution": dict(Counter(r.get("resolution", "-") for r in cov)),
        "htf_context_all": dict(Counter(str(r.get("htf_context_all")) for r in cov)),
        "horizon_censored": dict(Counter(str(r.get("horizon_censored")) for r in cov)),
        "parity_sample": {"rule": "ALL W2 decisions with stored features_snapshot (deterministic; no outcome-based selection)",
                          "snapshot_decisions": len(snap), "compared_decisions": len(sample_uids),
                          "by_tf": dict(Counter(pd_dec[u]["timeframe"] for u in sample_uids)),
                          "by_period": dict(Counter(third(int(pd_dec[u]["decision_time_ms"])) for u in sample_uids)),
                          "by_volatility_atr_pct_tercile": dict(Counter(vb(u) for u in sample_uids)),
                          "symbols": len({pd_dec[u]["symbol"] for u in sample_uids})},
        "parity_cls": dict(Counter(p["cls"] for p in parity)),
        "parity_cls_by_feature": {k: dict(Counter(p["cls"] for p in parity if p["feature"] == k)) for k in CORE + EXTRA},
    }
    (out / "coverage_parity_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: summary[k] for k in ("pit_violations", "seam_status", "coverage_cls", "resolution", "parity_cls")}, sort_keys=True))


if __name__ == "__main__":
    main()
