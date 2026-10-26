"""Paper economic-loss observation policy (owner decision 2026-10-26).

During R&D, economic outcomes -- daily/weekly loss, drawdown, loss streak -- are
OBSERVATIONS in Paper mode and need not stop simulated trade collection, while
every TECHNICAL / ADMINISTRATIVE safeguard stays fail-closed. This module is the
single source of truth for that classification and for the mode switch.

Design constraints:

* ``shared/risk_management.py`` is deliberately left byte-identical. Its hash is
  pinned in the research and production-runtime contracts
  (``research/governance/contracts``), and ``evaluate_new_trade`` stays the one
  implementation of the risk arithmetic. This module only *wraps* it.
* ``enforce`` (the default) returns exactly the legacy decision: every legacy
  RiskDecision field is unchanged. The extra fields are additive labels.
* ``observe`` is honoured only when ``PAPER_TRADING`` is true; any other value or
  context resolves to ``enforce`` (the restrictive direction) with a warning.
* Sizing multipliers (drawdown_caution/warning, weekly_reduce/minimum,
  loss_streak_reduce/minimum) are sizing, not stopping, and are unchanged in both
  modes. They can still lower the capacity used by the max_open_trades check.
* Nothing here writes, resets or rewrites loss history or counters.
"""
from dataclasses import dataclass, fields, replace
import logging
import math
import sys

from shared.risk_management import RiskDecision, RiskLimits, RiskSnapshot, evaluate_new_trade

logger = logging.getLogger(__name__)

ENFORCE = 'enforce'
OBSERVE = 'observe'
ECONOMIC_HALT_MODES = (ENFORCE, OBSERVE)
RISK_POLICY_VERSIONS = {ENFORCE: 'econ-enforce-v1', OBSERVE: 'econ-observe-v1'}

# ---- classification (single source of truth) ------------------------------------------
# Economic outcome halts: blocking in enforce mode, observed-only in Paper observe mode.
# Tuple order is the legacy evaluate_new_trade hard-stop precedence.
ECONOMIC_HARD_STOP_ORDER = (
    'daily_loss_limit', 'weekly_loss_limit', 'max_drawdown_limit', 'loss_streak_halt')
ECONOMIC_HARD_STOPS = frozenset(ECONOMIC_HARD_STOP_ORDER)
# Technical hard halts: always blocking AND always persisted as a pause.
TECHNICAL_HARD_STOPS = frozenset({'invalid_risk_state'})
# Administrative / state-integrity stops (shared.trading_state pause reasons): always
# blocking in both modes. Any persisted pause row -- including an old 'risk:<economic>'
# row written before observe mode was activated -- stays an administrative pause that
# only the owner's /resume clears. Names repeated here (not imported) so this module
# stays importable without the database facade.
ADMIN_STOPS = frozenset({
    'manual_pause', 'trading_paused', 'risk_state_missing', 'risk_state_inconsistent'})
# Portfolio-construction limits: always blocking in both modes (not outcome halts).
PORTFOLIO_LIMITS = frozenset({
    'gross_exposure_limit', 'symbol_concentration_limit', 'strategy_concentration_limit',
    'regime_concentration_limit', 'max_open_trades'})
# Sizing labels: never a stop on their own (they label a capacity block when the reduced
# max_positions is reached, which is the max_open_trades portfolio limit).
SIZING_REASONS = frozenset({
    'drawdown_caution', 'drawdown_warning', 'weekly_reduce', 'weekly_minimum',
    'loss_streak_reduce', 'loss_streak_minimum'})

OBSERVED_PREFIX = 'observed:'


def classify_reason(reason: str | None) -> str:
    """'economic' | 'technical' | 'admin' | 'portfolio' | 'sizing' | 'observed' | 'ok'."""
    r = str(reason or '')
    if r in ECONOMIC_HARD_STOPS:
        return 'economic'
    if r in TECHNICAL_HARD_STOPS:
        return 'technical'
    if r in PORTFOLIO_LIMITS:
        return 'portfolio'
    if r in SIZING_REASONS:
        return 'sizing'
    if r.startswith(OBSERVED_PREFIX):
        return 'observed'
    if r in ('', 'within_limits'):
        return 'ok'
    # Every other reason comes from a persisted pause (manual, risk:<x>, state fault,
    # or an operator free-text reason): administrative, fail-closed.
    return 'admin'


# ---- mode resolution --------------------------------------------------------------------
_WARNED: set = set()


def resolve_economic_halt_mode(raw, paper_trading: bool) -> tuple[str, str | None]:
    """Pure resolution: (effective_mode, warning_or_None)."""
    mode = str(raw if raw is not None else ENFORCE).strip().lower() or ENFORCE
    if mode not in ECONOMIC_HALT_MODES:
        return ENFORCE, (f'unknown PAPER_ECONOMIC_HALT_MODE {raw!r}; '
                         f'using {ENFORCE!r} (economic halts stay blocking)')
    if mode == OBSERVE and not paper_trading:
        return ENFORCE, ('PAPER_ECONOMIC_HALT_MODE=observe ignored: PAPER_TRADING is not '
                         f'true; using {ENFORCE!r} (economic halts stay blocking)')
    return mode, None


