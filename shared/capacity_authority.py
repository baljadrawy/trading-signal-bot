"""WP-E08 capacity authority, legacy mode ``legacy_v1`` (WP-IR-03, WP-IR-04, WP-IR-05; PR-14; R7).

The single F7 capacity decision for one new trade: "admit", or a refusal with its inputs and
exactly one attributed reason code of funnel taxonomy v1
(``docs/design/remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md`` section 8). In
``legacy_v1`` it reproduces today's decision and changes nothing:

* ``decide_capacity`` runs the existing risk policy,
  ``shared.economic_halt_policy.evaluate_with_policy`` (a wrapper of the hash-pinned
  ``shared.risk_management.evaluate_new_trade``), with the ``(snapshot, limits, mode)`` that the
  tracker passes at ``trade_tracker/main.py:L1006``. ``CapacityDecision.risk_decision`` IS the
  object that call returned, so a call site that returns it stays byte-identical.
  ``attribute_decision`` describes a decision the caller already holds, without re-evaluating.
* Attribution re-reads the decision's own computed values with the identical comparisons and
  precedence of ``shared/risk_management.py:L122-L142`` and checks that they reproduce the legacy
  ``allowed`` and ``reason``; a mismatch raises ``CapacityAttributionError``. A slot refusal is
  ``F7.capacity_full`` even when the legacy reason is a ladder label (L141-L142); the label is
  kept in ``detail``. No ``F6`` code is ever produced here: a rank loss is not capacity.

Inputs, read the way the legacy code reads them (this module holds no limit and no default):

* slot limit ``min(MAX_OPEN_TRADES, RISK_CANARY_MAX_OPEN_TRADES)``
  (``trade_tracker/main.py:L979``; ``telegram/main.py:L379``), configured at
  ``shared/config.py:L159`` and ``L150``. The runtime-verified effective value is 2 (VER-12:
  canary 2, ``MAX_OPEN_TRADES`` unset, so 10);
* effective slots ``max(1, floor(min(limit, exposure bound) * multiplier))``
  (``shared/risk_management.py:L116-L120``); the multiplier is the loss ladder L-1 (L95-L114);
* occupancy is open ``active_trades`` only (``trade_tracker/main.py:L935-L941``). Working paper
  entry orders (``fill.action == 'wait'``, L806-L810) are reported, never counted (PR-12), so
  ``detail['reserved']`` is 0 in this mode;
* a zero or negative limit is refused by the legacy policy itself as ``invalid_risk_state``
  (``shared/risk_management.py:L71-L76``) and maps to ``F7.risk_state_invalid``. A non-integer
  or missing limit is refused at this boundary; the services cannot produce one, because
  ``shared/config.py`` parses both names with ``int()``.

Mirrors of the legacy pre-checks. Each returns the legacy result byte-for-byte plus a canonical
code; ``compare_shadow`` compares them with the authority and records every disagreement
without resolving any:

* ``delivery_gate``: ``telegram/main.py:L364-L382`` (``can_deliver_candidate``). The pause
  check comes first (L375-L376), then ``open >= min(...)`` only when that minimum is above zero
  (L377-L381), so a zero limit means "unlimited" there;
* ``tracker_precheck``: ``trade_tracker/main.py:L708-L716`` and ``L752-L759``.
  ``open >= MAX_OPEN_TRADES`` is checked only when ``MAX_OPEN_TRADES > 0``;
* ``legacy_admission_queue``: the duplicate and concurrency predicates of the admission query
  ``trade_tracker/main.py:L719-L749``. An already-registered signal (L728, and the
  ``ON CONFLICT (signal_id)`` insert at L873 recorded at L898-L899) maps to
  ``F7.already_registered``. One open trade per symbol (L730-L733) maps to ``F7.exposure_symbol``
  with ``legacy_rule`` ``one_open_per_symbol``; this mapping is INFERRED, since no pack row names
  that rule's code. The newest pending signal per symbol (``DISTINCT ON``, L720 and L748)
  supersedes the others as ``F7.superseded``. The rule is one open trade per symbol whatever its
  ``trade_type``; the legacy code has no one-per-kind rule.

Every citation is @ 19b6bc4 and identical @ bb7825f: the cited files did not change in
between.

Gaps, which are inputs here and never guessed:

* the pause state comes from ``get_pause_state()`` (``shared/trading_state.py``, a database
  read) and is an input to ``delivery_gate`` and to ``RiskSnapshot.manually_paused``;
* the open count is a separate database COUNT at delivery (``telegram/main.py:L377-L378``),
  before each signal (``trade_tracker/main.py:L753-L755``) and at admission (L935-L941). Each
  mirror takes it as an input, and a count that differs is recorded as ``open_count_differs``;
* admission-query predicates that are not capacity rules are not mirrored: delivered and ready
  (L726-L727), the 2-hour window (L729), one trade per (symbol, timeframe) per candle interval
  (L734-L740), rejected approvals (L741-L744) and the blacklist (L745-L747). The database
  collation of ``ORDER BY s.symbol`` and the order of rows with equal ``signal_time`` are not
  known here; equal times are refused;
* the force-close above ``MAX_OPEN_TRADES`` (``trade_tracker/main.py:L508-L556``) is not a
  capacity check (WP-OD-02) and is not mirrored. Target mode (``RiskBudget.max_positions``,
  counted reservations) is gated by PR-OD16, PR-OD21 and WP-G23 and is not implemented.

``resolve_capacity_mode`` validates a configured mode: only ``legacy_v1`` exists, and any other
value refuses. Pure and deterministic: no I/O, clock, randomness, configuration or service
import.
"""
from __future__ import annotations

