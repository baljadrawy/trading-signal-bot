"""Service-side wiring of the WP-E08 capacity authority and the F7 funnel records.

``shared/capacity_authority.py`` is pure; this module is the thin layer the tracker and the
delivery gate call.

* ``routed_risk_decision`` runs the admission policy through ``decide_capacity`` and returns the
  policy's own decision object, so the tracker's return value is byte-identical
  (``CapacityDecision.risk_decision`` IS that object). The attribution is a description: if it
  cannot reproduce the legacy decision it is reported through ``on_attribution_error`` and the
  legacy decision is returned unchanged. A failure of the policy itself propagates exactly as
  before, and the policy is called once.
* ``TrackerAdmissionFunnel`` and ``record_delivery_refusal`` emit F7 ``RejectionRecord``s with the
  canonical codes of the authority (``F7.capacity_full``, ``F7.paused``, ``F7.risk_state_invalid``,
  ``F7.economic_limit:<rule>``, ``F7.exposure_*``, ``F7.already_registered``) and the taxonomy F7
  codes of the entry path (``F7.no_price``, ``F7.entry_rejected``), through the evidence-v2 store of
  ``shared/funnel_hooks.py``. They exist only when ``FUNNEL_RECORDING=on``
  (``shared/funnel_flags.py``); every method observes, never raises and never changes a decision.

Not recorded at F7 (not capacity): the tracker's enforce-mode integrity re-check (F4 freshness)
and an invalid bracket (F5); they are excluded from the F7 input count and kept in the cycle notes,
so conservation at F7 is exact.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from shared import capacity_authority as ca

TRACKER_RULE_REF = "trade_tracker/main.py:register_new_signals"
DELIVERY_RULE_REF = "telegram/main.py:can_deliver_candidate"
CODE_NO_PRICE = "F7.no_price"
CODE_ENTRY_REJECTED = "F7.entry_rejected"
CODE_HALT_UNDER_LOCK = "F7.economic_limit:loss_streak_halt"
_DETAIL_KEYS = ("open", "reserved", "limit", "multiplier", "budget_version", "configured_limit",
                "exposure_slot_bound", "ladder_reasons", "legacy_reason", "economic_flags",
                "observed_economic_stop", "risk_policy_version", "invalid_inputs")


def routed_risk_decision(snapshot, limits, mode, *, evaluate: Callable,
                         on_attribution_error: Callable | None = None):
    """``(decision, capacity_decision_or_None)`` for one admission, ``decision`` being exactly
    ``evaluate(snapshot, limits, mode)``."""
    limit = getattr(limits, "max_open_trades", None)
    if isinstance(limit, bool) or not isinstance(limit, int):
        return evaluate(snapshot, limits, mode), None       # outside the authority's domain
    captured = []

    def policy(s, l, m):
        decision = evaluate(s, l, m)
        captured.append(decision)
        return decision

    try:
        authority = ca.decide_capacity(snapshot, limits, economic_halt_mode=mode,
                                       working_orders=None, evaluate=policy)
    except Exception as exc:
        if not captured:
            raise
        if on_attribution_error is not None:
            try:
                on_attribution_error(exc)
            except Exception:
                pass
        return captured[0], None
    return authority.risk_decision, authority


def _features(sig) -> dict:
    try:
        features = sig["features_snapshot"] if "features_snapshot" in sig.keys() else None
    except Exception:
        features = None
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except ValueError:
            features = None
    return features if isinstance(features, Mapping) else {}


def subject_fields(sig) -> dict:
    """Opportunity-scope subject of a signal row (symbol, timeframe, strategy, setup)."""
    from shared.funnel_hooks import candidate_fields
    features = _features(sig)
    setup = features.get("setup_identity") if isinstance(features.get("setup_identity"), Mapping) else {}
    get = (lambda k: sig[k] if k in sig.keys() else None) if hasattr(sig, "keys") else (lambda k: None)
    return candidate_fields({"symbol": get("symbol"), "timeframe": get("timeframe"),
                             "trade_type": get("trade_type"), "setup_identity": setup,
                             "candle_identity": {"candle_close_time_ms": setup.get("candle_close_time_ms")}})


def _compact(detail: Mapping) -> dict:
    return {k: detail[k] for k in _DETAIL_KEYS if k in detail}


class TrackerAdmissionFunnel:
    """F7 records of one ``register_new_signals`` pass. Build with ``begin`` only when the funnel
    flag is on; every method is total (failures are counted in the cycle, never raised)."""

    def __init__(self, cycle):
        self.cycle = cycle
        self.n_in = 0
        self.passed = 0
        self.held = 0
        self.excluded = {}

    @classmethod
    def begin(cls, service) -> "TrackerAdmissionFunnel | None":
        try:
            return cls(service.begin())
        except Exception:
            return None

    def _add(self, sig, code: str, rule: str, detail: Mapping) -> None:
        try:
            self.cycle.add(stage="F7", scope="opportunity", reason_code=code,
                           rule_ref=f"{TRACKER_RULE_REF}:{rule}", sub_stage="shared.admission",
                           detail=dict(detail), **subject_fields(sig))
        except Exception as exc:
            self.cycle.fail(f"record:{type(exc).__name__}")

    def considered(self, n: int) -> None:
        self.n_in += int(n)

    def loop_entry_full(self, pre: ca.TrackerPrecheck) -> None:
        """No signal was read (legacy returns first): one cycle-scope record of zero subjects."""
        try:
            self.cycle.add(stage="F7", scope="cycle", reason_code=pre.reason_code or ca.CODE_CAPACITY_FULL,
                           rule_ref=f"{TRACKER_RULE_REF}:loop_entry",
                           detail={**pre.detail, "subject_count": 0, "signals_read": False})
        except Exception as exc:
            self.cycle.fail(f"record:{type(exc).__name__}")

    def capacity_full(self, pending, pre: ca.TrackerPrecheck) -> None:
        for sig in pending:
            self._add(sig, ca.CODE_CAPACITY_FULL, "per_signal", pre.detail)

    def no_price(self, sig) -> None:
        self._add(sig, CODE_NO_PRICE, "no_price", {"legacy_reason": "no_current_fill_price"})

    def entry_rejected(self, sig, reason) -> None:
        self._add(sig, CODE_ENTRY_REJECTED, "entry_rejected", {"legacy_reason": str(reason)[:120]})

    def held_wait(self) -> None:
        self.held += 1

    def risk_refused(self, sig, authority) -> None:
        if authority is None:
            self.cycle.fail("risk_attribution_unavailable")
            return
        fields = authority.record_fields() or {}
        self._add(sig, fields.get("reason_code") or ca.CODE_RISK_STATE_INVALID, "assess_new_trade_risk",
                  _compact(fields.get("detail") or {}))

    def halt_under_lock(self, sig) -> None:
        self._add(sig, CODE_HALT_UNDER_LOCK, "admission_lock", {"legacy_reason": "loss_streak_halt"})

    def already_registered(self, sig) -> None:
        self._add(sig, ca.CODE_ALREADY_REGISTERED, "insert",
                  {"legacy_reason": "active_trade_exists_for_signal"})

    def admitted(self) -> None:
        self.passed += 1

    def exclude(self, kind: str) -> None:
        """A drop recorded outside F7 (F4 integrity, F5 bracket): out of the F7 input count."""
        self.excluded[kind] = self.excluded.get(kind, 0) + 1
        self.n_in -= 1

    def finish(self) -> dict | None:
        try:
            self.cycle.recorder.observe_counts("F7", n_in=max(self.n_in, 0), passed=self.passed,
                                               held=self.held)
            self.cycle.notes.update({f"excluded:{k}": v for k, v in sorted(self.excluded.items())})
            return self.cycle.finish()
        except Exception:
            return None


def record_delivery_refusal(service, signal, gate: ca.DeliveryGate | None) -> dict | None:
    """One cycle with one F7 record for a refused delivery (telegram); never raises."""
    try:
        cycle = service.begin()
        code = gate.reason_code if gate is not None and gate.reason_code else None
        cycle.recorder.observe_counts("F7", n_in=1, passed=0)
        if code is None:
            cycle.fail("delivery_gate_unavailable")
        else:
            cycle.add(stage="F7", scope="opportunity", reason_code=code,
                      rule_ref=DELIVERY_RULE_REF, sub_stage="shared.admission",
                      detail=dict(gate.detail), **subject_fields(signal))
        return cycle.finish()
    except Exception:
        return None


def funnel_service(name: str, *, max_records_per_day: int | None) -> Any:
    """The evidence-v2 funnel service of a process (``shared/funnel_hooks.FunnelService``) with
    the start-up daily record cap (``FUNNEL_MAX_RECORDS_PER_DAY``; required when recording)."""
    from shared.funnel_hooks import FunnelService
    return FunnelService(name, max_records_per_day=max_records_per_day)
