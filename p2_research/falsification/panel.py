"""P2-F0 evidence panel: the candidate's full eligible decision-row panel, rebuilt into positions BY P2-F0.

P2-F0 never trusts a candidate's own position list or metrics. It receives the row panel (every eligible decision row
of the evaluation window with the signal flag and the labels) and re-derives positions with the P2-D0 rule:

  * per (trial, symbol) at most one open position; a new entry only when flat;
  * time exit exactly at the trial horizon (no stop, no target);
  * flat again at ``t_entry + horizon`` (a row at exactly that time may enter).

Placebo signals (random entry, time shift, one-row lag) go through the same rule, so exposure and turnover are
built the same way as the candidate's.

Day clusters: positions are grouped by the eligible-day index of their ENTRY row. The cluster value of day d is the
equal-weight mean of the position returns entered on d. Positions entered on the same day share the BTC / market
common factor, so they are one observation, not many (pseudo-replication defence).
"""
from __future__ import annotations

import math
import random

SCEN_KEYS = {"EXEC-IDEALIZED": "net_idealized", "EXEC-BASE": "net_base", "EXEC-STRESS": "net_stress"}
HORIZON_MS = {"4h": 4 * 3600 * 1000, "24h": 24 * 3600 * 1000}
DAY_MS = 86400 * 1000
ROW_FIELDS = ("sym", "tier", "t_ms", "day", "elig", "sig", "feat_avail_ms", "entry_ms", "label_end_ms", "gross",
              "net_idealized", "net_base", "net_stress", "depth_ok_500")


class PanelError(ValueError):
    pass


def by_symbol(rows):
    out = {}
    for r in rows:
        out.setdefault(r["sym"], []).append(r)
    for v in out.values():
        v.sort(key=lambda r: r["t_ms"])
    return out


def build_positions(rows_by_sym: dict, flags: dict, horizon_ms: int):
    """Apply the P2-D0 position rule. ``flags`` maps (sym, t_ms) -> truthy for a signal. Returns entry rows."""
    out = []
    for sym in sorted(rows_by_sym):
        flat_at = -math.inf
        for r in rows_by_sym[sym]:
            if r["t_ms"] >= flat_at and flags.get((sym, r["t_ms"])):
                out.append(r)
                flat_at = r["t_ms"] + horizon_ms
    return out


def signal_flags(rows, key: str = "sig"):
    return {(r["sym"], r["t_ms"]): 1 for r in rows if r.get(key) and r.get("elig")}


def lag_flags(rows_by_sym: dict, flags: dict, lag: int = 1):
    """Signal of the ``lag``-th previous decision row of the same symbol (a stale signal acted on now)."""
    out = {}
    for sym, rs in rows_by_sym.items():
        for i in range(lag, len(rs)):
            if flags.get((sym, rs[i - lag]["t_ms"])) and rs[i].get("elig"):
                out[(sym, rs[i]["t_ms"])] = 1
    return out


def cluster_series(positions, key: str, days=None, impute=None):
    """Day-cluster series {day: mean of position[key]} over positions with a non-null value (or ``impute(r)`` for a
    null one when ``impute`` is given). Returns (sorted list of (day, value)), n_null)."""
    acc, n_null = {}, 0
    for r in positions:
        v = r.get(key)
        if v is None:
            n_null += 1
            if impute is None:
                continue
            v = impute(r)
        acc.setdefault(r["day"], []).append(v)
    items = sorted((d, math.fsum(v) / len(v)) for d, v in acc.items() if days is None or d in days)
    return items, n_null


def portfolio_series(positions, key: str, days):
    """Aligned per-day series over ALL ``days`` (cash = 0 on a day without entries)."""
    cl = dict(cluster_series(positions, key)[0])
    return [cl.get(d, 0.0) for d in sorted(days)]


def time_index(rows):
    """Sorted list of the distinct decision times of the panel and their index."""
    ts = sorted({r["t_ms"] for r in rows})
    return ts, {t: i for i, t in enumerate(ts)}


def shifted_flags(flags: dict, ts: list, tix: dict, k: int, elig_keys: set):
    """Circularly shift every symbol's signal series by ``k`` decision times on the common grid (a shifted signal
    landing on a non-eligible or missing row is dropped)."""
    n = len(ts)
    out = {}
    for (s, t), f in flags.items():
        if f:
            key = (s, ts[(tix[t] + k) % n])
            if key in elig_keys:
                out[key] = 1
    return out


def random_entry_flags(elig_by_tier: dict, count_by_tier: dict, rng: random.Random):
    """Exposure-matched random entry: per tier, as many random eligible rows as the candidate has positions in that
    tier (uniform over the evaluation window, without replacement); the position rule is applied afterwards."""
    out = {}
    for tier in sorted(count_by_tier):
        pool = elig_by_tier.get(tier, [])
        k = min(count_by_tier[tier], len(pool))
        for r in rng.sample(pool, k):
            out[(r["sym"], r["t_ms"])] = 1
    return out


def day_factors(rows):
    """Per evaluation day: (mean BTCUSDT gross label, mean gross label over all eligible rows) over the eligible rows
    with a non-null gross label. A day without a BTCUSDT row gives None for the BTC factor."""
    acc = {}
    for r in rows:
        if r.get("elig") and r.get("gross") is not None:
            a = acc.setdefault(r["day"], [[], []])
            a[1].append(r["gross"])
            if r["sym"] == "BTCUSDT":
                a[0].append(r["gross"])
    return {d: (math.fsum(b) / len(b) if b else None, math.fsum(m) / len(m)) for d, (b, m) in acc.items()}


def time_mean_gross(rows):
    """{t_ms: mean gross label over the eligible rows at that decision time} (the cross-section at T)."""
    acc = {}
    for r in rows:
        if r.get("elig") and r.get("gross") is not None:
            acc.setdefault(r["t_ms"], []).append(r["gross"])
    return {t: math.fsum(v) / len(v) for t, v in acc.items()}


def excess_positions(positions, tmean):
    """Copies of the positions whose net_base is replaced by net_base minus the time-matched cross-sectional mean
    gross (market-excess); a position without a cross-section keeps None."""
    out = []
    for p in positions:
        q = dict(p)
        m = tmean.get(p["t_ms"])
        q["net_base"] = None if (p["net_base"] is None or m is None) else p["net_base"] - m
        out.append(q)
    return out
