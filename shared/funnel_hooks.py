"""Funnel observability wiring for the scanner, analyzer and signal engine (WP-B01; R6.a, R6.c, R1.f).

The services build objects from this module only when ``FUNNEL_RECORDING=on``
(``shared/funnel_flags.py``). With ``off`` nothing here is constructed, so there is no wrapper,
extra read, clock call or event. With ``on`` every hook only observes. A hook returns exactly
what the wrapped code returned, re-raises exactly what it raised, and never raises on its own
account. A recording problem becomes a counted integration failure, and the cycle report is then
marked invalid. It never changes a decision.

Stages recorded (OPPORTUNITY_FUNNEL.md section 7; taxonomy v1 of ``shared/funnel_records.py``):

* **Scanner, F0 to F2 (``ScannerTap``).** ``scanner/scanner_logic.py`` is hash-pinned and stays
  byte-identical. The BinanceScanner *instance* is tapped. The tap captures the listing returned
  by ``get_exchange_info``, the USDT list, the 24 h tickers, every per-symbol verdict of the
  initial filter and the returned candidates, all exactly as returned. Reason codes come from
  those captured inputs. A code is accepted only when the derived verdict equals the pinned
  verdict for that symbol; a disagreement is a counted ``mirror_mismatch``. The blacklist is
  re-read only when a symbol without a ticker makes "blacklisted or no ticker" ambiguous.
* **Analyzer, F4 bar/data (``AnalyzerTap``).** ``analyzer/technical_analyzer.py`` and
  ``analyzer/main.py`` call the tap at their skip points. Today those points are silent (OF-05).
* **Signal engine, F3 to F6 (``SignalEngineTap``).**
  - The candidate query's cut is recorded in shadow. Under the legacy policy it is
    ``F6.legacy_alphabetical_cut``, taken from the rows the evidence-v2 truncation diagnostic
    (``_v2_truncation``) already reads: no statement of its own. Rows beyond that diagnostic's
    list are one cycle-scope record with their count. Under a declared policy the cut is
    ``F6.rank_below_cap``.
  - The live selector in ``signal_engine/signal_logic.py`` is pinned. Its gate outcomes are read
    from ``engine.last_decisions``, which the pinned code keys by symbol only (OF-08). So F2 to F5
    are recorded at symbol scope, in the pinned gate order, and attributed by each symbol's last
    label. Per-timeframe gate reasons are BLOCKED-WP-OD-01 (WP-B02).
  - The F6 ranking is observed exactly. The instance's ``_fixed_candidate_key`` is wrapped, and
    the selector calls it once per eligible candidate. Each loser gets ``F6.rank_below_cap`` with
    its rank and offer cap 1, never a capacity code (WP-IR-04).
  - The macro veto is one cycle-scope F3 record, and its cause is read from the macro context.

Records and per-cycle counters go to the existing evidence-v2 store (``funnel.rejection``,
``funnel.rejection_series_closed``, ``funnel.cycle``). Counters are never sampled: every cycle's
envelope carries the complete stage counts and conservation result. Records are compacted to one
event per state change of (stage, scope, subject, reason, analysis identity), with
``first_seen``, ``last_seen`` and ``repeat_count`` on the closing event (OF section 8.4). This
covers the scanner's F0 to F2 and the signal engine's F2 to F6. A per-cycle emission bound
(``max_records_per_cycle``) stops a pathological cycle from flooding the queue; the excess is
counted as ``records_overflow`` and retried on the next cycle. A failed or dropped emit is
counted as ``not_recorded``.

Identity fields are labels, not the WP-IR-09 identifier:
* ``strategy_version`` is ``config.APP_VERSION``;
* ``strategy_id`` maps the row's ``trade_type`` onto the declared current-family ids, or is
  ``unassigned`` for a row with no setup;
* ``snapshot_hash`` stays unavailable until WP-B03.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from typing import Any, Mapping

from shared import evidence_v2
from shared.config import config
from shared.funnel_records import (FRESHNESS_REASON_CODES, SE_NAME_MAP, RejectionRecord,
                                   canonical_for_legacy, validate_reason_code)
from shared.funnel_recorder import FunnelRecorder

ENVELOPE_SCHEMA = "tsb.funnel.cycle_envelope"
ENVELOPE_VERSION = 1
SNAPSHOT_HASH_UNAVAILABLE = "unavailable:wp-b03"      # MarketSnapshot capture is WP-B03
# = shared/strategy_identity.py CURRENT_FAMILY_IDS (owner-review proposal); tests hold them equal.
STRATEGY_BY_TRADE_TYPE = {"momentum": "momentum_breakout", "reversion": "reversion_rsi_bb"}
UNASSIGNED_STRATEGY_ID = "unassigned"                 # a row before (or without) strategy assignment
LEGACY_RANK_VERSION = "fixed_execution_quality_v1"    # analyzer/technical_analyzer.py selection_policy label
# Legacy literals reproduced for derivation only (scanner/scanner_logic.py @ af319bb).
LEGACY_STABLE_PAIRS = ("USDCUSDT", "BUSDUSDT", "TUSDUSDT")   # L79
LEGACY_STRESS_TREND = "strong_bearish"                        # L108
LEGACY_STRESS_MOVE_PCT = 5                                    # L108
ANALYZER_SYMBOL_TIMEOUT_S = 60                                # analyzer/main.py wait_for timeout


def _num(value: Any, digits: int = 8):
    """A finite float rounded for a record detail, else None (records refuse NaN and inf)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) else None


