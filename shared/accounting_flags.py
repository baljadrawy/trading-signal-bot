"""Flags of the WP2 accounting and capacity integration in trade_tracker and telegram.

Every flag is read from the environment once, at service start-up (``resolve_accounting_flags``),
and every unknown value refuses to start (RuntimeError). Like ``shared/funnel_flags.py``, these are
not ``shared.config.Config`` fields: every Config field enters ``evidence_v2.compute_config_hash``,
which is stamped on signals and events, so a new field would change those bytes even at its
default. A missing variable means the default; an empty or unknown value refuses.

==============================  =============================  ==============================
environment variable            default (legacy, byte-for-byte) other accepted value
==============================  =============================  ==============================
``PAPER_COST_LABEL_POLICY``     ``net_after_modeled_cost_v1``  ``net_single_count_legacy_v1``
``PAPER_BREAK_EVEN_POLICY``     ``legacy_tracker_v1``          ``single_count_legacy_v1``
``LEDGER_SHADOW``               ``off``                        ``on``
``POSITION_STATE_SHADOW``       ``off``                        ``on``
==============================  =============================  ==============================

* ``PAPER_COST_LABEL_POLICY`` (R4.a / R4.e, WP-E07): which rule fills the A38 economic fields of a
  new ``trade_results`` row. The default is the legacy flat round trip of ``legacy_tracker_v1``
  (``shared/fees.py``). The alternative books the same model's fee once per leg on that leg's
  executed notional and its stop slippage once, in the stop fill (``shared/cost_label_policy.py``).
  It changes stored economics and labels, not decisions; activation is WP-G07 (SE-68, SE-82).
* ``PAPER_BREAK_EVEN_POLICY`` (R4.b, WP-G06): the post-T1 break-even stop. The alternative changes
  exits, so it is a strategy-version boundary; it is developed here and never activated.
* ``LEDGER_SHADOW`` (WP-E02, PR-I13): reconcile each close against ``shared/portfolio_ledger.py``.
* ``POSITION_STATE_SHADOW`` (WP-D03, SE-66): validate the tracker's lifecycle steps through
  ``shared/position_state.py``. Enforce mode does not exist.

The funnel flag is ``FUNNEL_RECORDING`` of ``shared/funnel_flags.py`` (one flag for every service);
``resolve_accounting_flags`` resolves it too, so one start-up call refuses every bad value.

No research cost model can be selected by any value here (WP-IR-07; SE-81, SE-87, OQ-08).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

LEGACY_LABEL_POLICY = "net_after_modeled_cost_v1"           # == shared.fees.LABEL_POLICY
SINGLE_COUNT_LABEL_POLICY = "net_single_count_legacy_v1"
LABEL_POLICIES = (LEGACY_LABEL_POLICY, SINGLE_COUNT_LABEL_POLICY)

LEGACY_BREAK_EVEN = "legacy_tracker_v1"
SINGLE_COUNT_BREAK_EVEN = "single_count_legacy_v1"
BREAK_EVEN_POLICIES = (LEGACY_BREAK_EVEN, SINGLE_COUNT_BREAK_EVEN)

SHADOW_MODES = ("off", "on")

COST_LABEL_POLICY_ENV = "PAPER_COST_LABEL_POLICY"
BREAK_EVEN_POLICY_ENV = "PAPER_BREAK_EVEN_POLICY"
LEDGER_SHADOW_ENV = "LEDGER_SHADOW"
POSITION_STATE_SHADOW_ENV = "POSITION_STATE_SHADOW"


def _choice(env: Mapping[str, str], name: str, default: str, allowed: tuple) -> str:
    raw = env.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value not in allowed:
        raise RuntimeError(f"unknown {name} {raw!r}; expected one of {allowed}")
    return value


@dataclass(frozen=True)
class AccountingFlags:
    """Resolved flag values. ``AccountingFlags()`` is the legacy configuration."""
    cost_label_policy: str = LEGACY_LABEL_POLICY
    break_even_policy: str = LEGACY_BREAK_EVEN
    ledger_shadow: bool = False
    position_state_shadow: bool = False
    funnel_recording: bool = False

    def __post_init__(self):
        if self.cost_label_policy not in LABEL_POLICIES:
            raise RuntimeError(f"unknown cost label policy {self.cost_label_policy!r}")
        if self.break_even_policy not in BREAK_EVEN_POLICIES:
            raise RuntimeError(f"unknown break-even policy {self.break_even_policy!r}")
        for name in ("ledger_shadow", "position_state_shadow", "funnel_recording"):
            if not isinstance(getattr(self, name), bool):
                raise RuntimeError(f"{name} must be a bool")

    @property
    def is_legacy(self) -> bool:
        return self == LEGACY_FLAGS

    def as_dict(self) -> dict:
        return {"cost_label_policy": self.cost_label_policy,
                "break_even_policy": self.break_even_policy,
                "ledger_shadow": self.ledger_shadow,
                "position_state_shadow": self.position_state_shadow,
                "funnel_recording": self.funnel_recording}


LEGACY_FLAGS = AccountingFlags()


def resolve_accounting_flags(environ: Mapping[str, str] | None = None, *,
                             require_store: bool = True) -> AccountingFlags:
    """Read every flag; an unknown value raises RuntimeError (call before any I/O at start-up).
    ``require_store`` is passed to ``funnel_recording_enabled`` (FUNNEL_RECORDING=on needs the
    evidence-v2 store)."""
    from shared.funnel_flags import funnel_recording_enabled
    env = os.environ if environ is None else environ
    return AccountingFlags(
        cost_label_policy=_choice(env, COST_LABEL_POLICY_ENV, LEGACY_LABEL_POLICY, LABEL_POLICIES),
        break_even_policy=_choice(env, BREAK_EVEN_POLICY_ENV, LEGACY_BREAK_EVEN, BREAK_EVEN_POLICIES),
        ledger_shadow=_choice(env, LEDGER_SHADOW_ENV, "off", SHADOW_MODES) == "on",
        position_state_shadow=_choice(env, POSITION_STATE_SHADOW_ENV, "off", SHADOW_MODES) == "on",
        funnel_recording=funnel_recording_enabled(env, require_store=require_store),
    )
