"""S3 shadow sidecar (out of process; DISABLED unless run explicitly with --enable).

Reads ONLY operational diagnostic data, read-only (default_transaction_read_only, statement
timeout): the engine's fresh analysis_results window (the engine's own WHERE/ORDER/LIMIT) and
the latest scanner volume per symbol. Never reads signals/trade_results, Evidence V2 or any
protected research data, and never writes to the database. Writes bounded JSONL via
shared.s3_shadow_store. The engine marks every timeframe row of a selected symbol
'signal_created', so the selected timeframe is not recoverable here: the operational column is
the exact production-parity replica, cross-checked at symbol level against those rows.

Bounds: --cycles <= 1440, --interval >= 30 s, rows capped by ShadowConfig.max_candidates, record
and disk budgets by StoreConfig. Run it under an external `timeout` for a hard wall-clock bound.
Starting it against production is a deployment decision for the owner.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from shared.s3_shadow import ShadowConfig, build_snapshot, run_shadow_safely
from shared.s3_shadow_store import ShadowStore, StoreConfig

FRESH_SQL = """
    SELECT symbol, timeframe, analysis_data, decision_reason FROM analysis_results
    WHERE signal_generated = false
    AND analyzed_at > NOW() - INTERVAL '30 minutes'
    AND symbol NOT IN (SELECT symbol FROM active_trades WHERE status = 'open')
    ORDER BY symbol, (analysis_data->>'total_score')::float DESC
    LIMIT 200"""
SELECTED_SQL = """SELECT DISTINCT symbol FROM analysis_results
    WHERE processing_status = 'signal_created' AND decision_at > NOW() - INTERVAL '2 minutes'"""
VOLUME_SQL = """SELECT DISTINCT ON (symbol) symbol, (data->>'volume_usdt')::float AS v
    FROM scan_candidates WHERE symbol = ANY($1::text[]) ORDER BY symbol, scan_time DESC"""


def cycle_record(rows, volumes, engine_signal_symbols, *, decision_ms, shadow: ShadowConfig) -> dict:
    """Pure: one sidecar cycle -> one shadow record (never raises)."""
    rows = [dict(r) for r in rows][: shadow.max_candidates]
    cooldown = {r["symbol"] for r in rows if r.get("decision_reason") == "symbol_cooldown"}
    snap = build_snapshot([{k: r[k] for k in ("symbol", "timeframe", "analysis_data")} for r in rows],
                          {k: v for k, v in volumes.items()}, decision_ms=decision_ms,
                          source="sidecar_read_only", cooldown=cooldown)
    rec = run_shadow_safely(snap, None, config=shadow)
    if rec.get("status") == "OK":
        replica = rec["replica"]["pick"]
        rec["engine_signal_symbols"] = sorted(engine_signal_symbols)
        rec["engine_symbol_agrees_with_replica"] = (
            (replica[0] in engine_signal_symbols) if replica else not engine_signal_symbols)
    return rec


async def run(dsn: str, store: ShadowStore, *, cycles: int, interval: float, shadow: ShadowConfig) -> dict:
    import asyncpg
    conn = await asyncpg.connect(dsn, server_settings={"default_transaction_read_only": "on",
                                                        "statement_timeout": "5000"})
    out = {"cycles": 0, "statuses": {}}
    try:
        for i in range(cycles):
            rows = await conn.fetch(FRESH_SQL)
            rows = [{**dict(r), "analysis_data": json.loads(r["analysis_data"])
                     if isinstance(r["analysis_data"], str) else r["analysis_data"]} for r in rows]
            vols = {r["symbol"]: r["v"] for r in await conn.fetch(
                VOLUME_SQL, sorted({r["symbol"] for r in rows}))}
            selected = {r["symbol"] for r in await conn.fetch(SELECTED_SQL)}
            rec = cycle_record(rows, vols, selected, decision_ms=int(time.time() * 1000), shadow=shadow)
            st = store.append(rec)
            out["statuses"][st] = out["statuses"].get(st, 0) + 1
            out["cycles"] += 1
            if i + 1 < cycles:
                await asyncio.sleep(interval)
    finally:
        await conn.close()
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--enable", action="store_true", help="required: the sidecar is disabled by default")
    p.add_argument("--dsn", required=False)
    p.add_argument("--dir", required=False)
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--interval", type=float, default=60.0)
    a = p.parse_args(argv)
    if not a.enable:
        print("s3-shadow-sidecar: disabled (pass --enable explicitly)")
        return 2
    if not (a.dsn and a.dir) or not 1 <= a.cycles <= 1440 or a.interval < 30:
        print("s3-shadow-sidecar: need --dsn, --dir, 1<=--cycles<=1440, --interval>=30")
        return 2
    store = ShadowStore(StoreConfig(enabled=True, directory=a.dir))
    res = asyncio.run(run(a.dsn, store, cycles=a.cycles, interval=a.interval,
                          shadow=ShadowConfig(enabled=True)))
    print(json.dumps({"result": res, "store": store.counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