def economic_halt_mode(cfg=None) -> str:
    """Effective mode for this process; logs each coercion warning once."""
    if cfg is None:
        from shared.config import config as cfg
    mode, warning = resolve_economic_halt_mode(
        getattr(cfg, 'PAPER_ECONOMIC_HALT_MODE', ENFORCE), bool(getattr(cfg, 'PAPER_TRADING', False)))
    if warning and warning not in _WARNED:
        _WARNED.add(warning)
        logger.warning(warning)
    return mode


def risk_policy_version(cfg=None) -> str:
    return RISK_POLICY_VERSIONS[economic_halt_mode(cfg)]


def persisted_halt_reasons(mode: str) -> frozenset:
    """Decision reasons that record_risk_decision persists as is_trading_paused=true."""
    if mode == OBSERVE:
        return TECHNICAL_HARD_STOPS
    return ECONOMIC_HARD_STOPS | TECHNICAL_HARD_STOPS     # legacy hard_halts set, exactly


def economic_halt_blocks(mode: str) -> bool:
    return mode != OBSERVE


# ---- decision ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyRiskDecision(RiskDecision):
    """RiskDecision plus additive, auditable policy labels."""
    economic_flags: tuple = ()
    observed_economic_stop: str | None = None
    risk_policy_version: str = RISK_POLICY_VERSIONS[ENFORCE]


_LEGACY_FIELDS = tuple(f.name for f in fields(RiskDecision))


def legacy_fields(decision) -> tuple:
    """The legacy RiskDecision fields, for byte-identity comparisons."""
    return tuple(getattr(decision, name) for name in _LEGACY_FIELDS)


def economic_flags(decision: RiskDecision, limits: RiskLimits) -> tuple:
    """Every breached economic hard limit, in legacy precedence order.

    Uses evaluate_new_trade's own computed values and the identical comparisons, so
    in enforce mode the first flag is exactly the economic hard stop it returned.
    """
    if decision.reason in TECHNICAL_HARD_STOPS:
        return ()                     # the economic values were never computed
    hits = (
        decision.daily_pnl_pct <= -limits.max_daily_loss_pct,
        decision.weekly_pnl_pct <= -limits.max_weekly_loss_pct,
        decision.drawdown_pct >= limits.max_drawdown_pct,
        decision.consecutive_losses >= limits.loss_halt_count,
    )
    return tuple(name for name, hit in zip(ECONOMIC_HARD_STOP_ORDER, hits) if hit)


def _neutral_economic_limits(limits: RiskLimits) -> RiskLimits:
    """Same limits with only the four economic HARD thresholds made unreachable.

    Sizing thresholds (caution/warning/reduce/minimum) are untouched, so multipliers and
    capacity are exactly the enforce-mode values.
    """
    return replace(limits, max_daily_loss_pct=math.inf, max_weekly_loss_pct=math.inf,
                   max_drawdown_pct=math.inf, loss_halt_count=sys.maxsize)


def _labelled(base: RiskDecision, **labels) -> PolicyRiskDecision:
    values = {name: getattr(base, name) for name in _LEGACY_FIELDS}
    values.update(labels)
    return PolicyRiskDecision(**values)


def evaluate_with_policy(snapshot: RiskSnapshot, limits: RiskLimits,
                         mode: str = ENFORCE) -> PolicyRiskDecision:
    """evaluate_new_trade under the economic-halt policy.

    enforce: the legacy decision, unchanged, plus labels.
    observe: if (and only if) the binding legacy stop is economic, the decision is
    re-derived with the economic hard thresholds neutralised: it is allowed unless a
    technical, administrative or portfolio stop still applies, and the would-be stop
    is kept in ``observed_economic_stop`` / ``reason`` ('observed:<stop>').
    """
    base = evaluate_new_trade(snapshot, limits)
    flags = economic_flags(base, limits)
    if mode != OBSERVE:
        return _labelled(base, economic_flags=flags, observed_economic_stop=None,
                         risk_policy_version=RISK_POLICY_VERSIONS[ENFORCE])
    version = RISK_POLICY_VERSIONS[OBSERVE]
    if base.reason not in ECONOMIC_HARD_STOPS:
        # Allowed already, or bound by a technical/admin/portfolio stop: unchanged.
        return _labelled(base, economic_flags=flags, observed_economic_stop=None,
                         risk_policy_version=version)
    alt = evaluate_new_trade(snapshot, _neutral_economic_limits(limits))
    reason = f'{OBSERVED_PREFIX}{base.reason}' if alt.allowed else alt.reason
    return _labelled(alt, reason=reason, economic_flags=flags,
                     observed_economic_stop=base.reason, risk_policy_version=version)


def loss_streak_status_label(mode: str) -> str:
    """Status wording for an active loss-streak condition."""
    if mode == OBSERVE:
        return 'observed (Paper observe mode, not blocking)'
    return 'halt active'
