"""WP-E03 ledger store (PR-C04, R7.c): persistence of ``shared/portfolio_ledger.py`` entries.

Writes and reads the tables of ``database/migrations/012_portfolio_ledger.sql`` through a
connection the caller passes in (an asyncpg ``Connection``, or anything with the same
``execute``/``fetch``/``fetchrow``/``transaction`` methods). The store opens no pool, reads no
configuration and has no clock. No service calls it yet: wiring the writer into the tracker is
WP-E04, gated on PR-OD1 (Paper genesis) and PR-OD2 (genesis amount).

Row format (one row per ``LedgerEntry``):

* ``event_payload`` is the canonical form of the normalized event (``portfolio_ledger._canon``):
  decimals are exact strings, times are UTC ISO strings. It is the replay input.
* ``event_fingerprint`` is ``portfolio_ledger.event_fingerprint`` of that event (PR-I7);
  ``deltas`` are the entry's balance deltas, also canonical strings.
* ``prev_state_hash`` and ``state_hash`` are the library's hash chain (PR-I8). The database
  refuses an insert that does not extend the chain by exactly one entry; the store never computes
  a hash of its own.

Reading (``load_ledger``) folds the stored events from empty with the library and requires every
recomputed fingerprint, delta, sequence and hash to equal the stored one. Any difference raises
``LedgerInvariantViolation`` (PR-I8): a tampered or partial log is refused, never repaired.

Idempotency (PR-I7). ``append_entries`` skips an entry whose ``event_id`` is already stored with
the same fingerprint, sequence and hash, and records the repeat as ``duplicate_noop``. The same
``event_id`` with a different payload raises ``LedgerEventConflict`` (``F7.ledger_event_conflict``);
the same payload at a different position raises ``LedgerInvariantViolation``. Both are recorded
as ``conflict`` after the batch is rolled back, and nothing of the batch is written.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

from shared import portfolio_ledger as pl

STORE_VERSION = "wp-e03-ledger-store-v1"
_EVENT_CLASSES = {cls.__name__: cls for cls in pl.EVENT_TYPES}
_DECIMAL_FIELDS = frozenset({"amount", "qty", "price", "fee", "cost", "ref_price"})
# Columns the replay recomputes and compares with the stored row.
_COMPARED = ("entry_id", "event_id", "event_type", "as_of", "cost_model_id", "subject_id", "symbol",
             "event_fingerprint", "prev_state_hash", "state_hash")

_INSERT_LEDGER = """
INSERT INTO portfolio_ledgers (ledger_id, quote_asset, cost_model_id, money_quantum, ledger_version)
VALUES ($1, $2, $3, $4, $5) ON CONFLICT (ledger_id) DO NOTHING"""
_SELECT_LEDGER = """
SELECT ledger_id, quote_asset, cost_model_id, money_quantum, ledger_version
FROM portfolio_ledgers WHERE ledger_id = $1"""
_SELECT_EVENT = """
SELECT sequence, event_fingerprint, state_hash FROM portfolio_ledger_entries
WHERE ledger_id = $1 AND event_id = $2"""
_INSERT_ENTRY = """
INSERT INTO portfolio_ledger_entries (ledger_id, sequence, entry_id, event_id, event_type, as_of,
    cost_model_id, subject_id, symbol, event_payload, event_fingerprint, deltas, prev_state_hash,
    state_hash)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12::jsonb, $13, $14)"""
_INSERT_REPEAT = """
INSERT INTO portfolio_ledger_repeats (ledger_id, event_id, event_fingerprint, outcome)
VALUES ($1, $2, $3, $4)"""
_SELECT_ENTRIES = """
SELECT ledger_id, sequence, entry_id, event_id, event_type, as_of, cost_model_id, subject_id, symbol,
       event_payload, event_fingerprint, deltas, prev_state_hash, state_hash
