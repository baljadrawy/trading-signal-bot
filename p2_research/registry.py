"""Versioned, machine-readable feature registry (P2-C feature set v1).

Every feature computed by ``features.py`` MUST be listed here and vice versa (tested). The JSON export
``registry/feature_registry_v1.json`` is generated from this module (``python -m p2_research.registry --write``)
and its SHA-256 is recorded in every dataset manifest. Statuses: experimental | candidate | accepted | rejected.
All v1 features start as ``experimental``: none has been evaluated, and none may be promoted without a separately
authorized, predeclared evaluation (no W3 data, no Paper outcomes).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

FEATURE_SET_ID = "p2c-fs"
FEATURE_SET_VERSION = "1.0.0"
STATUSES = ("experimental", "candidate", "accepted", "rejected")
DECISION_GRID = {"id": "grid-15m-plus390s-v1", "step_ms": 900_000, "offset_ms": 390_000,
                 "why": "15m boundary + 390 s >= candle fetch margin (15 s offset + 300 s spread + 60 s fetch)"}

_CANDLE_PIT = "candle.available_at_ms <= T and close_ms < T; the latest CLOSED candle (close boundary <= T) must be available"
_CANDLE_MISS = "null + reason: latest_closed_candle_unavailable | insufficient_history | candle_history_gap | zero_range"
_BOOK_PIT = "latest book sample with available_at_ms (= observed_at_ms <= sample_ms) <= T, same run, age <= tier stale limit"
_BOOK_MISS = "null + reason: no_observation | book_stale | from_previous_run | insufficient_history"
_DEPTH_PIT = "latest depth sample with available_at_ms <= T, same run, age <= depth_by_tier stale limit"
_DEPTH_MISS = "null + reason: no_observation | depth_stale | from_previous_run | empty_book"
_MKT_PIT = "latest market snapshot with available_at_ms <= T, startup_complete, T - observed <= 70 s; universe = epoch known at T"
_MKT_MISS = "null + reason: no_market_snapshot | market_stale | market_startup_incomplete | too_few_symbols | symbol_absent"
_ALL = [0, 1, 2]


def _f(fid, family, source, formula, hist, rng, pit, miss, norm="none", cost="O(1)", sampling="per decision",
       delay="0 (uses only inputs available at T)", tiers=None, status="experimental"):
    return {"id": fid, "version": 1, "family": family, "source": source, "formula": formula,
            "required_history": hist, "sampling_frequency": sampling, "availability_delay": delay,
            "missing_data_behavior": miss, "normalization": norm, "expected_range": rng, "pit_rule": pit,
            "tier_applicability": tiers or _ALL, "cost": cost, "status": status}


_CD = "candle available_at = max(close+1, observed); fetched ~B+5..315 s"
FEATURES = [
    # ---------------- price / momentum ----------------
    _f("mom.ret_15m_1", "price_momentum", "candle:15m", "ln(c[t]/c[t-1])", "2 closed 15m", [-0.5, 0.5], _CANDLE_PIT, _CANDLE_MISS, delay=_CD),
    _f("mom.ret_1h_1", "price_momentum", "candle:1h", "ln(c[t]/c[t-1])", "2 closed 1h", [-0.7, 0.7], _CANDLE_PIT, _CANDLE_MISS, delay=_CD),
    _f("mom.ret_4h_1", "price_momentum", "candle:4h", "ln(c[t]/c[t-1])", "2 closed 4h", [-1, 1], _CANDLE_PIT, _CANDLE_MISS, delay=_CD),
    _f("mom.ret_1d_1", "price_momentum", "candle:1d", "ln(c[t]/c[t-1])", "2 closed 1d", [-1.5, 1.5], _CANDLE_PIT, _CANDLE_MISS, delay=_CD),
    _f("mom.mom_norm_15m_16", "price_momentum", "candle:15m", "ln(c[t]/c[t-16]) / (rv_15m_16 * sqrt(16))", "17 closed 15m",
       [-10, 10], _CANDLE_PIT, _CANDLE_MISS + " | zero_vol", norm="volatility-scaled", cost="O(16)", delay=_CD),
    _f("mom.dist_high_15m_96", "price_momentum", "candle:15m", "ln(c[t] / max(h[t-95..t]))", "96 closed 15m (24 h)", [-1, 0],
       _CANDLE_PIT, _CANDLE_MISS, cost="O(96)", delay=_CD),
    _f("mom.dist_low_15m_96", "price_momentum", "candle:15m", "ln(c[t] / min(l[t-95..t]))", "96 closed 15m (24 h)", [0, 2],
       _CANDLE_PIT, _CANDLE_MISS, cost="O(96)", delay=_CD),
    _f("mom.trend_eff_1h_24", "price_momentum", "candle:1h", "|ln(c[t]/c[t-24])| / sum_i |ln(c[i]/c[i-1])| (efficiency ratio)",
       "25 closed 1h", [0, 1], _CANDLE_PIT, _CANDLE_MISS + " | zero_path", norm="ratio", cost="O(24)", delay=_CD),
    _f("mom.body_ratio_15m", "price_momentum", "candle:15m", "(c-o)/(h-l) of the last closed 15m", "1 closed 15m", [-1, 1],
       _CANDLE_PIT, _CANDLE_MISS, norm="ratio", delay=_CD),
    _f("mom.range_rel_15m", "price_momentum", "candle:15m", "(h-l)/c of the last closed 15m", "1 closed 15m", [0, 0.5],
       _CANDLE_PIT, _CANDLE_MISS, norm="price-relative", delay=_CD),
    # ---------------- volatility ----------------
    _f("vol.rv_15m_16", "volatility", "candle:15m", "sample stdev of 16 close-to-close log returns", "17 closed 15m", [0, 0.2],
       _CANDLE_PIT, _CANDLE_MISS, cost="O(16)", delay=_CD),
    _f("vol.rv_1h_24", "volatility", "candle:1h", "sample stdev of 24 close-to-close log returns", "25 closed 1h", [0, 0.3],
       _CANDLE_PIT, _CANDLE_MISS, cost="O(24)", delay=_CD),
    _f("vol.atr_norm_1h_14", "volatility", "candle:1h", "mean(true range over 14) / c[t]", "15 closed 1h", [0, 0.3],
       _CANDLE_PIT, _CANDLE_MISS, norm="price-relative", cost="O(14)", delay=_CD),
    _f("vol.vol_ratio_15m_16_96", "volatility", "candle:15m", "rv over last 16 / rv over last 96 returns", "97 closed 15m",
       [0, 10], _CANDLE_PIT, _CANDLE_MISS + " | zero_vol", norm="ratio", cost="O(96)", delay=_CD),
    _f("vol.range_expansion_15m_16", "volatility", "candle:15m", "(h-l)[t] / mean((h-l)[t-16..t-1])", "17 closed 15m",
       [0, 20], _CANDLE_PIT, _CANDLE_MISS, norm="ratio", cost="O(16)", delay=_CD),
    # ---------------- liquidity / microstructure (forward data) ----------------
    _f("liq.spread_bps", "liquidity", "book", "(ask-bid)/mid * 1e4", "1 fresh book sample", [0, 500], _BOOK_PIT, _BOOK_MISS),
    _f("liq.spread_norm_1h", "liquidity", "book", "spread_bps(T) / median(spread_bps of samples in (T-1h, T])",
       ">= 10 book samples in the last hour", [0, 50], _BOOK_PIT, _BOOK_MISS + " | zero_spread_median", norm="ratio",
       cost="O(samples/h)"),
    _f("liq.tob_imbalance", "liquidity", "book", "(bid_qty-ask_qty)/(bid_qty+ask_qty)", "1 fresh book sample", [-1, 1],
       _BOOK_PIT, _BOOK_MISS, norm="ratio"),
    _f("liq.depth_imbalance_10", "liquidity", "depth", "(bidN-askN)/(bidN+askN), N = notional of first 10 levels",
       "1 fresh depth sample", [-1, 1], _DEPTH_PIT, _DEPTH_MISS, norm="ratio"),
    _f("liq.depth_concentration_10", "liquidity", "depth", "(bid1+ask1 notional) / (bidN+askN)", "1 fresh depth sample",
       [0, 1], _DEPTH_PIT, _DEPTH_MISS, norm="ratio"),
    _f("liq.spread_change_5m_bps", "liquidity", "book", "spread_bps(T) - spread_bps(T-5m)", "fresh samples at T and T-5m",
       [-500, 500], _BOOK_PIT, _BOOK_MISS),
    _f("liq.liq_change_15m", "liquidity", "depth", "ln(N(T)/N(T-15m)), N = bid+ask notional of first 10 levels",
       "fresh depth at T and T-15m", [-5, 5], _DEPTH_PIT, _DEPTH_MISS, norm="log-ratio"),
    # ---------------- volume / activity ----------------
    _f("act.rel_volume_15m_96", "volume", "candle:15m", "qv[t] / mean(qv[t-96..t-1])", "97 closed 15m", [0, 100],
       _CANDLE_PIT, _CANDLE_MISS + " | zero_volume", norm="ratio", cost="O(96)", delay=_CD),
    _f("act.volume_accel_15m_4", "volume", "candle:15m", "ln(sum qv[t-3..t] / sum qv[t-7..t-4])", "8 closed 15m", [-10, 10],
       _CANDLE_PIT, _CANDLE_MISS + " | zero_volume", norm="log-ratio", delay=_CD),
    _f("act.volume_price_15m", "volume", "candle:15m", "sign(ret_15m_1) * ln(1 + qv[t]/mean(qv[t-16..t-1]))", "17 closed 15m",
       [-10, 10], _CANDLE_PIT, _CANDLE_MISS + " | zero_volume", cost="O(16)", delay=_CD),
    # ---------------- market context ----------------
    _f("ctx.btc_ret_1h_1", "market_context", "candle:1h BTCUSDT", "ln(c[t]/c[t-1]) of BTCUSDT", "2 closed 1h", [-0.5, 0.5],
       _CANDLE_PIT, _CANDLE_MISS, delay=_CD),
    _f("ctx.btc_rv_1h_24", "market_context", "candle:1h BTCUSDT", "rv_1h_24 of BTCUSDT", "25 closed 1h", [0, 0.3],
       _CANDLE_PIT, _CANDLE_MISS, cost="O(24)", delay=_CD),
    _f("ctx.breadth_24h", "market_context", "market", "fraction of universe-at-T symbols with miniTicker c > o (rolling 24 h)",
       ">= 5 universe symbols in the snapshot", [0, 1], _MKT_PIT, _MKT_MISS, norm="fraction", cost="O(universe)"),
    _f("ctx.universe_ret_24h_median", "market_context", "market", "median over universe-at-T of ln(c/o) (rolling 24 h)",
       ">= 5 universe symbols", [-1, 1], _MKT_PIT, _MKT_MISS, cost="O(universe log universe)"),
    _f("ctx.universe_disp_24h", "market_context", "market", "population stdev over universe-at-T of ln(c/o)",
       ">= 5 universe symbols", [0, 1], _MKT_PIT, _MKT_MISS, cost="O(universe)"),
    _f("ctx.xs_rank_ret_24h", "market_context", "market", "(#{r < r_s} + 0.5 #{r = r_s, other}) / (n-1), r = ln(c/o)",
       ">= 5 universe symbols incl. the symbol", [0, 1], _MKT_PIT, _MKT_MISS, norm="rank", cost="O(universe)"),
    _f("ctx.tier", "market_context", "universe epoch", "tier of the symbol in the epoch KNOWN at T (effective_from <= T and "
       "announcing record available <= T); never a later/retrospective tier", "1 epoch", [0, 2],
       "epoch.effective_from_ms <= T and epoch.available_at_ms <= T", "row excluded if no epoch known (no_universe_epoch_known)"),
    # ---------------- data quality (exposed, never hidden) ----------------
    _f("dq.book_age_s", "data_quality", "book", "(T - observed_at_ms of the latest book sample) / 1000", "none", [0, 86400],
       "available_at_ms <= T", "null + reason: no_observation | from_previous_run"),
    _f("dq.depth_age_s", "data_quality", "depth", "(T - observed_at_ms of the latest depth sample) / 1000", "none", [0, 86400],
       "available_at_ms <= T", "null + reason: no_observation | from_previous_run"),
    _f("dq.stale_flag", "data_quality", "book+depth", "1 if book or depth is missing, from a previous run, or older than its "
       "stale limit (book: tier0 120 s, tier1/2 suspect 120 s; depth: by tier), else 0", "none", [0, 1],
       "available_at_ms <= T", "never null"),
    _f("dq.gap_known_1h", "data_quality", "gap records", "count of gap records (book|S, depth|S, candle|*|S, market|ALL) with "
       "available_at_ms <= T overlapping (T-1h, T]; a gap is KNOWN only after it closed (SCHEMA section 5)", "none", [0, 1000],
       "gap.available_at_ms <= T", "never null", cost="O(gaps)"),
    _f("dq.reconnect_age_s", "data_quality", "lifecycle", "seconds since the latest ws_connected/ws_disconnected/"
       "ws_connect_failed of the current run known at T (else since ws_start), capped 86400", "none", [0, 86400],
       "lifecycle.available_at_ms <= T", "null + reason: no_run_at_T"),
    _f("dq.run_age_s", "data_quality", "runs/downtime", "seconds since the current run's ws_start, capped 2592000", "none",
       [0, 2592000], "ws_start <= T (downtime.until_ms)", "null + reason: no_run_at_T"),
    _f("dq.degraded_flag", "data_quality", "health", "1 if the latest health record known at T is not HEALTHY or lists one "
       "of the symbol's streams as not observing, else 0", "none", [0, 1], "health.available_at_ms <= T",
       "null + reason: no_health_record (fail closed)"),
    _f("dq.clock_suspect", "data_quality", "clock+book+depth", "1 if the latest clock record known at T, or the book/depth "
       "sample used, is clock_suspect, else 0", "none", [0, 1], "available_at_ms <= T", "never null"),
]


def registry_doc() -> dict:
    ids = [f["id"] for f in FEATURES]
    assert len(ids) == len(set(ids)), "duplicate feature id"
    assert all(f["status"] in STATUSES for f in FEATURES)
    return {"record": "tsb.p2c.feature_registry", "record_version": 1, "feature_set_id": FEATURE_SET_ID,
            "feature_set_version": FEATURE_SET_VERSION, "decision_grid": DECISION_GRID,
            "pit_contract": "every feature value carries feature_available_at; a value is usable only if "
                            "feature_available_at <= decision_time (enforced by the builder, PITViolation otherwise)",
            "features": FEATURES}


def registry_json() -> str:
    return json.dumps(registry_doc(), sort_keys=True, indent=1) + "\n"


def registry_sha256() -> str:
    return hashlib.sha256(registry_json().encode()).hexdigest()


def registry_markdown() -> str:
    """Human-readable table generated from the registry (docs/p2/P2C_FEATURE_REGISTRY.md)."""
    out = [f"# P2-C feature registry ({FEATURE_SET_ID} {FEATURE_SET_VERSION})", "",
           "Generated by `python -m p2_research.registry --markdown`; the machine-readable source of truth is "
           "`p2_research/registry/feature_registry_v1.json` (SHA-256 recorded in every dataset manifest).", "",
           f"Decision grid: `{DECISION_GRID['id']}` ({DECISION_GRID['why']}). All features: status `experimental`, "
           "tiers 0/1/2, version 1. Missing inputs give null plus a reason; nothing is filled or interpolated.", "",
           "| id | family | source | formula | history | range | missing / PIT |", "|---|---|---|---|---|---|---|"]
    for f in FEATURES:
        cell = lambda x: str(x).replace("|", "/")
        out.append(f"| `{f['id']}` | {f['family']} | {cell(f['source'])} | {cell(f['formula'])} | "
                   f"{cell(f['required_history'])} | {f['expected_range']} | {cell(f['missing_data_behavior'])}; "
                   f"PIT: {cell(f['pit_rule'])} |")
    return "\n".join(out) + "\n"


REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry", "feature_registry_v1.json")

if __name__ == "__main__":
    if "--write" in sys.argv:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as fh:
            fh.write(registry_json())
    if "--markdown" in sys.argv:
        sys.stdout.write(registry_markdown())
    else:
        print(json.dumps({"features": len(FEATURES), "sha256": registry_sha256()}))
