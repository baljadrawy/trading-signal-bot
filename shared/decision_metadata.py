"""Traceable decision metadata: an immutable, deterministic record of one decision's identity.

Pure and dormant (WP2 lane A; R5.d, R5 test 2; SE-51, SE-55; WP-IR-08, WP-IR-09). This is the
identity-and-inputs core of the SE-51 ``DecisionRecord``: which strategy version decided, on
which inputs, with which models, at which bar, producing which canonical output. It does not
emit anything, does not register an evidence-v2 payload and does not verify chains; those are
the remaining WP-A05 steps.

* ``decision_id`` = sha256 over the canonical (decision_type, the five StrategyVersion fields,
  input hashes, input facts, bar close time, model and selection ids, parent decision ids).
  Wall-clock times and runtime identifiers are excluded, so a replay on another machine yields
  the same ``decision_id`` (SE-55).
* ``record_hash`` = sha256 over the canonical record without ``record_hash``; it covers the
  output, the runtime block, the times and ``prev_record_hash``.
* A record without a complete strategy identity is refused at construction (fail closed), and
  ``from_dict`` refuses a record whose stored hashes do not match its content.
* ``lineage`` never enters a record (WP-IR-09).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from shared.strategy_identity import (HEX64, ClosureError, StrategyVersion, canonical_hash,
                                      canonical_json)

SCHEMA = "tsb-decision-metadata/1"
DECISION_ID_SCHEME = "tsb-decision-id/1"
DECISION_TYPES = ("candidate", "rejection", "opportunity_rank", "sizing", "order_intent",
                  "fill", "position_transition", "ledger_entry")
RUNTIME_KEYS = ("boot_id", "code_sha", "compose_config_hash", "image_id", "runtime_manifest_hash")
INPUT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,127}$")


class DecisionMetadataError(ClosureError):
    """The decision cannot be attributed; it must not be recorded (fail closed)."""


def _ms(value, name: str, required: bool) -> int | None:
    if value is None and not required:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DecisionMetadataError(f"{name} must be a positive integer of milliseconds")
    return value


def _opt_id(value, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not MODEL_ID.match(value):
        raise DecisionMetadataError(f"invalid {name} {value!r}")
    return value


def _pairs_hashes(mapping) -> tuple:
    if not isinstance(mapping, Mapping):
        raise DecisionMetadataError("input_hashes must be a mapping")
    out = []
    for name in sorted(mapping):
        value = mapping[name]
        if not isinstance(name, str) or not INPUT_NAME.match(name):
            raise DecisionMetadataError(f"invalid input name {name!r}")
        if not isinstance(value, str) or not HEX64.match(value):
            raise DecisionMetadataError(f"input {name} must be a sha256 hex digest")
        out.append((name, value))
    return tuple(out)


def _pairs_facts(mapping) -> tuple:
    if not isinstance(mapping, Mapping):
        raise DecisionMetadataError("input_facts must be a mapping")
    out = []
    for name in sorted(mapping):
        value = mapping[name]
        if not isinstance(name, str) or not INPUT_NAME.match(name):
            raise DecisionMetadataError(f"invalid fact name {name!r}")
        if not (value is None or isinstance(value, (bool, int, str))
                or (isinstance(value, float) and math.isfinite(value))):
            raise DecisionMetadataError(f"fact {name} must be a JSON scalar")
        out.append((name, value))
    return tuple(out)


def _runtime_pairs(mapping) -> tuple:
    if not isinstance(mapping, Mapping) or set(mapping) != set(RUNTIME_KEYS):
        raise DecisionMetadataError(f"runtime must name exactly {RUNTIME_KEYS} (None = not available)")
    out = []
    for name in RUNTIME_KEYS:
        value = mapping[name]
        if value is not None and (not isinstance(value, str) or not value):
            raise DecisionMetadataError(f"runtime {name} must be a non-empty string or None")
        out.append((name, value))
    return tuple(out)


@dataclass(frozen=True)
class DecisionMetadata:
    decision_type: str
    strategy_id: str
    strategy_version: str
    source_hash: str
    config_hash: str
    contract_hash: str
    input_hashes: tuple
    input_facts: tuple
    bar_close_time_ms: int | None
    decision_time_ms: int
    recorded_at_ms: int | None
    cost_model_id: str | None
    fill_model_id: str | None
    selection_version: str | None
    parent_decision_ids: tuple
    runtime: tuple
    output_json: str
    prev_record_hash: str | None
    decision_id: str
    record_hash: str

    def __post_init__(self):
        if self.decision_type not in DECISION_TYPES:
            raise DecisionMetadataError(f"unknown decision_type {self.decision_type!r}")
        try:
            StrategyVersion(strategy_id=self.strategy_id, version=self.strategy_version,
                            source_hash=self.source_hash, config_hash=self.config_hash,
                            contract_hash=self.contract_hash)
        except ClosureError as exc:
            raise DecisionMetadataError(f"incomplete strategy identity: {exc}") from None
        if _pairs_hashes(dict(self.input_hashes)) != tuple(self.input_hashes):
            raise DecisionMetadataError("input_hashes are not normalized")
        if _pairs_facts(dict(self.input_facts)) != tuple(self.input_facts):
            raise DecisionMetadataError("input_facts are not normalized")
        if _runtime_pairs(dict(self.runtime)) != tuple(self.runtime):
            raise DecisionMetadataError("runtime is not normalized")
        _ms(self.bar_close_time_ms, "bar_close_time_ms", required=False)
        _ms(self.decision_time_ms, "decision_time_ms", required=True)
        _ms(self.recorded_at_ms, "recorded_at_ms", required=False)
        for name in ("cost_model_id", "fill_model_id", "selection_version"):
            _opt_id(getattr(self, name), name)
        parents = tuple(self.parent_decision_ids)
        if any(not isinstance(p, str) or not HEX64.match(p) for p in parents) \
                or list(parents) != sorted(set(parents)):
            raise DecisionMetadataError("parent_decision_ids must be sorted, distinct sha256 digests")
        if self.prev_record_hash is not None and (not isinstance(self.prev_record_hash, str)
                                                  or not HEX64.match(self.prev_record_hash)):
            raise DecisionMetadataError("prev_record_hash must be a sha256 digest or None")
        try:
            output = json.loads(self.output_json)
        except (TypeError, ValueError):
            raise DecisionMetadataError("output_json is not JSON") from None
        if not isinstance(output, dict) or canonical_json(output) != self.output_json:
            raise DecisionMetadataError("output must be a canonical JSON object")
        fields = self._fields()
        if _decision_id_of(fields) != self.decision_id:
            raise DecisionMetadataError("decision_id does not match the decision content")
        if canonical_hash(_record_of(fields)) != self.record_hash:
            raise DecisionMetadataError("record_hash does not match the record content")

    def _fields(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def strategy_identity(self) -> dict:
        return _identity_of(self._fields())

    def output(self) -> dict:
        return json.loads(self.output_json)

    def to_dict(self) -> dict:
        return {**_record_of(self._fields()), "record_hash": self.record_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, doc: Mapping) -> "DecisionMetadata":
        """Rebuild from ``to_dict`` output; any content that does not match the stored
        ``decision_id`` or ``record_hash`` is refused."""
        try:
            if doc["schema"] != SCHEMA:
                raise DecisionMetadataError(f"unknown schema {doc['schema']!r}")
            s, t, v = doc["strategy"], doc["times"], doc["versions"]
            return cls(
                decision_type=doc["decision_type"], strategy_id=s["strategy_id"],
                strategy_version=s["version"], source_hash=s["source_hash"],
                config_hash=s["config_hash"], contract_hash=s["contract_hash"],
                input_hashes=_pairs_hashes(doc["inputs"]["hashes"]),
                input_facts=_pairs_facts(doc["inputs"]["facts"]),
                bar_close_time_ms=t["bar_close_time_ms"], decision_time_ms=t["decision_time_ms"],
                recorded_at_ms=t["recorded_at_ms"], cost_model_id=v["cost_model_id"],
                fill_model_id=v["fill_model_id"], selection_version=v["selection_version"],
                parent_decision_ids=tuple(doc["parent_decision_ids"]),
                runtime=_runtime_pairs(doc["runtime"]),
                output_json=canonical_json(doc["output"]),
                prev_record_hash=doc["prev_record_hash"], decision_id=doc["decision_id"],
                record_hash=doc["record_hash"])
        except (KeyError, TypeError) as exc:
            raise DecisionMetadataError(f"malformed record: {exc!r}") from None


def _identity_of(f: Mapping) -> dict:
    return {"strategy_id": f["strategy_id"], "version": f["strategy_version"],
            "source_hash": f["source_hash"], "config_hash": f["config_hash"],
            "contract_hash": f["contract_hash"]}


def _decision_id_of(f: Mapping) -> str:
    return canonical_hash({
        "scheme": DECISION_ID_SCHEME,
        "decision_type": f["decision_type"],
        "strategy": _identity_of(f),
        "input_hashes": dict(f["input_hashes"]),
        "input_facts": dict(f["input_facts"]),
        "bar_close_time_ms": f["bar_close_time_ms"],
        "cost_model_id": f["cost_model_id"],
        "fill_model_id": f["fill_model_id"],
        "selection_version": f["selection_version"],
        "parent_decision_ids": list(f["parent_decision_ids"]),
    })


def _record_of(f: Mapping) -> dict:
    """The canonical record without ``record_hash``."""
    return {
        "schema": SCHEMA,
        "decision_id": f["decision_id"],
        "decision_type": f["decision_type"],
        "strategy": _identity_of(f),
        "inputs": {"hashes": dict(f["input_hashes"]), "facts": dict(f["input_facts"])},
        "versions": {"cost_model_id": f["cost_model_id"], "fill_model_id": f["fill_model_id"],
                     "selection_version": f["selection_version"]},
        "parent_decision_ids": list(f["parent_decision_ids"]),
        "times": {"bar_close_time_ms": f["bar_close_time_ms"],
                  "decision_time_ms": f["decision_time_ms"],
                  "recorded_at_ms": f["recorded_at_ms"]},
        "runtime": dict(f["runtime"]),
        "output": json.loads(f["output_json"]),
        "prev_record_hash": f["prev_record_hash"],
    }


def make_decision(*, decision_type: str, strategy: StrategyVersion,
                  input_hashes: Mapping[str, str], input_facts: Mapping[str, Any],
                  bar_close_time_ms: int | None, decision_time_ms: int, output: Mapping,
                  runtime: Mapping[str, str | None], cost_model_id: str | None = None,
                  fill_model_id: str | None = None, selection_version: str | None = None,
                  parent_decision_ids=(), recorded_at_ms: int | None = None,
                  prev_record_hash: str | None = None) -> DecisionMetadata:
    """Build a record from explicit inputs; no clock, environment or I/O is touched."""
    if not isinstance(strategy, StrategyVersion):
        raise DecisionMetadataError("strategy must be a StrategyVersion")
    if not isinstance(output, Mapping):
        raise DecisionMetadataError("output must be a mapping")
    try:
        output_json = canonical_json(dict(output))
    except ClosureError as exc:
        raise DecisionMetadataError(f"output: {exc}") from None
    parents = parent_decision_ids
    if isinstance(parents, (str, bytes)) or not isinstance(parents, (list, tuple)):
        raise DecisionMetadataError("parent_decision_ids must be a list or tuple")
    if len(set(parents)) != len(parents):
        raise DecisionMetadataError("parent_decision_ids must be distinct")
    fields = dict(
        decision_type=decision_type, strategy_id=strategy.strategy_id,
        strategy_version=strategy.version, source_hash=strategy.source_hash,
        config_hash=strategy.config_hash, contract_hash=strategy.contract_hash,
        input_hashes=_pairs_hashes(input_hashes), input_facts=_pairs_facts(input_facts),
        bar_close_time_ms=bar_close_time_ms, decision_time_ms=decision_time_ms,
        recorded_at_ms=recorded_at_ms, cost_model_id=cost_model_id, fill_model_id=fill_model_id,
        selection_version=selection_version, parent_decision_ids=tuple(sorted(parents)),
        runtime=_runtime_pairs(runtime), output_json=output_json,
        prev_record_hash=prev_record_hash)
    fields["decision_id"] = _decision_id_of(fields)
    return DecisionMetadata(**fields, record_hash=canonical_hash(_record_of(fields)))
