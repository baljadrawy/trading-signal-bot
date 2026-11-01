"""Cost-model registry (WP-D04): the legacy Paper accounting rule and the proposed research models.

Three models, named by ``cost_model_id`` (WP-IR-07; STRATEGY_AND_EXECUTION_CONTRACT.md §C4):

* ``legacy_tracker_v1`` describes the rule the Paper tracker books today. A flat
  ``FEE_ROUNDTRIP_PCT`` (percent) is charged once per trade on the configured notional
  ``TRADE_AMOUNT_USDT`` (``shared/fees.py:L20-24, L52-60``; ``trade_tracker/main.py:L409, L947,
  L1350``). Every stop exit also fills at ``stop_reference × (1 − STOP_SLIPPAGE)``
  (``shared/triple_barrier.py:L320``; the tracker passes the value at ``trade_tracker/main.py:L1209``).
  The flat 0.3 is documented as "0.1%/side fee + ~0.1% slippage" (``shared/config.py:L89-91``), so
  slippage on a stop exit is charged twice. This is the R4 defect. It is reproduced here, declared
  in the data and never hidden.
* ``research_baseline_v1`` and ``research_stress_v1`` hold the charter's PROPOSED research costs:
  0.40% and 0.60% all-in round trip, including a standard 0.10% fee per side (charter §3 C, CH:L25).
  They are booked once per leg on that leg's executed notional (SE-44 to SE-46). Adoption for any
  evaluation or for Paper accounting is a WP3 owner decision (SE-81, SE-87, OQ-08).

Code citations are ``@ bb7825f``. The cited files are byte-identical at ``46578aa`` and at the
branch HEAD this module was written on.

**Selection.** The registry describes models and never selects one. There is no default model
and no activation switch: every caller names its ``cost_model_id``, and every priced leg, trade
and binding carries that id.

**Single booking (SE-45; PR-I11).** Each cost component of a model is booked exactly once per leg,
in exactly one place. It is either inside the execution price (``in_execution_price``), an
explicit fee on the leg's executed notional (``explicit_fee_on_leg``), or, for the legacy model
only, a flat charge once per trade (``flat_per_trade``). Attribution components name a share of a
booked component and are never booked themselves. A cost kind (fee, spread, slippage) charged by
two booked components is a double count. ``validate_model`` refuses an undeclared one, and only
``legacy_tracker_v1`` declares one: ``slippage``, defect R4. ``CostBook`` refuses a leg booked
twice, an already-priced leg, an exit beyond the bought quantity and a second close. ``aggregate``
refuses mixing models, so the stress model is never added on top of the baseline.

**Identity.** ``CostModel.content_hash`` is sha256 over the canonical JSON (sorted keys, compact
separators, ASCII) of the model's economic content: components, parameter values, required
inputs, declared double counts and defects. This is the scheme ``shared/strategy_identity.py``
uses. Citations and notes are provenance and are not hashed. Every number is a decimal string, so
the hash never depends on a float's repr. A bound ``LegacyTrackerV1`` adds a ``config_hash`` over
the values it was bound to: numeric parameters enter ``config_hash``, never an identifier.

**Two numeric surfaces for the legacy model.**

* *Float surface* (``fee_usdt``, ``net_usdt``, ``net_pct``, ``economic_close``,
  ``barrier_cost_kwargs``). These are the calls ``trade_tracker/main.py`` makes today. They call
  ``shared/fees.py`` with explicit arguments, so the legacy figures stay byte-identical by
  construction and ``shared/fees.py`` stays the one implementation of the legacy rule.
* *Decimal surface* (``price_leg``, ``trade_bookings``, used through ``CostBook``). It states the
  same rule per leg for ledgers (PR-C03). It agrees with the float surface within quantization.

This module reads no environment variable, clock, database or network itself; importing
``shared/fees.py`` loads ``shared/config.py`` as it does in every service. Configuration values
arrive as arguments. ``legacy_tracker_v1_from_config`` reads three attributes of the object it is
given.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import (ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation,
                     Overflow, localcontext)
from types import MappingProxyType
from typing import Any, ClassVar, Iterable, Mapping

from shared import fees as _fees

COST_MODEL_SCHEME = "tsb-cost-model/1"
COST_BINDING_SCHEME = "tsb-cost-model-binding/1"

LEGACY_TRACKER_V1 = "legacy_tracker_v1"
RESEARCH_BASELINE_V1 = "research_baseline_v1"
RESEARCH_STRESS_V1 = "research_stress_v1"
# WP-IR-07: exactly these three identifiers (shared/portfolio_ledger.py holds the same tuple).
COST_MODEL_IDS = (LEGACY_TRACKER_V1, RESEARCH_BASELINE_V1, RESEARCH_STRESS_V1)
# An identifier never carries a value (WP-IR-07): lower-case words plus a version suffix.
IDENTIFIER = re.compile(r"^[a-z]+(_[a-z]+)*_v[1-9][0-9]*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

# What a model describes. Neither value selects or activates anything.
KIND_LEGACY = "legacy_runtime"
KIND_RESEARCH = "research_proposed"
STATUS_LEGACY = "LEGACY_RUNTIME_RULE"      # the rule the Paper tracker books today (VER-19)
STATUS_PROPOSED = "PROPOSED_NOT_ADOPTED"   # charter proposal; adoption is a WP3 owner decision
UNSPECIFIED = "UNSPECIFIED"                # a value no source gives; an owner decision

LEGACY_LABEL_POLICY = _fees.LABEL_POLICY   # 'net_after_modeled_cost_v1' (shared/fees.py:L41)

COST_KINDS = ("fee", "spread", "slippage")

BOOK_EXPLICIT_FEE = "explicit_fee_on_leg"
BOOK_IN_PRICE = "in_execution_price"
BOOK_FLAT_PER_TRADE = "flat_per_trade"
BOOK_ATTRIBUTION = "attribution_only"
BOOK_NOT_MODELLED = "not_modelled"
BOOKED = (BOOK_EXPLICIT_FEE, BOOK_IN_PRICE, BOOK_FLAT_PER_TRADE)
BOOKINGS = BOOKED + (BOOK_ATTRIBUTION, BOOK_NOT_MODELLED)

BASIS_EXECUTED_LEG_NOTIONAL = "executed_leg_notional"
BASIS_LEG_REFERENCE = "leg_reference_price"
BASIS_CONFIGURED_NOTIONAL = "configured_notional"
BASIS_NONE = "none"
BASES = (BASIS_EXECUTED_LEG_NOTIONAL, BASIS_LEG_REFERENCE, BASIS_CONFIGURED_NOTIONAL, BASIS_NONE)

LEGS_EVERY = "every_leg"
LEGS_TAKER = "taker_legs"
LEGS_STOP = "stop_legs"
LEGS_TRADE = "once_per_trade"
LEGS_NONE = "none"
LEG_SCOPES = (LEGS_EVERY, LEGS_TAKER, LEGS_STOP, LEGS_TRADE, LEGS_NONE)

COMPONENT_STATUSES = ("SPECIFIED", "DERIVED", "DOCUMENTED_ATTRIBUTION", "UNSPECIFIED",
                      "NOT_MODELLED")

ROLE_ENTRY = "entry"
ROLE_TARGET = "target"
ROLE_STOP = "stop"            # stop_loss, break_even and trailing stops all fill as a stop
ROLE_TIME_EXIT = "time_exit"
ROLE_THESIS_EXIT = "thesis_exit"
ROLES = (ROLE_ENTRY, ROLE_TARGET, ROLE_STOP, ROLE_TIME_EXIT, ROLE_THESIS_EXIT)
# SE-46: stops are market orders on trigger; time and thesis exits are taker fills.
RESEARCH_TAKER_ONLY_ROLES = (ROLE_STOP, ROLE_TIME_EXIT, ROLE_THESIS_EXIT)

# Exact decimal arithmetic: every booking is a sum or product of finite decimals, so it is exact
# at this precision. Inexact is trapped: a result that would need rounding is refused.
_EXACT = Context(prec=80, rounding=ROUND_HALF_EVEN, Emin=-999_999, Emax=999_999,
                 traps=[InvalidOperation, DivisionByZero, Overflow, Inexact])
ZERO = Decimal(0)
HUNDRED = Decimal(100)


class CostModelError(ValueError):
    """A refused model, binding, leg or booking. ``reason`` is a stable machine-readable code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ── canonical JSON (the shared/strategy_identity.py scheme, stdlib only) ─────────────────────