import math
import types
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from shared.economic_halt_policy import (
    ECONOMIC_HARD_STOP_ORDER, OBSERVED_PREFIX, evaluate_with_policy, legacy_fields,
)
from shared.risk_management import RiskDecision, RiskLimits, RiskSnapshot

CAPACITY_MODE_LEGACY_V1 = "legacy_v1"
CAPACITY_MODES = (CAPACITY_MODE_LEGACY_V1,)  # target mode: PR-OD16, PR-OD21, then WP-G23
BUDGET_VERSION_LEGACY_V1 = "legacy_v1"     # RiskBudget mode name (PR section 5, "Legacy mode")
ADMIT = "admit"
REFUSE = "refuse"
SLOTS_FREE, SLOTS_FULL, SLOTS_INVALID = "free", "full", "invalid"

STAGE = "F7"
SCOPE = "opportunity"
SUB_STAGE_ADMISSION = "shared.admission"
CODE_CAPACITY_FULL = "F7.capacity_full"
CODE_RISK_STATE_INVALID = "F7.risk_state_invalid"
CODE_PAUSED = "F7.paused"
CODE_ALREADY_REGISTERED = "F7.already_registered"
CODE_SUPERSEDED = "F7.superseded"
CODE_EXPOSURE_GROSS = "F7.exposure_gross"
CODE_EXPOSURE_SYMBOL = "F7.exposure_symbol"
CODE_EXPOSURE_STRATEGY = "F7.exposure_strategy"
CODE_EXPOSURE_REGIME = "F7.exposure_regime"
ECONOMIC_LIMIT_CODES = tuple(f"F7.economic_limit:{rule}" for rule in ECONOMIC_HARD_STOP_ORDER)

# Configuration names the legacy call sites read; the caller passes their values.
SLOT_LIMIT_CONFIG = ("MAX_OPEN_TRADES", "RISK_CANARY_MAX_OPEN_TRADES")
LEGACY_RISK_LIMITS_CONFIG = (       # trade_tracker/main.py:L976-L988, besides the slot limit
    ("capital_usdt", "RISK_CAPITAL_USDT"),
    ("trade_amount_usdt", "TRADE_AMOUNT_USDT"),
    ("max_gross_exposure_pct", "MAX_GROSS_EXPOSURE_PERCENT"),
    ("max_symbol_exposure_pct", "MAX_SYMBOL_EXPOSURE_PERCENT"),
    ("max_strategy_exposure_pct", "MAX_STRATEGY_EXPOSURE_PERCENT"),
    ("max_regime_exposure_pct", "MAX_REGIME_EXPOSURE_PERCENT"),
    ("max_daily_loss_pct", "MAX_DAILY_LOSS_PERCENT"),
    ("max_weekly_loss_pct", "MAX_WEEKLY_LOSS_PERCENT"),
    ("max_drawdown_pct", "MAX_DRAWDOWN_PERCENT"),
    ("loss_halt_count", "STOP_ON_CONSECUTIVE_LOSSES"),
)