def _pos_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def candidate_fields(data: Mapping | None, symbol: str | None = None,
                     timeframe: str | None = None) -> dict:
    """Subject fields of one analysis row as a candidate-scope record subject."""
    data = data if isinstance(data, Mapping) else {}
    trade_type = data.get("trade_type") or None
    pit = data.get("pit") if isinstance(data.get("pit"), Mapping) else {}
    ident = data.get("candle_identity") if isinstance(data.get("candle_identity"), Mapping) else {}
    setup = data.get("setup_identity") if isinstance(data.get("setup_identity"), Mapping) else {}
    setup_key = setup.get("key")
    return {"symbol": str(data.get("symbol") or symbol or ""),
            "timeframe": str(data.get("timeframe") or timeframe or ""),
            "strategy_id": STRATEGY_BY_TRADE_TYPE.get(trade_type, UNASSIGNED_STRATEGY_ID),
            "strategy_version": str(getattr(config, "APP_VERSION", "") or "") or None,
            "bar_close_time": _pos_ms(pit.get("candle_close_time_ms"))
            or _pos_ms(ident.get("candle_close_time_ms")),
            "setup_key": setup_key if isinstance(setup_key, str) and setup_key else None}


def engine_label_code(label: Any):
    """``(stage, reason_code, sub_stage)`` for a signal-engine decision label, or None when the
    documented maps (WP-IR-01, WP-IR-04, OF section 8.2) give no canonical code. Never guesses."""
    if not isinstance(label, str) or not label:
        return None
    if label.startswith("stop_rejected:"):
        reason = label.split(":", 1)[1]
        code = ("F5.stop_risk_above_cap" if reason == "structural_risk_exceeds_cap"
                else f"F5.stop_invalid:{reason}")
        try:
            return "F5", validate_reason_code(code, "F5"), "strategy.geometry"
        except ValueError:
            return None
    if label in SE_NAME_MAP:
        stage, code, sub = SE_NAME_MAP[label]
        return stage, code, sub
    if label in FRESHNESS_REASON_CODES:
        return "F4", FRESHNESS_REASON_CODES[label], "shared.identity"
    try:
        code = canonical_for_legacy(label)
    except ValueError:
        return None
    return code.split(".", 1)[0], code, ("strategy.entry" if code == "F4.no_setup" else None)


# ── per-service state and emission ─────────────────────────────────────────────────────────

class FunnelService:
    """Per-process funnel state of one service: cycle numbering, compaction, health counters."""

    def __init__(self, service: str, *, compact_stages=(), max_records_per_cycle: int | None = None):
        self.service = service
        self.compact_stages = frozenset(compact_stages)
        if max_records_per_cycle is not None and (isinstance(max_records_per_cycle, bool)
                                                  or not isinstance(max_records_per_cycle, int)
                                                  or max_records_per_cycle < 1):
            raise ValueError("max_records_per_cycle must be a positive int or None")
        self.max_records_per_cycle = max_records_per_cycle
        try:
            self.config_hash = evidence_v2.compute_config_hash(config)
        except Exception:
            self.config_hash = "unavailable"
        self._cycles = itertools.count(1)
        self._series: dict = {}
        self._series_cap = int(getattr(config, "EVIDENCE_V2_STATE_CACHE", 50000) or 50000)
        self.stats = {"cycles": 0, "valid_cycles": 0, "invalid_cycles": 0, "records": 0,
                      "events_recorded": 0, "not_recorded": 0, "compacted_repeats": 0,
                      "series_closed": 0, "publish_failures": 0, "records_overflow": 0}
        self.last_envelope: dict | None = None
        self.last_records: tuple = ()
        self._budget: int | None = None
        self._overflow = 0

    def begin(self, decision_time_ms: int | None = None) -> "FunnelCycle":
        t = decision_time_ms if decision_time_ms is not None else evidence_v2.now_ms()
        return FunnelCycle(self, f"{self.service}:{t}:{next(self._cycles)}", int(t))

    def health(self) -> dict:
        return dict(self.stats, last_cycle_valid=(self.last_envelope or {}).get("valid"))

    def _emit(self, event_type: str, subject: dict, payload: dict, event_time_ms: int) -> bool:
        try:
            ok = bool(evidence_v2.emit(self.service, event_type, subject, payload,
                                       event_time_ms=event_time_ms))
        except Exception:
            ok = False
        self.stats["events_recorded" if ok else "not_recorded"] += 1
        return ok

    def _emit_record(self, record: RejectionRecord, series: dict | None = None) -> None:
        if self._budget is not None:
            if self._budget <= 0:
                self._overflow += 1
                return
            self._budget -= 1
        payload = record.as_dict()
        if series is not None:
            payload["series"] = series
        self._emit("funnel.rejection", {"record_id": record.record_id, "stage": record.stage,
                                        "reason_code": record.reason_code, "symbol": record.symbol,
                                        "timeframe": record.timeframe}, payload, record.decision_time)

    def publish(self, cycle: "FunnelCycle", *, chain=(), close_series: bool = False) -> dict:
        report = cycle.recorder.report(chain=tuple(chain))
        records = report.records if report is not None else ()
        self._budget, self._overflow = self.max_records_per_cycle, 0
        seen = set()
        for r in records:
            if r.stage not in self.compact_stages:
                self._emit_record(r)
                continue
            # one series per (stage, scope, subject, reason, analysis identity); the subject of a
            # candidate-scope record already carries its bar_close_time and setup_key
            key = (r.stage, r.scope, r.subject_key(), r.reason_code, cycle.identities.get(r.record_id))
            seen.add(key)
            entry = self._series.get(key)
            if entry is not None:
                entry["last_seen_ms"] = r.decision_time
                entry["repeat_count"] += 1
                self.stats["compacted_repeats"] += 1
                continue
            series = {"compaction": "state_change_v1", "first_seen_ms": r.decision_time}
            if self._budget is not None and self._budget <= 0:
                self._overflow += 1                    # not tracked: retried on the next cycle
                seen.discard(key)
                continue
            if len(self._series) < self._series_cap:
                self._series[key] = {"first_seen_ms": r.decision_time, "last_seen_ms": r.decision_time,
                                     "repeat_count": 1, "first_record_id": r.record_id,
                                     "reason_code": r.reason_code, "symbol": r.symbol}
            else:
                series["compaction"] = "untracked_series_cap"
            self._emit_record(r, series)
        if close_series:
            for key in [k for k in self._series if k not in seen]:
                if self._budget is not None:
                    if self._budget <= 0:
                        break                          # closed on a later cycle (still absent)
                    self._budget -= 1
                entry = self._series.pop(key)
                self.stats["series_closed"] += 1
                self._emit("funnel.rejection_series_closed",
                           {"first_record_id": entry["first_record_id"], "stage": key[0],
                            "reason_code": entry["reason_code"], "symbol": entry["symbol"]},
                           {**entry, "closed_in_cycle": cycle.cycle_id}, cycle.decision_time)
        valid = bool(report is not None and report.valid and not cycle.failures)
        summary = report.as_dict() if report is not None else {}
        summary.pop("records", None)
        envelope = {"schema": ENVELOPE_SCHEMA, "schema_version": ENVELOPE_VERSION,
                    "service": self.service, "cycle_id": cycle.cycle_id,
                    "decision_time": cycle.decision_time, "valid": valid,
                    "record_count": len(records), "records_overflow": self._overflow,
                    "report": summary,
                    "integration_failures": [list(x) for x in sorted(cycle.failures.items())],
                    "notes": dict(cycle.notes), "snapshot_hash": SNAPSHOT_HASH_UNAVAILABLE}
        self._emit("funnel.cycle", {"stream": f"{self.service}.funnel", "cycle_id": cycle.cycle_id},
                   envelope, cycle.decision_time)
        self.stats["cycles"] += 1
        self.stats["valid_cycles" if valid else "invalid_cycles"] += 1
        self.stats["records"] += len(records)
        self.stats["records_overflow"] += self._overflow
        self.last_envelope, self.last_records = envelope, records
        return envelope


