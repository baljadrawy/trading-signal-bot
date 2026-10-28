"""Cost- and turnover-aware net evaluation of a trade population (a45g-ne-v1). Research only.

Answers, for a set of closed (or unfilled) PAPER / synthetic trades: how much of the gross result is eaten by
each cost component, what gross edge per trade would be needed to break even, whether the sign of the net
result survives cost stress, how much the population turns over, how deep the fixed-notional drawdown is, and
how uncertain the mean is once trades are clustered by day (the A45-F design-effect question).

Conventions (one convention for the whole module; matches ``shared/execution_calibration.cost_ledger``,
``a48-cost-v1``, and the cost rules of docs/governance/OWNER_OPERATING_CONTRACT.md section 1)
------------------------------------------------------------------------------------------------------
* Every per-trade quantity is a fraction of the trade's entry notional (0.01 = 1 %).
* ``gross``: price P&L at reference prices (mid or intended level) on the bought quantity; unsold dust is
  valued at zero (conservative).
* ``fee``: 0.10 % per side on executed notional (entry notional + exit notional). A record whose fee is
  below ``BASELINE_FEE_PER_SIDE * turnover`` is refused: discounted fees are never modelled.
* ``spread``: half-spread paid on taker legs. ``slippage``: execution price vs reference price, realised
  once (negative = price improvement). Both are reported separately from the fee and from each other.
* ``net = gross - fee - spread - slippage`` exactly, so the attribution always sums.
* The tracker's flat 0.30 % round-trip label is reported beside the model (``tracker_flat_mean_net``), never
  instead of it.
* Cost stress multiplies spread and adverse slippage by k (1.5, 2); the fee is never stressed downward or
  upward. This is first order: it ignores the k-dependence of the exit notional (a rate-squared term).
* ``turnover`` per trade = executed notional / entry notional (about 2 for a full round trip, 0 unfilled).

Uncertainty
-----------
Trades on the same UTC day share one market factor (A45 W11). ``se_day_cluster`` is the cluster-robust
standard error of the per-trade mean with days as clusters; ``design_effect`` = its variance over the iid
variance; ``effective_n`` = n / design_effect. ``ci_mean_net`` is a seeded day-cluster bootstrap percentile
interval. Day clustering does not model serial dependence across days (use a HAC / stationary bootstrap on
the daily series for that). Strata (e.g. by regime) are descriptive: no multiple-comparison control.

Evidence class
--------------
``evaluate`` writes ``SYNTHETIC`` only for the synthetic permission marker, and
``EXPLORATORY_NOT_CONFIRMATORY`` only for a recorded, licence-cleared, holdout-excluding
``DatasetPermission`` plus a non-empty owner ``authorization_ref``. Nothing else (confirmatory included:
D1/D2 HOLD) is ever written. ``not_a_profitability_claim`` is always True.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from research.mechanisms.costs import BASELINE_FEE_PER_SIDE, TRACKER_FLAT_ROUNDTRIP
from research.mechanisms.simulate import DatasetPermission

VERSION = "a45g-ne-v1"
SYNTHETIC = "SYNTHETIC"
EXPLORATORY = "EXPLORATORY_NOT_CONFIRMATORY"
DAY_SECONDS = 86400.0
DEFAULT_STRESS = (1.0, 1.5, 2.0)
_FEE_TOL = 1e-9


class EvaluationError(ValueError):
    """Invalid trade record, refused cost assumption, or refused evidence label."""


def _num(x, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise EvaluationError(f"{name} must be a number")
    v = float(x)
    if not math.isfinite(v):
        raise EvaluationError(f"{name} must be finite")
    return v


def _nonneg(x, name: str) -> float:
    v = _num(x, name)
    if v < 0:
        raise EvaluationError(f"{name} must be >= 0")
    return v


def _pos(x, name: str) -> float:
    v = _num(x, name)
    if v <= 0:
        raise EvaluationError(f"{name} must be > 0")
    return v


# ── per-trade record ───────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TradeRecord:
    """One trade intent. All money fields are fractions of entry notional (see module conventions)."""
    trade_id: str
    symbol: str
    entry_ts: float                 # UTC epoch seconds of the entry fill (or of the intent when unfilled)
    exit_ts: float
    gross: float
    fee: float
    spread: float
    slippage: float
    turnover: float
    risk: float | None = None       # planned (entry - stop) / entry, for R-unit reporting
    regime: str | None = None
    filled: bool = True

    def __post_init__(self):
        for name in ("trade_id", "symbol"):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                raise EvaluationError(f"{name} must be a non-empty string")
        e, x = _num(self.entry_ts, "entry_ts"), _num(self.exit_ts, "exit_ts")
        if x < e:
            raise EvaluationError("exit_ts before entry_ts")
        g = _num(self.gross, "gross")
        fee, spr = _nonneg(self.fee, "fee"), _nonneg(self.spread, "spread")
        _num(self.slippage, "slippage")
        to = _nonneg(self.turnover, "turnover")
        if not isinstance(self.filled, bool):
            raise EvaluationError("filled must be a bool")
        if self.risk is not None:
            _pos(self.risk, "risk")
        if self.regime is not None and (not isinstance(self.regime, str) or not self.regime):
            raise EvaluationError("regime must be None or a non-empty string")
        if not self.filled:
            if any(v != 0 for v in (g, fee, spr, self.slippage, to)):
                raise EvaluationError("an unfilled intent has zero gross, costs and turnover")
            return
        if g <= -1:
            raise EvaluationError("gross must be > -1 on a long-only spot trade")
        if to <= 0:
            raise EvaluationError("a filled trade has turnover > 0")
        if fee < BASELINE_FEE_PER_SIDE * to * (1 - _FEE_TOL) - 1e-15:
            raise EvaluationError("fee below 0.10 % per side of executed notional: discounted fees are "
                                  "not modelled")

    @property
    def cost(self) -> float:
        return self.fee + self.spread + self.slippage

    @property
    def net(self) -> float:
        return self.gross - self.cost

    def stressed_net(self, k: float) -> float:
        """Net with spread and adverse slippage multiplied by k (fee unchanged)."""
        adverse = max(self.slippage, 0.0)
        return self.gross - self.fee - k * self.spread - k * adverse - (self.slippage - adverse)

    @property
    def day(self) -> int:
        return math.floor(self.entry_ts / DAY_SECONDS)

    @property
    def holding_hours(self) -> float:
        return (self.exit_ts - self.entry_ts) / 3600.0


def trade_from_prices(trade_id: str, symbol: str, entry_ts: float, exit_ts: float, *, entry_ref: float,
                      exit_ref: float, half_spread_entry: float, half_spread_exit: float,
                      slippage_entry: float, slippage_exit: float,
                      fee_per_side: float = BASELINE_FEE_PER_SIDE, risk: float | None = None,
                      regime: str | None = None) -> TradeRecord:
    """Two-leg trade (one buy, one sell) under the a48-cost-v1 convention.

    Rates are fractions per side. Slippage moves the execution price (buy at ref(1+q_e), sell at
    ref(1-q_x)); the half-spread is a separate charge on each leg's executed notional (pass 0 for a
    resting-limit leg); the fee is ``fee_per_side`` on each leg's executed notional."""
    p_e, p_x = _pos(entry_ref, "entry_ref"), _pos(exit_ref, "exit_ref")
    h_e, h_x = _nonneg(half_spread_entry, "half_spread_entry"), _nonneg(half_spread_exit, "half_spread_exit")
    q_e, q_x = _nonneg(slippage_entry, "slippage_entry"), _nonneg(slippage_exit, "slippage_exit")
    f = _nonneg(fee_per_side, "fee_per_side")
    if f < BASELINE_FEE_PER_SIDE:
        raise EvaluationError("fee_per_side below the 0.10 % baseline")
    if q_x >= 1:
        raise EvaluationError("slippage_exit must be < 1")
    buy, sell = p_e * (1 + q_e), p_x * (1 - q_x)
    qty = 1.0 / buy                                   # quantity per unit of entry notional
    exit_notional = qty * sell
    return TradeRecord(trade_id, symbol, entry_ts, exit_ts,
                       gross=qty * (p_x - p_e),
                       fee=f * (1.0 + exit_notional),
                       spread=h_e * 1.0 + h_x * exit_notional,
                       slippage=qty * (buy - p_e) + qty * (p_x - sell),
                       turnover=1.0 + exit_notional, risk=risk, regime=regime)