# shared/risk_management.py:L133-L140, in precedence order:
# (decision value, limit field, legacy reason, canonical code).
_EXPOSURE_CHECKS = (
    ("gross_exposure_pct_after", "max_gross_exposure_pct", "gross_exposure_limit",
     CODE_EXPOSURE_GROSS),
    ("symbol_exposure_pct_after", "max_symbol_exposure_pct", "symbol_concentration_limit",
     CODE_EXPOSURE_SYMBOL),
    ("strategy_exposure_pct_after", "max_strategy_exposure_pct", "strategy_concentration_limit",
     CODE_EXPOSURE_STRATEGY),
    ("regime_exposure_pct_after", "max_regime_exposure_pct", "regime_concentration_limit",
     CODE_EXPOSURE_REGIME),
)


class CapacityAttributionError(RuntimeError):
    """The attribution did not reproduce the legacy decision; it is never guessed."""


def _frozen(value: Any) -> Any:
    if isinstance(value, Mapping):
        return types.MappingProxyType({k: _frozen(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)                       # 'nan' / 'inf': stated, never hidden
    return value


# ── legacy input builders (byte-identical to the call sites) ────────────────

def legacy_slot_limit(max_open_trades, risk_canary_max_open_trades):
    """``min(MAX_OPEN_TRADES, RISK_CANARY_MAX_OPEN_TRADES)``, exactly as
    trade_tracker/main.py:L979 and telegram/main.py:L379, L764 compute it."""
    return min(max_open_trades, risk_canary_max_open_trades)


def legacy_risk_limits(cfg) -> RiskLimits:
    """The ``RiskLimits`` the tracker builds (trade_tracker/main.py:L976-L988).

    Every value is read from ``cfg`` by its configuration name; a missing name raises. Fields the
    tracker does not pass keep the ``RiskLimits`` declarations (shared/risk_management.py:L15-L24),
    exactly as there."""
    values = {name: getattr(cfg, key) for name, key in LEGACY_RISK_LIMITS_CONFIG}
    slot_limit = legacy_slot_limit(*(getattr(cfg, key) for key in SLOT_LIMIT_CONFIG))
    return RiskLimits(max_open_trades=slot_limit, **values)


def legacy_open_counts(open_trades: Iterable[Mapping], symbol, trade_type=None, regime=None) -> dict:
    """The occupancy fields of the tracker's ``RiskSnapshot`` (trade_tracker/main.py:L995-L1001).

    ``open_trades`` are rows with ``symbol``, ``trade_type`` and ``regime``. A falsy
    ``trade_type`` or ``regime`` counts 0, as in the legacy expressions."""
    trades = list(open_trades)
    return {
        "open_count": len(trades),
        "symbol_open_count": sum(1 for t in trades if t["symbol"] == symbol),
        "strategy_open_count": sum(1 for t in trades if trade_type and t["trade_type"] == trade_type),
        "regime_open_count": sum(1 for t in trades if regime and t["regime"] == regime),
    }


def resolve_capacity_mode(raw) -> str:
    """Validate a configured capacity mode. Only ``legacy_v1`` exists; any other value,
    including an empty one, refuses (an unknown flag value refuses to start)."""
    mode = str(raw).strip().lower() if raw is not None else ""
    if mode not in CAPACITY_MODES:
        raise ValueError(f"unknown capacity mode {raw!r}; expected one of {CAPACITY_MODES}")
    return mode


def _invalid_inputs(snapshot: RiskSnapshot, limits: RiskLimits) -> tuple:
    """Names failing the legacy validity predicate (shared/risk_management.py:L65-L74).

    Non-empty exactly when that predicate refuses."""
    numeric = (
        ("capital_usdt", limits.capital_usdt), ("trade_amount_usdt", limits.trade_amount_usdt),
        ("realized_total_usdt", snapshot.realized_total_usdt),
        ("daily_pnl_usdt", snapshot.daily_pnl_usdt), ("weekly_pnl_usdt", snapshot.weekly_pnl_usdt),
        ("unrealized_pnl_usdt", snapshot.unrealized_pnl_usdt),
        ("peak_equity_usdt", snapshot.peak_equity_usdt),
    )
    bad = [name for name, value in numeric if not math.isfinite(value)]
    checks = (
        ("capital_usdt", limits.capital_usdt <= 0),
        ("trade_amount_usdt", limits.trade_amount_usdt <= 0),
        ("max_open_trades", limits.max_open_trades <= 0),
        ("open_count", snapshot.open_count < 0),
        ("symbol_open_count", snapshot.symbol_open_count < 0),
        ("consecutive_losses", snapshot.consecutive_losses < 0),
    )
    bad.extend(name for name, failed in checks if failed and name not in bad)
    return tuple(bad)


def exposure_slot_bound(limits: RiskLimits) -> int:
    """The exposure-derived slot bound (shared/risk_management.py:L116-L118), same expression."""
    return math.floor(limits.capital_usdt * limits.max_gross_exposure_pct / 100
                      / limits.trade_amount_usdt + 1e-12)


def ladder_reasons(decision, limits: RiskLimits) -> tuple:
    """Every L-1 ladder label in legacy order (shared/risk_management.py:L95-L114), re-read from
    the decision's own drawdown, weekly and streak values with the identical comparisons."""
    out = []
    if decision.drawdown_pct >= limits.drawdown_warning_pct:
        out.append("drawdown_warning")
    elif decision.drawdown_pct >= limits.drawdown_caution_pct:
        out.append("drawdown_caution")
    if decision.weekly_pnl_pct <= -limits.weekly_minimum_pct:
        out.append("weekly_minimum")
    elif decision.weekly_pnl_pct <= -limits.weekly_reduce_pct:
        out.append("weekly_reduce")
    if decision.consecutive_losses >= limits.loss_minimum_count:
        out.append("loss_streak_minimum")
    elif decision.consecutive_losses >= limits.loss_reduce_count:
        out.append("loss_streak_reduce")
    return tuple(out)


# ── the authority ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapacityDecision:
    """One F7 admission decision in ``legacy_v1``. ``outcome`` always equals the legacy
    ``allowed``; ``slots`` is the slot check alone, so a full book under a higher-precedence
    stop is still visible as ``full``."""
    outcome: str
    reason_code: str | None
    slots: str
    detail: Mapping
    inputs: Mapping
    risk_decision: RiskDecision
    capacity_mode: str = CAPACITY_MODE_LEGACY_V1
    sub_stage: str | None = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "detail", _frozen(self.detail))
        object.__setattr__(self, "inputs", _frozen(self.inputs))
        object.__setattr__(self, "sub_stage", None if self.reason_code is None else SUB_STAGE_ADMISSION)

    @property
    def admitted(self) -> bool:
        return self.outcome == ADMIT

    def legacy_fields(self) -> tuple:
        """The legacy ``RiskDecision`` fields (shared/economic_halt_policy.py:L137-L142)."""
        return legacy_fields(self.risk_decision)

    def record_fields(self) -> dict | None:
        """Keyword arguments of the funnel ``RejectionRecord`` for this refusal (stage F7, scope
        opportunity); the caller adds the cycle, subject, times, rule and hashes. ``None`` on
        admit. For ``F7.capacity_full``, ``detail`` carries open, reserved, limit, multiplier
        and ``budget_version`` (WP-IR-03 output)."""
        if self.admitted:
            return None
        return {"stage": STAGE, "scope": SCOPE, "reason_code": self.reason_code,
                "sub_stage": self.sub_stage, "detail": _thaw(self.detail)}

    def as_dict(self) -> dict:
        return {"capacity_mode": self.capacity_mode, "outcome": self.outcome,
                "reason_code": self.reason_code, "sub_stage": self.sub_stage, "slots": self.slots,
                "detail": _thaw(self.detail), "inputs": _thaw(self.inputs),
                "legacy_fields": _thaw(list(self.legacy_fields()))}


def _attribute(snapshot: RiskSnapshot, limits: RiskLimits, decision, invalid: tuple,
               ladder: tuple) -> tuple:
    """(code or None, the legacy reason that code implies), by the legacy precedence."""
    observed = getattr(decision, "observed_economic_stop", None)
    if invalid:
        return CODE_RISK_STATE_INVALID, "invalid_risk_state"
    if snapshot.manually_paused:
        return CODE_PAUSED, snapshot.manual_pause_reason or "manual_pause"
    if observed is None:          # observe mode re-derives with the economic stops neutralised
        hits = (decision.daily_pnl_pct <= -limits.max_daily_loss_pct,
                decision.weekly_pnl_pct <= -limits.max_weekly_loss_pct,
                decision.drawdown_pct >= limits.max_drawdown_pct,
                decision.consecutive_losses >= limits.loss_halt_count)
        for rule, code, hit in zip(ECONOMIC_HARD_STOP_ORDER, ECONOMIC_LIMIT_CODES, hits):
            if hit:
                return code, rule
    for value, limit, legacy, code in _EXPOSURE_CHECKS:
        if getattr(decision, value) > getattr(limits, limit) + 1e-9:
            return code, legacy
    if snapshot.open_count >= decision.max_positions:
        return CODE_CAPACITY_FULL, ladder[0] if ladder else "max_open_trades"
    if observed:
        return None, f"{OBSERVED_PREFIX}{observed}"
    return None, ladder[0] if ladder else "within_limits"


def _require_integer_limit(limits: RiskLimits) -> None:
    limit = limits.max_open_trades
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"max_open_trades_not_integer:{limit!r}")