class FunnelCycle:
    """One cycle of one service: the recorder plus integration failures and notes."""

    def __init__(self, service: FunnelService, cycle_id: str, decision_time: int):
        self.service, self.cycle_id, self.decision_time = service, cycle_id, decision_time
        self.recorder = FunnelRecorder(enabled=True, cycle_id=cycle_id)
        self.failures: dict = {}
        self.notes: dict = {}
        self.identities: dict = {}                 # record_id -> analysis identity (compaction key)
        self.closed = False

    def fail(self, kind: str) -> None:
        try:
            self.failures[kind] = self.failures.get(kind, 0) + 1
        except Exception:                                          # pragma: no cover
            pass

    def add(self, *, stage: str, scope: str, reason_code: str, rule_ref: str, as_of: int | None = None,
            series_identity: str | None = None, **fields) -> RejectionRecord | None:
        try:
            record = RejectionRecord(cycle_id=self.cycle_id, stage=stage, scope=scope,
                                     reason_code=reason_code, as_of=as_of or self.decision_time,
                                     decision_time=self.decision_time, rule_ref=rule_ref,
                                     snapshot_hash=SNAPSHOT_HASH_UNAVAILABLE,
                                     config_hash=self.service.config_hash, **fields)
        except Exception as exc:
            self.fail(f"record_refused:{type(exc).__name__}")
            return None
        if series_identity is not None:
            self.identities[record.record_id] = series_identity
        self.recorder.record(record)
        return record

    def count(self, stage: str, n_in: int, passed: int, expanded_from: int | None = None) -> None:
        self.recorder.observe_counts(stage, n_in=n_in, passed=passed, expanded_from=expanded_from)

    def finish(self, *, chain=(), close_series: bool = False) -> dict | None:
        if self.closed:
            return None
        self.closed = True
        try:
            return self.service.publish(self, chain=chain, close_series=close_series)
        except Exception:
            self.service.stats["publish_failures"] += 1
            return None


# ── scanner: F0 to F2 ───────────────────────────────────────────────────────────────────────

class _ListingClient:
    """Delegating client proxy that captures what ``get_exchange_info`` returned."""

    def __init__(self, client, tap):
        self._client = client
        self._tap = tap

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def get_exchange_info(self, *args, **kwargs):
        info = await self._client.get_exchange_info(*args, **kwargs)
        self._tap._see("listing", info)
        return info