def trade_from_cost_ledger(ledger, *, trade_id: str, symbol: str, entry_ts: float, exit_ts: float,
                           risk: float | None = None, regime: str | None = None) -> TradeRecord:
    """Adapter for an A48 ``CostLedger`` (duck-typed; this package does not import ``shared``).

    Fields are divided by the ledger notional; turnover is recomputed from the executed legs exactly as
    the ledger computes its fee base."""
    n = _pos(ledger.notional_usdt, "notional_usdt")
    legs = tuple(ledger.legs)
    if not legs or legs[0].kind != "entry":
        raise EvaluationError("ledger legs must start with the entry")
    q_total = _pos(ledger.quantity, "quantity")
    executed = q_total * legs[0].execution_price
    for leg in legs[1:]:
        q = leg.quantity if leg.quantity is not None else leg.fraction * q_total
        executed += q * leg.execution_price
    return TradeRecord(trade_id, symbol, entry_ts, exit_ts,
                       gross=ledger.gross_price_pnl_usdt / n, fee=ledger.explicit_fees_usdt / n,
                       spread=ledger.spread_cost_usdt / n, slippage=ledger.execution_slippage_usdt / n,
                       turnover=executed / n, risk=risk, regime=regime)


def unfilled_intent(trade_id: str, symbol: str, ts: float, *, regime: str | None = None) -> TradeRecord:
    """A resting order that never filled: an intent with zero return, kept for non-fill accounting."""
    return TradeRecord(trade_id, symbol, ts, ts, 0.0, 0.0, 0.0, 0.0, 0.0, regime=regime, filled=False)