FROM portfolio_ledger_entries WHERE ledger_id = $1 ORDER BY sequence"""
_ENTRY_COLUMNS = ("ledger_id", "sequence", "entry_id", "event_id", "event_type", "as_of",
                  "cost_model_id", "subject_id", "symbol", "event_payload", "event_fingerprint",
                  "deltas", "prev_state_hash", "state_hash")


class LedgerStoreError(pl.LedgerError):
    """A row, header or database refusal the store does not accept."""


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _parsed(value):
    """A JSONB value as asyncpg returns it (text) or as a mapping."""
    return json.loads(value) if isinstance(value, str) else dict(value)


def _chain(detail: str):
    raise pl.LedgerInvariantViolation("invariant_violation", f"PR-I8: {detail}")


# ── pure row mapping ───────────────────────────────────────────────────────────────────────

def header_row(ledger: pl.PortfolioLedger) -> dict:
    return {"ledger_id": ledger.ledger_id, "quote_asset": ledger.quote_asset,
            "cost_model_id": ledger.cost_model_id, "money_quantum": str(ledger.money_quantum),
            "ledger_version": pl.LEDGER_VERSION}


def _subject(event) -> tuple:
    if isinstance(event, (pl.Reserve, pl.ReleaseReservation, pl.EntryFill)):
        subject = event.intent_id
    elif isinstance(event, pl.ExitFill):
        subject = event.position_id
    else:
        subject = None
    symbol = event.symbol if isinstance(event, (pl.Reserve, pl.Mark)) else None
    return subject, symbol


def entry_row(entry: pl.LedgerEntry) -> dict:
    """The column values of one entry. ``event_payload`` and ``deltas`` are JSON text."""
    event = entry.event
    if not isinstance(event, pl.EVENT_TYPES) or type(event).__name__ != entry.event_type:
        raise LedgerStoreError("event_type_unsupported", entry.event_type)
    subject, symbol = _subject(event)
    return {"ledger_id": entry.ledger_id, "sequence": entry.sequence, "entry_id": entry.entry_id,
            "event_id": entry.event_id, "event_type": entry.event_type, "as_of": entry.as_of,
            "cost_model_id": entry.cost_model_id, "subject_id": subject, "symbol": symbol,
            "event_payload": _json(pl._canon(event)),
            "event_fingerprint": pl.event_fingerprint(event),
            "deltas": _json(pl._canon(dict(entry.deltas))),
            "prev_state_hash": entry.prev_state_hash, "state_hash": entry.state_hash}


def event_from_payload(event_type: str, payload: Mapping):
    """Rebuild one event from its stored canonical payload. Unknown types (including the not yet
    implemented ``Correction``) and payloads that do not match the event's fields are refused."""
    cls = _EVENT_CLASSES.get(event_type)
    if cls is None:
        raise LedgerStoreError("event_type_unsupported", repr(event_type))
    names = [f.name for f in dataclasses.fields(cls)]
    if not isinstance(payload, Mapping) or set(payload) != set(names):
        raise LedgerStoreError("payload_shape", f"{event_type} payload fields differ")
    values = {}
    for name in names:
        raw = payload[name]
        if raw is None and name == "ref_price":          # the only optional field
            values[name] = None
            continue
        if not isinstance(raw, str):
            raise LedgerStoreError("payload_shape", f"{event_type}.{name} is not a string")
        try:
            if name == "as_of":
                values[name] = datetime.fromisoformat(raw)
            elif name in _DECIMAL_FIELDS:
                values[name] = Decimal(raw)
            else:
                values[name] = raw
        except (ValueError, InvalidOperation) as exc:
            raise LedgerStoreError("payload_shape", f"{event_type}.{name}: {exc}") from exc
    return cls(**values)


