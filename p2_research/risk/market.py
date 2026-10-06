"""PIT market inputs for risk measurement: the P2-X market state (books, depth ladders, control records) plus CLOSED
candles, behind one view truncated at the snapshot time.

Adapter: ``load_risk_market`` reads SEALED days through ``p2_research.execution.market_state.load_sealed`` (all the
P2-C reader verification) and collects candle records through its read-only ``observer`` side channel using the P2-C
reader's own candle ingest (identity, alignment, idempotent re-fetch keeps the earliest availability, conflicting
content fails closed). Read-only; stdlib only; never imports ``p2_forward``.

PIT: ``RiskView(market, T)`` is the only data path of the metrics. Every accessor refuses ``t > T`` and re-asserts
``available_at_ms <= T`` (and ``close_ms < T`` for candles) on every returned element, so a leaky source raises
``PITViolation``. W3 (RM0-METRICS w3): a book / depth record available inside W3 is masked; a candle whose interval
starts before the W3 end is masked; a snapshot time inside W3 is refused.
"""
from __future__ import annotations

import bisect

from .. import reader as RD
from ..execution import market_state as MS
from ..execution import model as XM
from ..execution import quality as XQ
from ..execution.market_state import PITMarketView, PITViolation

CANDLE = ("open_ms", "open", "high", "low", "close", "volume", "close_ms", "quote_volume", "available_at_ms",
          "clock_suspect")
RISK_LOADER_VERSION = "p2rm-market-v1"


def in_w3(t_ms) -> bool:
    return XM.W3_START_US <= t_ms * 1000 < XM.W3_END_US


def w3_masked(open_ms: int, close_ms: int) -> bool:
    """True when the candle interval [open_ms, close_ms] overlaps W3 = [W3_START, W3_END)."""
    return open_ms * 1000 < XM.W3_END_US and close_ms * 1000 >= XM.W3_START_US


class RiskMarket:
    """Market state + candles. ``candles[(symbol, tf)]`` = list of CANDLE tuples sorted by open_ms."""

    def __init__(self, state: MS.ForwardMarketState, candles: dict, meta: dict | None = None):
        self.state = state
        self.candles = {k: sorted(v, key=lambda c: c[0]) for k, v in candles.items()}
        self._opens = {k: [c[0] for c in v] for k, v in self.candles.items()}
        self.meta = dict(state.meta)
        self.meta["risk_loader_version"] = RISK_LOADER_VERSION
        if meta:
            self.meta.update(meta)

    def candles_between(self, sym: str, tf: str, lo_open: int, hi_open: int, t: int) -> list:
        """Source accessor: candles with lo_open <= open <= hi_open, available at t and closed before t."""
        k = (sym, tf)
        if k not in self.candles:
            return []
        ks = self._opens[k]
        seg = self.candles[k][bisect.bisect_left(ks, lo_open):bisect.bisect_right(ks, hi_open)]
        return [c for c in seg if c[8] <= t and c[6] < t]


class RiskView:
    """Everything a snapshot at T may see."""

    def __init__(self, market: RiskMarket, t_ms: int):
        XM.require_outside_w3(int(t_ms), "snapshot_time")
        self.M, self.T = market, int(t_ms)
        self.pv = PITMarketView(market.state, self.T)
        self.audit = {"w3_masked_candles": 0, "w3_masked_records": 0}

    def _guard(self, t):
        if t > self.T:
            raise PITViolation(f"access at {t} > snapshot time {self.T}")

    # ---------------- candles ----------------
    def closed_candles(self, sym: str, tf: str, lo_open: int, hi_open: int) -> tuple:
        """({open_ms: CANDLE}, n_w3_masked) of closed, available, non-W3 candles with open in [lo_open, hi_open]."""
        self._guard(hi_open)
        out, masked = {}, 0
        for c in self.M.candles_between(sym, tf, lo_open, hi_open, self.T):
            if c[8] > self.T or c[6] >= self.T:
                raise PITViolation(f"candle source returned {sym} {tf} {c[0]} available {c[8]} / close {c[6]} at T={self.T}")
            if w3_masked(c[0], c[6]):
                masked += 1
                continue
            out[c[0]] = c
        self.audit["w3_masked_candles"] += masked
        return out, masked

    # ---------------- books / depth / control (P2-X PIT view) ----------------
    def book(self, sym: str):
        rec = self.pv.book(sym, self.T)
        if rec is not None and in_w3(rec[0]):
            self.audit["w3_masked_records"] += 1
            return None
        return rec

    def depth(self, sym: str):
        rec = self.pv.depth(sym, self.T)
        if rec is not None and in_w3(rec[0]):
            self.audit["w3_masked_records"] += 1
            return None
        return rec

    def classify(self, kind: str, sym: str, rec) -> dict:
        """P2-X X1-STALE-POLICY / X1-DQ classification at T (same implementation as X0, rules identical)."""
        return XQ.classify(self.pv, kind, sym, self.T, rec)

    def epoch(self):
        return self.pv.epoch_at(self.T)

    def tiers(self) -> dict:
        e = self.epoch()
        return dict(e["tiers"]) if e else {}


# ====================================================================== sealed-day adapter ======
class _CandleObserver:
    """Collects candle records with the P2-C reader's candle semantics (read-only side channel)."""

    def __init__(self):
        self.B = RD.Bundle()

    def __call__(self, r):
        if r["type"] == "candle":
            RD._ingest(self.B, r, {})


def load_risk_market(base: str, days: list, query_times) -> RiskMarket:
    """Load SEALED consecutive days (P2-X loader, pruned to ``query_times``) plus every candle."""
    obs = _CandleObserver()
    S = MS.load_sealed(base, days, query_times=query_times, observer=obs)
    candles = {k: sorted(v.values(), key=lambda c: c[0]) for k, v in obs.B.candles.items()}
    M = RiskMarket(S, candles)
    M.quality = dict(S.quality)
    M.quality.update({f"candle.{k}": v for k, v in sorted(obs.B.quality.items())})
    return M
