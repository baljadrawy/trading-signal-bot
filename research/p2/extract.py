"""P2-A canonical W1/W2 extraction from an ISOLATED restore of a verified trading_signals backup.

Usage (host):
  python3 -m research.p2.extract --psql "docker exec -i <isolated-container> psql -U p2a_extract -d trading_signals" \
      --out <dir> --source-backup-set <set> --source-backup-sha256 <sha>

Standard library only. W3 exclusion is enforced IN THE SQL: no row whose authoritative time is at or after the
freeze is ever selected with value columns. Rows whose W3 status cannot be determined are quarantined and only
their counts/reasons (and signal ids for straddling W2 decisions) are written. Never point --psql at production.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import pathlib
import shlex
import subprocess
import sys
from collections import Counter, defaultdict

from . import contract as C
from . import validate as V

csv.field_size_limit(1 << 30)
F = C.FREEZE_SQL
W1E = C.W1_END_EXCLUSIVE_SQL

# Per-signal W3 classification. A decision enters W1/W2 only if its decision time AND every linked lifecycle
# event time (trade open, trade exit, target fills, approval request/response) is strictly before the freeze.
CLS = f"""
cls AS (
  SELECT s.id AS signal_id, s.signal_time,
    greatest(a.opened_at, r.exit_time, f.max_filled, ap.max_ap) AS max_linked_time,
    ((a.id IS NOT NULL AND a.opened_at IS NULL) OR (r.id IS NOT NULL AND r.exit_time IS NULL)
      OR coalesce(f.null_filled,0) > 0 OR coalesce(ap.null_req,0) > 0) AS linked_null,
    (a.id IS NOT NULL AND r.id IS NULL) AS trade_without_result,
    (r.id IS NOT NULL AND a.id IS NULL) AS result_without_trade
  FROM signals s
  LEFT JOIN active_trades a ON a.signal_id = s.id
  LEFT JOIN trade_results r ON r.signal_id = s.id
  LEFT JOIN (SELECT t.signal_id, max(x.filled_at) AS max_filled, count(*) FILTER (WHERE x.filled_at IS NULL) AS null_filled
             FROM trade_target_fills x JOIN active_trades t ON t.id = x.active_trade_id GROUP BY 1) f ON f.signal_id = s.id
  LEFT JOIN (SELECT signal_id, greatest(max(requested_at), max(responded_at)) AS max_ap,
                    count(*) FILTER (WHERE requested_at IS NULL) AS null_req FROM approval_requests GROUP BY 1) ap ON ap.signal_id = s.id
),
dec AS (
  SELECT signal_id, CASE
    WHEN signal_time IS NULL THEN 'Q:null_decision_time'
    WHEN signal_time >= {F} THEN 'W3'
    WHEN linked_null THEN 'Q:linked_event_time_null'
    WHEN max_linked_time >= {F} THEN 'Q:linked_event_at_or_after_freeze'
    WHEN trade_without_result THEN 'Q:trade_without_result'
    WHEN result_without_trade THEN 'Q:result_without_trade'
    WHEN signal_time < {W1E} THEN 'W1' ELSE 'W2' END AS cls
  FROM cls
)"""

SIGNAL_COLS = ("s.id, s.symbol, s.timeframe, s.signal_time, s.market_condition, s.entry_price, s.target_1, "
               "s.target_2, s.target_3, s.stop_loss, s.score, s.score_details, s.claude_approved, s.telegram_sent, "
               "s.is_paper_trade, s.volume_usdt, s.features_snapshot, s.trade_type, s.macro_snapshot, "
               "s.decision_source, s.strategy_version")

QUERIES = {
    "raw_signals": f"WITH {CLS} SELECT d.cls AS window, {SIGNAL_COLS} FROM signals s JOIN dec d ON d.signal_id = s.id "
                   f"WHERE d.cls IN ('W1','W2') ORDER BY s.id",
    "raw_active_trades": f"WITH {CLS} SELECT a.* FROM active_trades a JOIN dec d ON d.signal_id = a.signal_id "
                         f"WHERE d.cls IN ('W1','W2') ORDER BY a.id",
    "raw_trade_results": f"WITH {CLS} SELECT r.id, r.signal_id, r.symbol, r.entry_price, r.exit_price, r.exit_time, "
                         f"r.result, r.profit_percent, r.target_reached, r.stop_hit, r.duration_hours, r.failure_reason, "
                         f"r.profit_usdt FROM trade_results r JOIN dec d ON d.signal_id = r.signal_id "
                         f"WHERE d.cls IN ('W1','W2') ORDER BY r.id",
    "raw_trade_target_fills": f"WITH {CLS} SELECT x.* FROM trade_target_fills x JOIN active_trades t ON t.id = x.active_trade_id "
                              f"JOIN dec d ON d.signal_id = t.signal_id WHERE d.cls IN ('W1','W2') ORDER BY x.id",
    "raw_approval_requests": f"WITH {CLS} SELECT p.* FROM approval_requests p JOIN dec d ON d.signal_id = p.signal_id "
                             f"WHERE d.cls IN ('W1','W2') ORDER BY p.id",
    "raw_outbox_lifecycle": f"""WITH {CLS}, ok AS (SELECT signal_id FROM dec WHERE cls IN ('W1','W2'))
        SELECT o.id, o.event_type, o.aggregate_type, o.aggregate_id, o.status, o.attempts, o.max_attempts,
               o.available_at, o.created_at, o.processed_at
        FROM outbox_events o
        WHERE o.created_at < {F} AND (o.processed_at IS NULL OR o.processed_at < {F}) AND o.available_at < {F}
          AND (  (o.aggregate_type = 'signal' AND o.aggregate_id IN (SELECT signal_id FROM ok))
              OR (o.aggregate_type = 'active_trade' AND o.aggregate_id IN (SELECT id FROM active_trades WHERE signal_id IN (SELECT signal_id FROM ok)))
              OR (o.aggregate_type = 'trade_result' AND o.aggregate_id IN (SELECT id FROM trade_results WHERE signal_id IN (SELECT signal_id FROM ok)))
              OR (o.aggregate_type = 'active_trade_target' AND o.aggregate_id IN (SELECT x.id FROM trade_target_fills x JOIN active_trades t ON t.id = x.active_trade_id WHERE t.signal_id IN (SELECT signal_id FROM ok)))
              OR (o.aggregate_type IN ('risk_transition','runtime_transition')))
        ORDER BY o.id""",
    "raw_risk_management": f"SELECT id, date, signals_sent, wins, losses, consecutive_losses, daily_pnl_percent, "
                           f"is_trading_paused, pause_reason FROM risk_management WHERE date < {C.FREEZE_DATE_SQL} ORDER BY date",
    "raw_macro_history": f"SELECT date, usdt_d, btc_d, btc_trend, eth_trend, updated_at FROM macro_history "
                         f"WHERE date < {C.FREEZE_DATE_SQL} AND updated_at < {F} ORDER BY date",
    "raw_analysis_latest_state": f"SELECT symbol, timeframe, analyzed_at, decision_at, processing_status, signal_generated, "
                                 f"decision_reason, analysis_data FROM analysis_results WHERE analyzed_at < {F} "
                                 f"AND (decision_at IS NULL OR decision_at < {F}) ORDER BY symbol, timeframe",
}

# Count-only queries (never return value columns of excluded rows).
COUNT_QUERIES = {
    "decision_classification": f"WITH {CLS} SELECT cls, count(*) AS n FROM dec GROUP BY 1 ORDER BY 1",
    "straddling_decision_ids": f"WITH {CLS} SELECT signal_id, cls AS reason FROM dec WHERE cls LIKE 'Q:%' ORDER BY 1",
    "excluded_counts": f"""SELECT 'signals' AS source, 'signal_time' AS authoritative_column,
          count(*) FILTER (WHERE signal_time >= {F}) AS at_or_after_freeze, count(*) FILTER (WHERE signal_time IS NULL) AS null_time FROM signals
        UNION ALL SELECT 'active_trades','opened_at', count(*) FILTER (WHERE opened_at >= {F}), count(*) FILTER (WHERE opened_at IS NULL) FROM active_trades
        UNION ALL SELECT 'trade_results','exit_time', count(*) FILTER (WHERE exit_time >= {F}), count(*) FILTER (WHERE exit_time IS NULL) FROM trade_results
        UNION ALL SELECT 'trade_target_fills','filled_at', count(*) FILTER (WHERE filled_at >= {F}), count(*) FILTER (WHERE filled_at IS NULL) FROM trade_target_fills
        UNION ALL SELECT 'approval_requests','requested_at', count(*) FILTER (WHERE requested_at >= {F}), count(*) FILTER (WHERE requested_at IS NULL) FROM approval_requests
        UNION ALL SELECT 'outbox_events','created_at|processed_at', count(*) FILTER (WHERE created_at >= {F} OR processed_at >= {F} OR available_at >= {F}), count(*) FILTER (WHERE created_at IS NULL) FROM outbox_events
        UNION ALL SELECT 'risk_management','date (daily; freeze day straddles)', count(*) FILTER (WHERE date >= {C.FREEZE_DATE_SQL}), count(*) FILTER (WHERE date IS NULL) FROM risk_management
        UNION ALL SELECT 'risk_recovery_events','epoch_started_at', count(*) FILTER (WHERE epoch_started_at >= {F}::timestamp AT TIME ZONE 'UTC'), count(*) FILTER (WHERE epoch_started_at IS NULL) FROM risk_recovery_events
        UNION ALL SELECT 'macro_history','date|updated_at', count(*) FILTER (WHERE date >= {C.FREEZE_DATE_SQL} OR updated_at >= {F}), count(*) FILTER (WHERE date IS NULL) FROM macro_history
        UNION ALL SELECT 'analysis_results','analyzed_at|decision_at', count(*) FILTER (WHERE analyzed_at >= {F} OR decision_at >= {F}), count(*) FILTER (WHERE analyzed_at IS NULL) FROM analysis_results
        ORDER BY 1""",
    "join_integrity": f"""SELECT 'active_trades_null_signal_id' AS check_name, count(*) AS n FROM active_trades WHERE signal_id IS NULL
        UNION ALL SELECT 'active_trades_orphan_signal', count(*) FROM active_trades a WHERE a.signal_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM signals s WHERE s.id = a.signal_id)
        UNION ALL SELECT 'trade_results_null_signal_id', count(*) FROM trade_results WHERE signal_id IS NULL
        UNION ALL SELECT 'trade_results_orphan_signal', count(*) FROM trade_results r WHERE r.signal_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM signals s WHERE s.id = r.signal_id)
        UNION ALL SELECT 'trade_results_without_active_trade', count(*) FROM trade_results r WHERE NOT EXISTS (SELECT 1 FROM active_trades a WHERE a.signal_id = r.signal_id)
        UNION ALL SELECT 'active_trades_without_result', count(*) FROM active_trades a WHERE NOT EXISTS (SELECT 1 FROM trade_results r WHERE r.signal_id = a.signal_id)
        UNION ALL SELECT 'target_fills_orphan_trade', count(*) FROM trade_target_fills x WHERE NOT EXISTS (SELECT 1 FROM active_trades a WHERE a.id = x.active_trade_id)
        UNION ALL SELECT 'target_fills_signal_mismatch', count(*) FROM trade_target_fills x JOIN active_trades a ON a.id = x.active_trade_id WHERE x.signal_id IS DISTINCT FROM a.signal_id
        UNION ALL SELECT 'approval_orphan_signal', count(*) FROM approval_requests p WHERE NOT EXISTS (SELECT 1 FROM signals s WHERE s.id = p.signal_id)
        UNION ALL SELECT 'signals_duplicate_symbol_tf_time', count(*) FROM (SELECT 1 FROM signals GROUP BY symbol, timeframe, signal_time HAVING count(*) > 1) z
        UNION ALL SELECT 'signals_multiple_trades', count(*) FROM (SELECT 1 FROM active_trades WHERE signal_id IS NOT NULL GROUP BY signal_id HAVING count(*) > 1) z
        UNION ALL SELECT 'signals_multiple_results', count(*) FROM (SELECT 1 FROM trade_results WHERE signal_id IS NOT NULL GROUP BY signal_id HAVING count(*) > 1) z
        ORDER BY 1""",
}


def _copy(psql: list, sql: str) -> list:
    cmd = psql + ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)"]
    res = subprocess.run(cmd, capture_output=True, check=False)
    if res.returncode != 0:
        raise SystemExit(f"extraction query failed (rc={res.returncode}); stderr suppressed by design, length={len(res.stderr)}")
    return list(csv.DictReader(io.StringIO(res.stdout.decode("utf-8"))))


def _write_csv_gz(path: pathlib.Path, cols: list, rows: list) -> dict:
    """Deterministic: fixed column order, rows as given (callers sort), gzip mtime=0, no filename."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    raw = buf.getvalue().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0, compresslevel=9) as gz:
            gz.write(raw)
    return {"rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(), "bytes": path.stat().st_size}


def read_csv_gz(path) -> list:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _ms(text):
    return "" if not text else str(C.naive_utc_text_to_ms(text))


def _js(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _flatten(ns: str, obj, out: list):
    for k in sorted(obj):
        v = obj[k]
        if isinstance(v, dict):
            _flatten(f"{ns}.{k}", v, out)
        else:
            out.append((ns, k, v))


def _vtype(v):
    return "null" if v is None else "bool" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) \
        else "string" if isinstance(v, str) else "json"


def _code_identity() -> dict:
    here = pathlib.Path(__file__).parent
    files = sorted(p for p in here.glob("*.py"))
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode()); h.update(hashlib.sha256(p.read_bytes()).digest())
    return {"code_sha256": h.hexdigest(), "files": [p.name for p in files], "contract": C.CONTRACT_VERSION}


