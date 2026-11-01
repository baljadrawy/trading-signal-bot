"""WP-B01 integration: funnel records from the real scanner, analyzer and signal_engine loops.

Synthetic fakes only (tests/funnel_service_harness.py): no network, database or docker. The
central property: with FUNNEL_RECORDING off or on, every database call, saved signal and
heartbeat (minus its added 'funnel' entry) is identical, and the recording is conserved.
"""
import copy
import json
import os
import random
import sys
import time

import pytest

from funnel_service_harness import (FakeDB, Health, events, load_service, run_main,
                                    set_recording)
from shared import evidence_v2 as ev2
from shared import funnel_hooks as fh
from shared.config import config
from shared.funnel_flags import funnel_recording_enabled, funnel_recording_mode

H4 = 14_400_000


# ── flag ────────────────────────────────────────────────────────────────────────────────────

def test_flag_is_strict_off_by_default_and_on_needs_the_store(monkeypatch):
    assert funnel_recording_mode({}) == "off"
    assert funnel_recording_mode({"FUNNEL_RECORDING": " ON "}) == "on"
    for bad in ("true", "1", "yes", "", "enabled", "of"):
        with pytest.raises(RuntimeError, match="unknown FUNNEL_RECORDING"):
            funnel_recording_mode({"FUNNEL_RECORDING": bad})
    monkeypatch.setattr(config, "EVIDENCE_V2_ENABLED", False)
    assert funnel_recording_enabled({"FUNNEL_RECORDING": "off"}) is False
    with pytest.raises(RuntimeError, match="EVIDENCE_V2_ENABLED"):
        funnel_recording_enabled({"FUNNEL_RECORDING": "on"})
    assert funnel_recording_enabled({"FUNNEL_RECORDING": "on"}, require_store=False) is True
    monkeypatch.setattr(config, "EVIDENCE_V2_ENABLED", True)
    assert funnel_recording_enabled({"FUNNEL_RECORDING": "on"}) is True


@pytest.mark.parametrize("service", ["scanner", "analyzer", "signal_engine"])
def test_unknown_flag_refuses_before_any_io(service, monkeypatch):
    mod = load_service(service)
    db = FakeDB(lambda *a: [])
    db.install(monkeypatch)
    connected = []

    async def connect():
        connected.append(1)
    monkeypatch.setattr(mod.Database, "connect", connect)
    monkeypatch.setenv("FUNNEL_RECORDING", "maybe")
    with pytest.raises(RuntimeError, match="FUNNEL_RECORDING"):
        run_main(mod)
    assert connected == [] and db.calls == []


def test_flag_is_not_a_config_field():
    """A Config field would enter evidence_v2's config_hash and move it with the flag off."""
    import dataclasses
    names = {f.name for f in dataclasses.fields(config)}
    assert not {"FUNNEL_RECORDING", "SELECTION_POLICY", "SELECTION_VERSION", "SELECTION_SCORE_KEY"} & names


def test_strategy_ids_are_the_declared_family_ids():
    from shared.strategy_identity import CURRENT_FAMILY_IDS
    assert tuple(fh.STRATEGY_BY_TRADE_TYPE.values()) == CURRENT_FAMILY_IDS


def test_engine_label_map_uses_only_documented_mappings():
    assert fh.engine_label_code("no_trade_setup") == ("F4", "F4.no_setup", "strategy.entry")
    assert fh.engine_label_code("symbol_cooldown") == ("F4", "F4.cooldown_active", None)
    assert fh.engine_label_code("order_book_unavailable") == ("F2", "F2.book_unavailable", None)
    assert fh.engine_label_code("spread_invalid") == ("F2", "F2.spread_invalid", None)
    assert fh.engine_label_code("spread_exceeds_limit") == ("F2", "F2.spread_above_limit", None)
    assert fh.engine_label_code("stop_rejected:structural_risk_exceeds_cap") == (
        "F5", "F5.stop_risk_above_cap", "strategy.geometry")
    assert fh.engine_label_code("stop_rejected:risk_exceeds_cap") == (
        "F5", "F5.stop_invalid:risk_exceeds_cap", "strategy.geometry")
    assert fh.engine_label_code("not_selected_capacity") == ("F6", "F6.rank_below_cap", None)
    assert fh.engine_label_code("duplicate_setup_key") == ("F4", "F4.duplicate_setup", "shared.identity")
    assert fh.engine_label_code("superseded_by_newer_candle") == ("F4", "F4.bar_stale", "shared.identity")
    for unmapped in ("open_trade_exists", "learned_gate_throttled", "macro_block",
                     "safety_state_unverified:open_positions", "stop_rejected:Bad Reason", None, ""):
        assert fh.engine_label_code(unmapped) is None, unmapped


