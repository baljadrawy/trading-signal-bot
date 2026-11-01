"""WP2 funnel observability data: RejectionRecord, taxonomy v1, conservation — pure; no production caller.

The data side of WP-B01 (OF-T01; R6.a, R6.c, R1.f) under the canonical interface
choices of ``docs/design/remediation-design-pack-20261101/IMPLEMENTATION_WORKPLAN.md``
section 8 (WP-IR-01, WP-IR-02, WP-IR-04, WP-IR-05) and the schema of
``OPPORTUNITY_FUNNEL.md`` sections 8.1 to 8.3.

Observation only. Nothing here filters, ranks, sizes or admits a candidate:

* ``RejectionRecord`` — one drop, one closed ``F<n>.<reason>`` code whose prefix is the
  stage it is counted under; strategy stage names go in ``sub_stage``, a strategy's own
  code in ``detail.strategy_code``; all times are integer UTC epoch milliseconds;
* ``EligibilityResult`` — every failed rule of one subject at one stage, never only the first;
* ``CandidateRef`` — how the funnel identifies a Candidate. ``risk_plan`` belongs to the
  Candidate (WP-IR-02, owned by WP-A02); the funnel carries only ``risk_plan_hash``;
* ``RankingInput`` — the score components and ``tie_break_key`` a ranker was given, as
  plain data. No ranking rule lives here (WP-B05/WP-B06 own it, behind their gates);
* capacity (``F7.capacity_full``) and rank (``F6.rank_below_cap``) are separate builders:
  a rank loss is never labelled as capacity (WP-IR-04);
* ``check_conservation`` — ``in = passed + held + rejected subjects`` per stage, plus an
  optional stage-to-stage link check, so a silent drop is a reported violation.

Every threshold, limit and bound is an explicit argument without a default; none is chosen here.

Integration boundary (not wired; BLOCKED until separately approved): the hooks in
scanner, analyzer, signal_engine, telegram and trade_tracker, and the enabling flag in
``shared/config.py`` (WP-B01; WP-OD-01 for the hash-pinned files); retention and read
access of the records (OF-OD-18, WP-G19). Removing the legacy ``LIMIT 200`` or changing
ranking is a StrategyVersion boundary (R1.c, WP-G01) and is not done here: the legacy
cut is only *recorded* as ``F6.legacy_alphabetical_cut``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import types
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "tsb.funnel.rejection"
SCHEMA_VERSION = 1
TAXONOMY_VERSION = "of-taxonomy-v1"
RECORD_ID_VERSION = "wp2-rid-v1"

STAGES = ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7")
SCOPES = ("cycle", "symbol", "candidate", "opportunity")

# WP-IR-01 item 4: closed sub_stage enumeration, each filed under one funnel stage.
SUB_STAGE_STAGE = {
    "strategy.input": "F4",
    "strategy.regime": "F4",
    "strategy.entry": "F4",
    "strategy.geometry": "F5",
    "shared.identity": "F4",
    "shared.sizing": "F7",
    "shared.order_intent": "F7",
    "shared.admission": "F7",
}
SUB_STAGES = tuple(SUB_STAGE_STAGE)

# OPPORTUNITY_FUNNEL.md section 8.2, verbatim. ``<x>`` marks a parameterised family.
_OF_TAXONOMY = {
    "F0": ("snapshot_stale", "snapshot_incomplete", "clock_offset_exceeded"),
    "F1": ("status_not_trading", "quote_not_approved", "stable_or_pegged", "leveraged_product",
           "filters_missing", "min_order_infeasible", "listing_age_insufficient", "owner_excluded",
           "symbol_unsupported"),
    "F2": ("volume_below_floor", "volume_missing", "move_below_floor", "book_stale", "spread_invalid",
           "spread_above_limit", "depth_insufficient", "book_unavailable"),
    "F3": ("regime_stale", "regime_unavailable", "regime_veto:<series>", "regime_unknown_used"),
    "F4": ("history_insufficient", "data_quality", "bar_not_closed", "bar_stale", "no_setup",
           "duplicate_setup", "setup_conflict", "cooldown_active", "state_read_failed"),
    "F5": ("stop_missing", "stop_invalid:<reason>", "stop_risk_above_cap", "cost_above_budget",
           "bracket_invalid"),
    "F6": ("rank_below_cap", "resource_cap"),
    "F7": ("paused", "capacity_full", "exposure_symbol", "exposure_strategy", "exposure_regime",
           "exposure_correlation", "risk_state_invalid", "min_notional_infeasible", "no_price",
           "entry_rejected", "entry_wait_expired", "superseded", "already_registered"),
}
# IMPLEMENTATION_WORKPLAN.md WP-IR-01 "Taxonomy v1 additions" (from WP-IR-01, -04, -05).
_IR_ADDITIONS = {
    "F4": ("regime_stale", "regime_not_accepted", "bar_before_version_activation"),
    "F5": ("t1_not_cost_feasible",),
    "F6": ("legacy_alphabetical_cut",),
    "F7": ("mark_stale", "ledger_mismatch", "ledger_event_conflict", "economic_limit:<rule>",
           "exposure_gross", "heat_cap"),
}
TAXONOMY = {s: _OF_TAXONOMY[s] + _IR_ADDITIONS.get(s, ()) for s in STAGES}

# WP-IR-05: the economic-limit family is closed; the other two families take an identifier.
ECONOMIC_LIMIT_RULES = ("daily_loss_limit", "weekly_loss_limit", "max_drawdown_limit", "loss_streak_halt")
_PARAM_RE = re.compile(r"^[a-z0-9][a-z0-9_.]{0,63}$")

REASON_CODES = frozenset(f"{s}.{r}" for s in STAGES for r in TAXONOMY[s] if ":" not in r)

# Taxonomy v1.1: an additive bump (WP2 SE-1 integration). Every v1 code keeps its meaning and its
# records keep ``taxonomy_version`` v1, byte for byte; only a record carrying one of these codes is
# stamped v1.1. Sources are the live selector's labels (signal_engine/signal_logic.py @ ea8ae4f):
# * ``F4.learned_gate_throttled``: a (trade_type, timeframe) cell throttled by the learned gates
#   (L826, ``setdefault(symbol, 'learned_gate_throttled')``); no v1 code describes that drop;
# * ``F4.learned_gate_exploration``: a throttled cell admitted by fixed exploration (L823). It is
#   an admit flag, not a drop, so it is an annotation like ``F3.regime_unknown_used``;
# * ``F4.unattributed``: a subject that left the funnel with no decision label, or with a label no
#   documented map covers. It is counted exactly once, so conservation stays checkable, and its
#   ``detail.legacy_reason`` keeps whatever label there was.
TAXONOMY_VERSION_V1_1 = "of-taxonomy-v1.1"
TAXONOMY_VERSIONS = (TAXONOMY_VERSION, TAXONOMY_VERSION_V1_1)
TAXONOMY_V1_1_ADDITIONS = {"F4": ("learned_gate_throttled", "learned_gate_exploration", "unattributed")}
REASON_CODES_V1_1 = frozenset(f"{s}.{r}" for s, rs in TAXONOMY_V1_1_ADDITIONS.items() for r in rs)
PARAMETERISED_FAMILIES = {f"{s}.{r.split(':')[0]}": (ECONOMIC_LIMIT_RULES if r.startswith("economic_limit") else None)
                          for s in STAGES for r in TAXONOMY[s] if ":" in r}
# F3 fail-open: the candidate proceeds and is flagged (OF F3). Recorded, never counted as a drop.
ANNOTATION_CODES = frozenset({"F3.regime_unknown_used", "F4.learned_gate_exploration"})
RANKED_CODES = frozenset({"F6.rank_below_cap", "F6.resource_cap", "F6.legacy_alphabetical_cut"})

MAX_DETAIL_KEYS = 32
MAX_DETAIL_BYTES = 2048
_MAX_DETAIL_DEPTH = 4


# ── canonical helpers ───────────────────────────────────────────────────────

def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """Strict, deterministic JSON: sorted keys, no whitespace, ASCII, no NaN, no fallbacks."""
    return json.dumps(_thaw(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _freeze(value: Any, depth: int = 0) -> Any:
    """Deep, immutable copy of a JSON-like value; anything else is refused."""
    if depth > _MAX_DETAIL_DEPTH:
        raise ValueError("detail_too_deep")
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("detail_not_finite")
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("detail_key_not_str")
            out[key] = _freeze(item, depth + 1)
        return types.MappingProxyType(out)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, depth + 1) for item in value)
    raise ValueError(f"detail_type:{type(value).__name__}")


def _req_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name}_required")
    return value


def _opt_str(value: Any, name: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"{name}_malformed")
    return value


def _int_ms(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name}_not_epoch_ms")
    return value


def _count(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name}_invalid")
    return value


# ── taxonomy ────────────────────────────────────────────────────────────────

def validate_reason_code(code: Any, stage: str | None = None) -> str:
    """Return ``code`` if it is in taxonomy v1 (and its prefix equals ``stage``); else raise."""
    if not isinstance(code, str):
        raise ValueError("reason_code_not_str")
    prefix = code.split(".", 1)[0]
    if stage is not None and prefix != stage:
        raise ValueError(f"reason_code_stage_mismatch:{code}:{stage}")
    if code in REASON_CODES or code in REASON_CODES_V1_1:
        return code
    family, sep, param = code.partition(":")
    if sep and family in PARAMETERISED_FAMILIES:
        allowed = PARAMETERISED_FAMILIES[family]
        if (param in allowed) if allowed is not None else bool(_PARAM_RE.match(param)):
            return code
    raise ValueError(f"reason_code_unknown:{code}")


def taxonomy_version_of(code: str) -> str:
    """The taxonomy version a record with this code carries (v1 unless the code is a v1.1 addition)."""
    return TAXONOMY_VERSION_V1_1 if code in REASON_CODES_V1_1 else TAXONOMY_VERSION


def stage_of(code: str) -> str:
    return validate_reason_code(code).split(".", 1)[0]


def is_annotation(code: str) -> bool:
    return code in ANNOTATION_CODES


# ── subjects ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidateRef:
    """One Candidate as the funnel identifies it (the Candidate type itself is WP-A02's).

    ``risk_plan`` lives on the Candidate (WP-IR-02); only its hash is carried, so a plan
    edited between F5 and F7 appears as a different hash, never as a silent copy.
    """
    symbol: str
    strategy_id: str
    strategy_version: str
    timeframe: str
    bar_close_time: int
    setup_key: str | None = None
    risk_plan_hash: str | None = None

    def __post_init__(self):
        for name in ("symbol", "strategy_id", "strategy_version", "timeframe"):
            _req_str(getattr(self, name), name)
        _int_ms(self.bar_close_time, "bar_close_time")
        _opt_str(self.setup_key, "setup_key")
        _opt_str(self.risk_plan_hash, "risk_plan_hash")

    def subject_key(self) -> tuple:
        return ("candidate", self.symbol, self.strategy_id, self.strategy_version, self.timeframe,
                self.bar_close_time, self.setup_key)

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version, "timeframe": self.timeframe,
                "bar_close_time": self.bar_close_time, "setup_key": self.setup_key,
                "risk_plan_hash": self.risk_plan_hash}


# ── RejectionRecord (OF 8.1 as reconciled by WP-IR-01/WP-IR-08) ─────────────

_RECORD_FIELDS = ("cycle_id", "stage", "scope", "reason_code", "as_of", "decision_time", "rule_ref",
                  "snapshot_hash", "config_hash", "sub_stage", "symbol", "timeframe", "strategy_id",
                  "strategy_version", "setup_key", "bar_close_time", "detail", "rank", "decision_id")


@dataclass(frozen=True)
class RejectionRecord:
    """One drop. Append-only; ``record_id`` is derived, never supplied."""
    cycle_id: str
    stage: str
    scope: str
    reason_code: str
    as_of: int
    decision_time: int
    rule_ref: str
    snapshot_hash: str
    config_hash: str
    sub_stage: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    setup_key: str | None = None
    bar_close_time: int | None = None
    detail: Mapping = field(default_factory=dict)
    rank: int | None = None
    decision_id: str | None = None          # SE-51 computation id (WP-IR-08); not part of record_id
    record_id: str = field(init=False)

    def __post_init__(self):
        _req_str(self.cycle_id, "cycle_id")
        _req_str(self.rule_ref, "rule_ref")
        for name in ("snapshot_hash", "config_hash"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name}_not_str")
        if self.stage not in STAGES:
            raise ValueError(f"stage_unknown:{self.stage}")
        validate_reason_code(self.reason_code, self.stage)
        if self.sub_stage is not None:
            if self.sub_stage not in SUB_STAGE_STAGE:
                raise ValueError(f"sub_stage_unknown:{self.sub_stage}")
            if SUB_STAGE_STAGE[self.sub_stage] != self.stage:
                raise ValueError(f"sub_stage_stage_mismatch:{self.sub_stage}:{self.stage}")
        if self.scope not in SCOPES:
            raise ValueError(f"scope_unknown:{self.scope}")
        _int_ms(self.as_of, "as_of")
        _int_ms(self.decision_time, "decision_time")
        if self.bar_close_time is not None:
            _int_ms(self.bar_close_time, "bar_close_time")
        for name in ("symbol", "timeframe", "strategy_id", "strategy_version", "setup_key", "decision_id"):
            _opt_str(getattr(self, name), name)
        detail = _freeze(self.detail if self.detail is not None else {})
        if not isinstance(detail, Mapping):
            raise ValueError("detail_not_object")
        if len(detail) > MAX_DETAIL_KEYS or len(canonical_json(detail)) > MAX_DETAIL_BYTES:
            raise ValueError("detail_too_large")
        object.__setattr__(self, "detail", detail)
        self._check_scope()
        self._check_rank()
        object.__setattr__(self, "record_id", _sha([RECORD_ID_VERSION, self.cycle_id, self.stage,
                                                   self.scope, list(self.subject_key()), self.reason_code]))

    def _check_scope(self) -> None:
        candidate_fields = (self.timeframe, self.setup_key, self.bar_close_time)
        if self.scope == "cycle":                       # may name the strategy it covers (OF F3)
            if self.symbol is not None or any(v is not None for v in candidate_fields):
                raise ValueError("cycle_scope_has_subject")
            _count(self.detail.get("subject_count"), "detail.subject_count")
            return
        if self.stage == "F0":
            raise ValueError("F0_is_cycle_scope")
        if self.symbol is None:
            raise ValueError("symbol_required")
        if self.stage == "F1" and self.scope != "symbol":
            raise ValueError(f"scope_not_allowed_at_F1:{self.scope}")
        if self.scope == "symbol" and (self.strategy_id is not None or self.strategy_version is not None
                                       or any(v is not None for v in candidate_fields)):
            raise ValueError("symbol_scope_has_candidate_fields")
        if self.scope in ("candidate", "opportunity") and (self.strategy_id is None or self.timeframe is None):
            raise ValueError("candidate_fields_required")
        if self.scope == "opportunity" and self.stage not in ("F6", "F7"):
            raise ValueError("opportunity_scope_before_F6")

    def _check_rank(self) -> None:
        if self.rank is not None:
            _count(self.rank, "rank", minimum=1)
            if self.stage not in ("F6", "F7"):
                raise ValueError("rank_before_F6")
        elif self.reason_code in RANKED_CODES:
            raise ValueError("rank_required")

    def __hash__(self):                                 # detail is a mapping proxy
        return hash(self.record_id)

    @property
    def is_drop(self) -> bool:
        return self.reason_code not in ANNOTATION_CODES

    @property
    def subject_count(self) -> int:
        return int(self.detail["subject_count"]) if self.scope == "cycle" else 1

    def subject_key(self) -> tuple:
        if self.scope == "cycle":
            return ("cycle", self.strategy_id, self.strategy_version)
        if self.scope == "symbol":
            return ("symbol", self.symbol)
        return ("candidate", self.symbol, self.strategy_id, self.strategy_version, self.timeframe,
                self.bar_close_time, self.setup_key)

    def as_dict(self) -> dict:
        out = {name: _thaw(getattr(self, name)) for name in _RECORD_FIELDS}
        out.update(schema=SCHEMA, schema_version=SCHEMA_VERSION,
                   taxonomy_version=taxonomy_version_of(self.reason_code),
                   record_id=self.record_id)
        return out

    def to_json(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def from_dict(cls, data: Mapping) -> "RejectionRecord":
        if (data.get("schema"), data.get("schema_version")) != (SCHEMA, SCHEMA_VERSION) \
                or data.get("taxonomy_version") not in TAXONOMY_VERSIONS \
                or data.get("taxonomy_version") != taxonomy_version_of(data.get("reason_code")):
            raise ValueError("schema_mismatch")
        unknown = set(data) - set(_RECORD_FIELDS) - {"schema", "schema_version", "taxonomy_version", "record_id"}
        if unknown:
            raise ValueError(f"unknown_fields:{sorted(unknown)}")
        record = cls(**{name: data[name] for name in _RECORD_FIELDS if name in data})
        if data.get("record_id") != record.record_id:
            raise ValueError("record_id_mismatch")
        return record

    @classmethod
    def from_json(cls, text: str) -> "RejectionRecord":
        return cls.from_dict(json.loads(text))


def _candidate_fields(candidate: CandidateRef) -> dict:
    if not isinstance(candidate, CandidateRef):
        raise ValueError("candidate_ref_required")
    return {"symbol": candidate.symbol, "strategy_id": candidate.strategy_id,
            "strategy_version": candidate.strategy_version, "timeframe": candidate.timeframe,
            "bar_close_time": candidate.bar_close_time, "setup_key": candidate.setup_key}


# ── eligibility (F1, F2a/F2b, F4, F5) ───────────────────────────────────────

ELIGIBILITY_STAGES = ("F1", "F2", "F4", "F5")


@dataclass(frozen=True)
class EligibilityResult:
    """All failed rules of one subject at one stage; ``eligible`` is derived, never supplied."""
    stage: str
    symbol: str
    as_of: int
    reason_codes: tuple = ()
    candidate: CandidateRef | None = None
    eligible: bool = field(init=False)

    def __post_init__(self):
        if self.stage not in ELIGIBILITY_STAGES:
            raise ValueError(f"eligibility_stage_unknown:{self.stage}")
        _req_str(self.symbol, "symbol")
        _int_ms(self.as_of, "as_of")
        if isinstance(self.reason_codes, str):
            raise ValueError("reason_codes_not_sequence")
        codes = tuple(sorted(set(validate_reason_code(c, self.stage) for c in self.reason_codes)))
        if any(c in ANNOTATION_CODES for c in codes):
            raise ValueError("annotation_is_not_a_failed_rule")
        if self.candidate is not None:
            if not isinstance(self.candidate, CandidateRef) or self.candidate.symbol != self.symbol:
                raise ValueError("candidate_mismatch")
            if self.stage == "F1":
                raise ValueError("F1_is_symbol_scope")
        object.__setattr__(self, "reason_codes", codes)
        object.__setattr__(self, "eligible", not codes)

    def to_rejections(self, *, cycle_id: str, decision_time: int, rule_refs: Mapping[str, str],
                      snapshot_hash: str, config_hash: str,
                      details: Mapping[str, Mapping] | None = None,
                      sub_stage: str | None = None) -> tuple:
        """One RejectionRecord per failed rule. Every code needs its own ``rule_refs`` entry."""
        missing = [c for c in self.reason_codes if c not in rule_refs]
        if missing:
            raise ValueError(f"rule_ref_missing:{missing}")
        subject = (_candidate_fields(self.candidate) if self.candidate is not None
                   else {"symbol": self.symbol})
        scope = "candidate" if self.candidate is not None else "symbol"
        return tuple(RejectionRecord(cycle_id=cycle_id, stage=self.stage, scope=scope, reason_code=code,
                                     as_of=self.as_of, decision_time=decision_time,
                                     rule_ref=rule_refs[code], snapshot_hash=snapshot_hash,
                                     config_hash=config_hash, sub_stage=sub_stage,
                                     detail=(details or {}).get(code, {}), **subject)
                     for code in self.reason_codes)

    def as_dict(self) -> dict:
        return {"stage": self.stage, "symbol": self.symbol, "as_of": self.as_of,
                "eligible": self.eligible, "reason_codes": list(self.reason_codes),
                "candidate": self.candidate.as_dict() if self.candidate is not None else None}


# ── ranking-input capture (data only; no ranking rule) ─────────────────────

SCORE_DIRECTIONS = ("higher_first", "lower_first")


def _scalar(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"{name}_not_finite_scalar")


@dataclass(frozen=True)
class RankingInput:
    """What one candidate presented to a ranker: its score, components and tie-break key.

    Captured as given. Missing or non-finite inputs must be passed as ``None`` by the caller,
    so the record says "missing" instead of hiding a NaN.
    """
    candidate: CandidateRef
    selection_version: str
    tie_break_key: str
    input_position: int
    score: float | int | None = None
    score_direction: str | None = None
    components: tuple = ()

    def __post_init__(self):
        if not isinstance(self.candidate, CandidateRef):
            raise ValueError("candidate_ref_required")
        _req_str(self.selection_version, "selection_version")
        _req_str(self.tie_break_key, "tie_break_key")
        _count(self.input_position, "input_position")
        if self.score is not None:
            if isinstance(self.score, bool) or not isinstance(self.score, (int, float)) \
                    or not math.isfinite(self.score):
                raise ValueError("score_not_finite_number")
            if self.score_direction is None:
                raise ValueError("score_direction_required")
        if self.score_direction is not None and self.score_direction not in SCORE_DIRECTIONS:
            raise ValueError(f"score_direction_unknown:{self.score_direction}")
        items = self.components.items() if isinstance(self.components, Mapping) else self.components
        pairs = tuple(sorted(((_req_str(k, "component_name"), _scalar(v, f"component:{k}")) for k, v in items),
                              key=lambda kv: kv[0]))
        if len({k for k, _ in pairs}) != len(pairs):
            raise ValueError("component_name_duplicate")
        object.__setattr__(self, "components", pairs)

    def as_dict(self) -> dict:
        return {"candidate": self.candidate.as_dict(), "selection_version": self.selection_version,
                "tie_break_key": self.tie_break_key, "input_position": self.input_position,
                "score": self.score, "score_direction": self.score_direction,
                "components": [[k, v] for k, v in self.components]}


# ── F6 and F7 record builders (WP-IR-03, WP-IR-04) ──────────────────────────

def _common(cycle_id, as_of, decision_time, rule_ref, snapshot_hash, config_hash) -> dict:
    return {"cycle_id": cycle_id, "as_of": as_of, "decision_time": decision_time, "rule_ref": rule_ref,
            "snapshot_hash": snapshot_hash, "config_hash": config_hash}


def rank_below_cap_record(*, cycle_id: str, candidate: CandidateRef, rank: int, offer_cap: int,
                          selection_version: str, as_of: int, decision_time: int, rule_ref: str,
                          snapshot_hash: str, config_hash: str) -> RejectionRecord:
    """Lost on rank below the per-cycle offer count. Never a capacity code (WP-IR-04)."""
    _count(offer_cap, "offer_cap")
    if _count(rank, "rank", minimum=1) <= offer_cap:
        raise ValueError("rank_within_offer_cap")
    return RejectionRecord(stage="F6", scope="candidate", reason_code="F6.rank_below_cap", rank=rank,
                           detail={"rank": rank, "offer_cap": offer_cap,
                                   "selection_version": _req_str(selection_version, "selection_version")},
                           **_common(cycle_id, as_of, decision_time, rule_ref, snapshot_hash, config_hash),
                           **_candidate_fields(candidate))


def resource_cap_record(*, cycle_id: str, candidate: CandidateRef, rank: int, hash_position: int,
                        guard_bound: int, as_of: int, decision_time: int, rule_ref: str,
                        snapshot_hash: str, config_hash: str) -> RejectionRecord:
    """Dropped by a hash-ordered resource guard (OF F6); the cycle is then ranking_incomplete."""
    _count(guard_bound, "guard_bound")
    if _count(hash_position, "hash_position", minimum=1) <= guard_bound:
        raise ValueError("hash_position_within_guard_bound")
    return RejectionRecord(stage="F6", scope="candidate", reason_code="F6.resource_cap", rank=rank,
                           detail={"hash_position": hash_position, "guard_bound": guard_bound},
                           **_common(cycle_id, as_of, decision_time, rule_ref, snapshot_hash, config_hash),
                           **_candidate_fields(candidate))


def legacy_alphabetical_cut_record(*, cycle_id: str, candidate: CandidateRef, position: int, limit: int,
                                   as_of: int, decision_time: int, rule_ref: str, snapshot_hash: str,
                                   config_hash: str) -> RejectionRecord:
    """Shadow-only record of today's name-ordered row cut (WP-IR-04). It records the cut; it does
    not perform, change or remove it. ``position`` is the 1-based place in name order."""
    _count(limit, "limit")
    if _count(position, "position", minimum=1) <= limit:
        raise ValueError("position_within_limit")
    return RejectionRecord(stage="F6", scope="candidate", reason_code="F6.legacy_alphabetical_cut",
                           rank=position, detail={"position": position, "limit": limit, "order": "name"},
                           **_common(cycle_id, as_of, decision_time, rule_ref, snapshot_hash, config_hash),
                           **_candidate_fields(candidate))


def capacity_full_record(*, cycle_id: str, candidate: CandidateRef, open_count: int, reserved: int,
                         limit: int, multiplier: float, budget_version: str, as_of: int,
                         decision_time: int, rule_ref: str, snapshot_hash: str, config_hash: str,
                         rank: int | None = None, sub_stage: str = "shared.admission",
                         extra_detail: Mapping | None = None) -> RejectionRecord:
    """Refusal by the single capacity authority (WP-IR-03 output detail). An invalid limit is
    not "full": it must be recorded as ``F7.risk_state_invalid`` instead, so it is refused here."""
    _count(open_count, "open_count")
    _count(reserved, "reserved")
    _count(limit, "limit", minimum=1)
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) \
            or not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("multiplier_invalid")
    detail = dict(extra_detail or {})
    clash = set(detail) & {"open", "reserved", "limit", "multiplier", "budget_version"}
    if clash:
        raise ValueError(f"extra_detail_overrides:{sorted(clash)}")
    detail.update(open=open_count, reserved=reserved, limit=limit, multiplier=float(multiplier),
                  budget_version=_req_str(budget_version, "budget_version"))
    return RejectionRecord(stage="F7", scope="opportunity", reason_code="F7.capacity_full", rank=rank,
                           sub_stage=sub_stage, detail=detail,
                           **_common(cycle_id, as_of, decision_time, rule_ref, snapshot_hash, config_hash),
                           **_candidate_fields(candidate))


# ── freshness (maps the A44 reference verdict; never re-implements the rule) ─

FRESHNESS_REASON_CODES = {
    "decision_before_candle_close": "F4.bar_not_closed",
    "superseded_by_newer_candle": "F4.bar_stale",
}


def freshness_record(*, cycle_id: str, candidate: CandidateRef, freshness: Any, decision_time: int,
                     rule_ref: str, snapshot_hash: str, config_hash: str) -> RejectionRecord | None:
    """Map a ``shared.signal_identity.Freshness`` verdict (``freshness_at``, the A44 reference
    rule) to its F4 record; ``None`` if admissible. The verdict is read by attribute, so this
    module imports no wired module (the A43 import-graph contract stays unchanged).

    The bound itself is the caller's (OF-OD-12); a reason the map does not know is refused,
    never guessed.
    """
    if not all(hasattr(freshness, a) for a in ("admissible", "reason", "age_ms", "age_bars")):
        raise ValueError("freshness_required")
    if freshness.admissible is True:
        return None
    if freshness.reason not in FRESHNESS_REASON_CODES:
        raise ValueError(f"freshness_reason_unmapped:{freshness.reason}")
    bars = float(freshness.age_bars)
    return RejectionRecord(stage="F4", scope="candidate", reason_code=FRESHNESS_REASON_CODES[freshness.reason],
                           sub_stage="shared.identity",
                           detail={"age_ms": int(freshness.age_ms),
                                   "age_bars": round(bars, 6) if math.isfinite(bars) else None,
                                   "reference_reason": freshness.reason},
                           **_common(cycle_id, candidate.bar_close_time, decision_time, rule_ref,
                                     snapshot_hash, config_hash),
                           **_candidate_fields(candidate))


# ── conservation (OF 8.3) ───────────────────────────────────────────────────

@dataclass(frozen=True)
class StageCount:
    """Inputs and survivors of one stage. ``held`` exists only at F7 (bounded queue);
    ``expanded_from`` declares a split (one symbol into several candidates)."""
    stage: str
    n_in: int
    passed: int
    held: int = 0
    expanded_from: int | None = None

    def __post_init__(self):
        if self.stage not in STAGES:
            raise ValueError(f"stage_unknown:{self.stage}")
        _count(self.n_in, "n_in")
        _count(self.passed, "passed")
        _count(self.held, "held")
        if self.held and self.stage != "F7":
            raise ValueError("held_only_at_F7")
        if self.expanded_from is not None:
            _count(self.expanded_from, "expanded_from")

    def as_dict(self) -> dict:
        return {"stage": self.stage, "n_in": self.n_in, "passed": self.passed, "held": self.held,
                "expanded_from": self.expanded_from}


@dataclass(frozen=True)
class ConservationViolation:
    stage: str
    kind: str            # stage_equation | records_without_counts | chain_stage_missing | chain_link
    expected: int
    observed: int

    def as_dict(self) -> dict:
        return {"stage": self.stage, "kind": self.kind, "expected": self.expected, "observed": self.observed}


@dataclass(frozen=True)
class ConservationResult:
    ok: bool
    violations: tuple
    rejected_subjects: tuple      # ((stage, n), ...): distinct dropped subjects per stage
    reason_counts: tuple          # ((code, n), ...): records per code (a subject may have several)
    annotation_counts: tuple      # ((code, n), ...): flagged, not dropped

    def as_dict(self) -> dict:
        return {"ok": self.ok, "violations": [v.as_dict() for v in self.violations],
                "rejected_subjects": [list(x) for x in self.rejected_subjects],
                "reason_counts": [list(x) for x in self.reason_counts],
                "annotation_counts": [list(x) for x in self.annotation_counts]}


def merge_stage_counts(counts: Iterable[StageCount]) -> dict:
    """Sum repeated observations of the same stage (for example one per timeframe loop)."""
    merged: dict = {}
    for c in counts:
        prev = merged.get(c.stage)
        if prev is None:
            merged[c.stage] = c
            continue
        expanded = None if prev.expanded_from is None and c.expanded_from is None else \
            (prev.expanded_from or 0) + (c.expanded_from or 0)
        merged[c.stage] = StageCount(c.stage, prev.n_in + c.n_in, prev.passed + c.passed,
                                     prev.held + c.held, expanded)
    return merged


def check_conservation(counts: Iterable[StageCount], records: Iterable[RejectionRecord], *,
                       chain: Sequence[str] = ()) -> ConservationResult:
    """Per stage: ``n_in == passed + held + distinct rejected subjects``. Records are de-duplicated
    by ``record_id``; a cycle-scope record contributes its ``detail.subject_count``. With ``chain``
    (stage order of one flow), each stage's input (or ``expanded_from``) must equal the previous
    stage's ``passed``: a subject that vanished between two stages is a violation too."""
    merged = merge_stage_counts(counts)
    seen, subjects, cycle_drops = set(), {}, {}
    reasons: dict = {}
    annotations: dict = {}
    for r in records:
        if r.record_id in seen:
            continue
        seen.add(r.record_id)
        if not r.is_drop:
            annotations[r.reason_code] = annotations.get(r.reason_code, 0) + 1
            continue
        reasons[r.reason_code] = reasons.get(r.reason_code, 0) + 1
        if r.scope == "cycle":
            cycle_drops[r.stage] = cycle_drops.get(r.stage, 0) + r.subject_count
        else:
            subjects.setdefault(r.stage, set()).add(r.subject_key())
    rejected = {s: len(subjects.get(s, ())) + cycle_drops.get(s, 0) for s in STAGES}
    violations = []
    for stage in STAGES:
        c = merged.get(stage)
        if c is None:
            if rejected[stage]:
                violations.append(ConservationViolation(stage, "records_without_counts", 0, rejected[stage]))
            continue
        out = c.passed + c.held + rejected[stage]
        if c.n_in != out:
            violations.append(ConservationViolation(stage, "stage_equation", c.n_in, out))
    for prev, nxt in zip(chain, chain[1:]):
        if prev not in merged or nxt not in merged:
            missing = prev if prev not in merged else nxt
            violations.append(ConservationViolation(missing, "chain_stage_missing", 1, 0))
            continue
        n = merged[nxt]
        entering = n.expanded_from if n.expanded_from is not None else n.n_in
        if entering != merged[prev].passed:
            violations.append(ConservationViolation(nxt, "chain_link", merged[prev].passed, entering))
    return ConservationResult(not violations, tuple(violations),
                              tuple((s, rejected[s]) for s in STAGES if rejected[s]),
                              tuple(sorted(reasons.items())), tuple(sorted(annotations.items())))


# ── legacy and contract name maps (shadow parity data; WP-IR-01, -04, -05) ─

# WP-IR-01 mapping table: each SE-side name, as the workplan writes it, exactly once ->
# (stage, reason_code, sub_stage). The SE name itself goes to detail.strategy_code.
SE_NAME_MAP = {
    "strategy.input/incomplete_candles": ("F4", "F4.data_quality", "strategy.input"),
    "strategy.input/insufficient_history": ("F4", "F4.history_insufficient", "strategy.input"),
    "NOT_ELIGIBLE_INSUFFICIENT_HISTORY": ("F4", "F4.history_insufficient", "strategy.input"),
    "REJECT_DATA_QUALITY": ("F4", "F4.data_quality", "strategy.input"),
    "strategy.input/stale_regime": ("F4", "F4.regime_stale", "strategy.input"),
    "strategy.regime": ("F4", "F4.regime_not_accepted", "strategy.regime"),
    "REJECT_REGIME": ("F4", "F4.regime_not_accepted", "strategy.regime"),
    "strategy.entry": ("F4", "F4.no_setup", "strategy.entry"),
    "REJECT_ENTRY": ("F4", "F4.no_setup", "strategy.entry"),
    "strategy.geometry/structural_risk_exceeds_cap": ("F5", "F5.stop_risk_above_cap", "strategy.geometry"),
    "REJECT_STOP_DISTANCE": ("F5", "F5.stop_risk_above_cap", "strategy.geometry"),
    "strategy.geometry/invalid_geometry": ("F5", "F5.bracket_invalid", "strategy.geometry"),
    "strategy.geometry/t1_not_cost_feasible": ("F5", "F5.t1_not_cost_feasible", "strategy.geometry"),
    "missing stop plan": ("F5", "F5.stop_missing", "strategy.geometry"),
    "duplicate_setup_key": ("F4", "F4.duplicate_setup", "shared.identity"),
    "bar_before_version_activation": ("F4", "F4.bar_before_version_activation", "shared.identity"),
    "signal_invalidated_before_fill": ("F7", "F7.entry_rejected", "shared.order_intent"),
    "EXPIRED_UNFILLED": ("F7", "F7.entry_wait_expired", "shared.order_intent"),
    "below_exchange_minimum": ("F7", "F7.min_notional_infeasible", "shared.order_intent"),
}

# WP-IR-04 and WP-IR-05: today's labels -> canonical code. Legacy strings stay where they are
# produced; the canonical code is added beside them, never substituted.
LEGACY_LABEL_MAP = {
    "not_selected_capacity": "F6.rank_below_cap",
    "rejected_fixed_policy_rank": "F6.rank_below_cap",
    "REJECT_RANK_CAPACITY": "F6.rank_below_cap",
    "selection_capacity": "F6.legacy_alphabetical_cut",
    "portfolio_capacity": "F7.capacity_full",
    "max_open_trades": "F7.capacity_full",
    "REJECT_MAX_TRADES": "F7.capacity_full",
    "below_min_notional": "F7.min_notional_infeasible",
    "below_exchange_minimum": "F7.min_notional_infeasible",
    "invalid_risk_state": "F7.risk_state_invalid",
    "mark_stale": "F7.mark_stale",
    "ledger_mismatch": "F7.ledger_mismatch",
    "ledger_event_conflict": "F7.ledger_event_conflict",
    "REJECT_DAILY_RISK": "F7.economic_limit:daily_loss_limit",
    "REJECT_WEEKLY_RISK": "F7.economic_limit:weekly_loss_limit",
    "REJECT_DRAWDOWN": "F7.economic_limit:max_drawdown_limit",
    "manual_pause": "F7.paused",
    "gross_exposure_limit": "F7.exposure_gross",
    "symbol_concentration_limit": "F7.exposure_symbol",
    "strategy_concentration_limit": "F7.exposure_strategy",
    "regime_concentration_limit": "F7.exposure_regime",
    "no_trade_setup": "F4.no_setup",
    "symbol_cooldown": "F4.cooldown_active",
    "order_book_unavailable": "F2.book_unavailable",
    "spread_invalid": "F2.spread_invalid",
    "spread_exceeds_limit": "F2.spread_above_limit",
}


def canonical_for_legacy(label: str) -> str:
    """The canonical code for a legacy label, or raise: an unmapped label is never guessed."""
    if label.startswith("portfolio_capacity_"):
        return "F7.capacity_full"
    if label in LEGACY_LABEL_MAP:
        return LEGACY_LABEL_MAP[label]
    raise ValueError(f"legacy_label_unmapped:{label}")