def ledger_from_rows(header: Mapping, rows: Sequence[Mapping]) -> pl.PortfolioLedger:
    """Fold stored rows from empty and verify each one against the recomputed entry (PR-I8)."""
    if header["ledger_version"] != pl.LEDGER_VERSION:
        raise LedgerStoreError("ledger_version_mismatch",
                               f"{header['ledger_version']!r} != {pl.LEDGER_VERSION!r}")
    try:
        quantum = Decimal(header["money_quantum"])
    except InvalidOperation as exc:
        raise LedgerStoreError("ledger_header_invalid", "money_quantum") from exc
    ledger = pl.PortfolioLedger(ledger_id=header["ledger_id"], quote_asset=header["quote_asset"],
                                cost_model_id=header["cost_model_id"], money_quantum=quantum)
    for index, row in enumerate(rows, start=1):
        if row["ledger_id"] != ledger.ledger_id or row["sequence"] != index:
            _chain(f"stored row {index} is out of order")
        event = event_from_payload(row["event_type"], _parsed(row["event_payload"]))
        before = len(ledger.entries)
        entry = ledger.apply(event)
        if len(ledger.entries) != before + 1:
            _chain(f"stored event {row['event_id']!r} repeats an earlier event")
        expected = entry_row(entry)
        for column in _COMPARED:
            if expected[column] != row[column]:
                _chain(f"{column} differs at sequence {index}")
        for column in ("event_payload", "deltas"):
            if json.loads(expected[column]) != _parsed(row[column]):
                _chain(f"{column} differs at sequence {index}")
    pl.verify_chain(ledger.entries)
    return ledger


# ── database access (explicit connection) ─────────────────────────────────────────────────

def _refused(exc: Exception) -> LedgerStoreError:
    state = getattr(exc, "sqlstate", None)
    return LedgerStoreError("database_refused", f"{state}: {exc}")


async def ensure_ledger(conn, ledger: pl.PortfolioLedger) -> str:
    """Create the ledger header, or accept an identical existing one. Returns 'created' or
    'exists'; a header that differs in any field raises ``ledger_header_conflict``."""
    want = header_row(ledger)
    status = await conn.execute(_INSERT_LEDGER, *(want[k] for k in (
        "ledger_id", "quote_asset", "cost_model_id", "money_quantum", "ledger_version")))
    row = await conn.fetchrow(_SELECT_LEDGER, ledger.ledger_id)
    if row is None or any(row[k] != v for k, v in want.items()):
        raise LedgerStoreError("ledger_header_conflict", ledger.ledger_id)
    return "created" if status.endswith(" 1") else "exists"


async def append_entries(conn, entries: Iterable[pl.LedgerEntry]) -> list:
    """Append entries in order, in one transaction. Returns 'inserted' or 'duplicate' per entry."""
    rows = [entry_row(entry) for entry in entries]
    outcomes, conflict = [], None
    try:
        async with conn.transaction():
            for row in rows:
                stored = await conn.fetchrow(_SELECT_EVENT, row["ledger_id"], row["event_id"])
                if stored is None:
                    try:
                        await conn.execute(_INSERT_ENTRY, *(row[c] for c in _ENTRY_COLUMNS))
                    except Exception as exc:          # a database refusal is a store refusal
                        if getattr(exc, "sqlstate", None) is None:
                            raise
                        raise _refused(exc) from exc
                    outcomes.append("inserted")
                    continue
                if stored["event_fingerprint"] != row["event_fingerprint"]:
                    conflict = row
                    raise pl.LedgerEventConflict("ledger_event_conflict", row["event_id"])
                if (stored["sequence"], stored["state_hash"]) != (row["sequence"], row["state_hash"]):
                    conflict = row
                    _chain(f"event {row['event_id']!r} is stored at another position")
                await conn.execute(_INSERT_REPEAT, row["ledger_id"], row["event_id"],
                                   row["event_fingerprint"], "duplicate_noop")
                outcomes.append("duplicate")
    except pl.LedgerError:
        if conflict is not None:
            await conn.execute(_INSERT_REPEAT, conflict["ledger_id"], conflict["event_id"],
                               conflict["event_fingerprint"], "conflict")
        raise
    return outcomes


async def sync_ledger(conn, ledger: pl.PortfolioLedger) -> list:
    """Make the stored ledger equal the in-memory one: header plus every entry, idempotently."""
    await ensure_ledger(conn, ledger)
    return await append_entries(conn, ledger.entries)


async def load_ledger(conn, ledger_id: str) -> pl.PortfolioLedger:
    """Read one ledger and rebuild it by replay; refuses unless every stored hash reproduces."""
    header = await conn.fetchrow(_SELECT_LEDGER, ledger_id)
    if header is None:
        raise LedgerStoreError("unknown_ledger", ledger_id)
    rows = await conn.fetch(_SELECT_ENTRIES, ledger_id)
    return ledger_from_rows(header, rows)