# ── scanner (F0-F2) ─────────────────────────────────────────────────────────────────────────

def scanner_scenario(seed):
    rng = random.Random(seed)
    entries, tickers, used = [], [], set()
    for i in range(rng.randint(0, 50)):
        quote = rng.choice(["USDT", "USDT", "USDT", "BTC"])
        symbol = f"C{i:03d}{quote}"
        roll = rng.random()
        if roll < 0.05 and "USDCUSDT" not in used:
            symbol, quote = "USDCUSDT", "USDT"
        elif roll < 0.10:
            symbol = f"币{i:03d}USDT"
            quote = "USDT"
        used.add(symbol)
        entries.append({"symbol": symbol, "quoteAsset": quote,
                        "status": rng.choice(["TRADING"] * 4 + ["BREAK"])})
        if rng.random() < 0.9:
            tickers.append({"symbol": symbol,
                            "quoteVolume": rng.choice(["1000000", "50000000", "200000000", "bad"]),
                            "priceChangePercent": f"{rng.uniform(-8, 8):.3f}",
                            "lastPrice": rng.choice(["1.5", "0.2"]), "highPrice": "2", "lowPrice": "1"})
    names = [e["symbol"] for e in entries]
    return {"entries": entries, "tickers": tickers,
            "blacklist": rng.sample(names, min(len(names), rng.randint(0, 4))),
            "btc_change": rng.choice([-5.0, -2.0, 0.0, 2.0, 5.0]),
            "paused": rng.random() < 0.08}


class _ScannerClient:
    def __init__(self, sc):
        self.sc = sc

    async def get_exchange_info(self):
        return copy.deepcopy({"symbols": self.sc["entries"]})

    async def get_ticker(self):
        return copy.deepcopy(self.sc["tickers"])

    async def get_klines(self, symbol, interval, limit):
        now = int(time.time() * 1000)
        start = 100.0
        rows = []
        for i in range(limit):
            close = start * (1 + self.sc["btc_change"] / 100 * i / (limit - 2)) if i < limit - 1 else start
            o = now - (limit - i + 1) * H4
            rows.append([o, "1", "1", "1", f"{close:.6f}", "1", o + H4 - 1, "1", 1, "1", "1", "0"])
        return rows

    async def close_connection(self):
        return None


def _scanner_env(monkeypatch, sc):
    mod = load_service("scanner")
    logic = sys.modules[mod.BinanceScanner.__module__]

    def route(kind, sql, args):
        if "symbol_blacklist" in sql:
            return [{"symbol": s} for s in sc["blacklist"]]
        return []
    db = FakeDB(route)
    db.install(monkeypatch)
    health = Health()
    health.install(monkeypatch, mod)

    class _Factory:
        @staticmethod
        async def create(**kw):
            return _ScannerClient(sc)
    monkeypatch.setattr(mod, "AsyncClient", _Factory)

    async def pause():
        return (True, "manual") if sc["paused"] else (False, None)
    monkeypatch.setattr(logic, "get_pause_state", pause)

    async def maintenance():
        return {"expired": 0}
    monkeypatch.setattr(mod, "maintain_pipeline", maintenance)
    return mod, db, health


