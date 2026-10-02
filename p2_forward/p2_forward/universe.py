"""Deterministic universe tiers (independent of trading activity and of any outcome).

Tier 0: configured (BTCUSDT, ETHUSDT).
Tier 1: SPOT USDT pairs with status TRADING, base not a stablecoin/fiat, ASCII symbol, 24h quoteVolume >=
        threshold; top `tier1_max` by quote volume; plus 7-day hysteresis members still TRADING.
Tier 2: top `tier2_top_volume` of Tier 1 by quote volume + top `tier2_top_movers` by |24h change|, deduped, <= max.
A symbol belongs to its highest tier only.
"""
from __future__ import annotations

import hashlib
import json

RULE_VERSION = "tiers-v1"


def compute(cfg: dict, exchange_info: dict, tickers: list, prior_tier1: set | None = None) -> dict:
    tier0 = list(cfg["tier0"])
    stable = set(cfg["stable_bases"])
    eligible = {}
    for s in exchange_info.get("symbols", []):
        sym = s.get("symbol", "")
        if (s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT" and s.get("baseAsset") not in stable
                and sym.isascii() and sym.isalnum()):
            eligible[sym] = s
    stats = {}
    for t in tickers:
        sym = t.get("symbol")
        if sym in eligible:
            try:
                qv, o, c = float(t["quoteVolume"]), float(t["openPrice"]), float(t["lastPrice"])
            except (KeyError, TypeError, ValueError):
                continue
            stats[sym] = (qv, (c / o - 1.0) if o > 0 else 0.0)
    ranked = sorted((s for s in stats if stats[s][0] >= cfg["tier1_min_quote_volume"] and s not in tier0),
                    key=lambda s: (-stats[s][0], s))
    tier1 = ranked[: cfg["tier1_max"]]
    hysteresis = sorted(s for s in (prior_tier1 or set()) if s in eligible and s not in tier1 and s not in tier0)
    tier1_all = tier1 + hysteresis
    t1_set = set(tier1_all)
    by_vol = [s for s in sorted(t1_set, key=lambda s: (-stats.get(s, (0, 0))[0], s))][: cfg["tier2_top_volume"]]
    movers = [s for s in sorted(t1_set - set(by_vol), key=lambda s: (-abs(stats.get(s, (0, 0))[1]), s))][: cfg["tier2_top_movers"]]
    tier2 = sorted((by_vol + movers)[: cfg["tier2_max"]])
    tier1_only = sorted(t1_set - set(tier2))
    inputs = hashlib.sha256(json.dumps({"syms": sorted(eligible), "stats": {k: stats[k] for k in sorted(stats)}},
                                       sort_keys=True).encode()).hexdigest()
    return {"rule_version": RULE_VERSION, "tier0": sorted(tier0), "tier1": tier1_only, "tier2": tier2,
            "hysteresis_members": hysteresis, "eligible_count": len(eligible), "inputs_sha256": inputs,
            "thresholds": {"min_quote_volume": cfg["tier1_min_quote_volume"], "tier1_max": cfg["tier1_max"],
                           "tier2": [cfg["tier2_top_volume"], cfg["tier2_top_movers"], cfg["tier2_max"]]}}


def tier0_only(cfg: dict) -> dict:
    return {"rule_version": RULE_VERSION, "tier0": sorted(cfg["tier0"]), "tier1": [], "tier2": [],
            "hysteresis_members": [], "eligible_count": None, "inputs_sha256": None, "profile": "tier0_only"}
