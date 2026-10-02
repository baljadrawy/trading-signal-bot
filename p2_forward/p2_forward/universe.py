"""Deterministic universe tiers (independent of trading activity and of any outcome). Rule version tiers-v2.

Tier 0: configured (BTCUSDT, ETHUSDT).
Tier 1: SPOT USDT pairs with status TRADING, base not a stablecoin/fiat, ASCII alphanumeric symbol, valid 24h
        ticker, quoteVolume >= threshold; top `tier1_max` by quote volume; plus hysteresis members (prior Tier 1/2
        members still eligible except for volume/rank) when a prior universe within `tier1_hysteresis_days` exists.
Tier 2: top `tier2_top_volume` of Tier 1 by quote volume + top `tier2_top_movers` by |24h change|, deduped, <= max.
A symbol belongs to its highest tier only.

R04: every evaluation persists, for EVERY candidate (each USDT-quoted symbol reported by exchangeInfo, any status,
plus USDT tickers absent from exchangeInfo), its raw ranking inputs, eligibility, exclusion reason, volume rank,
tier and hysteresis reason, so "which symbols were eligible at T and why" is answerable from the artifact alone.
F42: REST inputs are sanity-checked (`validate_inputs`) before they may become authoritative.
"""
from __future__ import annotations

import hashlib
import json
import math

RULE_VERSION = "tiers-v2"


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def validate_inputs(cfg: dict, exchange_info, tickers) -> tuple:
    """F42 sanity checks. Returns (ok, problems, stats). Any problem => the response is NOT authoritative."""
    problems, stats = [], {}
    if not isinstance(exchange_info, dict) or not isinstance(exchange_info.get("symbols"), list):
        return False, ["exchangeinfo_malformed"], stats
    if not isinstance(tickers, list):
        return False, ["ticker_malformed"], stats
    ei_syms, dup_ei, bad_ei = set(), 0, 0
    usdt_trading = set()
    for s in exchange_info["symbols"]:
        if not (isinstance(s, dict) and all(isinstance(s.get(k), str) and s.get(k) for k in ("symbol", "status", "baseAsset", "quoteAsset"))):
            bad_ei += 1; continue
        if s["symbol"] in ei_syms:
            dup_ei += 1
        ei_syms.add(s["symbol"])
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING":
            if not s["symbol"].endswith("USDT") or s["symbol"] != s["baseAsset"] + "USDT":
                problems.append(f"symbol_quote_inconsistent:{s['symbol']}")
            usdt_trading.add(s["symbol"])
    tk_syms, dup_tk, bad_tk = set(), 0, 0
    valid_tk = set()
    for t in tickers:
        if not (isinstance(t, dict) and isinstance(t.get("symbol"), str) and t["symbol"]):
            bad_tk += 1; continue
        if t["symbol"] in tk_syms:
            dup_tk += 1
        tk_syms.add(t["symbol"])
        qv, o, c = _num(t.get("quoteVolume")), _num(t.get("openPrice")), _num(t.get("lastPrice"))
        if qv is not None and qv >= 0 and o is not None and o >= 0 and c is not None and c >= 0:
            valid_tk.add(t["symbol"])
    # M3: reverse completeness — a liquid USDT ticker absent from exchangeInfo means exchangeInfo is partial
    missing_liquid = sorted(t["symbol"] for t in tickers if isinstance(t, dict) and isinstance(t.get("symbol"), str)
                            and t["symbol"].endswith("USDT") and t["symbol"] not in ei_syms
                            and (_num(t.get("quoteVolume")) or 0) >= cfg["tier1_min_quote_volume"])
    if missing_liquid:
        problems.append(f"liquid_ticker_missing_from_exchangeinfo:{len(missing_liquid)}:{','.join(missing_liquid[:5])}")
    st = {s["symbol"]: s.get("status") for s in exchange_info["symbols"] if isinstance(s, dict) and isinstance(s.get("symbol"), str)}
    for t0 in cfg["tier0"]:                                         # m6: Tier 0 must be TRADING with a valid ticker
        if st.get(t0) != "TRADING" or t0 not in valid_tk:
            problems.append(f"tier0_unavailable:{t0}")
    stats = {"exchangeinfo_symbols": len(ei_syms), "liquid_tickers_missing_from_exchangeinfo": len(missing_liquid), "usdt_trading": len(usdt_trading), "tickers": len(tk_syms),
             "tickers_valid": len(valid_tk), "dup_exchangeinfo": dup_ei, "dup_tickers": dup_tk,
             "malformed_exchangeinfo_entries": bad_ei, "malformed_ticker_entries": bad_tk}
    if not exchange_info["symbols"] or not tickers:
        problems.append("empty_result")
    if dup_ei or dup_tk:
        problems.append(f"duplicate_symbols:{dup_ei}/{dup_tk}")
    if bad_ei or bad_tk:
        problems.append(f"malformed_entries:{bad_ei}/{bad_tk}")
    if len(usdt_trading) < cfg["universe_min_usdt_trading"]:
        problems.append(f"too_few_usdt_trading:{len(usdt_trading)}<{cfg['universe_min_usdt_trading']}")
    cov = len(usdt_trading & valid_tk) / max(1, len(usdt_trading))
    stats["ticker_coverage"] = round(cov, 4)
    if cov < cfg["universe_min_ticker_coverage"]:
        problems.append(f"ticker_coverage:{cov:.3f}<{cfg['universe_min_ticker_coverage']}")
    invalid = len((usdt_trading & tk_syms) - valid_tk) / max(1, len(usdt_trading))
    stats["ticker_invalid_fraction"] = round(invalid, 4)
    if invalid > cfg["universe_max_invalid_fraction"]:
        problems.append(f"invalid_numeric_fraction:{invalid:.3f}")
    return not problems, problems, stats