def _run_scanner(monkeypatch, sc, on, cycles=2):
    rec = set_recording(monkeypatch, "scanner", on)
    if not on:
        def boom(*a, **k):
            raise AssertionError("ScannerTap built with FUNNEL_RECORDING=off")
        monkeypatch.setattr(fh, "ScannerTap", boom)
    mod, db, health = _scanner_env(monkeypatch, sc)
    run_main(mod, cycles=cycles)
    if not on:
        monkeypatch.undo()
    return db, health, rec


@pytest.mark.parametrize("seed", range(25))
def test_scanner_decisions_identical_off_and_on_and_conserved(seed, monkeypatch):
    sc = scanner_scenario(seed)
    db_off, h_off, rec_off = _run_scanner(monkeypatch, sc, on=False)
    off_events = events(rec_off)
    db_on, h_on, rec_on = _run_scanner(monkeypatch, sc, on=True)
    def writes(db):                       # scan_time is the pinned code's own wall clock: dropped
        out = []
        for kind, sql, args in db.calls:
            if kind in ("execute", "executemany"):
                out.append((kind, sql, [(s, {k: v for k, v in json.loads(d).items() if k != "scan_time"})
                                        for s, d in args]))
        return out
    assert writes(db_on) == writes(db_off)                                 # candidates saved
    assert h_on.without_funnel() == h_off.without_funnel()
    reads_off = [c for c in db_off.calls if c[0] == "fetch"]
    reads_on = [c for c in db_on.calls if c[0] == "fetch"]
    bl = fh.ScannerTap.BLACKLIST_SQL                  # the only extra read: an ambiguous blacklist
    assert [c for c in reads_on if c[1] != bl] == [c for c in reads_off if c[1] != bl]
    assert 0 <= len(reads_on) - len(reads_off) <= 2
    assert [e for e in off_events if e["event_type"].startswith("funnel.")] == []
    cycles = [e["payload"] for e in events(rec_on, "funnel.cycle")]
    assert len(cycles) == 2
    for env in cycles:
        assert env["valid"], env["integration_failures"]
        assert env["report"]["conservation"]["ok"]
        if sc["paused"]:
            assert env["report"]["stage_counts"] == []
    if not sc["paused"]:
        first, second = cycles
        assert second["record_count"] == first["record_count"]
        f2 = {c["stage"]: c for c in first["report"]["stage_counts"]}
        saved = [c for c in db_on.calls if c[0] == "executemany"]
        assert f2["F0"]["n_in"] == len(sc["entries"])
        assert f2["F2"]["passed"] == (len(saved[0][2]) if saved else 0)
        # compaction: identical second cycle emits no new rejection events
        rejections = events(rec_on, "funnel.rejection")
        assert len(rejections) == first["record_count"]
        assert all(e["payload"]["series"]["compaction"] == "state_change_v1" for e in rejections)
    assert h_on.funnel_health()[-1]["not_recorded"] == 0


def test_scanner_codes_for_known_symbols(monkeypatch):
    sc = {"entries": [{"symbol": "AAAUSDT", "quoteAsset": "USDT", "status": "TRADING"},
                      {"symbol": "BBBBTC", "quoteAsset": "BTC", "status": "BREAK"},
                      {"symbol": "USDCUSDT", "quoteAsset": "USDT", "status": "TRADING"},
                      {"symbol": "CCCUSDT", "quoteAsset": "USDT", "status": "TRADING"},
                      {"symbol": "DDDUSDT", "quoteAsset": "USDT", "status": "TRADING"},
                      {"symbol": "EEEUSDT", "quoteAsset": "USDT", "status": "TRADING"},
                      {"symbol": "FFFUSDT", "quoteAsset": "USDT", "status": "TRADING"}],
          "tickers": [{"symbol": s, "quoteVolume": v, "priceChangePercent": m, "lastPrice": "1",
                       "highPrice": "1", "lowPrice": "1"}
                      for s, v, m in (("AAAUSDT", "50000000", "3"), ("CCCUSDT", "1000", "0.1"),
                                      ("EEEUSDT", "50000000", "2"))],
          "blacklist": ["DDDUSDT", "EEEUSDT"], "btc_change": 0.0, "paused": False}
    db, health, rec = _run_scanner(monkeypatch, sc, on=True, cycles=1)
    got = sorted((e["payload"]["symbol"], e["payload"]["reason_code"])
                 for e in events(rec, "funnel.rejection"))
    assert got == [("BBBBTC", "F1.quote_not_approved"), ("BBBBTC", "F1.status_not_trading"),
                   ("CCCUSDT", "F2.move_below_floor"), ("CCCUSDT", "F2.volume_below_floor"),
                   ("DDDUSDT", "F1.owner_excluded"), ("EEEUSDT", "F1.owner_excluded"),
                   ("FFFUSDT", "F2.volume_missing"), ("USDCUSDT", "F1.stable_or_pegged")]
    env = events(rec, "funnel.cycle")[0]["payload"]
    assert env["valid"] and [c["passed"] for c in env["report"]["stage_counts"]] == [7, 3, 1]