def break_even_win_rate(avg_gross_win: float, avg_gross_loss: float, cost: float) -> float:
    """Two-outcome break-even hit rate p* with p (W - c) = (1 - p)(L + c), i.e. p* = (L + c) / (W + L).
    ``avg_gross_loss`` is a positive magnitude. A value >= 1 means the geometry cannot break even."""
    w, l, c = _pos(avg_gross_win, "avg_gross_win"), _pos(avg_gross_loss, "avg_gross_loss"), _nonneg(cost, "cost")
    return (l + c) / (w + l)


# ── labels ─────────────────────────────────────────────────────────────────────────────────────────

def authorize_label(permission, authorization_ref: str | None = None) -> str:
    """Evidence class allowed for this permission, or ``EvaluationError``."""
    if not isinstance(permission, DatasetPermission) or not permission.allows():
        raise EvaluationError("a valid DatasetPermission (synthetic marker or licence-cleared, "
                              "holdout-excluding record) is required")
    if permission.synthetic:
        return SYNTHETIC
    if not isinstance(authorization_ref, str) or not authorization_ref.strip():
        raise EvaluationError("a non-synthetic evaluation needs an owner authorization_ref")
    return EXPLORATORY


# ── result ─────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Interval:
    low: float
    high: float
    level: float
    method: str


@dataclass(frozen=True)
class CostAttribution:
    mean_fee: float
    mean_spread: float
    mean_slippage: float
    mean_total: float
    fee_share: float | None
    spread_share: float | None
    slippage_share: float | None


@dataclass(frozen=True)
class StressRow:
    multiplier: float
    mean_net: float
    break_even_gross_edge: float
    total_net_usdt: float


@dataclass(frozen=True)
class NetEvaluation:
    version: str
    evidence_class: str
    n_intents: int
    n_filled: int
    fill_rate: float | None
    n_days: int
    span_days: float
    n_symbols: int
    mean_gross: float | None
    mean_net: float | None
    median_net: float | None
    per_intent_mean_net: float | None
    win_rate_gross: float | None
    win_rate_net: float | None
    gross_win_net_loss_rate: float | None
    profit_factor_gross: float | None
    profit_factor_net: float | None
    costs: CostAttribution | None
    break_even_gross_edge: float | None
    cost_to_gross: float | None
    mean_gross_r: float | None
    mean_cost_r: float | None
    mean_net_r: float | None
    tracker_flat_mean_net: float | None
    stress: tuple = ()
    fragile: bool | None = None
    turnover_capital: float | None = None
    turnover_capital_per_day: float | None = None
    trades_per_day: float | None = None
    mean_holding_hours: float | None = None
    total_gross_usdt: float | None = None
    total_net_usdt: float | None = None
    max_drawdown_usdt: float | None = None
    max_drawdown_frac: float | None = None
    max_drawdown_trades: int | None = None
    gross_max_drawdown_usdt: float | None = None
    se_iid: float | None = None
    se_day_cluster: float | None = None
    design_effect: float | None = None
    effective_n: float | None = None
    ci_mean_net: Interval | None = None
    mean_net_without_top_1pct: float | None = None
    top_symbol_share: float | None = None
    top_day_share: float | None = None
    warnings: tuple = ()
    assumptions: Mapping = field(default_factory=dict)
    not_a_profitability_claim: bool = True


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────

