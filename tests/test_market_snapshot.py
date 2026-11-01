"""WP-B03 (OF-T03): MarketSnapshot adapter and its shadow capture in the scanner.

Synthetic venue-shaped payloads only. No recorded exchange data, protected data, network,
database or docker. The scanner tests drive the real ``scanner/main.py`` loop with in-memory fakes
(tests/funnel_service_harness.py). Before/after parity compares the current loop with the
``6ae70a2`` source of ``scanner/main.py``, loaded from git: its database calls, exchange calls and
heartbeats must be identical, with MARKET_SNAPSHOT_SHADOW off and with it on.
"""
import ast
import asyncio
import copy
import dataclasses
import importlib.util
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from funnel_service_harness import FakeDB, Health, events, load_service, run_main, set_recording
from shared import evidence_v2 as ev2
from shared import funnel_hooks as fh
from shared import market_snapshot as ms
from shared.config import config

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "6ae70a2"                 # scanner/main.py before the WP-B03 hook
T0 = 1_767_225_600_000                  # 2026-01-01 UTC, epoch ms
H4 = 14_400_000
SNAP_EVENTS = ("market_snapshot.cycle", "market_snapshot.listing", "market_snapshot.stats")


# ── synthetic venue payloads ────────────────────────────────────────────────────────────────