def test_scanner_series_close_when_a_rejection_stops(monkeypatch):
    service = fh.FunnelService("scanner", compact_stages=("F1",))
    rec = set_recording(monkeypatch, "scanner", True)
    for present in (True, False):
        cyc = service.begin(1_700_000_000_000)
        if present:
            cyc.add(stage="F1", scope="symbol", reason_code="F1.owner_excluded", rule_ref="r", symbol="XUSDT")
        cyc.count("F1", 1, 0 if present else 1)
        cyc.finish(close_series=True)
    closed = events(rec, "funnel.rejection_series_closed")
    assert len(closed) == 1 and closed[0]["payload"]["repeat_count"] == 1


class _StubScanner:
    """A scanner whose verdict disagrees with the reproduced rule (detects drift of the mirror)."""

    def __init__(self):
        self.client, self.btc_trend = None, "neutral"

    async def _get_usdt_pairs(self):
        return ["AAAUSDT"]

    async def _get_24h_tickers(self):
        return {"AAAUSDT": {"quoteVolume": "1", "priceChangePercent": "9", "lastPrice": "1"}}

    async def _passes_initial_filter(self, symbol, ticker):
        return True


def test_scanner_mirror_disagreement_is_counted_and_invalidates(monkeypatch):
    import asyncio
    rec = set_recording(monkeypatch, "scanner", True)
    stub = _StubScanner()
    tap = fh.ScannerTap(stub)

    async def cycle():
        tap.begin()
        tap._see("listing", {"symbols": [{"symbol": "AAAUSDT", "quoteAsset": "USDT", "status": "TRADING"}]})
        await stub._get_usdt_pairs()
        tickers = await stub._get_24h_tickers()
        verdict = await stub._passes_initial_filter("AAAUSDT", tickers["AAAUSDT"])
        return await tap.end([{"symbol": "AAAUSDT"}] if verdict else [])
    env = asyncio.run(cycle())
    assert env["valid"] is False and ["f2_mirror_mismatch", 1] in env["integration_failures"]


# ── analyzer (F4 bar/data) ──────────────────────────────────────────────────────────────────

FIXED_NOW = 1_767_225_600_000 + 7 * 86_400_000


def analyzer_scenario(seed):
    rng = random.Random(seed)
    kinds = [rng.choice(["ok", "ok", "short", "error"]) for _ in range(rng.randint(1, 4))]
    return [{"id": i + 1, "symbol": f"A{i:02d}USDT", "data": "{}", "kind": k} for i, k in enumerate(kinds)]