def evaluate(cfg: dict, exchange_info: dict, tickers: list, prior: dict | None = None) -> dict:
    """Deterministic tier evaluation with a full per-candidate record (R04). `prior` = previous trustworthy
    universe (for hysteresis), only if evaluated within `tier1_hysteresis_days`."""
    tier0 = sorted(cfg["tier0"])
    stable = set(cfg["stable_bases"])
    ei = {s["symbol"]: s for s in exchange_info.get("symbols", []) if isinstance(s, dict) and s.get("quoteAsset") == "USDT"}
    tk = {t["symbol"]: t for t in tickers if isinstance(t, dict) and isinstance(t.get("symbol"), str)}
    names = sorted(set(ei) | {s for s in tk if s.endswith("USDT")} | set(tier0))
    cand = {}
    for sym in names:
        e, t = ei.get(sym), tk.get(sym)
        qv = _num(t.get("quoteVolume")) if t else None
        o = _num(t.get("openPrice")) if t else None
        c = _num(t.get("lastPrice")) if t else None
        change = (c / o - 1.0) if (o and c is not None and o > 0) else (0.0 if t else None)   # unrounded for ranking
        rec = {"symbol": sym, "status": e.get("status") if e else None, "base": e.get("baseAsset") if e else None,
               "in_exchangeinfo": e is not None, "in_ticker": t is not None,
               "quote_volume_raw": t.get("quoteVolume") if t else None, "open_raw": t.get("openPrice") if t else None,
               "last_raw": t.get("lastPrice") if t else None, "quote_volume": qv,
               "change": change,
               "eligible": False, "excluded_reason": None, "volume_rank": None, "tier": None, "hysteresis_reason": None}
        if sym in tier0:
            rec["excluded_reason"] = None if e and e.get("status") == "TRADING" else "tier0_not_trading"
        elif e is None:
            rec["excluded_reason"] = "not_in_exchangeinfo_spot"
        elif e.get("status") != "TRADING":
            rec["excluded_reason"] = f"status_{e.get('status')}"
        elif e.get("baseAsset") in stable:
            rec["excluded_reason"] = "stable_or_fiat_base"
        elif not (sym.isascii() and sym.isalnum()):
            rec["excluded_reason"] = "non_ascii_or_non_alnum"
        elif t is None:
            rec["excluded_reason"] = "no_ticker"
        elif qv is None or o is None or c is None or qv < 0:
            rec["excluded_reason"] = "invalid_ticker"
        else:
            rec["eligible"] = True                                  # eligible except for volume/rank
        cand[sym] = rec
    eligible = [s for s, r in cand.items() if r["eligible"]]
    by_vol = sorted(eligible, key=lambda s: (-cand[s]["quote_volume"], s))
    for i, s in enumerate(by_vol, 1):
        cand[s]["volume_rank"] = i
    above = [s for s in by_vol if cand[s]["quote_volume"] >= cfg["tier1_min_quote_volume"]]
    tier1 = above[: cfg["tier1_max"]]
    for s in by_vol:
        if s not in tier1:
            cand[s]["excluded_reason"] = "rank_cut" if cand[s]["quote_volume"] >= cfg["tier1_min_quote_volume"] else "below_min_quote_volume"
    prior_members = set((prior or {}).get("tier1", [])) | set((prior or {}).get("tier2", []))
    hyst = sorted(s for s in prior_members if s in cand and cand[s]["eligible"] and s not in tier1 and s not in tier0)
    for s in hyst:
        cand[s]["hysteresis_reason"] = f"prior_member:{(prior or {}).get('universe_id')}"
        cand[s]["excluded_reason"] = None
    t1_all = set(tier1) | set(hyst)
    vol2 = sorted(t1_all, key=lambda s: (-cand[s]["quote_volume"], s))[: cfg["tier2_top_volume"]]
    movers = sorted(t1_all - set(vol2), key=lambda s: (-abs(cand[s]["change"]), s))[: cfg["tier2_top_movers"]]
    tier2 = sorted((vol2 + movers)[: cfg["tier2_max"]])
    tier1_only = sorted(t1_all - set(tier2))
    for s in tier0:
        cand[s]["tier"] = 0
    for s in tier2:
        cand[s]["tier"] = 2
    for s in tier1_only:
        cand[s]["tier"] = 1
    inputs = hashlib.sha256(json.dumps([[s, cand[s]["status"], cand[s]["base"], cand[s]["quote_volume_raw"],
                                         cand[s]["open_raw"], cand[s]["last_raw"]] for s in names]).encode()).hexdigest()
    return {"rule_version": RULE_VERSION, "tier0": tier0, "tier1": tier1_only, "tier2": tier2,
            "hysteresis_members": hyst, "eligible_count": len(eligible), "candidate_count": len(names),
            "inputs_sha256": inputs, "prior_universe_id": (prior or {}).get("universe_id"),
            "thresholds": {"min_quote_volume": cfg["tier1_min_quote_volume"], "tier1_max": cfg["tier1_max"],
                           "tier2": [cfg["tier2_top_volume"], cfg["tier2_top_movers"], cfg["tier2_max"]],
                           "hysteresis_days": cfg["tier1_hysteresis_days"], "stable_bases": sorted(stable)},
            "ranking": "quote_volume desc, symbol asc; movers by |last/open - 1| desc, symbol asc",
            "candidates": [cand[s] for s in names]}


