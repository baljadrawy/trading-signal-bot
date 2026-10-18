"""A45 setup diagnostics for the production Momentum (breakout) and Reversion setups.

Pure functions; no I/O; no production module imports this file. They EXPLAIN what the
production code decides — they never decide:

* ``explain_setups`` re-states ``analyzer/simple_entry.detect_trade_setup`` condition by
  condition (values, thresholds, first failure). A test holds it to exact decision parity.
* ``setup_geometry`` measures the bracket the production ``_calculate_levels`` produced in
  volatility units: breakout extension, stop anchor, risk in ATR, T1-cap provenance, cost burden.
* ``validate_indicator_frame`` checks the inputs of the *active* setups (finite values,
  warm-up sufficiency, candle hygiene) and records provenance.
* ``MarketStateGate`` / ``ExtensionCap`` / ``SeasonalVolumeConfirmation`` are the A45-E
  hypotheses as versioned, DISABLED specifications (a disabled policy never blocks).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from importlib import metadata
from typing import Mapping

import pandas as pd

from shared.signal_quality import CostModel, PolicyDecision

VERSION = "a45-sd-v1"
BARS_PER_DAY = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# ── setup explanation (mirror of detect_trade_setup) ────────────────────────

@dataclass(frozen=True)
class Condition:
    name: str
    value: float | str | None
    threshold: float | str | None
    passed: bool


@dataclass(frozen=True)
class SetupExplanation:
    setup: str
    passed: bool
    conditions: tuple
    first_failure: str | None


def _explain(setup, conds) -> SetupExplanation:
    first = next((c.name for c in conds if not c.passed), None)
    return SetupExplanation(setup, first is None, tuple(conds), first)


def explain_setups(df: pd.DataFrame, *, market_condition: str | None, breakout_n: int = 20,
                   vol_mult: float = 1.2, rev_rsi: float = 35.0,
                   bb_max_position: float = 0.20) -> dict:
    """{'momentum': SetupExplanation, 'reversion': SetupExplanation, 'decision': str|None}.

    Same order and comparisons as detect_trade_setup: momentum is evaluated first and wins.
    Comparisons with NaN are False, exactly as in production (a NaN input fails a condition)."""
    if df is None or len(df) < 2:
        empty = _explain("momentum", [Condition("history", len(df) if df is not None else 0, 2, False)])
        return {"momentum": empty, "reversion": _explain("reversion", empty.conditions),
                "decision": None}
    last, prev = df.iloc[-1], df.iloc[-2]
    close, ema20, ema50 = _f(last["close"]), _f(last.get("ema20")), _f(last.get("ema50"))
    window = df.iloc[-(breakout_n + 1):-1]
    prior_high = _f(window["high"].max())
    vol_ma = _f(window["volume"].mean())
    volume = _f(last["volume"])
    mom = [
        Condition("regime_bullish", market_condition, "bullish|None",
                  market_condition in (None, "bullish")),
        Condition("close_above_ema20", close, ema20, close > ema20),
        Condition("ema20_above_ema50", ema20, ema50, ema20 > ema50),
        Condition("breakout_above_prior_high", close, prior_high, close > prior_high),
        Condition("volume_confirmation", volume, vol_mult * vol_ma, volume > vol_mult * vol_ma),
    ]
    bb_low, bb_up = _f(last.get("bb_lower")), _f(last.get("bb_upper"))
    rng = bb_up - bb_low
    bb_pos = (close - bb_low) / rng if rng > 0 else float("inf")
    rsi = _f(last.get("rsi"))
    rev = [
        Condition("regime_sideways", market_condition, "sideways|None",
                  market_condition in (None, "sideways")),
        Condition("rsi_oversold", rsi, rev_rsi, rsi < rev_rsi),
        Condition("close_above_previous_close", close, _f(prev["close"]), close > _f(prev["close"])),
        Condition("close_above_open", close, _f(last["open"]), close > _f(last["open"])),
        Condition("near_lower_band", bb_pos, bb_max_position, bb_pos <= bb_max_position),
    ]
    m, r = _explain("momentum", mom), _explain("reversion", rev)
    return {"momentum": m, "reversion": r,
            "decision": "momentum" if m.passed else "reversion" if r.passed else None}


# ── volatility-normalised geometry of the production bracket ────────────────

@dataclass(frozen=True)
class SetupGeometry:
    trade_type: str | None
    atr_pct: float
    extension_atr: float          # momentum: (close − prior high) / ATR; reversion: (close − 20-bar low) / ATR
    risk_atr: float               # (entry − stop) / ATR
    stop_anchor: str              # atr_floor | structure | legacy | invalid
    risk_pct: float
    t1_r: float
    t1_cap_source: str            # none | prior_bars | current_bar
    cost_over_risk: float
    flags: tuple = field(default_factory=tuple)


def setup_geometry(df: pd.DataFrame, levels: Mapping, trade_type: str | None, *,
                   breakout_n: int = 20, cost: CostModel = CostModel(),
                   spread_pct: float | None = None) -> SetupGeometry:
    """Measure the production bracket ``levels`` (from ``_calculate_levels``) on frame ``df``."""
    last = df.iloc[-1]
    atr, close = _f(last["atr"]), _f(last["close"])
    entry, stop, t1 = _f(levels.get("entry")), _f(levels.get("stop")), _f(levels.get("t1"))
    if not all(math.isfinite(v) and v > 0 for v in (atr, close, entry, stop, t1)) or stop >= entry:
        return SetupGeometry(trade_type, float("nan"), float("nan"), float("nan"), "invalid",
                             float("nan"), float("nan"), "none", float("nan"), ("invalid_inputs",))
    risk = entry - stop
    recent = df.tail(20)
    if trade_type == "momentum":
        ref = _f(df["high"].iloc[-(breakout_n + 1):-1].max())
        extension = (close - ref) / atr
        structural = ref - 0.25 * atr
        anchor = "structure" if structural < entry - atr - 1e-12 * entry else "atr_floor"
    elif trade_type == "reversion":
        ref = _f(recent["low"].min())
        extension = (close - ref) / atr
        structural = ref - 0.25 * atr
        anchor = "structure" if structural < entry - atr - 1e-12 * entry else "atr_floor"
    else:
        extension, anchor = float("nan"), "legacy"
    capped = (t1 - entry) < risk * 0.999
    source = "none"
    if capped:
        source = "current_bar" if int(recent["high"].values.argmax()) == len(recent) - 1 else "prior_bars"
    c = cost.exchange_fee_roundtrip_pct + cost.entry_slippage_pct + cost.exit_slippage_pct
    if cost.include_spread and spread_pct is not None and math.isfinite(_f(spread_pct)):
        c += _f(spread_pct)
    risk_pct = risk / entry * 100
    flags = []
    if source == "current_bar":
        flags.append("t1_capped_by_own_breakout_bar")
    if c >= risk_pct:
        flags.append("cost_exceeds_risk")
    if trade_type == "momentum" and extension > 0.75:
        flags.append("extended_entry")
    return SetupGeometry(trade_type, atr / close * 100, extension, risk / atr, anchor, risk_pct,
                         (t1 - entry) / risk, source, c / risk_pct, tuple(flags))


# ── indicator-frame validation and provenance ───────────────────────────────

ACTIVE_COLUMNS = {
    "regime": ("close", "ema20", "atr", "adx"),
    "momentum": ("close", "high", "volume", "ema20", "ema50", "atr"),
    "reversion": ("open", "close", "rsi", "bb_upper", "bb_lower", "atr"),
}
EMA_SPANS = {"ema20": 20, "ema50": 50, "ema200": 200}
INACTIVE_IN_LIVE = ("ema200", "macd", "macd_signal", "macd_hist", "stoch_k", "stoch_d",
                    "obv", "obv_ema", "bb_width", "volume_ratio")


@dataclass(frozen=True)
class IndicatorReport:
    valid: bool
    issues: tuple
    notes: tuple
    provenance: dict


def ema_seed_weight(span: int, bars: int) -> float:
    """Residual weight of the first observation in an EMA after ``bars`` bars (adjust=False)."""
    alpha = 2.0 / (span + 1.0)
    return (1.0 - alpha) ** max(bars - 1, 0)


def validate_indicator_frame(df: pd.DataFrame, timeframe: str, *, regime_vol_lookback: int = 100,
                             seed_weight_limit: float = 1e-3) -> IndicatorReport:
    """Fail-closed checks on the inputs the ACTIVE setups read; inactive indicators only noted."""
    from shared.ohlcv import validate_ohlcv
    issues, notes = [], []
    try:
        validate_ohlcv(df[["open", "high", "low", "close", "volume"]], timeframe)
    except (ValueError, KeyError) as exc:
        issues.append(f"ohlcv:{exc}")
    bars = len(df)
    for group, cols in ACTIVE_COLUMNS.items():
        for col in cols:
            if col not in df.columns:
                issues.append(f"{group}:{col}:missing")
            elif bars == 0 or not math.isfinite(_f(df[col].iloc[-1])):
                issues.append(f"{group}:{col}:non_finite_last")
    for col, span in EMA_SPANS.items():
        w = ema_seed_weight(span, bars)
        if w > seed_weight_limit:                       # under-warmed EMA
            (notes if col in INACTIVE_IN_LIVE else issues).append(f"{col}:seed_weight={w:.2e}")
    if "atr" in df.columns and "close" in df.columns:
        atr_hist = (df["atr"] / df["close"]).replace([float("inf"), -float("inf")], pd.NA).dropna()
        if len(atr_hist) < regime_vol_lookback:
            issues.append(f"regime:volatility_history={len(atr_hist)}<{regime_vol_lookback}")
    try:
        ta_version = metadata.version("ta")
    except metadata.PackageNotFoundError:
        ta_version = None
    provenance = {"version": VERSION, "timeframe": timeframe, "bars": bars, "ta_version": ta_version,
                  "last_open_ms": int(df.index[-1].value // 1_000_000)
                  if bars and isinstance(df.index, pd.DatetimeIndex) else None}
    return IndicatorReport(not issues, tuple(issues), tuple(notes), provenance)


# ── A45-E hypotheses as disabled, versioned specifications ──────────────────

@dataclass(frozen=True)
class MarketStateGate:
    """H1: take momentum breakouts only when the crypto market's own trend is non-negative.

    Input is the BTC 3-day (18 × 4h closed candles) change the macro context already computes —
    no new lookback; the threshold 0 is the sign of the trend, not a fitted value."""
    enabled: bool = False
    version: str = "a45-h1-market-state-v1"
    min_btc_change_pct: float = 0.0

    def evaluate(self, trade_type: str | None, btc_change_pct) -> PolicyDecision:
        reasons = []
        if trade_type == "momentum":
            v = _f(btc_change_pct)
            if not math.isfinite(v):
                reasons.append("market_state_unavailable")       # fail closed when enabled
            elif v < self.min_btc_change_pct:
                reasons.append("market_trend_negative")
        return PolicyDecision("market_state_gate", self.version, self.enabled, not reasons, tuple(reasons))


@dataclass(frozen=True)
class ExtensionCap:
    """H2: do not buy a breakout bar that already closed more than 0.75 ATR above the level.

    0.75 is not fitted: it is the point where the production stop stops being the 1-ATR floor
    (entry − 1 ATR) and becomes the structural stop (level − 0.25 ATR), i.e. where the entry
    starts paying for extension with a wider risk."""
    enabled: bool = False
    version: str = "a45-h2-extension-v1"
    max_extension_atr: float = 0.75

    def evaluate(self, geometry: SetupGeometry) -> PolicyDecision:
        reasons = []
        if geometry.trade_type == "momentum":
            if not math.isfinite(geometry.extension_atr):
                reasons.append("extension_unavailable")
            elif geometry.extension_atr > self.max_extension_atr:
                reasons.append("extension_exceeds_cap")
        return PolicyDecision("extension_cap", self.version, self.enabled, not reasons, tuple(reasons))


@dataclass(frozen=True)
class SeasonalVolumeConfirmation:
    """H3: volume confirmation against the same time of day, not the previous 20 bars.

    Uses the production multiple (1.2) unchanged; only the baseline changes from "last 20 bars"
    to "the same intraday slot on each of the previous ``days`` days"."""
    enabled: bool = False
    version: str = "a45-h3-slot-volume-v1"
    days: int = 20
    vol_mult: float = 1.2

    def baseline(self, df: pd.DataFrame, timeframe: str) -> float:
        per_day = BARS_PER_DAY.get(timeframe)
        if not per_day or per_day == 1:
            return float("nan")                                  # no intraday seasonality to remove
        need = self.days * per_day + 1
        if len(df) < need:
            return float("nan")
        idx = [len(df) - 1 - k * per_day for k in range(1, self.days + 1)]
        return float(df["volume"].iloc[idx].mean())

    def evaluate(self, df: pd.DataFrame, timeframe: str, trade_type: str | None) -> PolicyDecision:
        reasons = []
        if trade_type == "momentum" and timeframe in ("15m", "1h", "4h"):
            base = self.baseline(df, timeframe)
            if not math.isfinite(base):
                reasons.append("slot_history_insufficient")
            elif not _f(df["volume"].iloc[-1]) > self.vol_mult * base:
                reasons.append("volume_not_above_slot_baseline")
        return PolicyDecision("slot_volume", self.version, self.enabled, not reasons, tuple(reasons))
