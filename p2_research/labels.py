"""Forward-looking labels (label set v1). Separate namespace, separate output file; NEVER a feature input.

Two families, kept apart:
  * ``mkt.*`` market-movement labels from 15m candles (recoverable data): forward return, MFE, MAE, horizon
    drawdown and meaningful-decline occurrence for horizons 1h / 4h / 24h;
  * ``exe.*`` execution labels from the forward book (irreplaceable data): executable entry (next ask after the
    decision), entry spread, an explicit fee assumption and a cost-adjusted round trip; the realized Paper outcome
    is a declared slot that stays null until a separately authorized PAPER-R1 linkage exists.
Labels are anchored strictly AFTER the decision time and are null (with a reason) when any required forward
observation is missing or lies beyond the loaded range; nothing is interpolated.
"""
from __future__ import annotations

import math

LABEL_SET_ID = "p2c-ls"
LABEL_SET_VERSION = "1.0.0"
HORIZONS = {"1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}
DECLINE_THRESHOLD = {"1h": 0.015, "4h": 0.03, "24h": 0.06}       # predeclared, NOT tuned (no outcome data used)
FEE_BPS_PER_SIDE = 10.0                                             # Binance spot base taker fee assumption
BOOK_MATCH_WINDOW_MS = 60_000
BAR = 900_000


def _rnd(v):
    return None if v is None else float(f"{v:.12g}")


def label_definitions() -> list:
    d = []
    for h in HORIZONS:
        d += [
            {"id": f"mkt.fwd_ret_{h}", "family": "market", "formula": "ln(close of last 15m bar in [A, A+h) / open of bar at A)"},
            {"id": f"mkt.mfe_{h}", "family": "market", "formula": "max(high in [A, A+h)) / p0 - 1"},
            {"id": f"mkt.mae_{h}", "family": "market", "formula": "min(low in [A, A+h)) / p0 - 1"},
            {"id": f"mkt.max_dd_{h}", "family": "market",
             "formula": "max_{i<=j} (H_i - L_j)/H_i over 15m bars (intra-bar order unknown: conservative, includes i=j)"},
            {"id": f"mkt.decline_{h}", "family": "market",
             "formula": f"1 if mae_{h} <= -{DECLINE_THRESHOLD[h]} else 0 (predeclared threshold)"},
            {"id": f"exe.net_ret_{h}", "family": "execution",
             "formula": "ln(bid of first book sample observed in (T+h, T+h+60s] / exe.entry_ask) - 2*fee"},
        ]
    d += [{"id": "exe.entry_ask", "family": "execution", "formula": "ask of first book sample observed in (T, T+60s]; null if no run at T"},
          {"id": "exe.entry_delay_ms", "family": "execution", "formula": "observed_at_ms(entry sample) - T"},
          {"id": "exe.entry_spread_bps", "family": "execution", "formula": "(ask-bid)/mid*1e4 at the entry sample"},
          {"id": "exe.fee_bps_roundtrip", "family": "execution", "formula": f"constant 2 x {FEE_BPS_PER_SIDE} bps (assumption)"},
          {"id": "exe.paper_outcome", "family": "execution",
           "formula": "realized PAPER-R1 outcome via candidate_id/signal_id linkage; NOT IMPLEMENTED (null, reason)"}]
    return d


def anchor(T: int) -> int:
    """First 15m boundary strictly after the decision time."""
    return (T // BAR + 1) * BAR


def _book_after(B, sym, t):
    """First book observation strictly after ``t`` and within the match window (any run: a market observation)."""
    x = B.first_after("book", sym, t)
    if x is None or x[2] > t + BOOK_MATCH_WINDOW_MS:
        return None, "no_book_after_time"
    return x, None


def compute_labels(B, sym: str, T: int) -> tuple:
    """(labels, null_reasons). ``B`` is the full bundle (forward access is the point of a label)."""
    L, R = {}, {}

    def put(k, v, why=None):
        L[k] = _rnd(v) if isinstance(v, float) else v
        if v is None:
            R[k] = why or "undefined"

    A = anchor(T)
    store = B.candles.get((sym, "15m"), {})
    p0c = store.get(A)
    for h, H in HORIZONS.items():
        keys = [f"mkt.fwd_ret_{h}", f"mkt.mfe_{h}", f"mkt.mae_{h}", f"mkt.max_dd_{h}", f"mkt.decline_{h}"]
        why = None
        if A + H > B.coverage_end_ms:
            why = "beyond_loaded_range"
        elif p0c is None:
            why = "anchor_candle_missing"
        else:
            bars = [store.get(A + i * BAR) for i in range(H // BAR)]
            if any(b is None for b in bars):
                why = "forward_candle_missing"
        if why:
            for k in keys:
                put(k, None, why)
            continue
        p0 = p0c[1]
        hi, lo = max(b[2] for b in bars), min(b[3] for b in bars)
        dd, peak = 0.0, 0.0
        for b in bars:
            peak = max(peak, b[2])
            dd = max(dd, (peak - b[3]) / peak)
        mae = lo / p0 - 1
        put(keys[0], math.log(bars[-1][4] / p0))
        put(keys[1], hi / p0 - 1)
        put(keys[2], mae)
        put(keys[3], dd)
        put(keys[4], 1 if mae <= -DECLINE_THRESHOLD[h] else 0)
    run = B.run_at(T)
    fee = 2 * FEE_BPS_PER_SIDE
    put("exe.fee_bps_roundtrip", fee)
    put("exe.paper_outcome", None, "paper_r1_linkage_not_authorized")
    ent, why = (None, "no_run_at_T") if run is None else _book_after(B, sym, T)
    if ent is not None and T + BOOK_MATCH_WINDOW_MS > B.range_end_ms:
        ent, why = None, "beyond_loaded_range"
    if ent is None or ent[4] <= 0:
        for k in ("exe.entry_ask", "exe.entry_delay_ms", "exe.entry_spread_bps"):
            put(k, None, why or "zero_ask")
    else:
        mid = (ent[3] + ent[4]) / 2
        put("exe.entry_ask", ent[4])
        put("exe.entry_delay_ms", ent[2] - T)
        put("exe.entry_spread_bps", (ent[4] - ent[3]) / mid * 1e4)
    for h, H in HORIZONS.items():
        k = f"exe.net_ret_{h}"
        if ent is None or ent[4] <= 0:
            put(k, None, why or "zero_ask")
            continue
        if T + H + BOOK_MATCH_WINDOW_MS > B.range_end_ms:
            put(k, None, "beyond_loaded_range")
            continue
        ex, w2 = _book_after(B, sym, T + H)
        if ex is None or ex[3] <= 0:
            put(k, None, w2 or "zero_bid")
            continue
        put(k, math.log(ex[3] / ent[4]) - fee / 1e4)
    return L, R