def f1_listing_codes(entry: Mapping) -> list:
    """Listing rules of ``BinanceScanner._get_usdt_pairs`` (scanner_logic.py:L75-81), all evaluated."""
    symbol = entry.get("symbol")
    codes = []
    if entry.get("quoteAsset") != "USDT":
        codes.append("F1.quote_not_approved")
    if entry.get("status") != "TRADING":
        codes.append("F1.status_not_trading")
    if symbol in LEGACY_STABLE_PAIRS:
        codes.append("F1.stable_or_pegged")
    if not (isinstance(symbol, str) and symbol.isascii()):
        codes.append("F1.symbol_unsupported")
    return codes


def f2_filter_codes(ticker: Mapping, btc_trend: str) -> tuple:
    """Rules of ``BinanceScanner._passes_initial_filter`` (scanner_logic.py:L88-114), all evaluated,
    with the pinned comparisons, so a NaN input passes exactly as it does there.
    Returns (codes, details, unmapped)."""
    codes, details, unmapped = [], {}, []
    try:
        volume = float(ticker["quoteVolume"])
    except (KeyError, TypeError, ValueError):
        codes.append("F2.volume_missing")
        details["F2.volume_missing"] = {"cause": "unparseable_quote_volume"}
    else:
        if volume < config.MIN_VOLUME_USDT:
            codes.append("F2.volume_below_floor")
            details["F2.volume_below_floor"] = {"quote_volume": _num(volume, 2),
                                                "floor": _num(config.MIN_VOLUME_USDT, 2)}
    try:
        move = abs(float(ticker["priceChangePercent"]))
    except (KeyError, TypeError, ValueError):
        codes.append("F2.move_below_floor")
        details["F2.move_below_floor"] = {"cause": "unparseable_price_change"}
    else:
        stress = btc_trend == LEGACY_STRESS_TREND and move < LEGACY_STRESS_MOVE_PCT
        if move < config.MIN_PRICE_CHANGE_PERCENT or stress:
            codes.append("F2.move_below_floor")
            details["F2.move_below_floor"] = {
                "abs_change_pct": _num(move, 6), "floor": _num(config.MIN_PRICE_CHANGE_PERCENT, 6),
                "btc_trend": str(btc_trend),
                "stress_floor": LEGACY_STRESS_MOVE_PCT if btc_trend == LEGACY_STRESS_TREND else None}
    try:
        if float(ticker["lastPrice"]) <= 0:
            unmapped.append("last_price_not_positive")
    except (KeyError, TypeError, ValueError):
        unmapped.append("last_price_unparseable")
    return codes, details, unmapped