def _analyzer_env(monkeypatch, rows):
    from evidence_v2_fakes import synthetic_klines
    mod = load_service("analyzer")
    monkeypatch.setattr(ev2, "now_ms", lambda: FIXED_NOW)
    monkeypatch.setattr(config, "TIMEFRAMES", ["4h", "1d"])
    monkeypatch.setattr(config, "LIVE_LEARNING_MODE", True)
    klines = {}
    for row in rows:
        for tf in ("4h", "1d"):
            n = 230 if row["kind"] == "ok" else 120
            data, _ = synthetic_klines(tf, n_closed=n, seed=row["id"], now_ms=FIXED_NOW)
            klines[(row["symbol"], tf)] = data[:-1]                          # closed candles only

    class _Client:
        async def get_klines(self, symbol, interval, limit):
            kind = next(r["kind"] for r in rows if r["symbol"] == symbol)
            if kind == "error":
                raise ConnectionError("synthetic fetch failure")
            return klines[(symbol, interval)][-limit:]

        async def get_order_book(self, symbol, limit):
            return {"bids": [["99.9", "5"], ["99.8", "5"]], "asks": [["100.1", "5"], ["100.2", "5"]]}

        async def close_connection(self):
            return None

    class _Factory:
        @staticmethod
        async def create(**kw):
            return _Client()
    monkeypatch.setattr(mod, "AsyncClient", _Factory)

    def route(kind, sql, args):
        if "scan_candidates" in sql:
            return [{k: r[k] for k in ("id", "symbol", "data")} for r in rows]
        return []
    db = FakeDB(route)
    db.install(monkeypatch)
    health = Health()
    health.install(monkeypatch, mod)
    return mod, db, health


@pytest.mark.parametrize("seed", range(8))
def test_analyzer_writes_identical_off_and_on_and_drops_recorded(seed, monkeypatch):
    rows = analyzer_scenario(seed)
    out = {}
    for on in (False, True):
        rec = set_recording(monkeypatch, "analyzer", on)
        mod, db, health = _analyzer_env(monkeypatch, rows)
        run_main(mod, cycles=1)
        out[on] = (db.trace(), health.without_funnel(), rec)
    assert out[True][0] == out[False][0]
    assert out[True][1] == out[False][1]
    rec = out[True][2]
    env = events(rec, "funnel.cycle")[0]["payload"]
    assert env["valid"], env["integration_failures"]
    got = sorted((e["payload"]["symbol"], e["payload"]["timeframe"], e["payload"]["reason_code"])
                 for e in events(rec, "funnel.rejection"))
    want = sorted((r["symbol"], tf, "F4.history_insufficient" if r["kind"] == "short" else "F4.data_quality")
                  for r in rows if r["kind"] != "ok" for tf in ("4h", "1d"))
    assert got == want
    assert all(e["payload"]["strategy_id"] == fh.UNASSIGNED_STRATEGY_ID for e in events(rec, "funnel.rejection"))


def test_analyzer_timeout_and_unobserved_paths():
    service = fh.FunnelService("analyzer")
    tap = fh.AnalyzerTap(service)
    tap.begin()
    tap.written("AUSDT", "4h")
    rows = [{"symbol": "AUSDT"}, {"symbol": "BUSDT"}]
    env = tap.end(rows, [None, TimeoutError()], ["4h"])
    assert env["valid"] and service.last_records[0].detail["cause"] == "symbol_timeout"
    tap.begin()
    tap.timeframe_error("AUSDT", "4h", RuntimeError("db down"))
    env = tap.end([{"symbol": "AUSDT"}], [None], ["4h"])
    assert not env["valid"] and ["unmapped:persist_or_orderbook_error", 1] in env["integration_failures"]


# ── signal engine (F3-F6) ───────────────────────────────────────────────────────────────────

SE_TFS = ("15m", "4h", "1d")


def engine_scenario(seed):
    from evidence_v2_fakes import analysis_row
    rng = random.Random(seed)
    n_symbols = rng.choice([0, 3, 12, 40, 90, 110])
    rows = []
    for i in range(n_symbols):
        for tf in SE_TFS:
            if rng.random() < 0.85:
                row = analysis_row(f"S{i:03d}USDT", tf, rng.choice([None, "momentum", "reversion", "momentum"]),
                                   spread=rng.choice([None, round(rng.uniform(0, 0.4), 4)]),
                                   valid=rng.random() > 0.1, stop_valid=rng.choice([True, True, False, None]),
                                   entry=round(rng.uniform(0.5, 50), 4))
                row["analysis_data"]["total_score"] = round(rng.uniform(0, 8), 2)
                rows.append(row)
    rng.shuffle(rows)
    names = sorted({r["symbol"] for r in rows})
    return {"rows": rows, "cooldown": set(rng.sample(names, min(3, len(names)))),
            "open": set(rng.sample(names, min(2, len(names)))) if rng.random() < 0.2 else set(),
            "macro": rng.choice(["ok"] * 6 + ["btc", "stale"]),
            "volume": {s: rng.uniform(1e5, 1e7) for s in names}}