def _describe(snapshot: RiskSnapshot, limits: RiskLimits, decision, working_orders,
              extra_inputs: Mapping) -> CapacityDecision:
    if working_orders is not None and (isinstance(working_orders, bool)
                                       or not isinstance(working_orders, int) or working_orders < 0):
        raise ValueError("working_orders_invalid")
    invalid = _invalid_inputs(snapshot, limits)
    ladder = () if invalid else ladder_reasons(decision, limits)
    code, implied_reason = _attribute(snapshot, limits, decision, invalid, ladder)
    if (code is None) != bool(decision.allowed) or implied_reason != decision.reason:
        raise CapacityAttributionError(
            f"attribution {code!r}/{implied_reason!r} does not reproduce legacy "
            f"{decision.allowed!r}/{decision.reason!r}")
    slots = (SLOTS_INVALID if invalid
             else SLOTS_FULL if snapshot.open_count >= decision.max_positions else SLOTS_FREE)
    detail = {
        "open": snapshot.open_count,
        "reserved": 0,                               # legacy_v1 counts no reservation (PR-12)
        "limit": decision.max_positions,             # effective slots the open count meets
        "multiplier": float(decision.size_multiplier),
        "budget_version": BUDGET_VERSION_LEGACY_V1,
        "configured_limit": limits.max_open_trades,
        "exposure_slot_bound": None if invalid else exposure_slot_bound(limits),
        "ladder_reasons": list(ladder),
        "legacy_reason": decision.reason,
        "economic_flags": list(getattr(decision, "economic_flags", ()) or ()),
        "observed_economic_stop": getattr(decision, "observed_economic_stop", None),
        "risk_policy_version": getattr(decision, "risk_policy_version", None),
        "working_orders": working_orders,
        "check": "shared.risk_management.evaluate_new_trade",
    }
    if invalid:
        detail["invalid_inputs"] = list(invalid)
    inputs = {"snapshot": asdict(snapshot), "limits": asdict(limits),
              "working_orders": working_orders, **extra_inputs}
    return CapacityDecision(outcome=ADMIT if code is None else REFUSE, reason_code=code,
                            slots=slots, detail=detail, inputs=inputs, risk_decision=decision)


