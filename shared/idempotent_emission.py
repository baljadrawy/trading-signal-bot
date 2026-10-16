"""A43 idempotent signal persistence — reference implementation, no production caller.

Requires the proposed column/index in ``docs/a43/proposed_011_signal_setup_key.sql``.
The unique partial index is the concurrency primitive: concurrent workers,
restarted processes and repeated cycles all race on the same ``setup_key``;
exactly one ``INSERT … ON CONFLICT DO NOTHING`` returns a row, and only that
transaction publishes ``signal.ready``. A loser learns whether the stored
setup had the same bracket (``duplicate``) or a different one (``conflict``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping

EMISSION_VERSION = "a43-ie-v1"

INSERT_ONCE_SQL = """
    INSERT INTO signals (symbol, timeframe, market_condition, entry_price, target_1, target_2,
                         target_3, stop_loss, score, features_snapshot, trade_type,
                         decision_source, strategy_version, setup_key)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14)
    ON CONFLICT (setup_key) WHERE setup_key IS NOT NULL DO NOTHING
    RETURNING id
"""

EXISTING_SQL = """
    SELECT id, features_snapshot->>'a43_bracket_hash' AS bracket_hash
    FROM signals WHERE setup_key = $1
"""


@dataclass(frozen=True)
class EmissionResult:
    status: str               # created | duplicate | conflict
    signal_id: int | None
    existing_id: int | None = None


async def insert_signal_once(conn, signal: Mapping, *, setup_key: str, bracket_hash: str,
                             strategy_version: str, decision_source: str,
                             publish: Callable[[object, int], Awaitable]) -> EmissionResult:
    """Insert the signal and publish its event atomically, at most once per ``setup_key``."""
    if not setup_key:
        raise ValueError("setup_key_required")
    snapshot = dict(signal.get("features_snapshot") or {})
    snapshot.update({"a43_setup_key": setup_key, "a43_bracket_hash": bracket_hash,
                     "a43_emission_version": EMISSION_VERSION})
    async with conn.transaction():
        signal_id = await conn.fetchval(
            INSERT_ONCE_SQL, signal["symbol"], signal["timeframe"],
            signal.get("market_condition", "unknown"), signal["entry_price"], signal["target_1"],
            signal["target_2"], signal["target_3"], signal["stop_loss"],
            int(signal.get("total_score") or 0), json.dumps(snapshot, default=str),
            signal.get("trade_type"), decision_source, strategy_version, setup_key)
        if signal_id is not None:
            await publish(conn, signal_id)        # same transaction: no row ⇒ no event, and vice versa
            return EmissionResult("created", signal_id)
        row = await conn.fetchrow(EXISTING_SQL, setup_key)
    same = row is not None and row["bracket_hash"] == bracket_hash
    return EmissionResult("duplicate" if same else "conflict", None, row["id"] if row else None)