class ScannerTap:
    """Instance-level observation of a ``BinanceScanner``; its source file stays byte-identical."""

    RULES = {"F1.quote_not_approved": "scanner_logic._get_usdt_pairs:quote_asset_usdt",
             "F1.status_not_trading": "scanner_logic._get_usdt_pairs:status_trading",
             "F1.stable_or_pegged": "scanner_logic._get_usdt_pairs:named_stable_pairs",
             "F1.symbol_unsupported": "scanner_logic._get_usdt_pairs:ascii_symbol",
             "F1.owner_excluded": "scanner_logic.scan:symbol_blacklist",
             "F2.volume_missing": "scanner_logic.scan:ticker_present+initial_filter:volume",
             "F2.volume_below_floor": "scanner_logic._passes_initial_filter:MIN_VOLUME_USDT",
             "F2.move_below_floor": "scanner_logic._passes_initial_filter:MIN_PRICE_CHANGE_PERCENT+btc_stress",
             "F0.snapshot_incomplete": "scanner_logic.scan:abort_on_failure"}
    BLACKLIST_SQL = "SELECT symbol FROM symbol_blacklist"

    def __init__(self, scanner, service: FunnelService | None = None, *, fetch=None):
        self.service = service or FunnelService("scanner", compact_stages=("F0", "F1", "F2"))
        self.cycle: FunnelCycle | None = None
        self._obs: dict | None = None
        self._scanner = scanner
        self._fetch = fetch
        orig_pairs = scanner._get_usdt_pairs
        orig_tickers = scanner._get_24h_tickers
        orig_filter = scanner._passes_initial_filter
        tap = self

        async def _get_usdt_pairs():
            out = await orig_pairs()
            tap._see("pairs", out)
            return out

        async def _get_24h_tickers():
            out = await orig_tickers()
            tap._see("tickers", out)
            return out

        async def _passes_initial_filter(symbol, ticker):
            verdict = await orig_filter(symbol, ticker)
            tap._see_verdict(symbol, verdict)
            return verdict

        scanner.client = _ListingClient(scanner.client, self)
        scanner._get_usdt_pairs = _get_usdt_pairs
        scanner._get_24h_tickers = _get_24h_tickers
        scanner._passes_initial_filter = _passes_initial_filter

    def _see(self, kind, value) -> None:
        try:
            if self._obs is not None:
                self._obs[kind] = value
        except Exception:                                          # pragma: no cover
            pass

    def _see_verdict(self, symbol, verdict) -> None:
        try:
            if self._obs is not None:
                self._obs["verdicts"].append((symbol, verdict))
        except Exception:                                          # pragma: no cover
            pass

    def health(self) -> dict:
        return self.service.health()

    def begin(self) -> None:
        try:
            self._obs = {"verdicts": []}
            self.cycle = self.service.begin()
        except Exception:
            self._obs, self.cycle = None, None

    async def end(self, candidates=None, error: BaseException | None = None) -> dict | None:
        cycle, obs = self.cycle, self._obs
        self._obs = None
        if cycle is None or cycle.closed:
            return None
        chain, complete = (), False
        try:
            chain, complete = await self._build(cycle, obs or {}, candidates, error)
        except Exception as exc:
            cycle.fail(f"tap_error:{type(exc).__name__}")
        return cycle.finish(chain=chain, close_series=complete)

    async def _read_blacklist(self) -> set:
        fetch = self._fetch
        if fetch is None:
            from shared.database import Database
            fetch = Database.fetch
        return {r["symbol"] for r in await fetch(self.BLACKLIST_SQL)}

    async def _build(self, cyc: FunnelCycle, obs: dict, candidates, error):
        listing = obs.get("listing")
        entries = listing.get("symbols") if isinstance(listing, Mapping) else None
        if error is not None:
            n = len(entries) if isinstance(entries, list) else 0
            cyc.add(stage="F0", scope="cycle", reason_code="F0.snapshot_incomplete",
                    rule_ref=self.RULES["F0.snapshot_incomplete"],
                    detail={"subject_count": n, "error": type(error).__name__,
                            "listing": listing is not None, "tickers": "tickers" in obs})
            cyc.count("F0", n, 0)
            cyc.notes["outcome"] = "scan_failed"
            return (), False
        if listing is None:
            cyc.notes["outcome"] = "paused_or_not_scanned"
            if candidates:
                cyc.fail("candidates_without_listing")
            return (), False
        pairs, tickers = obs.get("pairs"), obs.get("tickers")
        if not isinstance(entries, list) or not isinstance(pairs, list) or not isinstance(tickers, Mapping):
            cyc.fail("partial_observation")
            return (), False
        cyc.notes["outcome"] = "scanned"
        n_listing = len(entries)
        cyc.count("F0", n_listing, n_listing)
        # F1: listing rules, then the owner exclusion list.
        pair_set = set(pairs)
        derived_pass = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                cyc.fail("listing_entry_unreadable")
                continue
            symbol = entry.get("symbol")
            codes = f1_listing_codes(entry)
            if not codes:
                derived_pass.append(symbol)
                continue
            if symbol in pair_set or not isinstance(symbol, str) or not symbol:
                cyc.fail("f1_mirror_mismatch")
                continue
            details = {"F1.quote_not_approved": {"quote_asset": str(entry.get("quoteAsset"))},
                       "F1.status_not_trading": {"status": str(entry.get("status"))}}
            for code in codes:
                cyc.add(stage="F1", scope="symbol", reason_code=code, rule_ref=self.RULES[code],
                        symbol=symbol, detail=details.get(code, {}))
        if derived_pass != pairs:
            cyc.fail("f1_mirror_mismatch")
        verdicts = {}
        for symbol, verdict in obs.get("verdicts", ()):
            if symbol in verdicts:
                cyc.fail("verdict_repeated")
            verdicts[symbol] = verdict
        blacklisted = {s for s in pairs if tickers.get(s) and s not in verdicts}
        ambiguous = [s for s in pairs if not tickers.get(s)]
        unresolved: set = set()
        if ambiguous:
            try:
                listed = await self._read_blacklist()
            except Exception as exc:
                cyc.fail(f"blacklist_read_failed:{type(exc).__name__}")
                listed = None
            if listed is not None:
                if not blacklisted <= listed:
                    cyc.fail("blacklist_changed_during_cycle")
                blacklisted |= {s for s in ambiguous if s in listed}
            else:
                unresolved = set(ambiguous)          # blacklisted or no ticker: left unrecorded
        for symbol in sorted(blacklisted):
            cyc.add(stage="F1", scope="symbol", reason_code="F1.owner_excluded",
                    rule_ref=self.RULES["F1.owner_excluded"], symbol=symbol,
                    detail={"list": "symbol_blacklist"})
        passed_f1 = [s for s in pairs if s not in blacklisted]
        cyc.count("F1", n_listing, len(passed_f1))
        # F2: ticker presence, then the initial filter (its verdict is the pinned one).
        btc_trend = getattr(self._scanner, "btc_trend", None)
        passed_f2 = []
        for symbol in passed_f1:
            if symbol in unresolved:
                continue
            ticker = tickers.get(symbol)
            if not ticker:
                cyc.add(stage="F2", scope="symbol", reason_code="F2.volume_missing",
                        rule_ref=self.RULES["F2.volume_missing"], symbol=symbol,
                        detail={"cause": "ticker_missing"})
                continue
            if symbol not in verdicts:
                cyc.fail("verdict_missing")
                continue
            codes, details, unmapped = f2_filter_codes(ticker, btc_trend)
            derived = not codes and not unmapped
            if derived != bool(verdicts[symbol]):
                cyc.fail("f2_mirror_mismatch")
                if verdicts[symbol]:
                    passed_f2.append(symbol)
                continue
            if verdicts[symbol]:
                passed_f2.append(symbol)
                continue
            if not codes:
                for kind in unmapped:
                    cyc.fail(f"unmapped_rule:{kind}")
                continue
            for code in codes:
                cyc.add(stage="F2", scope="symbol", reason_code=code, rule_ref=self.RULES[code],
                        symbol=symbol, detail=details.get(code, {}))
        cyc.count("F2", len(passed_f1), len(passed_f2))
        returned = [c.get("symbol") for c in (candidates or ()) if isinstance(c, Mapping)]
        if returned != passed_f2:
            cyc.fail("candidates_mismatch")
        return ("F0", "F1", "F2"), True