def plausible_vs_prior(cfg: dict, new: dict, prior: dict | None) -> list:
    """F42: a refresh that changes Tier 1 by more than the allowed fraction is suspicious (not authoritative)."""
    if not prior or not prior.get("tier1") and not prior.get("tier2"):
        return []
    old = set(prior.get("tier1", [])) | set(prior.get("tier2", []))
    nw = set(new["tier1"]) | set(new["tier2"])
    changed = len(old ^ nw) / max(1, len(old))
    return [f"tier1_change:{changed:.2f}>{cfg['universe_max_tier1_change']}"] if changed > cfg["universe_max_tier1_change"] else []


def refresh_decision(previous: dict | None, new: dict | None, problems: list) -> tuple:
    """F42 deterministic refresh policy. Returns (universe_to_use, degraded, action).
    - trustworthy new result => use it, not degraded;
    - untrustworthy result with a previous trustworthy universe => keep previous, DEGRADED until a refresh succeeds;
    - untrustworthy result and no previous universe (initial load) => no universe (fail closed, F25)."""
    if new is not None and not problems:
        return new, False, "accepted"
    if previous is not None:
        return previous, True, "kept_previous_degraded"
    return None, True, "fail_closed"


def tier0_only(cfg: dict) -> dict:
    t0 = sorted(cfg["tier0"])
    return {"rule_version": RULE_VERSION, "tier0": t0, "tier1": [], "tier2": [], "hysteresis_members": [],
            "eligible_count": None, "candidate_count": len(t0), "inputs_sha256": None, "profile": "tier0_only",
            "prior_universe_id": None,
            "candidates": [{"symbol": s, "tier": 0, "eligible": True, "excluded_reason": None, "configured": True}
                           for s in t0]}


def compute(cfg: dict, exchange_info: dict, tickers: list, prior_tier1: set | None = None) -> dict:
    """Compatibility wrapper (tiers-v1 call shape) around `evaluate`."""
    prior = {"tier1": sorted(prior_tier1), "tier2": [], "universe_id": "legacy_prior_set"} if prior_tier1 else None
    return evaluate(cfg, exchange_info, tickers, prior)