def legacy_order(rows):
    from shared.candidate_selection import production_query_window
    return production_query_window(rows, limit=10 ** 9)


class EngineMacro:
    def __init__(self, kind):
        self.kind = kind
        self._last_valid_ts = 0.0 if kind == "never" else time.time() - 60

    async def should_block_now(self):
        return self.kind != "ok"

    def data_is_fresh(self):
        return self.kind not in ("stale", "never")

    def macro_state_key(self):
        return "usdtd_flat"

    def snapshot(self):
        return {"macro_data_valid": self.data_is_fresh(), "macro_age_seconds": 60.0}

    def state(self):
        return {"btc_trend": "strong_bearish" if self.kind == "btc" else "neutral", "usdtd_trend": "flat"}


def _engine_env(monkeypatch, sc, extra_env=None):
    mod = load_service("signal_engine")
    logic = sys.modules["signal_logic"]
    for k, v in (extra_env or {}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config, "LIVE_LEARNING_MODE", True)
    monkeypatch.setattr(config, "ENABLE_EVIDENCE_RECORDER", False)
    monkeypatch.setattr(config, "LEARNING_GATES_ENABLED", False)
    monkeypatch.setattr(config, "SIGNAL_INTEGRITY_MODE", "off")
    ordered = legacy_order(sc["rows"])

    def route(kind, sql, args):
        if kind == "fetchval":
            return len(sc["rows"])
        if kind == "fetchrow":
            return None
        if "LIMIT 200" in sql:
            return copy.deepcopy(ordered[:200])
        if sql == mod._RANKED_CANDIDATES_SQL:
            return copy.deepcopy(sc["rows"])
        if sql == mod._FUNNEL_LEGACY_ORDER_SQL:
            return [{"symbol": r["symbol"], "timeframe": r["timeframe"],
                     "trade_type": r["analysis_data"].get("trade_type"),
                     "bar_close_ms": str(r["analysis_data"]["pit"]["candle_close_time_ms"])} for r in ordered]
        if "OFFSET" in sql:
            return [{"symbol": r["symbol"], "timeframe": r["timeframe"]} for r in ordered[200:700]]
        if "active_trades" in sql:
            return [{"symbol": s} for s in sorted(sc["open"])]
        return []
    db = FakeDB(route)
    db.install(monkeypatch)
    health = Health()
    health.install(monkeypatch, mod)
    saved = []

    async def save(self, signal):
        saved.append(json.dumps(signal, sort_keys=True, default=str))
        return 101

    async def cooldown(self):
        return set(sc["cooldown"])

    async def volume(self, symbol):
        return sc["volume"][symbol]

    async def thresholds(self):
        return 5.0, 2
    for n, f in (("save_signal", save), ("_get_symbol_cooldown_set", cooldown),
                 ("_get_volume_usdt", volume), ("_get_live_thresholds", thresholds)):
        monkeypatch.setattr(logic.SignalEngine, n, f)
    monkeypatch.setattr(mod, "MacroContext", lambda client: EngineMacro(sc["macro"]))

    class _Factory:
        @staticmethod
        async def create(*a, **kw):
            class _C:
                async def close_connection(self):
                    return None
            return _C()
    monkeypatch.setattr(mod, "AsyncClient", _Factory)
    return mod, db, health, saved