def _check_canonical(value: Any, where: str = "$") -> None:
    """Only str, int, bool, None, lists and str-keyed mappings: floats are refused outright so a
    hash never depends on a float's repr."""
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check_canonical(item, f"{where}[{i}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CostModelError("not_canonical", f"non-string key {key!r} at {where}")
            _check_canonical(item, f"{where}.{key}")
        return
    raise CostModelError("not_canonical", f"{type(value).__name__} at {where}")


def canonical_json(value: Any) -> str:
    _check_canonical(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _decimal_text(text: str, where: str) -> Decimal:
    if not isinstance(text, str):
        raise CostModelError("invalid_parameter", f"{where} must be a decimal string")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise CostModelError("invalid_parameter", f"{where} = {text!r}") from None
    if not number.is_finite() or number < 0:
        raise CostModelError("invalid_parameter", f"{where} = {text!r}")
    return number


# ── model specification ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Parameter:
    """One numeric parameter. ``value`` is a decimal string or ``UNSPECIFIED``. ``source``,
    ``evidence`` and ``runtime`` are provenance (not hashed); ``runtime`` records the
    runtime-verified value beside a legacy code default."""
    name: str
    value: str
    unit: str
    source: str
    evidence: str
    runtime: str = ""

    def identity(self) -> dict:
        return {"name": self.name, "value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class CostComponent:
    """One cost component: what it charges, where it is booked, on which basis and legs.
    ``part_of`` names the booked component an attribution component is a share of."""
    component_id: str
    charges: tuple
    booking: str
    basis: str
    legs: str
    parameter: str | None
    status: str
    part_of: str | None = None
    source: str = ""
    note: str = ""

    def identity(self) -> dict:
        return {"component_id": self.component_id, "charges": list(self.charges),
                "booking": self.booking, "basis": self.basis, "legs": self.legs,
                "parameter": self.parameter, "status": self.status, "part_of": self.part_of}


@dataclass(frozen=True)
class CostModel:
    cost_model_id: str
    version: str
    kind: str
    status: str
    round_trip_pct: str
    label_policy: str
    components: tuple
    parameters: tuple
    required_inputs: tuple
    declared_double_counts: tuple
    defects: tuple
    adoption: str = ""
    sources: tuple = ()

    def parameter(self, name: str) -> Parameter:
        for p in self.parameters:
            if p.name == name:
                return p
        raise CostModelError("unknown_parameter", f"{self.cost_model_id}.{name}")

    def component(self, component_id: str) -> CostComponent:
        for c in self.components:
            if c.component_id == component_id:
                return c
        raise CostModelError("unknown_component", f"{self.cost_model_id}.{component_id}")

    def booked_components(self) -> tuple:
        return tuple(c for c in self.components if c.booking in BOOKED)

    def leg_components(self) -> tuple:
        """Booked components that appear once on every leg (amount 0 where they do not apply)."""
        return tuple(c for c in self.booked_components() if c.legs != LEGS_TRADE)

    def trade_components(self) -> tuple:
        return tuple(c for c in self.booked_components() if c.legs == LEGS_TRADE)

    def descriptor(self) -> dict:
        """The hashed economic content (no citations, no notes)."""
        return {
            "cost_model_id": self.cost_model_id, "version": self.version, "kind": self.kind,
            "status": self.status, "round_trip_pct": self.round_trip_pct,
            "label_policy": self.label_policy,
            "components": sorted((c.identity() for c in self.components),
                                 key=lambda d: d["component_id"]),
            "parameters": sorted((p.identity() for p in self.parameters), key=lambda d: d["name"]),
            "required_inputs": list(self.required_inputs),
            "declared_double_counts": list(self.declared_double_counts),
            "defects": list(self.defects),
            "activation_path": "none",
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash({"scheme": COST_MODEL_SCHEME, "descriptor": self.descriptor()})

    def identity(self) -> dict:
        return {"cost_model_id": self.cost_model_id, "version": self.version,
                "content_hash": self.content_hash}


def detect_overlaps(components: Iterable[CostComponent]) -> tuple:
    """Cost kinds charged by more than one BOOKED component (a double count)."""
    seen: dict[str, str] = {}
    dup: set[str] = set()
    for c in components:
        if c.booking not in BOOKED:
            continue
        for kind in c.charges:
            if kind in seen and seen[kind] != c.component_id:
                dup.add(kind)
            seen.setdefault(kind, c.component_id)
    return tuple(sorted(dup))


def validate_model(model: CostModel) -> CostModel:
    """Refuse a malformed model, an undeclared double count or a research model that is not
    booked per leg on executed notional."""
    mid = model.cost_model_id
    if mid not in COST_MODEL_IDS or not IDENTIFIER.match(mid):
        raise CostModelError("cost_model_unknown", repr(mid))
    if not SEMVER.match(model.version):
        raise CostModelError("invalid_version", f"{mid} {model.version!r}")
    legacy = mid == LEGACY_TRACKER_V1
    if (model.kind, model.status) != ((KIND_LEGACY, STATUS_LEGACY) if legacy
                                      else (KIND_RESEARCH, STATUS_PROPOSED)):
        raise CostModelError("invalid_status", f"{mid}: {model.kind}/{model.status}")
    params = {}
    for p in model.parameters:
        if p.name in params:
            raise CostModelError("duplicate_parameter", f"{mid}.{p.name}")
        params[p.name] = None if p.value == UNSPECIFIED else _decimal_text(p.value, f"{mid}.{p.name}")
    ids = [c.component_id for c in model.components]
    if len(set(ids)) != len(ids):
        raise CostModelError("duplicate_component", mid)
    by_id = {c.component_id: c for c in model.components}
    for c in model.components:
        where = f"{mid}.{c.component_id}"
        if (not c.charges or len(set(c.charges)) != len(c.charges)
                or not set(c.charges) <= set(COST_KINDS)):
            raise CostModelError("invalid_component", f"{where} charges {c.charges!r}")
        if (c.booking not in BOOKINGS or c.basis not in BASES or c.legs not in LEG_SCOPES
                or c.status not in COMPONENT_STATUSES):
            raise CostModelError("invalid_component", where)
        if c.parameter is not None and c.parameter not in params:
            raise CostModelError("unknown_parameter", f"{where} -> {c.parameter}")
        value = params.get(c.parameter) if c.parameter is not None else None
        if c.booking in BOOKED:
            if c.part_of is not None or c.parameter is None or value is None:
                raise CostModelError("invalid_component", f"{where}: a booked component needs a value")
            if (c.legs == LEGS_TRADE) != (c.booking == BOOK_FLAT_PER_TRADE):
                raise CostModelError("invalid_component", f"{where}: legs/booking mismatch")
        elif c.booking == BOOK_ATTRIBUTION:
            parent = by_id.get(c.part_of)
            if parent is None or parent.booking not in BOOKED or not set(c.charges) <= set(parent.charges):
                raise CostModelError("invalid_attribution", where)
            if (value is None) != (c.status == UNSPECIFIED):
                raise CostModelError("invalid_attribution", f"{where}: status/value mismatch")
        elif c.status not in ("NOT_MODELLED", UNSPECIFIED):
            raise CostModelError("invalid_component", where)
    overlaps = detect_overlaps(model.components)
    if overlaps != tuple(sorted(model.declared_double_counts)):
        raise CostModelError("undeclared_double_count",
                             f"{mid}: overlaps {overlaps} declared {model.declared_double_counts}")
    if legacy:
        if model.label_policy != LEGACY_LABEL_POLICY:
            raise CostModelError("invalid_label_policy", mid)
        if model.round_trip_pct != model.parameter("fee_roundtrip_pct").value:
            raise CostModelError("round_trip_mismatch", mid)
        parts = [params[c.parameter] for c in model.components
                 if c.part_of == "flat_roundtrip" and params.get(c.parameter) is not None]
        with localcontext(_EXACT):
            if parts and sum(parts, ZERO) != params["fee_roundtrip_pct"]:
                raise CostModelError("attribution_mismatch", mid)
    else:
        if model.declared_double_counts or model.required_inputs:
            raise CostModelError("research_not_per_leg", mid)
        if any(c.booking == BOOK_FLAT_PER_TRADE or c.basis == BASIS_CONFIGURED_NOTIONAL
               for c in model.components):
            raise CostModelError("research_not_per_leg", f"{mid}: flat or configured-notional cost")
        fee = params.get("fee_per_side")
        in_price = params.get("spread_and_slippage_per_side")
        if fee is None or in_price is None:
            raise CostModelError("research_not_per_leg", f"{mid}: fee or in-price rate missing")
        with localcontext(_EXACT):
            if 2 * (fee + in_price) * HUNDRED != _decimal_text(model.round_trip_pct, mid):
                raise CostModelError("round_trip_mismatch", mid)
    return model


# ── the three models ───────────────────────────────────────────────────────────────────────

_CFG = "shared/config.py"
_TB = "shared/triple_barrier.py"
_TT = "trade_tracker/main.py"
_FEES = "shared/fees.py"
_CAL = "shared/execution_calibration.py"
_SE = "docs/design/remediation-design-pack-20261101/STRATEGY_AND_EXECUTION_CONTRACT.md"
_CHARTER = "docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md:L25"

_LEGACY = CostModel(
    cost_model_id=LEGACY_TRACKER_V1, version="1.0.0", kind=KIND_LEGACY, status=STATUS_LEGACY,
    round_trip_pct="0.3", label_policy=LEGACY_LABEL_POLICY,
    parameters=(
        Parameter("fee_roundtrip_pct", "0.3", "percent_of_configured_notional_per_trade",
                  f"{_CFG}:L92 @ bb7825f (code default); {_TB}:L36 @ bb7825f "
                  "(ROUNDTRIP_COST_DEFAULT 0.003, the same value as a fraction)",
                  "SOURCE_VERIFIED", runtime="0.3 RUNTIME_VERIFIED (VER-19)"),
        Parameter("stop_slippage", "0.001", "fraction_of_stop_reference",
                  f"{_CFG}:L107 @ bb7825f (code default); {_TB}:L35 @ bb7825f "
                  "(STOP_SLIPPAGE_DEFAULT)", "SOURCE_VERIFIED",
                  runtime="0.001 RUNTIME_VERIFIED (VER-19)"),
        Parameter("fee_part_pct", "0.2", "percent_of_configured_notional_per_trade",
                  f"{_CFG}:L90 @ bb7825f (comment: 0.1%/side fee); {_CAL}:L344 @ bb7825f "
                  "(TRACKER_FEE_PART_PCT)", "DOCUMENTED_IN_SOURCE_COMMENT",
                  runtime="attribution of the code default 0.3 only"),
        Parameter("slippage_allowance_pct", "0.1", "percent_of_configured_notional_per_trade",
                  f"{_CFG}:L90 @ bb7825f (comment: '~0.1%' slippage, approximate); {_CAL}:L345 "
                  "@ bb7825f (TRACKER_SLIPPAGE_ALLOWANCE_PCT, exact 0.1)",
                  "DOCUMENTED_IN_SOURCE_COMMENT",
                  runtime="attribution of the code default 0.3 only"),
    ),
    components=(
        CostComponent("flat_roundtrip", ("fee", "slippage"), BOOK_FLAT_PER_TRADE,
                      BASIS_CONFIGURED_NOTIONAL, LEGS_TRADE, "fee_roundtrip_pct", "SPECIFIED",
                      source=(f"{_FEES}:L20-24, L52-60 @ bb7825f; {_TT}:L409, L947, L1350 "
                              "@ bb7825f"),
                      note=("configured_notional × fee_roundtrip_pct / 100, once per trade, "
                            "whatever the number of legs (PR-16); the stored gross is gross")),
        CostComponent("flat_fee_part", ("fee",), BOOK_ATTRIBUTION, BASIS_NONE, LEGS_NONE,
                      "fee_part_pct", "DOCUMENTED_ATTRIBUTION", part_of="flat_roundtrip",
                      source=f"{_CFG}:L89-91 @ bb7825f"),
        CostComponent("flat_slippage_allowance", ("slippage",), BOOK_ATTRIBUTION, BASIS_NONE,
                      LEGS_NONE, "slippage_allowance_pct", "DOCUMENTED_ATTRIBUTION",
                      part_of="flat_roundtrip", source=f"{_CFG}:L89-91 @ bb7825f"),
        CostComponent("stop_fill_slippage", ("slippage",), BOOK_IN_PRICE, BASIS_LEG_REFERENCE,
                      LEGS_STOP, "stop_slippage", "SPECIFIED",
                      source=(f"{_TB}:L308-322 @ bb7825f (fill = stop × (1 − slippage), L320); "
                              f"stop reference min(stop, observation) {_TB}:L198-200, L238-239; "
                              f"value passed at {_TT}:L1207-1211 @ bb7825f"),
                      note=("entry fills at the observed price (observed_price_v0), targets at the "
                            "target, time exits at the observation: no in-price cost (SE-13, SE-14)")),
        CostComponent("spread", ("spread",), BOOK_NOT_MODELLED, BASIS_NONE, LEGS_NONE, None,
                      UNSPECIFIED,
                      source=f"{_CFG}:L185 @ bb7825f (MAX_SPREAD_PCT is a selection filter)",
                      note=("spread is never booked (SE-11); whether the flat allowance is meant "
                            "to cover it is not stated in source")),
    ),
    required_inputs=("configured_notional_usdt",),
    declared_double_counts=("slippage",),
    defects=("R4: stop-exit slippage is charged in the stop fill and again in the flat allowance",
             "R4.e: the flat charge uses the configured notional, not each leg's executed notional"),
    adoption=("Describes the existing Paper rule; changing it is an owner strategy-version and "
              "measurement boundary (SE-68). configured_notional_usdt is a required input; its "
              f"code default is 50 ({_CFG}:L106 @ bb7825f), never used as a default here."),
    sources=(f"{_SE} SE-11, SE-12, §C4", "REMEDIATION_REGISTER.md R4"),
)


def _research(cost_model_id: str, round_trip: str, in_price_per_side: str) -> CostModel:
    return CostModel(
        cost_model_id=cost_model_id, version="1.0.0", kind=KIND_RESEARCH, status=STATUS_PROPOSED,
        round_trip_pct=round_trip, label_policy=UNSPECIFIED,
        parameters=(
            Parameter("fee_per_side", "0.001", "fraction_of_executed_leg_notional",
                      f"{_CHARTER} (standard 0.10% fee per side; account tier NOT_VERIFIED)",
                      "DOCUMENTED_ONLY (proposed)"),
            Parameter("spread_and_slippage_per_side", in_price_per_side,
                      "fraction_of_leg_reference_price",
                      f"{_CHARTER} total {round_trip}% minus 2 × fee, halved per the SE-44 "
                      "per-side form cost_i = N_i × (f + h + s)", "DERIVED (proposed)"),
            Parameter("half_spread_per_side", UNSPECIFIED, "fraction_of_leg_reference_price",
                      "no source gives the split; owner decision SE-81", UNSPECIFIED),
            Parameter("slippage_per_side", UNSPECIFIED, "fraction_of_leg_reference_price",
                      "no source gives the split; owner decision SE-81 (stop slippage in stress: "
                      "SE-87)", UNSPECIFIED),
        ),
        components=(
            CostComponent("exchange_fee", ("fee",), BOOK_EXPLICIT_FEE, BASIS_EXECUTED_LEG_NOTIONAL,
                          LEGS_EVERY, "fee_per_side", "SPECIFIED",
                          source=f"{_CHARTER}; {_SE} SE-44, SE-45"),
            CostComponent("spread_and_slippage", ("spread", "slippage"), BOOK_IN_PRICE,
                          BASIS_LEG_REFERENCE, LEGS_TAKER, "spread_and_slippage_per_side",
                          "DERIVED",
                          source=f"{_SE} SE-45 (in price), SE-46 (taker legs only)",
                          note=("a buy fills at reference × (1 + h + s), a sell at reference × "
                                "(1 − h − s); a resting limit fills at its limit")),
            CostComponent("half_spread", ("spread",), BOOK_ATTRIBUTION, BASIS_NONE, LEGS_NONE,
                          "half_spread_per_side", UNSPECIFIED, part_of="spread_and_slippage",
                          source="SE-81"),
            CostComponent("slippage", ("slippage",), BOOK_ATTRIBUTION, BASIS_NONE, LEGS_NONE,
                          "slippage_per_side", UNSPECIFIED, part_of="spread_and_slippage",
                          source="SE-81, SE-87"),
        ),
        required_inputs=(), declared_double_counts=(), defects=(),
        adoption=("PROPOSED: no activation path. Adoption for an evaluation or for Paper "
                  "accounting is a WP3 owner decision (SE-81, SE-87, OQ-08)."),
        sources=(_CHARTER, f"{_SE} SE-44 to SE-46, SE-67", "REMEDIATION_REGISTER.md R8.e"),
    )


_REGISTRY = {m.cost_model_id: validate_model(m) for m in (
    _LEGACY,
    _research(RESEARCH_BASELINE_V1, "0.40", "0.001"),
    _research(RESEARCH_STRESS_V1, "0.60", "0.002"),
)}
REGISTRY: Mapping[str, CostModel] = MappingProxyType(_REGISTRY)


def get_cost_model(cost_model_id: str) -> CostModel:
    """The registered model for an explicit id. There is no default."""
    try:
        return REGISTRY[cost_model_id]
    except (KeyError, TypeError):
        raise CostModelError("cost_model_unknown", repr(cost_model_id)) from None


def registry_identity() -> dict:
    """id → {version, content_hash} for every registered model, plus a digest over them."""
    models = {mid: REGISTRY[mid].identity() for mid in COST_MODEL_IDS}
    return {"scheme": COST_MODEL_SCHEME, "models": models,
            "digest": canonical_hash({"scheme": COST_MODEL_SCHEME, "models": models})}


# ── legs and bookings ──────────────────────────────────────────────────────────────────────

def _dec(value, name: str, *, positive: bool = False) -> Decimal:
    """A finite Decimal from a Decimal or an int. Floats are refused: they are not exact."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise CostModelError("invalid_leg", f"{name} must be Decimal or int, not {type(value).__name__}")
    number = Decimal(value)
    if not number.is_finite() or (positive and number <= 0) or number < 0:
        raise CostModelError("invalid_leg", f"{name} = {value!r}")
    return number


def _float_dec(value: float) -> Decimal:
    """The exact decimal of a float's shortest repr (0.3 → Decimal('0.3'))."""
    return Decimal(repr(float(value)))


@dataclass(frozen=True)
class Leg:
    """One executed leg before costs. ``reference_price`` is the observed price, limit or stop
    reference the fill model reports; it is never an already-costed execution price."""
    leg_id: str
    role: str
    quantity: Decimal
    reference_price: Decimal
    taker: bool

    @property
    def side(self) -> str:
        return "buy" if self.role == ROLE_ENTRY else "sell"


def _check_leg(leg) -> Leg:
    if isinstance(leg, LegCost):
        raise CostModelError("already_priced", f"leg {leg.leg_id!r} was priced under {leg.cost_model_id}")
    if not isinstance(leg, Leg):
        raise CostModelError("invalid_leg", type(leg).__name__)
    if not isinstance(leg.leg_id, str) or not leg.leg_id.strip():
        raise CostModelError("invalid_leg", "leg_id")
    if leg.role not in ROLES or not isinstance(leg.taker, bool):
        raise CostModelError("invalid_leg", f"{leg.leg_id}: role {leg.role!r} taker {leg.taker!r}")
    _dec(leg.quantity, "quantity", positive=True)
    _dec(leg.reference_price, "reference_price", positive=True)
    return leg


@dataclass(frozen=True)
class Booking:
    component_id: str
    booking: str
    charges: tuple
    amount: Decimal


@dataclass(frozen=True)
class LegCost:
    """A leg under one cost model. ``fee`` and ``explicit_cost`` are booked amounts;
    ``in_price_cost`` is already inside ``execution_price`` (attribution only, PR-I11)."""
    cost_model_id: str
    leg_id: str
    role: str
    side: str
    taker: bool
    quantity: Decimal
    reference_price: Decimal
    execution_price: Decimal
    executed_notional: Decimal
    fee: Decimal
    explicit_cost: Decimal
    in_price_cost: Decimal
    bookings: tuple

    @property
    def total_cost(self) -> Decimal:
        with localcontext(_EXACT):
            return self.fee + self.explicit_cost + self.in_price_cost


def _leg_cost(cost_model_id: str, leg: Leg, execution_price: Decimal, fee: Decimal,
              in_price_component: str | None, fee_component: str | None,
              model: CostModel) -> LegCost:
    with localcontext(_EXACT):
        q, ref = Decimal(leg.quantity), Decimal(leg.reference_price)
        in_price = q * abs(execution_price - ref)
        bookings = []
        for c in model.leg_components():
            if c.component_id == fee_component:
                amount = fee
            elif c.component_id == in_price_component:
                amount = in_price
            else:
                amount = ZERO
            bookings.append(Booking(c.component_id, c.booking, c.charges, amount))
        return LegCost(cost_model_id, leg.leg_id, leg.role, leg.side, leg.taker, q, ref,
                       execution_price, q * execution_price, fee, ZERO, in_price, tuple(bookings))


# ── bound models ───────────────────────────────────────────────────────────────────────────

def _finite_float(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CostModelError("invalid_binding", f"{name} must be a number, not {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise CostModelError("invalid_binding", f"{name} = {value!r}")
    return number


@dataclass(frozen=True)
class LegacyTrackerV1:
    """``legacy_tracker_v1`` bound to explicit values, normally the runtime configuration
    (``legacy_tracker_v1_from_config``). Every value is required; there are no defaults here."""
    fee_roundtrip_pct: float
    stop_slippage: float
    configured_notional_usdt: float

    cost_model_id: ClassVar[str] = LEGACY_TRACKER_V1
    label_policy: ClassVar[str] = LEGACY_LABEL_POLICY

    def __post_init__(self):
        fee = _finite_float(self.fee_roundtrip_pct, "fee_roundtrip_pct")
        slip = _finite_float(self.stop_slippage, "stop_slippage")
        notional = _finite_float(self.configured_notional_usdt, "configured_notional_usdt")
        if fee < 0 or not 0 <= slip < 1 or notional <= 0:
            raise CostModelError("invalid_binding", f"fee {fee!r} slippage {slip!r} notional {notional!r}")
        object.__setattr__(self, "fee_roundtrip_pct", fee)
        object.__setattr__(self, "stop_slippage", slip)
        object.__setattr__(self, "configured_notional_usdt", notional)

    @property
    def model(self) -> CostModel:
        return REGISTRY[LEGACY_TRACKER_V1]

    def binding(self) -> dict:
        return {"scheme": COST_BINDING_SCHEME, **self.model.identity(),
                "parameters": {"fee_roundtrip_pct": repr(self.fee_roundtrip_pct),
                               "stop_slippage": repr(self.stop_slippage),
                               "configured_notional_usdt": repr(self.configured_notional_usdt)}}

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.binding())

    def matches_code_defaults(self) -> bool:
        """True when the cost values equal the recorded code defaults (the notional is an input)."""
        m = self.model
        return (_float_dec(self.fee_roundtrip_pct) == Decimal(m.parameter("fee_roundtrip_pct").value)
                and _float_dec(self.stop_slippage) == Decimal(m.parameter("stop_slippage").value))

    # Float surface: the calls trade_tracker/main.py makes today, through shared/fees.py.
    def fee_usdt(self) -> float:
        """``TRADE_AMOUNT_USDT × FEE_ROUNDTRIP_PCT / 100`` (trade_tracker/main.py:L409, L947)."""
        return _fees.fee_usdt(self.configured_notional_usdt, self.fee_roundtrip_pct)

    def net_usdt(self, gross_usdt: float) -> float:
        """Gross minus one flat charge (trade_tracker/main.py:L416, L953, L974)."""
        return _fees.net_usdt(gross_usdt, self.configured_notional_usdt, self.fee_roundtrip_pct)

    def net_pct(self, gross_pct: float) -> float:
        return _fees.net_pct(gross_pct, self.fee_roundtrip_pct)

    def economic_close(self, gross_usdt: float) -> dict:
        """The stored economic fields (trade_tracker/main.py:L1350; shared/fees.py:L52-60)."""
        return _fees.economic_close(gross_usdt, self.configured_notional_usdt, self.fee_roundtrip_pct)

    def barrier_cost_kwargs(self) -> dict:
        """Cost arguments of ``create_config_from_trade`` (trade_tracker/main.py:L1209-1210)."""
        return {"stop_slippage": self.stop_slippage, "roundtrip_cost": self.fee_roundtrip_pct / 100.0}

    # Decimal surface: the same rule stated per leg, for ledgers (PR-C03).
    def price_leg(self, leg: Leg) -> LegCost:
        leg = _check_leg(leg)
        model = self.model
        with localcontext(_EXACT):
            ref = Decimal(leg.reference_price)
            price = ref * (1 - _float_dec(self.stop_slippage)) if leg.role == ROLE_STOP else ref
        return _leg_cost(self.cost_model_id, leg, price, ZERO, "stop_fill_slippage", None, model)

    def trade_bookings(self) -> tuple:
        flat = self.model.component("flat_roundtrip")
        with localcontext(_EXACT):
            amount = (_float_dec(self.configured_notional_usdt) * _float_dec(self.fee_roundtrip_pct)
                      / HUNDRED)
        return (Booking(flat.component_id, flat.booking, flat.charges, amount),)


def legacy_tracker_v1_from_config(cfg) -> LegacyTrackerV1:
    """Bind ``legacy_tracker_v1`` to a configuration object's ``FEE_ROUNDTRIP_PCT``,
    ``STOP_SLIPPAGE`` and ``TRADE_AMOUNT_USDT``. Build it at the call site, as the tracker reads
    ``config`` at the call site today, so a changed value is seen the same way."""
    return LegacyTrackerV1(fee_roundtrip_pct=cfg.FEE_ROUNDTRIP_PCT, stop_slippage=cfg.STOP_SLIPPAGE,
                           configured_notional_usdt=cfg.TRADE_AMOUNT_USDT)


@dataclass(frozen=True)
class ResearchPricer:
    """A PROPOSED research model applied to legs. Building one adopts nothing; every priced
    record carries the model id and its PROPOSED status."""
    cost_model_id: str

    def __post_init__(self):
        if self.cost_model_id not in (RESEARCH_BASELINE_V1, RESEARCH_STRESS_V1):
            raise CostModelError("not_a_research_model", repr(self.cost_model_id))

    @property
    def model(self) -> CostModel:
        return REGISTRY[self.cost_model_id]

    @property
    def fee_per_side(self) -> Decimal:
        return Decimal(self.model.parameter("fee_per_side").value)

    @property
    def spread_and_slippage_per_side(self) -> Decimal:
        return Decimal(self.model.parameter("spread_and_slippage_per_side").value)

    def price_leg(self, leg: Leg) -> LegCost:
        leg = _check_leg(leg)
        if leg.role in RESEARCH_TAKER_ONLY_ROLES and not leg.taker:
            raise CostModelError("taker_required", f"{leg.leg_id}: {leg.role} fills as a taker (SE-46)")
        model = self.model
        with localcontext(_EXACT):
            ref, a = Decimal(leg.reference_price), self.spread_and_slippage_per_side
            if not leg.taker:
                price = ref
            elif leg.side == "buy":
                price = ref * (1 + a)
            else:
                price = ref * (1 - a)
            fee = self.fee_per_side * Decimal(leg.quantity) * price
        return _leg_cost(self.cost_model_id, leg, price, fee, "spread_and_slippage", "exchange_fee",
                         model)

    def trade_bookings(self) -> tuple:
        return ()


# ── per-position booking guard ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TradeCost:
    cost_model_id: str
    model_status: str
    position_id: str
    legs: tuple
    trade_bookings: tuple
    quantity_bought: Decimal
    quantity_sold: Decimal
    unsold_quantity: Decimal
    gross_reference_pnl: Decimal     # Σ sell q·ref − Σ buy q·ref: no cost at all
    execution_pnl: Decimal           # Σ sell q·exec − Σ buy q·exec: in-price costs included
    fees: Decimal
    explicit_costs: Decimal
    in_price_costs: Decimal
    total_costs: Decimal
    net_pnl: Decimal                 # execution_pnl − fees − explicit_costs
    double_counted_kinds: tuple      # kinds charged by two booked components on this trade

    def ledger_fills(self) -> tuple:
        """Per-leg fields for ledger fills (shared/portfolio_ledger.py EntryFill / ExitFill):
        the per-trade explicit cost is booked on the last exit leg, where the tracker books it."""
        last_exit = max((i for i, l in enumerate(self.legs) if l.side == "sell"), default=None)
        with localcontext(_EXACT):
            trade_cost = sum((b.amount for b in self.trade_bookings), ZERO)
            return tuple({"leg_id": l.leg_id, "side": l.side, "qty": l.quantity,
                          "price": l.execution_price, "fee": l.fee,
                          "cost": l.explicit_cost + (trade_cost if i == last_exit else ZERO),
                          "ref_price": l.reference_price, "cost_model_id": self.cost_model_id}
                         for i, l in enumerate(self.legs))


def _trade_overlaps(legs: Iterable[LegCost], trade_bookings: Iterable[Booking]) -> tuple:
    seen: dict[str, str] = {}
    dup: set[str] = set()
    for b in [b for l in legs for b in l.bookings] + list(trade_bookings):
        if b.booking not in BOOKED or b.amount == 0:
            continue
        for kind in b.charges:
            if kind in seen and seen[kind] != b.component_id:
                dup.add(kind)
            seen.setdefault(kind, b.component_id)
    return tuple(sorted(dup))


class CostBook:
    """Books the legs of one position under one bound model, each exactly once.

    Refused: an already-priced leg (``already_priced``), a repeated ``leg_id``
    (``double_booking``), an exit before any entry or beyond the bought quantity (``oversold``),
    an entry after an exit, any leg after the close, and a second close (``already_closed``),
    so a per-trade charge is booked once."""

    def __init__(self, pricer, *, position_id: str):
        if not isinstance(pricer, (LegacyTrackerV1, ResearchPricer)):
            raise CostModelError("invalid_pricer", type(pricer).__name__)
        if not isinstance(position_id, str) or not position_id.strip():
            raise CostModelError("invalid_position", repr(position_id))
        self.pricer = pricer
        self.position_id = position_id
        self._legs: list[LegCost] = []
        self._bought = ZERO
        self._sold = ZERO
        self._closed: TradeCost | None = None

    @property
    def cost_model_id(self) -> str:
        return self.pricer.cost_model_id

    @property
    def legs(self) -> tuple:
        return tuple(self._legs)

    def book(self, leg: Leg) -> LegCost:
        if self._closed is not None:
            raise CostModelError("already_closed", self.position_id)
        leg = _check_leg(leg)
        if any(l.leg_id == leg.leg_id for l in self._legs):
            raise CostModelError("double_booking", f"{self.position_id}/{leg.leg_id}")
        with localcontext(_EXACT):
            if leg.side == "buy":
                if self._sold > 0:
                    raise CostModelError("entry_after_exit", leg.leg_id)
                bought, sold = self._bought + leg.quantity, self._sold
            else:
                bought, sold = self._bought, self._sold + leg.quantity
                if sold > bought:
                    raise CostModelError("oversold", f"{leg.leg_id}: {sold} > {bought}")
        cost = self.pricer.price_leg(leg)
        self._legs.append(cost)
        self._bought, self._sold = bought, sold
        return cost

    def close(self) -> TradeCost:
        if self._closed is not None:
            raise CostModelError("already_closed", self.position_id)
        if not any(l.side == "buy" for l in self._legs) or not any(l.side == "sell" for l in self._legs):
            raise CostModelError("incomplete_trade", self.position_id)
        trade_bookings = self.pricer.trade_bookings()
        with localcontext(_EXACT):
            buys = [l for l in self._legs if l.side == "buy"]
            sells = [l for l in self._legs if l.side == "sell"]
            gross = (sum((l.quantity * l.reference_price for l in sells), ZERO)
                     - sum((l.quantity * l.reference_price for l in buys), ZERO))
            execution = (sum((l.executed_notional for l in sells), ZERO)
                         - sum((l.executed_notional for l in buys), ZERO))
            fees = sum((l.fee for l in self._legs), ZERO)
            explicit = (sum((l.explicit_cost for l in self._legs), ZERO)
                        + sum((b.amount for b in trade_bookings), ZERO))
            in_price = sum((l.in_price_cost for l in self._legs), ZERO)
            trade = TradeCost(
                cost_model_id=self.cost_model_id, model_status=self.pricer.model.status,
                position_id=self.position_id, legs=tuple(self._legs),
                trade_bookings=tuple(trade_bookings), quantity_bought=self._bought,
                quantity_sold=self._sold, unsold_quantity=self._bought - self._sold,
                gross_reference_pnl=gross, execution_pnl=execution, fees=fees,
                explicit_costs=explicit, in_price_costs=in_price,
                total_costs=fees + explicit + in_price, net_pnl=execution - fees - explicit,
                double_counted_kinds=_trade_overlaps(self._legs, trade_bookings))
        check_single_booking(trade)
        self._closed = trade
        return trade


def check_single_booking(trade: TradeCost) -> TradeCost:
    """Every booked component appears exactly once per leg (or once per trade), in its declared
    place, the amounts reconcile, and any double count is one the model declares."""
    model = get_cost_model(trade.cost_model_id)
    leg_ids = [l.leg_id for l in trade.legs]
    if len(set(leg_ids)) != len(leg_ids):
        raise CostModelError("double_booking", f"{trade.position_id}: repeated leg")
    expected_leg = [(c.component_id, c.booking) for c in model.leg_components()]
    expected_trade = [(c.component_id, c.booking) for c in model.trade_components()]
    with localcontext(_EXACT):
        for l in trade.legs:
            if l.cost_model_id != trade.cost_model_id:
                raise CostModelError("mixed_cost_models", f"{l.leg_id}: {l.cost_model_id}")
            if sorted((b.component_id, b.booking) for b in l.bookings) != sorted(expected_leg):
                raise CostModelError("double_booking", f"{l.leg_id}: components {l.bookings!r}")
            fee = sum((b.amount for b in l.bookings if b.booking == BOOK_EXPLICIT_FEE), ZERO)
            in_price = sum((b.amount for b in l.bookings if b.booking == BOOK_IN_PRICE), ZERO)
            if (fee != l.fee or in_price != l.in_price_cost
                    or in_price != l.quantity * abs(l.execution_price - l.reference_price)
                    or l.executed_notional != l.quantity * l.execution_price):
                raise CostModelError("booking_mismatch", l.leg_id)
        if sorted((b.component_id, b.booking) for b in trade.trade_bookings) != sorted(expected_trade):
            raise CostModelError("double_booking", f"{trade.position_id}: trade components")
        if (trade.total_costs != trade.fees + trade.explicit_costs + trade.in_price_costs
                or trade.net_pnl != trade.gross_reference_pnl - trade.total_costs):
            raise CostModelError("booking_mismatch", f"{trade.position_id}: totals")
    if not set(trade.double_counted_kinds) <= set(model.declared_double_counts):
        raise CostModelError("undeclared_double_count", f"{trade.position_id}: {trade.double_counted_kinds}")
    return trade


def aggregate(trades: Iterable[TradeCost]) -> dict:
    """Totals over trades of ONE cost model. Mixing models is refused: the stress model is a
    separate evaluation, never an addition to the baseline (SE-45), and results are never pooled
    across models."""
    trades = list(trades)
    ids = {t.cost_model_id for t in trades}
    if len(ids) != 1:
        raise CostModelError("mixed_cost_models" if ids else "empty", repr(sorted(ids)))
    with localcontext(_EXACT):
        return {"cost_model_id": ids.pop(), "trades": len(trades),
                "fees": sum((t.fees for t in trades), ZERO),
                "explicit_costs": sum((t.explicit_costs for t in trades), ZERO),
                "in_price_costs": sum((t.in_price_costs for t in trades), ZERO),
                "net_pnl": sum((t.net_pnl for t in trades), ZERO)}


__all__ = [
    "COST_MODEL_IDS", "LEGACY_TRACKER_V1", "RESEARCH_BASELINE_V1", "RESEARCH_STRESS_V1",
    "REGISTRY", "UNSPECIFIED", "CostModelError", "CostModel", "CostComponent", "Parameter",
    "Leg", "LegCost", "Booking", "TradeCost", "CostBook", "LegacyTrackerV1", "ResearchPricer",
    "get_cost_model", "registry_identity", "legacy_tracker_v1_from_config", "validate_model",
    "detect_overlaps", "check_single_booking", "aggregate", "canonical_json", "canonical_hash",
]