# ── analyzer: F4 bar/data ───────────────────────────────────────────────────────────────────

class AnalyzerTap:
    """Receives the analyzer's skip points; one cycle = one intake batch."""

    RULE_HISTORY = "technical_analyzer.indicator_warmup_bars"
    RULE_DATA = "technical_analyzer.analyze:candles_and_indicators"

    def __init__(self, service: FunnelService | None = None):
        self.service = service or FunnelService("analyzer")
        self.cycle: FunnelCycle | None = None
        self._events: dict | None = None

    def health(self) -> dict:
        return self.service.health()

    def _note(self, symbol, timeframe, kind, detail=None) -> None:
        try:
            if self._events is not None:
                self._events.setdefault((symbol, timeframe), []).append((kind, detail or {}))
        except Exception:                                          # pragma: no cover
            pass

    # callbacks (each one never raises)
    def candles_unavailable(self, symbol, timeframe, exc) -> None:
        self._note(symbol, timeframe, "candles_unavailable", {"error": type(exc).__name__})

    def too_little_data(self, symbol, timeframe, bars, required) -> None:
        self._note(symbol, timeframe, "too_little_data", {"bars": bars, "required": required})

    def analysis_error(self, symbol, timeframe, exc) -> None:
        self._note(symbol, timeframe, "analysis_error", {"error": type(exc).__name__})

    def written(self, symbol, timeframe) -> None:
        self._note(symbol, timeframe, "written")

    def timeframe_error(self, symbol, timeframe, exc) -> None:
        self._note(symbol, timeframe, "timeframe_error", {"error": type(exc).__name__})

    def begin(self) -> None:
        try:
            self._events = {}
            self.cycle = self.service.begin()
        except Exception:
            self._events, self.cycle = None, None

    def end(self, candidates, outcomes, timeframes, error: BaseException | None = None) -> dict | None:
        cycle, events = self.cycle, self._events
        self._events = None
        if cycle is None or cycle.closed:
            return None
        try:
            self._build(cycle, events or {}, candidates, outcomes, timeframes, error)
        except Exception as exc:
            cycle.fail(f"tap_error:{type(exc).__name__}")
        return cycle.finish(chain=("F4",) if error is None else ())

    def _build(self, cyc, events, candidates, outcomes, timeframes, error):
        if error is not None:
            cyc.fail(f"cycle_exception:{type(error).__name__}")
            return
        timed_out = set()
        for row, result in zip(candidates, outcomes or ()):
            if isinstance(result, BaseException):
                if isinstance(result, TimeoutError):
                    timed_out.add(row["symbol"])
                else:
                    cyc.fail(f"symbol_task_error:{type(result).__name__}")
        pairs = list(dict.fromkeys((row["symbol"], tf) for row in candidates for tf in timeframes))
        written = 0
        for symbol, tf in pairs:
            kinds = events.get((symbol, tf), [])
            if any(k == "written" for k, _ in kinds):
                written += 1
                continue
            drop = next(((k, d) for k, d in kinds
                         if k in ("too_little_data", "analysis_error", "candles_unavailable")), None)
            if drop is not None and drop[0] == "too_little_data" and drop[1].get("bars") is not None:
                code, detail = "F4.history_insufficient", dict(drop[1])
            elif drop is not None:
                cause = next((k for k, _ in kinds if k in ("candles_unavailable", "analysis_error")), drop[0])
                info = next((d for k, d in kinds if k == cause), {})
                code, detail = "F4.data_quality", {"cause": cause, **info}
            elif symbol in timed_out:
                code, detail = "F4.data_quality", {"cause": "symbol_timeout",
                                                    "timeout_s": ANALYZER_SYMBOL_TIMEOUT_S}
            else:
                other = next((d for k, d in kinds if k == "timeframe_error"), None)
                cyc.fail("unmapped:persist_or_orderbook_error" if other is not None
                         else "unobserved_timeframe")
                continue
            cyc.add(stage="F4", scope="candidate", reason_code=code,
                    rule_ref=self.RULE_HISTORY if code == "F4.history_insufficient" else self.RULE_DATA,
                    detail=detail, **candidate_fields(None, symbol, tf))
        cyc.count("F4", len(pairs), written)


# ── signal engine: F3 to F6 ─────────────────────────────────────────────────────────────────

def _nan_safe(key) -> tuple:
    return tuple((1, 0.0) if isinstance(v, float) and math.isnan(v) else (0, v) for v in key)