def run_engine(monkeypatch, sc, on, extra_env=None):
    rec = set_recording(monkeypatch, "signal_engine", on)
    if not on:
        def boom(*a, **k):
            raise AssertionError("SignalEngineTap built with FUNNEL_RECORDING=off")
        monkeypatch.setattr(fh, "SignalEngineTap", boom)
    mod, db, health, saved = _engine_env(monkeypatch, sc, extra_env)
    run_main(mod, cycles=1)
    result = {"trace": db.trace(exclude=(mod._FUNNEL_LEGACY_ORDER_SQL,)), "saved": list(saved),
              "health": health.without_funnel(), "rec": rec, "db": db, "mod": mod,
              "funnel_health": health.funnel_health()}
    monkeypatch.undo()
    return result


def _eligible_count(sc, rows):
    from shared.candidate_selection import EligibilityPolicy, normalize, select
    cands = [normalize(r, sc["volume"][r["symbol"]]) for r in rows]
    res = select(cands, policy=EligibilityPolicy(max_spread_pct=config.MAX_SPREAD_PCT),
                 ranker="production_parity", open_symbols=frozenset(sc["open"]),
                 cooldown=frozenset(sc["cooldown"]))
    return len(res.ranked), res.selected


@pytest.mark.parametrize("seed", range(25))
def test_signal_engine_decisions_identical_off_and_on_and_conserved(seed, monkeypatch):
    sc = engine_scenario(seed)
    off = run_engine(monkeypatch, sc, on=False)
    on = run_engine(monkeypatch, sc, on=True)
    assert on["trace"] == off["trace"]
    assert on["saved"] == off["saved"]
    assert on["health"] == off["health"]
    assert not any(c[1] == off["mod"]._FUNNEL_LEGACY_ORDER_SQL for c in off["db"].calls)
    assert [e for e in events(off["rec"]) if e["event_type"].startswith("funnel.")] == []
    cycles = events(on["rec"], "funnel.cycle")
    if not sc["rows"]:
        assert cycles == []
        return
    env = cycles[0]["payload"]
    failures = dict(map(tuple, env["integration_failures"]))
    assert set(failures) <= {"legacy_label_unmapped:open_trade_exists"}, failures
    assert env["valid"] == (not failures)
    if not failures:
        assert env["report"]["conservation"]["ok"], env["report"]["conservation"]
    recs = [e["payload"] for e in events(on["rec"], "funnel.rejection")]
    n = len(sc["rows"])
    cut = [r for r in recs if r["reason_code"] == "F6.legacy_alphabetical_cut"]
    assert len(cut) == max(0, n - 200)
    assert sorted(r["rank"] for r in cut) == list(range(201, n + 1))
    returned = legacy_order(sc["rows"])[:200]
    rank = [r for r in recs if r["reason_code"] == "F6.rank_below_cap"]
    if sc["macro"] != "ok":
        f3 = [r for r in recs if r["stage"] == "F3"]
        assert [r["reason_code"] for r in f3] == [
            "F3.regime_veto:btc_trend" if sc["macro"] == "btc" else "F3.regime_stale"]
        assert f3[0]["detail"]["subject_count"] == len({r["symbol"] for r in returned})
        assert rank == []
    else:
        eligible, selected = _eligible_count(sc, returned)
        assert len(rank) == max(0, eligible - 1)
        assert all(r["detail"]["offer_cap"] == 1 and r["scope"] == "candidate" for r in rank)
        assert (len(on["saved"]) == 1) == (selected is not None)
    assert on["funnel_health"][-1]["not_recorded"] == 0