def attribute_decision(snapshot: RiskSnapshot, limits: RiskLimits, decision, *,
                       working_orders: int | None) -> CapacityDecision:
    """Describe a decision the legacy policy already returned for ``(snapshot, limits)``.

    ``decision`` is a ``RiskDecision`` or the tracker's ``PolicyRiskDecision``; it is kept as is.
    ``working_orders`` is the observed count of working paper entry orders, or ``None`` when it
    was not observed. It is reported and never counted (PR-12)."""
    _require_integer_limit(limits)
    return _describe(snapshot, limits, decision, working_orders, {})


def decide_capacity(snapshot: RiskSnapshot, limits: RiskLimits, *, economic_halt_mode: str,
                    working_orders: int | None,
                    evaluate: Callable = evaluate_with_policy) -> CapacityDecision:
    """The F7 capacity decision for one new trade in ``legacy_v1``.

    ``economic_halt_mode`` is the resolved mode the tracker passes
    (``economic_halt_mode()``, trade_tracker/main.py:L1006); it reaches the policy unchanged.
    ``evaluate`` is the policy callable; a call site passes its own module-level name so that
    the existing tests that patch it keep working. Its result is ``risk_decision``, unchanged."""
    _require_integer_limit(limits)
    decision = evaluate(snapshot, limits, economic_halt_mode)
    return _describe(snapshot, limits, decision, working_orders,
                     {"economic_halt_mode": economic_halt_mode})