class SignalEngineTap:
    """Observes one signal-engine process: candidate cut, gate outcomes and the F6 ranking."""

    RULE_CUT = "signal_engine.main:candidate_query:ORDER BY symbol:LIMIT"
    RULE_RANKED = "selection_policy.rank_then_limit"
    RULE_MACRO = "macro_context.should_block_now"
    RULE_RANK = "signal_logic.SignalEngine._fixed_candidate_key:min"

    # Stages whose records are compacted to one per state change (SE-1 volume bound).
    COMPACT_STAGES = ("F2", "F3", "F4", "F5", "F6")

    def __init__(self, engine, *, limit: int, cut_list_rows: int, service: FunnelService | None = None):
        # Per cycle at most: one record per symbol of the <= limit rows (F2-F5 or F3), one per
        # ranked loser (<= limit), the listed cut rows (<= cut_list_rows) and one record for an
        # unlisted cut tail. A larger emission is a pathological cycle: the excess is counted
        # (records_overflow), never emitted. Both numbers are the caller's existing bounds.
        self.service = service or FunnelService(
            "signal_engine", compact_stages=self.COMPACT_STAGES,
            max_records_per_cycle=2 * limit + cut_list_rows + 1)
        self.limit = limit
        self.cut_list_rows = cut_list_rows
        self.cycle: FunnelCycle | None = None
        self.chain: tuple = ()
        self._eligible: list | None = None
        self._seen: set = set()
        orig_key = engine._fixed_candidate_key
        tap = self

        def _observed_key(signal):
            key = orig_key(signal)
            tap._see_candidate(signal, key)
            return key

        engine._fixed_candidate_key = _observed_key

    def health(self) -> dict:
        return self.service.health()

    def _see_candidate(self, signal, key) -> None:
        try:
            if self._eligible is None or id(signal) in self._seen:
                return
            self._seen.add(id(signal))
            self._eligible.append({"id": id(signal), "key": tuple(key), "pos": len(self._eligible),
                                   "fields": candidate_fields(signal)})
        except Exception:
            if self.cycle is not None:
                self.cycle.fail("candidate_capture_failed")

    def begin(self, decision_time_ms: int | None = None) -> None:
        try:
            self.cycle = self.service.begin(decision_time_ms)
            self.chain = ()
            self._eligible, self._seen = None, set()
        except Exception:
            self.cycle = None

    # selection stage (candidate query)
    def observe_legacy_cut(self, results, truncation) -> None:
        """Record the legacy cut from the rows the evidence-v2 truncation diagnostic already read
        (``signal_engine/main.py`` ``_v2_truncation``: a count and the first ``cut_list_rows`` rows
        beyond the limit, in the query's order). No statement of its own."""
        cyc = self.cycle
        if cyc is None:
            return
        try:
            n = len(results)
            if n < self.limit:
                cyc.count("F6", n, n)
                cyc.notes["selection"] = {"policy": "legacy", "fetched": n, "cut": 0}
                return
            if not isinstance(truncation, Mapping) or "eligible_total" not in truncation:
                cyc.fail("legacy_cut_unavailable")
                return
            total = int(truncation["eligible_total"])
            listed = list(truncation.get("truncated_rows") or ())[:self.cut_list_rows]
            if total < n + len(listed):
                cyc.fail("cut_count_inconsistent")         # count and list are separate statements
                return
            for position, (symbol, timeframe) in enumerate(listed, start=self.limit + 1):
                cyc.add(stage="F6", scope="candidate", reason_code="F6.legacy_alphabetical_cut",
                        rule_ref=self.RULE_CUT, rank=position,
                        detail={"position": position, "limit": self.limit, "order": "name",
                                "source": "selection.truncation"},
                        **candidate_fields({"symbol": symbol, "timeframe": timeframe}))
            unlisted = total - n - len(listed)
            if unlisted:
                first = self.limit + len(listed) + 1
                cyc.add(stage="F6", scope="cycle", reason_code="F6.legacy_alphabetical_cut",
                        rule_ref=self.RULE_CUT, rank=first,
                        detail={"subject_count": unlisted, "positions_from": first, "limit": self.limit,
                                "order": "name", "rows_unlisted": True})
            cyc.count("F6", total, n)
            cyc.notes["selection"] = {"policy": "legacy", "fetched": total, "cut": total - n,
                                      "cut_listed": len(listed), "cut_unlisted": unlisted}
        except Exception as exc:
            cyc.fail(f"legacy_cut_failed:{type(exc).__name__}")

    def observe_ranked_cut(self, picked) -> None:
        cyc = self.cycle
        if cyc is None:
            return
        try:
            version = picked.policy.selection_version
            for r in picked.cut:
                cyc.add(stage="F6", scope="candidate", reason_code="F6.rank_below_cap",
                        rule_ref=self.RULE_RANKED, rank=r.rank,
                        detail={"rank": r.rank, "offer_cap": picked.limit, "selection_version": version,
                                "cap": "candidate_limit", "score": _num(r.score),
                                "score_missing": r.score_missing, "tie_break_key": r.tie_break_key},
                        **candidate_fields(r.data, r.symbol, r.timeframe))
            cyc.count("F6", len(picked.ranked), len(picked.rows))
            cyc.notes["selection"] = picked.truncation_info()
        except Exception as exc:
            cyc.fail(f"ranked_cut_failed:{type(exc).__name__}")

    def start_decision(self) -> None:
        if self.cycle is not None:
            self._eligible, self._seen = [], set()

    @staticmethod
    def _macro_cause(macro):
        try:
            state = dict(macro.state() or {})
            fresh_fn = getattr(macro, "data_is_fresh", None)
            fresh = bool(fresh_fn()) if callable(fresh_fn) else None
            had_valid = bool(getattr(macro, "_last_valid_ts", 0))
        except Exception:
            return None, {}
        if fresh is None:
            return None, {}
        if not fresh:
            return ("F3.regime_stale" if had_valid else "F3.regime_unavailable"), {"fresh": False}
        vetoes = [k for k, bad in (("btc_trend", state.get("btc_trend") == "strong_bearish"),
                                   ("usdtd_trend", state.get("usdtd_trend") == "rising_fast")) if bad]
        if not vetoes:
            return None, {}
        return f"F3.regime_veto:{vetoes[0]}", {"vetoes": vetoes, "btc_trend": str(state.get("btc_trend")),
                                               "usdtd_trend": str(state.get("usdtd_trend"))}

    def observe_decision(self, results, decisions, best, macro, live: bool) -> None:
        cyc = self.cycle
        eligible, self._eligible = self._eligible, None
        if cyc is None:
            return
        try:
            self._decision(cyc, results, decisions or {}, best, macro, live, eligible or [])
        except Exception as exc:
            cyc.fail(f"tap_error:{type(exc).__name__}")
            self.chain = ()

    def _decision(self, cyc, results, decisions, best, macro, live, eligible):
        symbols = list(dict.fromkeys(row["symbol"] for row in results))
        n = len(symbols)
        identity = self._symbol_identities(results)
        if not live:
            cyc.notes["gate_block"] = "unobserved_legacy_score_path"
            return
        ranked_symbols = {c["fields"]["symbol"] for c in eligible}
        if n and not eligible and all(decisions.get(s) == "macro_block" for s in symbols):
            code, detail = self._macro_cause(macro)
            cyc.count("F3", n, 0)
            if code is None:
                cyc.fail("macro_block_cause_not_reproduced")
            else:
                cyc.add(stage="F3", scope="cycle", reason_code=code, rule_ref=self.RULE_MACRO,
                        detail={"subject_count": n, "attribution": "post_decision_read", **detail})
            self.chain = ("F3",)
            return
        cyc.count("F3", n, n)
        drops = {"F4": [], "F2": [], "F5": []}
        for symbol in symbols:
            label = decisions.get(symbol)
            if symbol in ranked_symbols:
                if label not in ("selected", "not_selected_capacity"):
                    cyc.fail("ranked_symbol_label_inconsistent")
                continue
            mapped = engine_label_code(label)
            if mapped is None or mapped[0] not in drops:
                head = label.split(":", 1)[0] if isinstance(label, str) else "missing"
                cyc.fail(f"legacy_label_unmapped:{head}")
                drops["F4"].append((symbol, None, None, label))
                continue
            stage, code, sub = mapped
            drops[stage].append((symbol, code, sub, label))
        remaining = n
        for stage in ("F4", "F2", "F5"):
            cyc.count(stage, remaining, remaining - len(drops[stage]))
            remaining -= len(drops[stage])
            for symbol, code, sub, label in drops[stage]:
                if code is None:
                    continue
                cyc.add(stage=stage, scope="symbol", reason_code=code, sub_stage=sub, symbol=symbol,
                        series_identity=identity.get(symbol),
                        rule_ref=f"signal_logic.find_best_signal_live:{label.split(':', 1)[0]}",
                        detail={"legacy_reason": label, "attribution": "per_symbol_last_label"})
        if remaining != len(ranked_symbols):
            cyc.fail("gate_count_mismatch")
        ordered = sorted(eligible, key=lambda c: (_nan_safe(c["key"]), c["pos"]))
        if ordered and (best is None or id(best) != ordered[0]["id"]):
            cyc.fail("rank_mismatch")
        if not ordered and best is not None:
            cyc.fail("selected_without_ranking")
        cyc.count("F6", len(ordered), 1 if (ordered and best is not None) else 0,
                  expanded_from=len(ranked_symbols))
        for rank, c in enumerate(ordered[1:], start=2):
            cyc.add(stage="F6", scope="candidate", reason_code="F6.rank_below_cap", rank=rank,
                    rule_ref=self.RULE_RANK,
                    detail={"rank": rank, "offer_cap": 1, "selection_version": LEGACY_RANK_VERSION,
                            "legacy_reason": "not_selected_capacity",
                            "rank_key": [_num(v) if isinstance(v, float) else v for v in c["key"]]},
                    **c["fields"])
        self.chain = ("F3", "F4", "F2", "F5", "F6")

    @staticmethod
    def _symbol_identities(results) -> dict:
        """Per symbol, a digest of its rows' analysis identities (pit candidate_id, else the row
        content), so a re-analysed bar opens a new series while an unchanged one is compacted."""
        parts: dict = {}
        for row in results:
            data = row["analysis_data"]
            raw = data if isinstance(data, str) else None
            if raw is not None:
                try:
                    data = json.loads(raw)
                except ValueError:
                    data = None
            pit = data.get("pit") if isinstance(data, Mapping) else None
            cid = pit.get("candidate_id") if isinstance(pit, Mapping) else None
            basis = cid or raw or json.dumps(data, sort_keys=True, default=str)
            parts.setdefault(row["symbol"], []).append(f"{row['timeframe']}|{basis}")
        return {s: hashlib.sha256("\n".join(sorted(v)).encode()).hexdigest()[:32]
                for s, v in parts.items()}

    def note(self, key: str, value) -> None:
        if self.cycle is not None:
            self.cycle.notes[key] = value

    def end(self, *, complete: bool = True) -> dict | None:
        cyc = self.cycle
        self.cycle, self._eligible = None, None
        if cyc is None:
            return None
        return cyc.finish(chain=self.chain, close_series=complete)

    def abort(self, exc: BaseException) -> dict | None:
        if self.cycle is not None:
            self.cycle.fail(f"cycle_exception:{type(exc).__name__}")
            self.chain = ()
        return self.end(complete=False)