def test_broken_store_or_recorder_never_changes_decisions(monkeypatch):
    sc = engine_scenario(4)
    baseline = run_engine(monkeypatch, sc, on=False)

    def boom(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(ev2, "emit", boom)
    broken_store = run_engine(monkeypatch, sc, on=True)
    assert broken_store["trace"] == baseline["trace"] and broken_store["saved"] == baseline["saved"]
    assert broken_store["funnel_health"][-1]["not_recorded"] > 0

    monkeypatch.setattr(fh.FunnelService, "publish", boom)
    broken_publish = run_engine(monkeypatch, sc, on=True)
    assert broken_publish["trace"] == baseline["trace"] and broken_publish["saved"] == baseline["saved"]
    assert broken_publish["funnel_health"][-1]["publish_failures"] == 1

    monkeypatch.setattr(fh.FunnelCycle, "add", boom)
    broken_records = run_engine(monkeypatch, sc, on=True)
    assert broken_records["trace"] == baseline["trace"] and broken_records["saved"] == baseline["saved"]


def test_rank_records_match_the_reviewed_parity_selector(monkeypatch):
    sc = engine_scenario(3)
    sc["open"], sc["macro"] = set(), "ok"
    on = run_engine(monkeypatch, sc, on=True)
    returned = legacy_order(sc["rows"])[:200]
    from shared.candidate_selection import EligibilityPolicy, normalize, select
    res = select([normalize(r, sc["volume"][r["symbol"]]) for r in returned],
                 policy=EligibilityPolicy(max_spread_pct=config.MAX_SPREAD_PCT),
                 ranker="production_parity", cooldown=frozenset(sc["cooldown"]))
    want = [(c.symbol, c.timeframe, pos) for c, pos, _ in res.ranked[1:]]
    got = sorted((r["payload"]["symbol"], r["payload"]["timeframe"], r["payload"]["rank"])
                 for r in events(on["rec"], "funnel.rejection")
                 if r["payload"]["reason_code"] == "F6.rank_below_cap")
    assert got == sorted(want)


def _with_before_tree(service):
    """Swap the cached service module for the pre-change tree's copy (context manager)."""
    import contextlib
    import importlib.util
    from funnel_service_harness import _LOADED

    @contextlib.contextmanager
    def swap():
        spec = importlib.util.spec_from_file_location(
            f"wp2_before_{service}_main", os.path.join(os.environ["WP2_BEFORE_TREE"], service, "main.py"))
        before = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(before)
        if service == "signal_engine":
            before._RANKED_CANDIDATES_SQL = before._FUNNEL_LEGACY_ORDER_SQL = "<absent>"
        load_service(service)
        saved = _LOADED[service]
        _LOADED[service] = before
        try:
            yield
        finally:
            _LOADED[service] = saved
    return swap()


BEFORE_TREE = pytest.mark.skipif(not os.getenv("WP2_BEFORE_TREE"),
                                 reason="WP2_BEFORE_TREE not set (pre-change checkout)")


@BEFORE_TREE
@pytest.mark.parametrize("seed", range(25))
def test_signal_engine_off_equals_pre_change_tree(seed, monkeypatch):
    sc = engine_scenario(seed)
    now = run_engine(monkeypatch, sc, on=False)
    with _with_before_tree("signal_engine"):
        old = run_engine(monkeypatch, sc, on=False)
    assert now["trace"] == old["trace"] and now["saved"] == old["saved"] and now["health"] == old["health"]


@BEFORE_TREE
@pytest.mark.parametrize("seed", range(25))
def test_scanner_off_equals_pre_change_tree(seed, monkeypatch):
    sc = scanner_scenario(seed)
    now_db, now_h, _ = _run_scanner(monkeypatch, sc, on=False)
    with _with_before_tree("scanner"):
        old_db, old_h, _ = _run_scanner(monkeypatch, sc, on=False)
    strip = lambda db: json.dumps([(k, q, [(a[0], {x: y for x, y in json.loads(a[1]).items() if x != "scan_time"})
                                           for a in args] if k == "executemany" else args)
                                   for k, q, args in db.calls], default=str)
    assert strip(now_db) == strip(old_db) and now_h.calls == old_h.calls


@BEFORE_TREE
@pytest.mark.parametrize("seed", range(8))
def test_analyzer_off_equals_pre_change_tree(seed, monkeypatch):
    rows = analyzer_scenario(seed)
    out = []
    for before in (False, True):
        set_recording(monkeypatch, "analyzer", False)
        if before:
            with _with_before_tree("analyzer"):
                mod, db, health = _analyzer_env(monkeypatch, rows)
                run_main(mod, cycles=1)
        else:
            mod, db, health = _analyzer_env(monkeypatch, rows)
            run_main(mod, cycles=1)
        out.append((db.trace(), health.calls))
    assert out[0] == out[1]
