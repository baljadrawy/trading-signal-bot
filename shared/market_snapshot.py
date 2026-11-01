"""MarketSnapshot adapter and its shadow capture in the scanner (WP-B03; OF-T03, R6, R5).

This is the only module that knows venue field names (OPPORTUNITY_FUNNEL.md P7). It turns the
venue's listing (``exchangeInfo``) and 24 h ticker payloads into one venue-agnostic
``MarketSnapshot`` per cycle (OPPORTUNITY_FUNNEL.md F0; STRATEGY_AND_EXECUTION_CONTRACT.md §B3):

* ``as_of`` and ``as_of_basis``: venue time when the venue states it, otherwise host time;
* ``source`` and ``venue``;
* ``universe``: per symbol base asset, quote asset and venue status;
* ``filters`` (``MarketSnapshot.filters``, SE §B3): per symbol, glossary-named order filters as
  strings, the filter types that are not modelled, and the raw venue filter set (``venue_raw``);
* ``stats_24h``: per symbol 24 h statistics as strings; ``book``: best bid and ask from the same
  ticker, when present (``book_source``). This is not a fresh book: F2b reads its own;
* ``clock``: the measured offset between host and venue clocks and the round trip it came from;
* ``completeness`` and its reasons, and the ``listing_hash``, ``stats_hash`` and ``content_hash``.

Prices and sizes stay strings, as the venue wrote them, so hashing is exact and nothing is
rounded. Filter keys are the field names of ``shared/exchange_rules.SymbolFilters``.

The bounds for staleness and clock offset are owner decisions with no default here.
``assess_snapshot`` and ``admit_for_f1`` take them as required arguments. The shadow capture
records only measurements and never applies a bound.

Shadow capture (``MARKET_SNAPSHOT_SHADOW``, environment, ``off`` by default, or ``on``):
* ``off``: the scanner builds nothing from this module except the start-up flag parse, so the
  scan cycle has no wrapper, extra call, clock read, I/O or network.
* ``on``: ``SnapshotShadowTap`` puts a delegating proxy on the scanner instance's client. The proxy
  keeps a reference to what the scanner's own ``exchangeInfo`` and 24 h ticker requests returned,
  and reads the host clock around them. It makes no request of its own. After the scan returns,
  the tap builds the snapshot and records it in the existing evidence-v2 bounded store
  (``EVIDENCE_V2_ENABLED=true`` is required):
  - ``market_snapshot.listing`` holds the universe and filters, only when ``listing_hash``
    changes (evidence-v2 decision-state dedup);
  - ``market_snapshot.stats`` holds the 24 h statistics and book, in column form, when
    ``stats_hash`` changes;
  - ``market_snapshot.cycle`` holds the header with every hash, every cycle.
  ``snapshot_from_records`` rebuilds the snapshot from those three payloads and checks
  ``content_hash``. The tap never raises and never changes what the scanner receives. A failure
  is a counted health entry.

Pinned ``scanner/scanner_logic.py`` is not edited: the tap works on the instance only.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping

SCHEMA = "tsb.market_snapshot"
SCHEMA_VERSION = 1
VENUE = "binance_spot"
SOURCE = "binance_spot_rest:exchange_info+ticker_24h"
BOOK_SOURCE = "ticker_24h"

MARKET_SNAPSHOT_SHADOW_ENV = "MARKET_SNAPSHOT_SHADOW"
MARKET_SNAPSHOT_MODES = ("off", "on")

AS_OF_VENUE = "venue"
AS_OF_HOST = "host"
COMPLETE = "complete"
INCOMPLETE = "incomplete"

F0_STALE = "F0.snapshot_stale"
F0_INCOMPLETE = "F0.snapshot_incomplete"
F0_CLOCK = "F0.clock_offset_exceeded"

# ── venue vocabulary (Binance Spot REST): nowhere else ─────────────────────────────────────
_V_SERVER_TIME = "serverTime"
_V_SYMBOLS = "symbols"
_V_SYMBOL = "symbol"
_V_STATUS = "status"
_V_BASE = "baseAsset"
_V_QUOTE = "quoteAsset"
_V_FILTERS = "filters"
_V_FILTER_TYPE = "filterType"
# (venue filter type, venue field) -> glossary key (= shared/exchange_rules.SymbolFilters field)
_FILTER_FIELDS = {
    "PRICE_FILTER": {"tickSize": "tick_size", "minPrice": "min_price", "maxPrice": "max_price"},
    "LOT_SIZE": {"stepSize": "step_size", "minQty": "min_qty", "maxQty": "max_qty"},
    "MARKET_LOT_SIZE": {"stepSize": "market_step_size", "minQty": "market_min_qty",
                        "maxQty": "market_max_qty"},
    "NOTIONAL": {"minNotional": "min_notional", "maxNotional": "max_notional",
                 "applyMinToMarket": "apply_min_to_market", "applyMaxToMarket": "apply_max_to_market"},
    "MIN_NOTIONAL": {"minNotional": "min_notional", "applyToMarket": "apply_min_to_market"},
}
_NOTIONAL_PRIMARY = "NOTIONAL"           # NOTIONAL replaces the legacy MIN_NOTIONAL when both appear
_NOTIONAL_LEGACY = "MIN_NOTIONAL"
_TICKER_FIELDS = {"lastPrice": "last_price", "priceChange": "price_change",
                  "priceChangePercent": "price_change_pct", "weightedAvgPrice": "weighted_avg_price",
                  "openPrice": "open_price", "highPrice": "high_price", "lowPrice": "low_price",
                  "volume": "base_volume", "quoteVolume": "quote_volume", "openTime": "open_time_ms",
                  "closeTime": "close_time_ms", "count": "trade_count"}
_TICKER_CLOSE_TIME = "closeTime"
_TICKER_BID = "bidPrice"
_TICKER_ASK = "askPrice"
_CLIENT_LISTING_CALL = "get_exchange_info"
_CLIENT_TICKER_CALL = "get_ticker"

STATS_FIELDS = tuple(sorted(_TICKER_FIELDS.values()))
FILTER_KEYS = tuple(sorted({g for m in _FILTER_FIELDS.values() for g in m.values()}))


# ── flag ────────────────────────────────────────────────────────────────────────────────────

def market_snapshot_shadow_mode(environ: Mapping[str, str] | None = None) -> str:
    """``'off'`` or ``'on'``; an unknown value raises RuntimeError (fail closed at start-up)."""
    env = os.environ if environ is None else environ
    raw = env.get(MARKET_SNAPSHOT_SHADOW_ENV, "off")
    mode = str(raw).strip().lower()
    if mode not in MARKET_SNAPSHOT_MODES:
        raise RuntimeError(f"unknown {MARKET_SNAPSHOT_SHADOW_ENV} {raw!r}; "
                           f"expected one of {MARKET_SNAPSHOT_MODES}")
    return mode


def market_snapshot_shadow_enabled(environ: Mapping[str, str] | None = None, *,
                                   require_store: bool = True) -> bool:
    """True only for ``on``. With ``require_store``, ``on`` also needs EVIDENCE_V2_ENABLED=true."""
    on = market_snapshot_shadow_mode(environ) == "on"
    if on and require_store:
        from shared import evidence_v2
        if not evidence_v2.enabled():
            raise RuntimeError(f"{MARKET_SNAPSHOT_SHADOW_ENV}=on needs EVIDENCE_V2_ENABLED=true "
                               "(snapshots use the evidence-v2 bounded store)")
    return on


# ── canonical form ──────────────────────────────────────────────────────────────────────────

def _plain(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, no NaN: the form every hash here is taken over."""
    return json.dumps(_plain(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _sha(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _freeze(mapping: Mapping) -> Mapping:
    return MappingProxyType({k: (_freeze(v) if isinstance(v, Mapping) else v)
                             for k, v in sorted(mapping.items())})


def _text(value: Any) -> str | None:
    """A venue scalar as an exact string; None for a missing or non-scalar value."""
    if value is None or isinstance(value, (Mapping, list, tuple)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value) if value == value and value not in (float("inf"), float("-inf")) else None
    return str(value)


def _ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# ── snapshot ────────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ClockReading:
    """Host-to-venue offset measured around the listing request (venue minus host midpoint)."""
    offset_ms: int | None
    round_trip_ms: int | None
    venue_time_ms: int | None
    host_send_ms: int | None
    host_recv_ms: int | None

    def as_dict(self) -> dict:
        return {"offset_ms": self.offset_ms, "round_trip_ms": self.round_trip_ms,
                "venue_time_ms": self.venue_time_ms, "host_send_ms": self.host_send_ms,
                "host_recv_ms": self.host_recv_ms}


@dataclasses.dataclass(frozen=True)
class MarketSnapshot:
    as_of: int
    as_of_basis: str
    source: str
    venue: str
    universe: Mapping[str, Mapping[str, str]]
    filters: Mapping[str, Mapping[str, str]]
    stats_24h: Mapping[str, Mapping[str, str]]
    book: Mapping[str, tuple]
    book_source: str
    clock: ClockReading
    stats_as_of: int | None
    completeness: str
    incomplete_reasons: tuple
    counts: Mapping[str, int]
    listing_hash: str
    stats_hash: str
    content_hash: str

    @property
    def complete(self) -> bool:
        return self.completeness == COMPLETE

    def header(self) -> dict:
        """Everything except the per-symbol bodies; the bodies are behind the two hashes."""
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "as_of": self.as_of,
                "as_of_basis": self.as_of_basis, "source": self.source, "venue": self.venue,
                "book_source": self.book_source, "clock": self.clock.as_dict(),
                "stats_as_of": self.stats_as_of, "completeness": self.completeness,
                "incomplete_reasons": list(self.incomplete_reasons), "counts": dict(self.counts),
                "listing_hash": self.listing_hash, "stats_hash": self.stats_hash}

    def listing_body(self) -> dict:
        return {"universe": _plain(self.universe), "filters": _plain(self.filters)}

    def stats_body(self) -> dict:
        """Column form: field names once, one row per symbol (sorted)."""
        symbols = sorted(set(self.stats_24h) | set(self.book))
        rows = [[(self.stats_24h.get(s) or {}).get(f) for f in STATS_FIELDS]
                + list(self.book.get(s) or (None, None)) for s in symbols]
        return {"fields": list(STATS_FIELDS) + ["book_bid", "book_ask"], "symbols": symbols,
                "rows": rows}


def _content_hash(header: dict) -> str:
    return _sha({k: v for k, v in header.items() if k != "content_hash"})


def _listing_hash(universe, filters) -> str:
    return _sha({"universe": universe, "filters": filters})


def _stats_hash(stats, book) -> str:
    return _sha({"stats_24h": stats, "book": {s: list(v) for s, v in book.items()}})


def _symbol_filters(raw_filters: Any, counts: dict) -> dict:
    out: dict = {}
    types, unmodelled, raw_kept = set(), set(), []
    if not isinstance(raw_filters, list):
        counts["filter_sets_unreadable"] += 1
        raw_filters = []
    legacy: dict = {}
    for item in raw_filters:
        ftype = item.get(_V_FILTER_TYPE) if isinstance(item, Mapping) else None
        if not isinstance(ftype, str) or not ftype:
            counts["filter_entries_unreadable"] += 1
            continue
        raw_kept.append({str(k): _text(v) for k, v in item.items()})
        types.add(ftype)
        fields = _FILTER_FIELDS.get(ftype)
        if fields is None:
            unmodelled.add(ftype)
            continue
        target = legacy if ftype == _NOTIONAL_LEGACY else out
        for venue_key, key in fields.items():
            value = _text(item.get(venue_key))
            if value is not None:
                target[key] = value
    if _NOTIONAL_PRIMARY not in types:           # the legacy filter counts only without NOTIONAL
        for key, value in legacy.items():
            out.setdefault(key, value)
    raw_kept.sort(key=lambda d: (d.get(_V_FILTER_TYPE) or "", canonical_json(d)))
    out["venue_filter_types"] = ",".join(sorted(types))
    out["unmodelled"] = ",".join(sorted(unmodelled))
    out["venue_raw"] = canonical_json(raw_kept)
    return out


def build_snapshot(*, exchange_info: Any, tickers_24h: Any, listing_send_ms: int | None,
                   listing_recv_ms: int | None, stats_recv_ms: int | None) -> MarketSnapshot:
    """One snapshot from the venue payloads as returned, plus host clock readings around them.

    Pure and deterministic: identical inputs give an identical snapshot and hashes. A missing or
    unreadable part makes the snapshot ``incomplete`` (never partially trusted, F0). The inputs
    are read, never modified."""
    reasons: list = []
    counts = {"listed": 0, "with_stats": 0, "listed_without_stats": 0, "stats_without_listing": 0,
              "listing_entries_unreadable": 0, "stats_entries_unreadable": 0,
              "filter_sets_unreadable": 0, "filter_entries_unreadable": 0}
    universe: dict = {}
    filters: dict = {}
    venue_time = None
    entries = None
    if exchange_info is None:
        reasons.append("listing_missing")
    elif not isinstance(exchange_info, Mapping) or not isinstance(exchange_info.get(_V_SYMBOLS), list):
        reasons.append("listing_unreadable")
    else:
        venue_time = _ms(exchange_info.get(_V_SERVER_TIME))
        entries = exchange_info[_V_SYMBOLS]
    for entry in entries or ():
        symbol = entry.get(_V_SYMBOL) if isinstance(entry, Mapping) else None
        if not isinstance(symbol, str) or not symbol:
            counts["listing_entries_unreadable"] += 1
            continue
        if symbol in universe:
            if "listing_duplicate_symbol" not in reasons:
                reasons.append("listing_duplicate_symbol")
            continue
        universe[symbol] = {k: v for k, v in (("base_asset", _text(entry.get(_V_BASE))),
                                              ("quote_asset", _text(entry.get(_V_QUOTE))),
                                              ("status", _text(entry.get(_V_STATUS))))
                            if v is not None}
        filters[symbol] = _symbol_filters(entry.get(_V_FILTERS), counts)
    if counts["listing_entries_unreadable"]:
        reasons.append("listing_entry_unreadable")
    counts["listed"] = len(universe)

    stats: dict = {}
    book: dict = {}
    close_times = []
    if tickers_24h is None:
        reasons.append("stats_missing")
        items = ()
    elif isinstance(tickers_24h, Mapping):
        items = tuple(tickers_24h.values())
    elif isinstance(tickers_24h, (list, tuple)):
        items = tuple(tickers_24h)
    else:
        reasons.append("stats_unreadable")
        items = ()
    for t in items:
        symbol = t.get(_V_SYMBOL) if isinstance(t, Mapping) else None
        if not isinstance(symbol, str) or not symbol:
            counts["stats_entries_unreadable"] += 1
            continue
        if symbol not in universe:
            counts["stats_without_listing"] += 1      # outside the snapshot universe: counted only
            continue
        row = {key: v for vk, key in _TICKER_FIELDS.items() if (v := _text(t.get(vk))) is not None}
        stats[symbol] = row
        bid, ask = _text(t.get(_TICKER_BID)), _text(t.get(_TICKER_ASK))
        if bid not in (None, "") and ask not in (None, ""):
            book[symbol] = (bid, ask)
        ct = _ms(t.get(_TICKER_CLOSE_TIME))
        if ct is not None:
            close_times.append(ct)
    if counts["stats_entries_unreadable"]:
        reasons.append("stats_entry_unreadable")
    counts["with_stats"] = sum(1 for s in universe if s in stats)
    counts["listed_without_stats"] = counts["listed"] - counts["with_stats"]

    send, recv = _ms(listing_send_ms), _ms(listing_recv_ms)
    rtt = recv - send if send is not None and recv is not None and recv >= send else None
    offset = (venue_time - (send + recv) // 2) if venue_time is not None and rtt is not None else None
    clock = ClockReading(offset, rtt, venue_time, send, recv)
    stats_as_of = max(close_times) if close_times else None
    if venue_time is not None:
        as_of, basis = venue_time, AS_OF_VENUE
        if stats_as_of is not None:
            as_of = min(venue_time, stats_as_of)  # the snapshot is as old as its oldest part
    else:
        host = [x for x in (recv, _ms(stats_recv_ms)) if x is not None]
        as_of, basis = (min(host) if host else 0), AS_OF_HOST
        if not host:
            reasons.append("as_of_unknown")

    f_universe, f_filters = _freeze(universe), _freeze(filters)
    f_stats, f_book = _freeze(stats), MappingProxyType(dict(sorted(book.items())))
    listing_hash = _listing_hash(universe, filters)
    stats_hash = _stats_hash(stats, book)
    completeness = INCOMPLETE if reasons else COMPLETE
    snap = MarketSnapshot(as_of=int(as_of), as_of_basis=basis, source=SOURCE, venue=VENUE,
                          universe=f_universe, filters=f_filters, stats_24h=f_stats, book=f_book,
                          book_source=BOOK_SOURCE, clock=clock, stats_as_of=stats_as_of,
                          completeness=completeness, incomplete_reasons=tuple(reasons),
                          counts=MappingProxyType(dict(counts)), listing_hash=listing_hash,
                          stats_hash=stats_hash, content_hash="")
    return _with_hash(snap)


def _with_hash(snap: MarketSnapshot) -> MarketSnapshot:
    return dataclasses.replace(snap, content_hash=_content_hash(snap.header()))


def snapshot_from_records(header: Mapping, listing: Mapping, stats: Mapping) -> MarketSnapshot:
    """Rebuild a snapshot from its recorded payloads; refuses any hash that does not match."""
    universe = {s: dict(v) for s, v in (listing.get("universe") or {}).items()}
    filters = {s: dict(v) for s, v in (listing.get("filters") or {}).items()}
    if _listing_hash(universe, filters) != header.get("listing_hash"):
        raise ValueError("listing_hash mismatch")
    fields = list(stats.get("fields") or ())
    n = len(STATS_FIELDS)
    if fields != list(STATS_FIELDS) + ["book_bid", "book_ask"]:
        raise ValueError("stats fields mismatch")
    stats_map, book = {}, {}
    for symbol, row in zip(stats.get("symbols") or (), stats.get("rows") or ()):
        stats_map[symbol] = {f: v for f, v in zip(STATS_FIELDS, row[:n]) if v is not None}
        if row[n] is not None and row[n + 1] is not None:
            book[symbol] = (row[n], row[n + 1])
    if _stats_hash(stats_map, book) != header.get("stats_hash"):
        raise ValueError("stats_hash mismatch")
    c = header.get("clock") or {}
    snap = MarketSnapshot(
        as_of=int(header["as_of"]), as_of_basis=header["as_of_basis"], source=header["source"],
        venue=header["venue"], universe=_freeze(universe), filters=_freeze(filters),
        stats_24h=_freeze(stats_map), book=MappingProxyType(dict(sorted(book.items()))),
        book_source=header["book_source"],
        clock=ClockReading(c.get("offset_ms"), c.get("round_trip_ms"), c.get("venue_time_ms"),
                           c.get("host_send_ms"), c.get("host_recv_ms")),
        stats_as_of=header.get("stats_as_of"), completeness=header["completeness"],
        incomplete_reasons=tuple(header.get("incomplete_reasons") or ()),
        counts=MappingProxyType(dict(header.get("counts") or {})),
        listing_hash=header["listing_hash"], stats_hash=header["stats_hash"], content_hash="")
    snap = _with_hash(snap)
    if "content_hash" in header and snap.content_hash != header["content_hash"]:
        raise ValueError("content_hash mismatch")
    return snap


# ── F0 admission (bounds are required inputs, no defaults) ──────────────────────────────────

def _bound(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer (milliseconds), got {value!r}")
    return value


def venue_time_ms(host_ms: int, snapshot: MarketSnapshot) -> int | None:
    """Host time moved onto the venue clock with the snapshot's measured offset; None if unknown."""
    offset = snapshot.clock.offset_ms
    return None if offset is None else int(host_ms) + offset


def assess_snapshot(snapshot: MarketSnapshot, *, decision_time_ms: int, staleness_bound_ms: int,
                    clock_offset_bound_ms: int) -> tuple:
    """F0 reason codes for one snapshot at a venue-synchronised decision time; ``()`` = usable.

    * ``F0.snapshot_incomplete``: any part missing or unreadable;
    * ``F0.clock_offset_exceeded``: offset unknown, beyond its bound either way, or a snapshot
      dated after the decision by more than that bound;
    * ``F0.snapshot_stale``: decision time minus ``as_of`` above the staleness bound."""
    stale_bound = _bound("staleness_bound_ms", staleness_bound_ms)
    clock_bound = _bound("clock_offset_bound_ms", clock_offset_bound_ms)
    if isinstance(decision_time_ms, bool) or not isinstance(decision_time_ms, int):
        raise ValueError("decision_time_ms must be an integer epoch ms")
    codes = []
    if not snapshot.complete:
        codes.append(F0_INCOMPLETE)
    offset = snapshot.clock.offset_ms
    age = decision_time_ms - snapshot.as_of
    if offset is None or abs(offset) > clock_bound or age < -clock_bound:
        codes.append(F0_CLOCK)
    if age > stale_bound:
        codes.append(F0_STALE)
    return tuple(codes)


@dataclasses.dataclass(frozen=True)
class SnapshotAdmission:
    admitted: bool
    snapshot: MarketSnapshot | None     # None unless admitted: a refused snapshot never reaches F1
    reason_codes: tuple
    content_hash: str


def admit_for_f1(snapshot: MarketSnapshot, *, decision_time_ms: int, staleness_bound_ms: int,
                 clock_offset_bound_ms: int) -> SnapshotAdmission:
    codes = assess_snapshot(snapshot, decision_time_ms=decision_time_ms,
                            staleness_bound_ms=staleness_bound_ms,
                            clock_offset_bound_ms=clock_offset_bound_ms)
    return SnapshotAdmission(not codes, None if codes else snapshot, codes, snapshot.content_hash)


# ── shadow capture in the scanner ───────────────────────────────────────────────────────────

def _host_ms() -> int:
    return int(time.time() * 1000)


class _CaptureClient:
    """Delegating client proxy: returns exactly what the wrapped client returned (same object)
    or raises exactly what it raised, and keeps a reference plus host clock readings."""

    def __init__(self, client, tap: "SnapshotShadowTap"):
        self._client = client
        self._tap = tap

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def get_exchange_info(self, *args, **kwargs):
        send = self._tap._clock()
        info = await getattr(self._client, _CLIENT_LISTING_CALL)(*args, **kwargs)
        self._tap._see("listing", (info, send, self._tap._clock()))
        return info

    async def get_ticker(self, *args, **kwargs):
        out = await getattr(self._client, _CLIENT_TICKER_CALL)(*args, **kwargs)
        if not args and not kwargs:                 # the all-symbols 24 h request only
            self._tap._see("stats", (out, self._tap._clock()))
        return out


class SnapshotShadowTap:
    """Observe-only MarketSnapshot capture on one scanner instance (WP-B03)."""

    STREAM = "scanner.market_snapshot"

    def __init__(self, scanner, service: str = "scanner", *, clock_ms: Callable[[], int] | None = None,
                 emit: Callable[..., bool] | None = None):
        self.service = service
        self._clock_fn = clock_ms or _host_ms
        self._emit_fn = emit
        self._obs: dict | None = None
        self._seq = 0
        self.last_snapshot: MarketSnapshot | None = None
        self.stats = {"cycles": 0, "not_scanned": 0, "snapshots": 0, "complete": 0, "incomplete": 0,
                      "listing_recorded": 0, "listing_unchanged": 0, "stats_recorded": 0,
                      "stats_unchanged": 0, "events_recorded": 0, "not_recorded": 0,
                      "tap_failures": 0}
        scanner.client = _CaptureClient(scanner.client, self)

    def _clock(self) -> int | None:
        try:
            return int(self._clock_fn())
        except Exception:
            return None

    def _see(self, kind: str, value) -> None:
        try:
            if self._obs is not None and kind not in self._obs:     # first request of the cycle
                self._obs[kind] = value
        except Exception:                                          # pragma: no cover
            pass

    def health(self) -> dict:
        last = self.last_snapshot
        return dict(self.stats, last_content_hash=last.content_hash if last else None,
                    last_completeness=last.completeness if last else None,
                    last_clock_offset_ms=last.clock.offset_ms if last else None)

    def begin(self) -> None:
        self._obs = {}

    def end(self, candidates=None, error: BaseException | None = None) -> MarketSnapshot | None:
        """Build and record the cycle's snapshot. Never raises; returns the snapshot or None."""
        obs, self._obs = self._obs, None
        if obs is None:
            return None
        try:
            self.stats["cycles"] += 1
            if not obs:
                self.stats["not_scanned"] += 1           # paused cycle: nothing was requested
                return None
            info, send, recv = obs.get("listing", (None, None, None))
            tickers, stats_recv = obs.get("stats", (None, None))
            snap = build_snapshot(exchange_info=info, tickers_24h=tickers, listing_send_ms=send,
                                  listing_recv_ms=recv, stats_recv_ms=stats_recv)
            self.stats["snapshots"] += 1
            self.stats["complete" if snap.complete else "incomplete"] += 1
            self.last_snapshot = snap
            self._record(snap, error)
            return snap
        except Exception:
            self.stats["tap_failures"] += 1
            return None

    def _emit(self, event_type: str, subject: dict, payload: dict, **kw) -> bool:
        try:
            if self._emit_fn is not None:
                ok = bool(self._emit_fn(self.service, event_type, subject, payload, **kw))
            else:
                from shared import evidence_v2
                ok = bool(evidence_v2.emit(self.service, event_type, subject, payload, **kw))
        except Exception:
            ok = False
        self.stats["events_recorded" if ok else "not_recorded"] += 1
        return ok

    def _recorded(self, dedup_key: str, state: str) -> bool:
        if self._emit_fn is not None:
            return False
        try:
            from shared import evidence_v2
            return evidence_v2.is_recorded(self.service, dedup_key, state)
        except Exception:
            return False

    def _record(self, snap: MarketSnapshot, error: BaseException | None) -> None:
        self._seq += 1
        header = snap.header()
        header["content_hash"] = snap.content_hash
        bodies = (("listing", snap.listing_hash, snap.listing_body),
                  ("stats", snap.stats_hash, snap.stats_body))
        for kind, digest, body in bodies:
            key = f"{self.STREAM}.{kind}"
            if self._recorded(key, digest):
                self.stats[f"{kind}_unchanged"] += 1
                continue
            if self._emit(f"market_snapshot.{kind}", {"stream": key, f"{kind}_hash": digest},
                          dict(body(), **{f"{kind}_hash": digest}), state=digest, dedup_key=key,
                          event_time_ms=snap.as_of or None):
                self.stats[f"{kind}_recorded"] += 1
        header["outcome"] = "scan_failed" if error is not None else "scanned"
        header["error"] = type(error).__name__ if error is not None else None
        self._emit("market_snapshot.cycle",
                   {"stream": self.STREAM, "content_hash": snap.content_hash, "seq": self._seq},
                   header, event_time_ms=snap.as_of or None, transition=True,
                   state={"content_hash": snap.content_hash, "seq": self._seq})