# ── mirrors of the legacy pre-checks ─────────────────────────────────────────

TRACKER_PRECHECK_SITES = {
    "loop_entry": "trade_tracker/main.py:L708-L716",
    "per_signal": "trade_tracker/main.py:L752-L759",
}


@dataclass(frozen=True)
class TrackerPrecheck:
    """trade_tracker/main.py:L708-L716 or L752-L759. ``checked`` is False when
    ``MAX_OPEN_TRADES <= 0``: the count is then not read and nothing is blocked."""
    site: str
    checked: bool
    blocked: bool
    open_count: int | None
    limit: Any
    reason_code: str | None

    @property
    def detail(self) -> dict:
        return {"check": "tracker_precheck", "site": self.site, "open": self.open_count,
                "limit": self.limit, "limit_source": "MAX_OPEN_TRADES"}


def tracker_precheck(open_count: int | None, max_open_trades, *, site: str) -> TrackerPrecheck:
    """The tracker's own capacity stop: ``open >= MAX_OPEN_TRADES``, only when it is > 0.

    ``open_count`` is the call site's ``fetchval(...) or 0``; it may be ``None`` only when the
    check is skipped, because the legacy code does not read it then."""
    if site not in TRACKER_PRECHECK_SITES:
        raise ValueError(f"precheck_site_unknown:{site}")
    if not max_open_trades > 0:
        return TrackerPrecheck(site, False, False, None, max_open_trades, None)
    if open_count is None:
        raise ValueError("open_count_required")
    blocked = open_count >= max_open_trades
    return TrackerPrecheck(site, True, blocked, open_count, max_open_trades,
                           CODE_CAPACITY_FULL if blocked else None)


@dataclass(frozen=True)
class DeliveryGate:
    """telegram/main.py:L364-L382. ``legacy`` is the exact ``(allowed, block_reason)`` pair."""
    allowed: bool
    reason: str
    reason_code: str | None
    capacity_checked: bool
    open_count: int | None
    capacity: Any

    @property
    def legacy(self) -> tuple:
        return (self.allowed, self.reason)

    @property
    def detail(self) -> dict:
        return {"check": "delivery_gate", "open": self.open_count, "limit": self.capacity,
                "limit_source": "min(MAX_OPEN_TRADES, RISK_CANARY_MAX_OPEN_TRADES)",
                "legacy_reason": self.reason}


def delivery_gate(*, paused, pause_reason, open_count: int | None, max_open_trades,
                  risk_canary_max_open_trades) -> DeliveryGate:
    """The delivery pre-check. ``paused``/``pause_reason`` are ``get_pause_state()``'s result.
    ``open_count`` is the call site's ``fetchval(...) or 0``; it may be ``None`` only when
    paused, because the legacy code returns before reading it."""
    if paused:
        return DeliveryGate(False, pause_reason or "trading_paused", CODE_PAUSED, False, None, None)
    if open_count is None:
        raise ValueError("open_count_required")
    capacity = legacy_slot_limit(max_open_trades, risk_canary_max_open_trades)
    if capacity > 0 and open_count >= capacity:
        return DeliveryGate(False, f"portfolio_capacity_{open_count}/{capacity}", CODE_CAPACITY_FULL,
                            True, open_count, capacity)
    return DeliveryGate(True, "eligible", None, capacity > 0, open_count, capacity)