def venue_filters(tick="0.01", step="0.001", min_notional="5", *, legacy=False, extra=()):
    out = [{"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "100000", "tickSize": tick},
           {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "9000", "stepSize": step},
           {"filterType": "MARKET_LOT_SIZE", "minQty": "0", "maxQty": "500", "stepSize": "0"}]
    if legacy:
        out.append({"filterType": "MIN_NOTIONAL", "minNotional": min_notional, "applyToMarket": True,
                    "avgPriceMins": 5})
    else:
        out.append({"filterType": "NOTIONAL", "minNotional": min_notional, "applyMinToMarket": True,
                    "maxNotional": "9000000", "applyMaxToMarket": False, "avgPriceMins": 5})
    out.extend(extra)
    return out


def venue_entry(symbol, quote="USDT", status="TRADING", filters=None):
    return {"symbol": symbol, "status": status, "baseAsset": symbol[: -len(quote)] or symbol,
            "quoteAsset": quote, "permissions": ["SPOT"],
            "filters": venue_filters() if filters is None else filters}


def venue_ticker(symbol, last="1.5", qv="50000000", chg="3.0", close_time=T0, bid="1.49", ask="1.51"):
    t = {"symbol": symbol, "priceChange": "0.04", "priceChangePercent": chg, "weightedAvgPrice": last,
         "openPrice": "1.46", "highPrice": "1.6", "lowPrice": "1.4", "lastPrice": last,
         "volume": "1000", "quoteVolume": qv, "openTime": close_time - 86_400_000,
         "closeTime": close_time, "firstId": 1, "lastId": 9, "count": 9}
    if bid is not None:
        t["bidPrice"], t["askPrice"] = bid, ask
    return t


def base_payloads():
    info = {"timezone": "UTC", "serverTime": T0 + 250, "rateLimits": [], "exchangeFilters": [],
            "symbols": [venue_entry("AAAUSDT"), venue_entry("BBBBTC", quote="BTC", status="BREAK"),
                        venue_entry("CCCUSDT", filters=venue_filters(legacy=True)),
                        venue_entry("DDDUSDT", filters=venue_filters(
                            extra=[{"filterType": "PERCENT_PRICE_BY_SIDE", "bidMultiplierUp": "5"},
                                   {"filterType": "ICEBERG_PARTS", "limit": 10}]))]}
    tickers = [venue_ticker("AAAUSDT", close_time=T0 + 900), venue_ticker("BBBBTC", bid=None),
               venue_ticker("CCCUSDT", close_time=T0 + 800), venue_ticker("ZZZUSDT")]
    return info, tickers


def build(info=None, tickers=None, send=T0 - 100, recv=T0 + 100, stats_recv=T0 + 300):
    if info is None and tickers is None:
        info, tickers = base_payloads()
    return ms.build_snapshot(exchange_info=info, tickers_24h=tickers, listing_send_ms=send,
                             listing_recv_ms=recv, stats_recv_ms=stats_recv)


def assess(snap, decision, stale=60_000, clock=1_000):
    return ms.assess_snapshot(snap, decision_time_ms=decision, staleness_bound_ms=stale,
                              clock_offset_bound_ms=clock)


# ── flag ────────────────────────────────────────────────────────────────────────────────────

def test_flag_is_strict_off_by_default_and_on_needs_the_store(monkeypatch):
    assert ms.market_snapshot_shadow_mode({}) == "off"
    assert ms.market_snapshot_shadow_mode({"MARKET_SNAPSHOT_SHADOW": " On "}) == "on"
    for bad in ("true", "1", "yes", "", "shadow", "of", "enabled"):
        with pytest.raises(RuntimeError, match="unknown MARKET_SNAPSHOT_SHADOW"):
            ms.market_snapshot_shadow_mode({"MARKET_SNAPSHOT_SHADOW": bad})
    monkeypatch.setattr(config, "EVIDENCE_V2_ENABLED", False)
    assert ms.market_snapshot_shadow_enabled({"MARKET_SNAPSHOT_SHADOW": "off"}) is False
    with pytest.raises(RuntimeError, match="EVIDENCE_V2_ENABLED"):
        ms.market_snapshot_shadow_enabled({"MARKET_SNAPSHOT_SHADOW": "on"})
    assert ms.market_snapshot_shadow_enabled({"MARKET_SNAPSHOT_SHADOW": "on"}, require_store=False)
    monkeypatch.setattr(config, "EVIDENCE_V2_ENABLED", True)
    assert ms.market_snapshot_shadow_enabled({"MARKET_SNAPSHOT_SHADOW": "on"}) is True


def test_flag_is_not_a_config_field():
    """A Config field would enter evidence_v2's config_hash and move it with the flag off."""
    assert "MARKET_SNAPSHOT_SHADOW" not in {f.name for f in dataclasses.fields(config)}


@pytest.mark.parametrize("value", ["maybe", "1"])
def test_unknown_flag_refuses_before_any_io(value, monkeypatch):
    mod = load_service("scanner")
    db = FakeDB(lambda *a: [])
    db.install(monkeypatch)
    connected = []

    async def connect():
        connected.append(1)
    monkeypatch.setattr(mod.Database, "connect", connect)
    monkeypatch.setenv("FUNNEL_RECORDING", "off")
    monkeypatch.setenv("MARKET_SNAPSHOT_SHADOW", value)
    with pytest.raises(RuntimeError, match="MARKET_SNAPSHOT_SHADOW"):
        run_main(mod)
    assert connected == [] and db.calls == []


def test_module_top_level_imports_are_stdlib_only():
    tree = ast.parse((ROOT / "shared" / "market_snapshot.py").read_text(encoding="utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert top <= {"__future__", "dataclasses", "hashlib", "json", "os", "time", "types", "typing"}


# ── adapter: listing, filters, 24 h statistics ─────────────────────────────────────────────

def test_listing_filters_and_stats_use_glossary_names():
    snap = build()
    assert snap.source == ms.SOURCE and snap.venue == ms.VENUE and snap.complete
    assert set(snap.universe) == {"AAAUSDT", "BBBBTC", "CCCUSDT", "DDDUSDT"}
    assert dict(snap.universe["BBBBTC"]) == {"base_asset": "BBB", "quote_asset": "BTC", "status": "BREAK"}
    a = snap.filters["AAAUSDT"]
    assert (a["tick_size"], a["step_size"], a["min_notional"], a["max_notional"]) == ("0.01", "0.001", "5", "9000000")
    assert (a["apply_min_to_market"], a["apply_max_to_market"], a["market_max_qty"]) == ("true", "false", "500")
    assert a["unmodelled"] == "" and a["venue_filter_types"] == "LOT_SIZE,MARKET_LOT_SIZE,NOTIONAL,PRICE_FILTER"
    legacy = snap.filters["CCCUSDT"]
    assert legacy["min_notional"] == "5" and legacy["apply_min_to_market"] == "true"
    assert "max_notional" not in legacy
    assert snap.filters["DDDUSDT"]["unmodelled"] == "ICEBERG_PARTS,PERCENT_PRICE_BY_SIDE"
    raw = json.loads(snap.filters["DDDUSDT"]["venue_raw"])
    assert [r["filterType"] for r in raw] == sorted(r["filterType"] for r in raw) and len(raw) == 6
    s = snap.stats_24h["AAAUSDT"]
    assert set(s) == set(ms.STATS_FIELDS)
    assert (s["last_price"], s["quote_volume"], s["price_change_pct"], s["close_time_ms"]) == \
        ("1.5", "50000000", "3.0", str(T0 + 900))
    assert snap.book["AAAUSDT"] == ("1.49", "1.51") and "BBBBTC" not in snap.book
    assert snap.book_source == "ticker_24h"
    assert "ZZZUSDT" not in snap.stats_24h            # outside the listing: counted, not kept
    assert dict(snap.counts) == {"listed": 4, "with_stats": 3, "listed_without_stats": 1,
                                 "stats_without_listing": 1, "listing_entries_unreadable": 0,
                                 "stats_entries_unreadable": 0, "filter_sets_unreadable": 0,
                                 "filter_entries_unreadable": 0}
    assert set(ms.FILTER_KEYS) >= {k for f in snap.filters.values() for k in f} - {
        "venue_filter_types", "unmodelled", "venue_raw"}


def test_notional_takes_precedence_over_legacy_min_notional():
    both = venue_filters(min_notional="10") + [{"filterType": "MIN_NOTIONAL", "minNotional": "1",
                                                "applyToMarket": False}]
    info = {"serverTime": T0, "symbols": [venue_entry("AAAUSDT", filters=both)]}
    f = build(info, [venue_ticker("AAAUSDT")]).filters["AAAUSDT"]
    assert f["min_notional"] == "10" and f["apply_min_to_market"] == "true"


def test_filters_feed_the_existing_exchange_rules_validator():
    """The glossary keys are ``shared/exchange_rules.SymbolFilters`` fields (reuse, no duplicate
    validator). Imported here only: production code never imports the A47 module."""
    from shared.exchange_rules import SymbolFilters, check_order
    f = build().filters["AAAUSDT"]
    kw = {k: (f[k] == "true") if k.startswith("apply_") else f[k] for k in ms.FILTER_KEYS if k in f}
    sf = SymbolFilters(symbol="AAAUSDT", **kw)
    assert check_order(sf, side="BUY", order_type="LIMIT", price="1.50", quantity="10").valid
    bad = check_order(sf, side="BUY", order_type="LIMIT", price="1.505", quantity="1")
    assert set(bad.reasons) == {"PRICE_FILTER:tick_size", "NOTIONAL:min_notional"}


def test_inputs_are_not_modified_and_the_snapshot_is_immutable():
    info, tickers = base_payloads()
    keep = copy.deepcopy((info, tickers))
    snap = build(info, tickers)
    assert (info, tickers) == keep
    info["symbols"][0]["filters"][0]["tickSize"] = "9"
    assert snap.filters["AAAUSDT"]["tick_size"] == "0.01"
    with pytest.raises(TypeError):
        snap.filters["AAAUSDT"]["tick_size"] = "1"
    with pytest.raises(TypeError):
        snap.universe["NEW"] = {}
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.as_of = 1


# ── hashes ──────────────────────────────────────────────────────────────────────────────────

def test_identical_inputs_hash_identically_and_order_does_not_matter():
    a, b = build(), build()
    assert a == b and a.content_hash == b.content_hash and len(a.content_hash) == 64
    info, tickers = base_payloads()
    info["symbols"].reverse()
    for e in info["symbols"]:
        e["filters"].reverse()
    tickers.reverse()
    c = build(info, tickers)
    assert (c.listing_hash, c.stats_hash, c.content_hash) == (a.listing_hash, a.stats_hash, a.content_hash)


def _edit(path, value):
    info, tickers = base_payloads()
    target = {"info": info, "tickers": tickers}
    *keys, last = path
    node = target
    for k in keys:
        node = node[k]
    node[last] = value
    return info, tickers


@pytest.mark.parametrize("path,value,moves", [
    (("info", "symbols", 0, "filters", 0, "tickSize"), "0.001", "listing"),
    (("info", "symbols", 0, "status"), "BREAK", "listing"),
    (("info", "symbols", 1, "quoteAsset"), "ETH", "listing"),
    (("tickers", 0, "quoteVolume"), "49999999", "stats"),
    (("tickers", 0, "bidPrice"), "1.48", "stats"),
    (("info", "serverTime"), T0 + 251, "header"),
])
def test_every_input_change_moves_the_content_hash(path, value, moves):
    base = build()
    snap = build(*_edit(path, value))
    assert snap.content_hash != base.content_hash
    assert (snap.listing_hash != base.listing_hash) == (moves == "listing")
    assert (snap.stats_hash != base.stats_hash) == (moves == "stats")


def test_clock_readings_enter_the_content_hash():
    assert build(send=T0 - 101).content_hash != build().content_hash


# ── as_of and clock offset ──────────────────────────────────────────────────────────────────

def test_as_of_is_venue_time_and_offset_is_measured_around_the_listing():
    snap = build()
    assert snap.as_of_basis == "venue" and snap.as_of == T0 + 250       # min(serverTime, stats close)
    assert snap.stats_as_of == T0 + 900
    assert (snap.clock.offset_ms, snap.clock.round_trip_ms) == (250, 200)
    assert ms.venue_time_ms(T0 + 1_000, snap) == T0 + 1_250
    info, tickers = base_payloads()
    early = [venue_ticker("AAAUSDT", close_time=T0 + 10)]
    assert build(info, early).as_of == T0 + 10                            # oldest part wins


def test_without_venue_time_as_of_is_host_time_and_offset_unknown():
    info, tickers = base_payloads()
    del info["serverTime"]
    snap = build(info, tickers)
    assert snap.as_of_basis == "host" and snap.as_of == T0 + 100 and snap.clock.offset_ms is None
    assert ms.venue_time_ms(T0, snap) is None
    assert assess(snap, T0 + 100) == ("F0.clock_offset_exceeded",)


@pytest.mark.parametrize("offset,want", [(1_000, ()), (-1_000, ()),
                                         (1_001, ("F0.clock_offset_exceeded",)),
                                         (-1_001, ("F0.clock_offset_exceeded",))])
def test_clock_offset_on_both_sides_of_its_bound(offset, want):
    info, tickers = base_payloads()
    info["serverTime"] = T0 + offset                 # host midpoint is T0
    snap = build(info, [venue_ticker("AAAUSDT", close_time=T0 + 5_000)])
    assert snap.clock.offset_ms == offset
    assert assess(snap, snap.as_of + 10, clock=1_000) == want


def test_staleness_bound_is_exclusive_and_future_snapshots_fail_closed():
    snap = build()
    assert assess(snap, snap.as_of + 60_000) == ()
    assert assess(snap, snap.as_of + 60_001) == ("F0.snapshot_stale",)
    assert assess(snap, snap.as_of - 1_000) == ()
    assert assess(snap, snap.as_of - 1_001) == ("F0.clock_offset_exceeded",)


def test_bounds_are_required_inputs_without_defaults():
    snap = build()
    with pytest.raises(TypeError):
        ms.assess_snapshot(snap, decision_time_ms=T0)
    with pytest.raises(TypeError):
        ms.admit_for_f1(snap, decision_time_ms=T0, staleness_bound_ms=1)
    for bad in (0, -1, True, 1.5, "60000", None):
        with pytest.raises(ValueError):
            assess(snap, T0, stale=bad)
        with pytest.raises(ValueError):
            assess(snap, T0, clock=bad)
    with pytest.raises(ValueError):
        assess(snap, float(T0))


# ── stale and partial snapshots never reach F1 ──────────────────────────────────────────────

def _partials():
    info, tickers = base_payloads()
    dup = copy.deepcopy(info)
    dup["symbols"].append(venue_entry("AAAUSDT"))
    odd = copy.deepcopy(info)
    odd["symbols"].append({"status": "TRADING"})
    return {"listing_missing": (None, tickers), "stats_missing": (info, None),
            "listing_unreadable": ({"serverTime": T0}, tickers),
            "stats_unreadable": (info, "oops"),
            "listing_duplicate_symbol": (dup, tickers), "listing_entry_unreadable": (odd, tickers),
            "stats_entry_unreadable": (info, tickers + [["not", "a", "ticker"]])}


@pytest.mark.parametrize("reason", sorted(_partials()))
def test_partial_snapshot_is_incomplete_and_never_admitted(reason):
    info, tickers = _partials()[reason]
    snap = build(info, tickers)
    assert snap.completeness == "incomplete" and reason in snap.incomplete_reasons
    adm = ms.admit_for_f1(snap, decision_time_ms=snap.as_of + 1, staleness_bound_ms=60_000,
                          clock_offset_bound_ms=10_000)
    assert not adm.admitted and adm.snapshot is None and "F0.snapshot_incomplete" in adm.reason_codes
    assert adm.content_hash == snap.content_hash


def test_stale_snapshot_is_never_admitted_and_a_fresh_one_is():
    snap = build()
    stale = ms.admit_for_f1(snap, decision_time_ms=snap.as_of + 60_001, staleness_bound_ms=60_000,
                            clock_offset_bound_ms=1_000)
    assert (stale.admitted, stale.snapshot, stale.reason_codes) == (False, None, ("F0.snapshot_stale",))
    fresh = ms.admit_for_f1(snap, decision_time_ms=snap.as_of + 5, staleness_bound_ms=60_000,
                            clock_offset_bound_ms=1_000)
    assert fresh.admitted and fresh.snapshot is snap and fresh.reason_codes == ()


def test_unreadable_filter_entries_are_counted_per_symbol_not_trusted():
    bad = [{"tickSize": "0.1"}, "x", {"filterType": "PRICE_FILTER", "tickSize": "0.1"}]
    info = {"serverTime": T0, "symbols": [venue_entry("AAAUSDT", filters=bad),
                                          venue_entry("BBBUSDT", filters="none")]}
    snap = build(info, [venue_ticker("AAAUSDT"), venue_ticker("BBBUSDT")])
    assert snap.counts["filter_entries_unreadable"] == 2 and snap.counts["filter_sets_unreadable"] == 1
    assert dict(snap.filters["AAAUSDT"])["tick_size"] == "0.1"
    assert "tick_size" not in snap.filters["BBBUSDT"]     # F1.filters_missing is F1's call (OF-T04)


# ── records round trip ──────────────────────────────────────────────────────────────────────

def test_recorded_payloads_rebuild_the_same_snapshot_and_refuse_tampering():
    snap = build()
    header = dict(snap.header(), content_hash=snap.content_hash)
    listing, stats = json.loads(json.dumps(snap.listing_body())), json.loads(json.dumps(snap.stats_body()))
    again = ms.snapshot_from_records(header, listing, stats)
    assert again == snap
    for mutate, match in ((lambda h, l, s: l["filters"]["AAAUSDT"].update(tick_size="1"), "listing_hash"),
                          (lambda h, l, s: s["rows"][0].__setitem__(0, "9"), "stats_hash"),
                          (lambda h, l, s: h.update(as_of=h["as_of"] + 1), "content_hash")):
        h, l, s = copy.deepcopy((header, listing, stats))
        mutate(h, l, s)
        with pytest.raises(ValueError, match=match):
            ms.snapshot_from_records(h, l, s)


# ── P7: no venue field name outside the adapter ────────────────────────────────────────────

VENUE_NAMES = re.compile(r"\b(tickSize|stepSize|minNotional|maxNotional|minQty|maxQty|minPrice|maxPrice|"
                         r"filterType|applyToMarket|applyMinToMarket|applyMaxToMarket|serverTime|"
                         r"quoteVolume|priceChangePercent|lastPrice|quoteAsset|baseAsset|bidPrice|"
                         r"askPrice|highPrice|lowPrice|weightedAvgPrice|PRICE_FILTER|LOT_SIZE|"
                         r"MARKET_LOT_SIZE|get_exchange_info|get_ticker)\b")
# Live-path files that already held venue names at 6ae70a2 (pinned, or other owners): reported for
# a later P7 migration onto this adapter; no new file may join them.
PRE_EXISTING = {"scanner/scanner_logic.py", "shared/funnel_hooks.py", "shared/exchange_rules.py",
                "shared/position_state.py", "trade_tracker/main.py", "analyzer/backtest_volume_rsi_mtf.py"}


def test_the_hook_holds_no_venue_field_name():
    assert not VENUE_NAMES.search((ROOT / "scanner" / "main.py").read_text(encoding="utf-8"))
    assert VENUE_NAMES.search((ROOT / "shared" / "market_snapshot.py").read_text(encoding="utf-8"))


def test_no_new_live_path_file_holds_a_venue_field_name():
    found = set()
    for sub in ("scanner", "signal_engine", "analyzer", "shared", "trade_tracker", "telegram"):
        for p in (ROOT / sub).glob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            if rel != "shared/market_snapshot.py" and VENUE_NAMES.search(p.read_text(errors="ignore")):
                found.add(rel)
    assert found <= PRE_EXISTING, sorted(found - PRE_EXISTING)


# ── the real scanner loop: fakes ────────────────────────────────────────────────────────────

def scenario(seed):
    rng = random.Random(seed)
    entries, tickers = [], []
    for i in range(rng.randint(0, 30)):
        quote = rng.choice(["USDT", "USDT", "USDT", "BTC"])
        symbol = f"C{i:03d}{quote}" if rng.random() > 0.05 else f"币{i:03d}USDT"
        entries.append(venue_entry(symbol, quote="USDT" if symbol.endswith("USDT") else quote,
                                   status=rng.choice(["TRADING"] * 4 + ["BREAK"]),
                                   filters=venue_filters(legacy=rng.random() < 0.3)))
        if rng.random() < 0.9:
            tickers.append(venue_ticker(symbol, qv=rng.choice(["1000000", "50000000", "bad"]),
                                        chg=f"{rng.uniform(-8, 8):.3f}", last=rng.choice(["1.5", "0.2"]),
                                        bid=rng.choice([None, "1.4"])))
    tickers.append(venue_ticker("ORPHANUSDT"))
    info = {"serverTime": T0, "symbols": entries}
    if rng.random() < 0.2:
        del info["serverTime"]
    names = [e["symbol"] for e in entries]
    return {"info": info, "tickers": tickers,
            "blacklist": rng.sample(names, min(len(names), rng.randint(0, 3))),
            "btc_change": rng.choice([-5.0, 0.0, 2.0]), "paused": rng.random() < 0.1,
            "ticker_error_cycle": 2 if rng.random() < 0.2 else None}


class VenueClient:
    """Synthetic client; ``log`` records every exchange call, in order."""

    def __init__(self, sc, log):
        self.sc, self.log, self.cycle = sc, log, 0

    async def get_exchange_info(self):
        self.cycle += 1
        self.log.append(("exchange_info",))
        return copy.deepcopy(self.sc["info"])

    async def get_ticker(self):
        self.log.append(("ticker_24h",))
        if self.sc.get("ticker_error_cycle") == self.cycle:
            raise ConnectionError("synthetic")
        return copy.deepcopy(self.sc["tickers"])

    async def get_klines(self, symbol, interval, limit):
        self.log.append(("klines", symbol, interval, limit))
        now = int(time.time() * 1000)
        rows = []
        for i in range(limit):
            close = 100 * (1 + self.sc["btc_change"] / 100 * i / (limit - 2)) if i < limit - 1 else 100.0
            o = now - (limit - i + 1) * H4
            rows.append([o, "1", "1", "1", f"{close:.6f}", "1", o + H4 - 1, "1", 1, "1", "1", "0"])
        return rows

    async def close_connection(self):
        self.log.append(("close",))


def run_scanner(monkeypatch, mod, sc, *, snapshot, funnel=False, cycles=2, clock=None):
    rec = set_recording(monkeypatch, "scanner", funnel)        # also FUNNEL_RECORDING and the store
    monkeypatch.setenv("MARKET_SNAPSHOT_SHADOW", "on" if snapshot else "off")

    def boom(*a, **k):
        raise AssertionError("tap built with its flag off")
    real_snapshot_tap = ms.SnapshotShadowTap
    monkeypatch.setattr(ms, "SnapshotShadowTap", boom if not snapshot else (
        (lambda scanner: real_snapshot_tap(scanner, clock_ms=clock)) if clock else real_snapshot_tap))
    if not funnel:
        monkeypatch.setattr(fh, "ScannerTap", boom)
    logic = sys.modules[mod.BinanceScanner.__module__]

    def route(kind, sql, args):
        return [{"symbol": s} for s in sc["blacklist"]] if "symbol_blacklist" in sql else []
    db = FakeDB(route)
    db.install(monkeypatch)
    health = Health()
    health.install(monkeypatch, mod)
    log, made = [], []

    class _Factory:
        @staticmethod
        async def create(**kw):
            return VenueClient(sc, log)
    monkeypatch.setattr(mod, "AsyncClient", _Factory)
    real_scanner = mod.BinanceScanner

    def scanner_factory(client):
        made.append(real_scanner(client))
        return made[-1]
    monkeypatch.setattr(mod, "BinanceScanner", scanner_factory)

    async def pause():
        return (True, "manual") if sc["paused"] else (False, None)
    monkeypatch.setattr(logic, "get_pause_state", pause)

    async def maintenance():
        return {"expired": 0}
    monkeypatch.setattr(mod, "maintain_pipeline", maintenance)
    run_main(mod, cycles=cycles)
    out = {"db": db, "health": health, "log": log, "rec": rec, "scanner": made[0] if made else None}
    monkeypatch.setattr(ms, "SnapshotShadowTap", real_snapshot_tap)
    return out


def db_trace(db):
    """Every database call in order; ``scan_time`` is the pinned code's own wall clock."""
    out = []
    for kind, sql, args in db.calls:
        if kind == "executemany":
            args = [(a[0], {k: v for k, v in json.loads(a[1]).items() if k != "scan_time"}) for a in args]
        out.append((kind, sql, args))
    return json.dumps(out, sort_keys=True, default=str)


def heartbeats(health, drop=("market_snapshot",)):
    out = []
    for c in health.calls:
        if c[0] == "success":
            c = (c[0], c[1], {k: v for k, v in c[2].items() if k not in drop})
        out.append(c)
    return out


def funnel_view(rec):
    """Funnel events without their wall-clock identities (cycle ids carry the host time, and the
    store orders records by an id derived from them, so records compare as a sorted list)."""
    out = []
    for e in events(rec):
        if not e["event_type"].startswith("funnel."):
            continue
        p = e["payload"]
        if e["event_type"] == "funnel.cycle":
            out.append(("cycle", p["valid"], p["record_count"], json.dumps(p["report"].get("stage_counts"))))
        else:
            out.append((e["event_type"], p.get("reason_code"), p.get("symbol")))
    return sorted(out, key=repr)


@pytest.fixture(scope="module")
def before_main(tmp_path_factory):
    try:
        src = subprocess.run(["git", "show", f"{BASE_COMMIT}:scanner/main.py"], cwd=ROOT,
                             capture_output=True, text=True, check=True, timeout=30).stdout
    except Exception as exc:                                    # pragma: no cover
        pytest.skip(f"pre-change source unavailable ({BASE_COMMIT}:scanner/main.py): {exc}")
    assert "market_snapshot" not in src and "MARKET_SNAPSHOT" not in src
    load_service("scanner")                                     # sys.path for scanner_logic
    target = tmp_path_factory.mktemp("before_scanner") / "scanner_main_6ae70a2.py"
    target.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("wp_b03_scanner_main_before", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def after_main():
    return load_service("scanner")


@pytest.fixture(autouse=True)
def _reset_store():
    ev2.reset_for_tests()
    yield
    ev2.reset_for_tests()


# ── before/after parity against 6ae70a2 ────────────────────────────────────────────────────

@pytest.mark.parametrize("funnel", [False, True])
@pytest.mark.parametrize("seed", range(12))
def test_flag_off_is_identical_to_6ae70a2(seed, funnel, monkeypatch, before_main, after_main):
    sc = scenario(seed)
    old = run_scanner(monkeypatch, before_main, sc, snapshot=False, funnel=funnel)
    new = run_scanner(monkeypatch, after_main, sc, snapshot=False, funnel=funnel)
    assert db_trace(new["db"]) == db_trace(old["db"])
    assert new["log"] == old["log"]                              # exchange calls
    assert new["health"].calls == old["health"].calls            # heartbeats, unfiltered
    assert funnel_view(new["rec"]) == funnel_view(old["rec"])
    assert not [e for e in events(new["rec"]) if e["event_type"] in SNAP_EVENTS]
    if not funnel:                                               # no wrapper on the instance
        assert type(new["scanner"].client) is VenueClient
        assert set(vars(new["scanner"])) == set(vars(old["scanner"])) == {"client", "btc_trend"}


@pytest.mark.parametrize("funnel", [False, True])
@pytest.mark.parametrize("seed", range(12))
def test_flag_on_changes_no_decision_call_or_read(seed, funnel, monkeypatch, before_main, after_main):
    sc = scenario(seed)
    old = run_scanner(monkeypatch, before_main, sc, snapshot=False, funnel=funnel)
    new = run_scanner(monkeypatch, after_main, sc, snapshot=True, funnel=funnel)
    assert db_trace(new["db"]) == db_trace(old["db"])           # no extra read or write
    assert new["log"] == old["log"]                              # no new exchange call
    assert heartbeats(new["health"]) == old["health"].calls
    assert funnel_view(new["rec"]) == funnel_view(old["rec"])
    cycles = [e["payload"] for e in events(new["rec"], "market_snapshot.cycle")]
    scanned = sum(1 for c in old["log"] if c == ("exchange_info",))
    assert len(cycles) == scanned
    snaps = [h[2]["market_snapshot"] for h in new["health"].calls if h[0] == "success"]
    assert all(s["tap_failures"] == 0 and s["not_recorded"] == 0 for s in snaps)
    if funnel:
        assert all(e["payload"]["valid"] for e in events(new["rec"], "funnel.cycle"))


def test_recorded_snapshot_equals_the_adapter_on_what_the_scanner_fetched(monkeypatch, after_main):
    sc = scenario(3)
    sc.update(paused=False, ticker_error_cycle=None)
    sc["info"]["serverTime"] = T0
    ticks = iter(range(T0 - 50, T0 + 10_000, 10))
    new = run_scanner(monkeypatch, after_main, sc, snapshot=True, cycles=2, clock=lambda: next(ticks))
    cyc = [e["payload"] for e in events(new["rec"], "market_snapshot.cycle")]
    listing = [e["payload"] for e in events(new["rec"], "market_snapshot.listing")]
    stats = [e["payload"] for e in events(new["rec"], "market_snapshot.stats")]
    assert len(cyc) == 2 and len(listing) == 1 and len(stats) == 1    # unchanged bodies: once
    for header in cyc:
        assert header["outcome"] == "scanned" and header["completeness"] == "complete"
        c = header["clock"]
        want = ms.build_snapshot(exchange_info=sc["info"], tickers_24h=sc["tickers"],
                                 listing_send_ms=c["host_send_ms"], listing_recv_ms=c["host_recv_ms"],
                                 stats_recv_ms=None)
        assert header["content_hash"] == want.content_hash
        assert ms.snapshot_from_records(header, listing[0], stats[0]).content_hash == want.content_hash
        assert c["offset_ms"] == T0 - (c["host_send_ms"] + c["host_recv_ms"]) // 2
    assert cyc[0]["content_hash"] != cyc[1]["content_hash"]          # clock readings differ
    hb = [h[2]["market_snapshot"] for h in new["health"].calls if h[0] == "success"]
    assert hb[-1]["listing_recorded"] == 1 and hb[-1]["listing_unchanged"] == 1
    assert hb[-1]["last_content_hash"] == cyc[-1]["content_hash"]


def test_failed_scan_records_an_incomplete_snapshot_and_fails_as_before(monkeypatch, before_main,
                                                                         after_main):
    sc = scenario(5)
    sc.update(paused=False, ticker_error_cycle=1)
    old = run_scanner(monkeypatch, before_main, sc, snapshot=False)
    new = run_scanner(monkeypatch, after_main, sc, snapshot=True)
    assert db_trace(new["db"]) == db_trace(old["db"]) and new["log"] == old["log"]
    assert heartbeats(new["health"]) == old["health"].calls
    assert ("failure", "scanner", "ConnectionError") in new["health"].calls
    first = events(new["rec"], "market_snapshot.cycle")[0]["payload"]
    assert (first["outcome"], first["error"], first["completeness"]) == ("scan_failed", "ConnectionError",
                                                                        "incomplete")
    assert "stats_missing" in first["incomplete_reasons"]


def test_broken_store_or_adapter_never_changes_decisions(monkeypatch, before_main, after_main):
    sc = scenario(7)
    sc.update(paused=False, ticker_error_cycle=None)
    old = run_scanner(monkeypatch, before_main, sc, snapshot=False)

    def explode(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(ev2, "emit", explode)
    broken_store = run_scanner(monkeypatch, after_main, sc, snapshot=True)
    monkeypatch.undo()
    monkeypatch.setattr(ms, "build_snapshot", explode)
    broken_adapter = run_scanner(monkeypatch, after_main, sc, snapshot=True)
    for new, key in ((broken_store, "not_recorded"), (broken_adapter, "tap_failures")):
        assert db_trace(new["db"]) == db_trace(old["db"]) and new["log"] == old["log"]
        assert heartbeats(new["health"]) == old["health"].calls
        assert [h[2]["market_snapshot"][key] for h in new["health"].calls if h[0] == "success"][-1] > 0


def test_paused_cycles_request_nothing_and_record_nothing(monkeypatch, after_main):
    sc = scenario(1)
    sc["paused"] = True
    new = run_scanner(monkeypatch, after_main, sc, snapshot=True)
    assert [c for c in new["log"] if c != ("close",)] == []
    assert not [e for e in events(new["rec"]) if e["event_type"] in SNAP_EVENTS]
    hb = [h[2]["market_snapshot"] for h in new["health"].calls if h[0] == "success"]
    assert hb[-1]["not_scanned"] == 2 and hb[-1]["snapshots"] == 0


def test_proxy_returns_the_same_objects_and_raises_the_same_errors():
    class Inner:
        def __init__(self):
            self.info, self.tickers = {"symbols": []}, []

        async def get_exchange_info(self):
            return self.info

        async def get_ticker(self, **kw):
            if kw:
                raise KeyError("one-symbol request")
            return self.tickers

    class Holder:
        pass
    holder = Holder()
    holder.client = inner = Inner()
    tap = ms.SnapshotShadowTap(holder, emit=lambda *a, **k: True, clock_ms=lambda: T0)

    async def go():
        tap.begin()
        assert await holder.client.get_exchange_info() is inner.info
        assert await holder.client.get_ticker() is inner.tickers
        with pytest.raises(KeyError):
            await holder.client.get_ticker(symbol="AAAUSDT")
        return tap.end([])
    snap = asyncio.run(go())
    assert snap is not None and snap.as_of_basis == "host" and snap.counts["listed"] == 0
    assert tap.end() is None                                     # second end of a cycle: no-op