def build(psql: list, out: pathlib.Path, backup_set: str, backup_sha: str, ds0928_manifest_sha: str) -> dict:
    raw = {k: _copy(psql, q) for k, q in QUERIES.items()}
    counts = {k: _copy(psql, q) for k, q in COUNT_QUERIES.items()}

    sig = raw["raw_signals"]
    trades = {r["signal_id"]: r for r in raw["raw_active_trades"]}
    results = {r["signal_id"]: r for r in raw["raw_trade_results"]}
    fills_by_trade = defaultdict(list)
    for r in raw["raw_trade_target_fills"]:
        fills_by_trade[r["active_trade_id"]].append(r)
    approvals = defaultdict(list)
    for r in raw["raw_approval_requests"]:
        approvals[r["signal_id"]].append(r)

    decisions, context, execution, lifecycle, tfills = [], [], [], [], []
    uid_by_signal = {}
    for s in sig:
        dms = C.naive_utc_text_to_ms(s["signal_time"])
        uid = C.decision_uid(int(s["id"]), s["symbol"], s["timeframe"], s["signal_time"])
        uid_by_signal[s["id"]] = uid
        if C.window_for_ms(dms) != s["window"]:
            raise SystemExit("window mismatch between SQL and contract (fail closed)")
        fs = json.loads(s["features_snapshot"]) if s["features_snapshot"] else None
        ms = json.loads(s["macro_snapshot"]) if s["macro_snapshot"] else None
        sd = json.loads(s["score_details"]) if s["score_details"] else None
        fs_ok = isinstance(fs, dict) and len(fs) > 0
        ms_ok = isinstance(ms, dict) and len(ms) > 0
        cand = C.infer_decision_candle(dms, s["timeframe"]) if s["timeframe"] in C.TF_MS else None
        decisions.append({
            "decision_uid": uid, "decision_key": f"sig:{s['id']}", "signal_id": s["id"], "candidate_id": "",
            "observed_candle_id": "", "symbol": s["symbol"], "timeframe": s["timeframe"], "window": s["window"],
            "decision_time_utc": s["signal_time"], "decision_time_ms": str(dms),
            "decision_time_provenance": "OBSERVED", "strategy_version": s["strategy_version"],
            "decision_source": s["decision_source"], "trade_type": s["trade_type"],
            "selection_policy": (fs or {}).get("selection_policy", "") if fs_ok else "",
            "market_condition": s["market_condition"], "score": s["score"],
            "planned_entry": s["entry_price"], "planned_t1": s["target_1"], "planned_t2": s["target_2"],
            "planned_t3": s["target_3"], "planned_stop": s["stop_loss"], "geometry_provenance": "STORED_SNAPSHOT",
            "inferred_candle_id": C.candle_id(s["symbol"], s["timeframe"], cand["open_ms"]) if cand else "",
            "inferred_candle_open_ms": str(cand["open_ms"]) if cand else "",
            "inferred_candle_close_ms": str(cand["close_ms"]) if cand else "",
            "candle_provenance": "INFERRED" if cand else "MISSING",
            "candle_inference_method": "last_closed_tf_candle_before_signal_time" if cand else "",
            "candle_ambiguous": ("true" if cand["ambiguous"] else "false") if cand else "",
            "candle_alt_open_ms": str(cand["alt_open_ms"]) if cand and cand["alt_open_ms"] is not None else "",
            "candle_staleness_basis": ("current_code_30min_rule" if s["window"] == "W2"
                                       else "current_code_30min_rule_ASSUMED_for_W1_era") if cand else "",
            "has_features_snapshot": "true" if fs_ok else "false", "has_macro_snapshot": "true" if ms_ok else "false",
            "risk_context_pit": "MISSING", "extraction_contract": C.CONTRACT_VERSION,
        })
        items = []
        if fs_ok:
            _flatten("features_snapshot", fs, items)
        if isinstance(sd, dict):
            _flatten("score_details", sd, items)
        if s["volume_usdt"] not in ("", None):
            items.append(("signals_row", "volume_usdt", float(s["volume_usdt"])))
        for ns, k, v in items:
            context.append({"decision_uid": uid, "namespace": ns, "feature_name": k, "value_json": _js(v),
                            "value_type": _vtype(v), "provenance": "STORED_SNAPSHOT", "source": f"signals.{ns.split('.')[0]}",
                            "observed_at_ms": "", "available_at_ms": str(dms),
                            "available_at_basis": "stored_with_decision_row_upper_bound", "pit_safe": "true",
                            "feature_version": "stored_runtime_v0"})
        if ms_ok:
            age = ms.get("macro_age_seconds")
            obs = str(dms - int(round(float(age) * 1000))) if isinstance(age, (int, float)) and age >= 0 else ""
            flat = []
            _flatten("macro_snapshot", ms, flat)
            for ns, k, v in flat:
                context.append({"decision_uid": uid, "namespace": ns, "feature_name": k, "value_json": _js(v),
                                "value_type": _vtype(v), "provenance": "STORED_SNAPSHOT", "source": "signals.macro_snapshot",
                                "observed_at_ms": obs, "available_at_ms": obs or str(dms),
                                "available_at_basis": "decision_minus_macro_age" if obs else "stored_with_decision_row_upper_bound",
                                "pit_safe": "true", "feature_version": "stored_runtime_v0"})
        t = trades.get(s["id"])
        ap = sorted(approvals.get(s["id"], []), key=lambda r: int(r["id"]))
        last_ap = ap[-1] if ap else None
        planned = float(s["entry_price"]) if s["entry_price"] else None
        fill = float(t["entry_price"]) if t and t["entry_price"] else None
        execution.append({
            "decision_uid": uid, "signal_id": s["id"], "window": s["window"], "execution_provenance": "PAPER_MODEL",
            "delivered": s["telegram_sent"], "admission_path": "approval_request" if ap else "direct",
            "approval_status": last_ap["status"] if last_ap else "",
            "approval_requested_ms": _ms(last_ap["requested_at"]) if last_ap else "",
            "approval_responded_ms": _ms(last_ap["responded_at"]) if last_ap else "",
            "entered": "true" if t else "false", "active_trade_id": t["id"] if t else "",
            "entry_order_type": t["entry_order_type"] if t else "", "planned_entry": s["entry_price"],
            "fill_price": t["entry_price"] if t else "", "fill_time_ms": _ms(t["opened_at"]) if t else "",
            "fill_latency_ms": str(C.naive_utc_text_to_ms(t["opened_at"]) - dms) if t else "",
            "fill_vs_planned_bps": f"{(fill / planned - 1) * 10000:.4f}" if (fill and planned) else "",
            "fill_price_basis": "paper_model_observed_price_at_registration_era_code_unverified" if t else "",
            "no_fill_status": "NOT_APPLICABLE" if t else "NOT_COLLECTED",
        })
        if t:
            r = results.get(s["id"])
            fl = fills_by_trade.get(t["id"], [])
            lifecycle.append({
                "active_trade_id": t["id"], "decision_uid": uid, "signal_id": s["id"], "window": s["window"],
                "execution_provenance": "PAPER_MODEL", "opened_ms": _ms(t["opened_at"]), "status": t["status"],
                "entry_order_type": t["entry_order_type"], "stop_policy": t["stop_policy"],
                "exit_policy_version": t["exit_policy_version"], "expiry_policy_version": t["expiry_policy_version"],
                "expiry_h": t["expiry_h"], "t1_expiry_h": t["t1_expiry_h"], "no_t1_expiry_h": t["no_t1_expiry_h"],
                "highest_target_hit": t["highest_target_hit"], "peak_price": t["peak_price"],
                "remaining_fraction": t["remaining_fraction"], "realized_profit_percent": t["realized_profit_percent"],
                "realized_profit_usdt": t["realized_profit_usdt"], "trade_result_id": r["id"] if r else "",
                "exit_ms": _ms(r["exit_time"]) if r else "", "exit_price": r["exit_price"] if r else "",
                "result": r["result"] if r else "", "profit_percent": r["profit_percent"] if r else "",
                "profit_usdt": r["profit_usdt"] if r else "", "target_reached": r["target_reached"] if r else "",
                "stop_hit": r["stop_hit"] if r else "", "duration_hours": r["duration_hours"] if r else "",
                "failure_reason": r["failure_reason"] if r else "", "n_target_fills": str(len(fl)),
                "pnl_basis": "AS_STORED_BASIS_UNVERIFIED_PAPER_MODEL",
            })
            for x in sorted(fl, key=lambda r: int(r["id"])):
                tfills.append({"fill_id": x["id"], "active_trade_id": t["id"], "decision_uid": uid,
                               "target_number": x["target_number"], "fill_price": x["fill_price"],
                               "quantity_fraction": x["quantity_fraction"], "notional_usdt": x["notional_usdt"],
                               "gross_profit_percent_contribution": x["gross_profit_percent_contribution"],
                               "gross_profit_usdt": x["gross_profit_usdt"], "filled_ms": _ms(x["filled_at"]),
                               "execution_provenance": "PAPER_MODEL", "fill_price_basis": "paper_model_booked_at_exact_target_price"})

    risk = [{"risk_date": r["date"], "signals_sent": r["signals_sent"], "wins": r["wins"], "losses": r["losses"],
             "consecutive_losses": r["consecutive_losses"], "daily_pnl_percent": r["daily_pnl_percent"],
             "is_trading_paused": r["is_trading_paused"], "pause_reason": r["pause_reason"],
             "provenance": "NOT_POINT_IN_TIME_SAFE",
             "pit_note": "end_of_day_state_last_write_wins_not_known_at_intraday_decision"} for r in raw["raw_risk_management"]]

    decisions.sort(key=lambda r: r["decision_uid"])
    context.sort(key=lambda r: (r["decision_uid"], r["namespace"], r["feature_name"]))
    execution.sort(key=lambda r: r["decision_uid"])
    lifecycle.sort(key=lambda r: int(r["active_trade_id"]))
    tfills.sort(key=lambda r: int(r["fill_id"]))
    tables = {"decision": decisions, "decision_market_context": context, "market_outcome": [],
              "execution_outcome": execution, "trade_lifecycle": lifecycle, "trade_target_fill": tfills,
              "risk_context": risk}

    validation = V.run_all(tables)
    files = {}
    for name, rows in raw.items():
        cols = list(rows[0].keys()) if rows else []
        files[f"raw/{name}.csv.gz"] = _write_csv_gz(out / "raw" / f"{name}.csv.gz", cols, rows)
    for name, rows in tables.items():
        files[f"canonical/{name}.csv.gz"] = _write_csv_gz(out / "canonical" / f"{name}.csv.gz", C.SCHEMAS[name], rows)

    cls_counts = {r["cls"]: int(r["n"]) for r in counts["decision_classification"]}
    straddle = counts["straddling_decision_ids"]
    q = [{"entity": "decision", "reason": k, "count": v} for k, v in sorted(cls_counts.items()) if k.startswith("Q:")]
    files["quarantine/quarantine_counts.csv.gz"] = _write_csv_gz(out / "quarantine" / "quarantine_counts.csv.gz",
                                                                 ["entity", "reason", "count"], q)
    files["quarantine/quarantined_signal_ids.csv.gz"] = _write_csv_gz(
        out / "quarantine" / "quarantined_signal_ids.csv.gz", ["signal_id", "reason"], straddle)
    files["quarantine/w3_excluded_counts.csv.gz"] = _write_csv_gz(
        out / "quarantine" / "w3_excluded_counts.csv.gz",
        ["source", "authoritative_column", "at_or_after_freeze", "null_time"], counts["excluded_counts"])
    files["derived/join_integrity_source.csv.gz"] = _write_csv_gz(
        out / "derived" / "join_integrity_source.csv.gz", ["check_name", "n"], counts["join_integrity"])

    # Ordering anomalies on the included W1/W2 set (counts only).
    dms = {r["decision_uid"]: int(r["decision_time_ms"]) for r in decisions}
    ordering = Counter()
    for r in lifecycle:
        o = int(r["opened_ms"]); d = dms[r["decision_uid"]]
        if o < d: ordering["fill_before_decision"] += 1
        if r["exit_ms"] and int(r["exit_ms"]) < o: ordering["exit_before_open"] += 1
    ex = {r["active_trade_id"]: r for r in lifecycle}
    for f_ in tfills:
        t = ex[f_["active_trade_id"]]
        fm = int(f_["filled_ms"])
        if fm < int(t["opened_ms"]): ordering["target_fill_before_open"] += 1
        if t["exit_ms"] and fm > int(t["exit_ms"]): ordering["target_fill_after_exit"] += 1
    for r in execution:
        if r["approval_requested_ms"] and int(r["approval_requested_ms"]) < dms[r["decision_uid"]]:
            ordering["approval_before_decision"] += 1
    joins = {"ordering_anomalies_included_set": dict(sorted(ordering.items())),
             "signal_to_trade_cardinality": dict(Counter("1" if r["entered"] == "true" else "0" for r in execution)),
             "decisions_with_features_snapshot": dict(Counter(f"{r['window']}|{r['has_features_snapshot']}" for r in decisions)),
             "candle_ambiguous_by_window_tf": dict(Counter(f"{r['window']}|{r['timeframe']}|{r['candle_ambiguous']}" for r in decisions))}

    # Missingness: per field / window / timeframe (null or empty), plus the reason class for structural gaps.
    miss = []
    for entity in ("decision", "execution_outcome", "trade_lifecycle"):
        rows = tables[entity]
        grp = defaultdict(list)
        tfm = {r["decision_uid"]: r["timeframe"] for r in decisions}
        for r in rows:
            grp[(r.get("window"), tfm.get(r.get("decision_uid"), ""))].append(r)
        for (w, tf), rs in sorted(grp.items()):
            for col in C.SCHEMAS[entity]:
                n_empty = sum(1 for r in rs if r.get(col) in ("", None))
                if n_empty:
                    miss.append({"entity": entity, "field": col, "window": w, "timeframe": tf, "rows": len(rs),
                                 "empty": n_empty})
    files["derived/missingness_fields.csv.gz"] = _write_csv_gz(
        out / "derived" / "missingness_fields.csv.gz", ["entity", "field", "window", "timeframe", "rows", "empty"], miss)
    sym = Counter((r["symbol"], r["window"], r["timeframe"], r["has_features_snapshot"]) for r in decisions)
    files["derived/missingness_by_symbol.csv.gz"] = _write_csv_gz(
        out / "derived" / "missingness_by_symbol.csv.gz", ["symbol", "window", "timeframe", "has_features_snapshot", "decisions"],
        [{"symbol": a, "window": b, "timeframe": c, "has_features_snapshot": d, "decisions": n} for (a, b, c, d), n in sorted(sym.items())])

    code = _code_identity()
    prov_rows = [
        {"source_id": "p1bg_backup", "kind": "source_backup", "identity": backup_set, "checksum_sha256": backup_sha,
         "authoritative_time_column": "", "w3_rule": "", "rows_included": "", "notes": "pg_dump custom; restored into isolated PG 16.15"},
        {"source_id": "ds-09284abbc6453ff59acd", "kind": "certified_candles", "identity": "manifest.json",
         "checksum_sha256": ds0928_manifest_sha, "authoritative_time_column": "close_time", "w3_rule": "historical_end 2026-05-31",
         "rows_included": "", "notes": "used for W1 coverage index only in P2-A"},
        {"source_id": "extraction_code", "kind": "code", "identity": ",".join(code["files"]), "checksum_sha256": code["code_sha256"],
         "authoritative_time_column": "", "w3_rule": "", "rows_included": "", "notes": C.CONTRACT_VERSION},
    ]
    rules = {"raw_signals": ("signal_time + all linked lifecycle times", "decision < freeze AND linked < freeze; else quarantine"),
             "raw_active_trades": ("opened_at (via decision)", "decision included"),
             "raw_trade_results": ("exit_time (via decision)", "decision included"),
             "raw_trade_target_fills": ("filled_at (via decision)", "decision included"),
             "raw_approval_requests": ("requested_at/responded_at (via decision)", "decision included"),
             "raw_outbox_lifecycle": ("created_at/processed_at/available_at", "< freeze and aggregate belongs to included decision"),
             "raw_risk_management": ("date (daily)", "date < 2026-08-19 (freeze day quarantined)"),
             "raw_macro_history": ("date/updated_at (daily)", "date < 2026-08-19 and updated_at < freeze"),
             "raw_analysis_latest_state": ("analyzed_at/decision_at", "< freeze; latest-state only, not decision history")}
    for k, (col, rule) in rules.items():
        prov_rows.append({"source_id": k, "kind": "raw_extract", "identity": f"raw/{k}.csv.gz",
                          "checksum_sha256": files[f"raw/{k}.csv.gz"]["sha256"], "authoritative_time_column": col,
                          "w3_rule": rule, "rows_included": str(files[f"raw/{k}.csv.gz"]["rows"]), "notes": ""})
    files["canonical/provenance.csv.gz"] = _write_csv_gz(out / "canonical" / "provenance.csv.gz", C.SCHEMAS["provenance"], prov_rows)

    data_hash = hashlib.sha256("".join(f"{k}:{v['content_sha256']}\n" for k, v in sorted(files.items())).encode()).hexdigest()
    dataset_id = "p2a-" + data_hash[:20]
    tmin = min(int(r["decision_time_ms"]) for r in decisions) if decisions else None
    tmax = max(int(r["decision_time_ms"]) for r in decisions) if decisions else None
    manifest = {
        "dataset_id": dataset_id, "schema": "tsb.p2.canonical", "schema_version": 1, "contract": C.CONTRACT_VERSION,
        "created_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code": code, "source_backup": {"set": backup_set, "dump_sha256": backup_sha},
        "freeze": {"utc": C.FREEZE_UTC, "git_sha": C.FREEZE_GIT_SHA, "rule": "authoritative time < freeze; W3 SEALED"},
        "windows": C.WINDOWS, "decision_classification": cls_counts,
        "decision_time_range_ms": [tmin, tmax],
        "decision_time_range_utc": [dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).isoformat() for x in (tmin, tmax)] if decisions else [],
        "symbols": len({r["symbol"] for r in decisions}), "timeframes": sorted({r["timeframe"] for r in decisions}),
        "rows_by_window": {e: dict(Counter(r.get("window", "") for r in rows)) for e, rows in tables.items() if rows and "window" in rows[0]},
        "provenance_counts": {"decision_market_context": dict(Counter(r["provenance"] for r in context)),
                              "decision.candle_provenance": dict(Counter(r["candle_provenance"] for r in decisions)),
                              "risk_context": dict(Counter(r["provenance"] for r in risk))},
        "layers": {"raw": "W1/W2-filtered extracts (immutable)", "canonical": "entities per contract",
                   "derived": "reports/indexes (reproducible)", "quarantine": "counts/ids only, no values"},
        "entity_status": {"market_outcome": "EMPTY: AWAITING_P2D (W1 candles certified; W2 AWAITING_P2B)"},
        "validation": {k: len(v) for k, v in validation.items()},
        "join_integrity_included_set": joins,
        "files": files,
    }
    (out / "manifests").mkdir(parents=True, exist_ok=True)
    (out / "manifests" / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out / "manifests" / "validation_violations.json").write_text(json.dumps(validation, indent=1, sort_keys=True) + "\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--psql", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-backup-set", required=True)
    ap.add_argument("--source-backup-sha256", required=True)
    ap.add_argument("--ds0928-manifest-sha256", required=True)
    a = ap.parse_args(argv)
    psql = shlex.split(a.psql)
    if "trading-signal-bot" in a.psql or " postgres " in f" {a.psql} ":
        raise SystemExit("refusing: --psql must target an isolated research restore, never production")
    out = pathlib.Path(a.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit("refusing: output directory not empty")
    m = build(psql, out, a.source_backup_set, a.source_backup_sha256, a.ds0928_manifest_sha256)
    bad = {k: v for k, v in m["validation"].items() if v}
    print(json.dumps({"dataset_id": m["dataset_id"], "decision_classification": m["decision_classification"],
                      "validation_failures": bad}, sort_keys=True))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