def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    if not xs:
        return None
    s, m = sorted(xs), len(xs) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _quantile(sorted_xs, q):
    pos = q * (len(sorted_xs) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def _profit_factor(xs):
    wins, losses = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    return wins / losses if losses > 0 else None


def _drawdown(path_usdt, capital):
    """Max drawdown (USDT, fraction of peak equity, longest under-water stretch in trades)."""
    eq = peak = 0.0
    mdd = mdd_frac = 0.0
    under = longest = 0
    for x in path_usdt:
        eq += x
        if eq >= peak:
            peak, under = eq, 0
        else:
            under += 1
            longest = max(longest, under)
            dd = peak - eq
            if dd > mdd:
                mdd = dd
            mdd_frac = max(mdd_frac, dd / (capital + peak))
    return mdd, mdd_frac, longest


def _cluster_stats(trades, nets, mean):
    """Day-cluster robust SE of the per-trade mean, iid SE, design effect."""
    n = len(nets)
    by_day = defaultdict(float)
    for t, y in zip(trades, nets):
        by_day[t.day] += y - mean
    d = len(by_day)
    se_iid = math.sqrt(sum((y - mean) ** 2 for y in nets) / (n - 1) / n) if n > 1 else None
    if d < 2:
        return se_iid, None, None
    var_c = d / (d - 1) * sum(v * v for v in by_day.values()) / (n * n)
    se_c = math.sqrt(var_c)
    deff = var_c / se_iid ** 2 if se_iid else None
    return se_iid, se_c, deff


def _cluster_bootstrap(trades, nets, *, n_resamples, seed, level):
    sums, counts = defaultdict(float), defaultdict(int)
    for t, y in zip(trades, nets):
        sums[t.day] += y
        counts[t.day] += 1
    days = sorted(sums)
    if len(days) < 2:
        return None
    rng = random.Random(seed)
    k = len(days)
    stats = []
    for _ in range(n_resamples):
        s = c = 0
        for _ in range(k):
            day = days[rng.randrange(k)]
            s += sums[day]
            c += counts[day]
        stats.append(s / c)
    stats.sort()
    a = (1 - level) / 2
    return Interval(_quantile(stats, a), _quantile(stats, 1 - a), level, "day_cluster_bootstrap_percentile")


def _share(groups: Mapping, total: float):
    if total <= 0 or not groups:
        return None
    return max(groups.values()) / total


# ── evaluation ─────────────────────────────────────────────────────────────────────────────────────

def evaluate(trades: Iterable[TradeRecord], *, permission, authorization_ref: str | None = None,
             notional_usdt: float = 50.0, capital_usdt: float = 1000.0,
             stress: Sequence[float] = DEFAULT_STRESS, n_resamples: int = 2000, seed: int = 0,
             ci_level: float = 0.95, min_days_warning: int = 30) -> NetEvaluation:
    """Evaluate a trade population (see module docstring). Pure and deterministic given ``seed``."""
    label = authorize_label(permission, authorization_ref)
    trades = list(trades)
    for t in trades:
        if not isinstance(t, TradeRecord):
            raise EvaluationError("trades must be TradeRecord instances")
    if len({t.trade_id for t in trades}) != len(trades):
        raise EvaluationError("duplicate trade_id")
    notional, capital = _pos(notional_usdt, "notional_usdt"), _pos(capital_usdt, "capital_usdt")
    ks = tuple(_nonneg(k, "stress multiplier") for k in stress)
    if not ks or ks[0] != 1.0 or list(ks) != sorted(ks):
        raise EvaluationError("stress must start at 1.0 and be non-decreasing")
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, int) or n_resamples < 100:
        raise EvaluationError("n_resamples must be an int >= 100")
    if not 0 < ci_level < 1:
        raise EvaluationError("ci_level must be in (0, 1)")

    assumptions = {"fee_per_side_min": BASELINE_FEE_PER_SIDE, "tracker_flat_roundtrip": TRACKER_FLAT_ROUNDTRIP,
                   "notional_usdt": notional, "capital_usdt": capital, "stress": ks,
                   "cluster": "UTC entry day", "cost_convention": "a48-cost-v1",
                   "drawdown": "fixed notional per trade, exit-time order, concurrency ignored"}
    filled = sorted((t for t in trades if t.filled), key=lambda t: (t.exit_ts, t.trade_id))
    n_int, n = len(trades), len(filled)
    if n == 0:
        return NetEvaluation(VERSION, label, n_int, 0, 0.0 if n_int else None, 0, 0.0, 0,
                             *([None] * 16), warnings=("no_filled_trades",), assumptions=assumptions)

    warn = []
    gross = [t.gross for t in filled]
    nets = [t.net for t in filled]
    costs = [t.cost for t in filled]
    m_g, m_n, m_c = _mean(gross), _mean(nets), _mean(costs)
    fee, spr, slip = (_mean([t.fee for t in filled]), _mean([t.spread for t in filled]),
                      _mean([t.slippage for t in filled]))
    attribution = CostAttribution(fee, spr, slip, m_c, *((v / m_c) if m_c > 0 else None for v in (fee, spr, slip)))

    stress_rows = []
    for k in ks:
        sn = [t.stressed_net(k) for t in filled]
        stress_rows.append(StressRow(k, _mean(sn), m_g - _mean(sn), notional * sum(sn)))
    signs = {math.copysign(1.0, r.mean_net) if r.mean_net != 0 else 0.0 for r in stress_rows}
    fragile = len(signs) > 1
    if fragile:
        warn.append("fragile_net_sign_under_cost_stress")

    risks = [t.risk for t in filled]
    r_units = all(r is not None for r in risks)
    first_entry = min(t.entry_ts for t in filled)
    last_exit = max(t.exit_ts for t in filled)
    span_days = max((last_exit - first_entry) / DAY_SECONDS, 1.0 / 24)
    days = {t.day for t in filled}
    if len(days) < min_days_warning:
        warn.append("few_days_for_inference")

    se_iid, se_c, deff = _cluster_stats(filled, nets, m_n)
    if se_c is None:
        warn.append("single_day_no_cluster_se")
    ci = _cluster_bootstrap(filled, nets, n_resamples=n_resamples, seed=seed, level=ci_level)

    mdd, mdd_frac, mdd_len = _drawdown([notional * y for y in nets], capital)
    gmdd, _, _ = _drawdown([notional * y for y in gross], capital)

    drop = math.ceil(0.01 * n)
    trimmed = sorted(nets)[:-drop] if n > drop else []
    m_trim = _mean(trimmed)
    if m_trim is not None and m_n > 0 >= m_trim:
        warn.append("net_sign_depends_on_top_1pct")
    total_net = sum(nets)
    by_sym, by_day = defaultdict(float), defaultdict(float)
    for t in filled:
        by_sym[t.symbol] += t.net
        by_day[t.day] += t.net
    if _profit_factor(gross) is None:
        warn.append("gross_profit_factor_undefined_no_losses")
    if any(t.gross > 0 > t.net for t in filled):
        warn.append("gross_wins_turned_net_losses")

    return NetEvaluation(
        VERSION, label, n_int, n, n / n_int, len(days), span_days, len({t.symbol for t in filled}),
        m_g, m_n, _median(nets), sum(nets) / n_int,
        sum(g > 0 for g in gross) / n, sum(y > 0 for y in nets) / n,
        sum(t.gross > 0 > t.net for t in filled) / n,
        _profit_factor(gross), _profit_factor(nets), attribution, m_c,
        (m_c / m_g) if m_g > 0 else None,
        _mean([t.gross / t.risk for t in filled]) if r_units else None,
        _mean([t.cost / t.risk for t in filled]) if r_units else None,
        _mean([t.net / t.risk for t in filled]) if r_units else None,
        m_g - TRACKER_FLAT_ROUNDTRIP,
        stress=tuple(stress_rows), fragile=fragile,
        turnover_capital=sum(t.turnover for t in filled) * notional / capital,
        turnover_capital_per_day=sum(t.turnover for t in filled) * notional / capital / span_days,
        trades_per_day=n / span_days, mean_holding_hours=_mean([t.holding_hours for t in filled]),
        total_gross_usdt=notional * sum(gross), total_net_usdt=notional * total_net,
        max_drawdown_usdt=mdd, max_drawdown_frac=mdd_frac, max_drawdown_trades=mdd_len,
        gross_max_drawdown_usdt=gmdd, se_iid=se_iid, se_day_cluster=se_c, design_effect=deff,
        effective_n=(n / deff) if deff else None, ci_mean_net=ci, mean_net_without_top_1pct=m_trim,
        top_symbol_share=_share(by_sym, total_net), top_day_share=_share(by_day, total_net),
        warnings=tuple(warn), assumptions=assumptions)


def stratified(trades: Iterable[TradeRecord], key: Callable[[TradeRecord], str | None], **kw) -> dict:
    """``evaluate`` per stratum (``key(trade)``; None -> 'unlabelled'). Descriptive only: strata are not
    corrected for multiple comparisons and are never a selection rule."""
    groups = defaultdict(list)
    for t in trades:
        k = key(t)
        groups["unlabelled" if k is None else str(k)].append(t)
    out = {}
    for k in sorted(groups):
        ev = evaluate(groups[k], **kw)
        out[k] = replace(ev, warnings=ev.warnings + ("stratum_descriptive_only",))
    return out