# ── shadow comparison ─────────────────────────────────────────────────────────

DISAGREEMENT_KINDS = (
    "mirror_admits_slots_full",            # the mirror lets through what the authority refuses
    "mirror_refuses_slots_free",           # the mirror is stricter than the authority
    "mirror_unlimited_authority_invalid",  # zero/negative limit: "unlimited" vs fail-closed
    "mirror_unlimited_authority_valid",
    "mirror_admits_authority_invalid",
    "mirror_refuses_authority_invalid",    # both refuse, under different codes
    "open_count_differs",                  # the two counts were read at different moments
)
# Notes are observations, not disagreements; "mirror_not_reached" is suffixed with the mirror.
NOTE_KINDS = ("working_orders_uncounted", "capacity_labelled_by_ladder", "mirror_not_reached")


@dataclass(frozen=True)
class Disagreement:
    mirror: str
    kind: str
    mirror_verdict: str
    authority_verdict: str
    detail: Mapping

    def __post_init__(self):
        if self.kind not in DISAGREEMENT_KINDS:
            raise ValueError(f"disagreement_kind_unknown:{self.kind}")
        object.__setattr__(self, "detail", _frozen(self.detail))

    def as_dict(self) -> dict:
        return {"mirror": self.mirror, "kind": self.kind, "mirror_verdict": self.mirror_verdict,
                "authority_verdict": self.authority_verdict, "detail": _thaw(self.detail)}


@dataclass(frozen=True)
class ShadowComparison:
    authority: CapacityDecision
    compared: tuple
    disagreements: tuple
    notes: tuple

    @property
    def agree(self) -> bool:
        return not self.disagreements

    def as_dict(self) -> dict:
        return {"authority": self.authority.as_dict(), "compared": list(self.compared),
                "disagreements": [d.as_dict() for d in self.disagreements],
                "notes": list(self.notes), "agree": self.agree}


_VERDICT_KIND = {
    ("pass", SLOTS_FULL): "mirror_admits_slots_full",
    ("refuse", SLOTS_FREE): "mirror_refuses_slots_free",
    ("unchecked", SLOTS_INVALID): "mirror_unlimited_authority_invalid",
    ("unchecked", SLOTS_FREE): "mirror_unlimited_authority_valid",
    ("unchecked", SLOTS_FULL): "mirror_unlimited_authority_valid",
    ("pass", SLOTS_INVALID): "mirror_admits_authority_invalid",
    ("refuse", SLOTS_INVALID): "mirror_refuses_authority_invalid",
}


def _mirror_verdict(mirror) -> tuple:
    """(name, verdict, open count): verdict is refuse | pass | unchecked | not_reached."""
    if isinstance(mirror, DeliveryGate):
        if mirror.reason_code == CODE_PAUSED:
            return "delivery_gate", "not_reached", None
        if not mirror.capacity_checked:
            return "delivery_gate", "unchecked", mirror.open_count
        return "delivery_gate", "refuse" if mirror.reason_code else "pass", mirror.open_count
    if isinstance(mirror, TrackerPrecheck):
        if not mirror.checked:
            return f"tracker_precheck:{mirror.site}", "unchecked", None
        return (f"tracker_precheck:{mirror.site}", "refuse" if mirror.blocked else "pass",
                mirror.open_count)
    raise ValueError("mirror_type_unknown")


def compare_shadow(authority: CapacityDecision, mirrors: Sequence) -> ShadowComparison:
    """Compare each mirror's capacity verdict with the authority's slot verdict.

    Only the slot question is compared: the delivery gate checks no economic or exposure
    limit, so an authority refusal for those reasons is not a disagreement. Every mismatch is
    recorded with its kind and both limits; none is resolved here."""
    if not isinstance(authority, CapacityDecision):
        raise ValueError("authority_decision_required")
    a_open = authority.detail["open"]
    compared, disagreements, notes = [], [], []
    for mirror in mirrors:
        name, verdict, m_open = _mirror_verdict(mirror)
        if verdict == "not_reached":
            notes.append(f"mirror_not_reached:{name}")
            continue
        compared.append(name)
        detail = {"mirror": mirror.detail, "authority_open": a_open,
                  "authority_limit": authority.detail["limit"],
                  "authority_reason_code": authority.reason_code}
        if m_open is not None and m_open != a_open:
            disagreements.append(Disagreement(name, "open_count_differs", verdict, authority.slots,
                                              detail))
        kind = _VERDICT_KIND.get((verdict, authority.slots))
        if kind is not None:
            disagreements.append(Disagreement(name, kind, verdict, authority.slots, detail))
    working = authority.detail["working_orders"]
    if (authority.slots == SLOTS_FREE and working
            and a_open + working >= authority.detail["limit"]):
        notes.append("working_orders_uncounted")
    if (authority.reason_code == CODE_CAPACITY_FULL
            and authority.detail["legacy_reason"] != "max_open_trades"):
        notes.append("capacity_labelled_by_ladder")
    return ShadowComparison(authority, tuple(compared), tuple(disagreements), tuple(notes))


# ── admission-queue mirror (duplicates and concurrency) ──────────────────────

@dataclass(frozen=True)
class PendingSignal:
    """One delivered signal the admission query can return."""
    signal_id: int
    symbol: str
    signal_time_ms: int


@dataclass(frozen=True)
class QueueExclusion:
    signal_id: int
    symbol: str
    reason_code: str
    legacy_rule: str
    detail: Mapping

    def __post_init__(self):
        object.__setattr__(self, "detail", _frozen(self.detail))


@dataclass(frozen=True)
class AdmissionQueue:
    queue: tuple        # PendingSignal, in symbol order (L748)
    excluded: tuple     # QueueExclusion, in input order


def legacy_admission_queue(pending: Sequence[PendingSignal], *, open_symbols: Iterable[str],
                           registered_signal_ids: Iterable[int]) -> AdmissionQueue:
    """The duplicate and concurrency predicates of trade_tracker/main.py:L719-L749.

    ``registered_signal_ids`` are signals with any ``active_trades`` row (L725, L728);
    ``open_symbols`` are symbols with an open trade (L730-L733). A row failing both is attributed
    to the first predicate in query order. Legacy records none of these drops."""
    open_set, registered = frozenset(open_symbols), frozenset(registered_signal_ids)
    rows = list(pending)
    if len({p.signal_id for p in rows}) != len(rows):
        raise ValueError("signal_id_duplicate")
    excluded, latest = [], {}
    for p in rows:
        if p.signal_id in registered:
            excluded.append(QueueExclusion(p.signal_id, p.symbol, CODE_ALREADY_REGISTERED,
                                           "active_trade_exists_for_signal",
                                           {"site": "trade_tracker/main.py:L728"}))
        elif p.symbol in open_set:
            excluded.append(QueueExclusion(p.signal_id, p.symbol, CODE_EXPOSURE_SYMBOL,
                                           "one_open_per_symbol",
                                           {"site": "trade_tracker/main.py:L730-L733",
                                            "mapping": "inferred"}))
        else:
            latest.setdefault(p.symbol, []).append(p)
    queue = []
    for symbol in sorted(latest):
        group = sorted(latest[symbol], key=lambda p: p.signal_time_ms, reverse=True)
        if len(group) > 1 and group[0].signal_time_ms == group[1].signal_time_ms:
            raise ValueError(f"signal_time_tie:{symbol}")     # database order unspecified
        queue.append(group[0])
        excluded.extend(QueueExclusion(p.signal_id, p.symbol, CODE_SUPERSEDED, "distinct_on_symbol",
                                       {"site": "trade_tracker/main.py:L720, L748",
                                        "superseded_by": group[0].signal_id})
                        for p in group[1:])
    order = {p.signal_id: i for i, p in enumerate(rows)}
    excluded.sort(key=lambda e: order[e.signal_id])
    return AdmissionQueue(tuple(queue), tuple(excluded))
