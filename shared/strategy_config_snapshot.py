"""Versioned strategy configuration: a frozen, validated snapshot of decision parameters.

Pure and dormant (WP2 lane A; R5.d, R2.c; SE-37). The snapshot holds the **effective** values of
the declared decision keys, passed in explicitly by the caller. Nothing is read from the
environment, ``shared.config`` or the database, and no key has a default: every declared key
must be supplied, and an undeclared key is refused, so the hash can never silently omit a value.

``config_hash`` = sha256 over the canonical JSON of (scheme, schema hash, values). It is a
different, narrower quantity than the evidence-v2 envelope ``config_hash``
(``shared/evidence_v2.py`` hashes every non-secret config attribute); the two are reported side
by side, never substituted for each other.

``DRAFT_CURRENT_FAMILY_SCHEMA`` lists key **names** only, for the WP-A01 owner review. It
chooses no value. Database-held thresholds enter as one explicit ``DB_THRESHOLDS`` object; who
may read them, and how, is an owner gate (protected data), so this module never fetches them.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from shared.strategy_identity import (HEX64, STRATEGY_ID, ClosureError, canonical_hash,
                                      canonical_json)

# Copies of shared.t1_cap.T1_CAP_POLICIES and shared.signal_identity.INTEGRITY_MODES. They are not
# imported, so the A43/A44 import-isolation contract (tests/test_a43_signal_integrity.py) is
# unchanged; tests/test_wp2_strategy_identity.py asserts that the copies are equal.
T1_CAP_POLICY_CHOICES = ("legacy_window_v1", "independent_swing_v1")
SIGNAL_INTEGRITY_MODE_CHOICES = ("off", "enforce")

CONFIG_SCHEME = "tsb-strategy-config/1"
CONFIG_SCHEMA_SCHEME = "tsb-strategy-config-schema/1"
KINDS = ("str", "int", "float", "bool", "enum", "str_list", "json_object")
SOURCES = ("env", "database", "code_constant", "derived")
KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
SCHEMA_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-/]{0,79}$")


class ConfigSnapshotError(ClosureError):
    """The configuration cannot be snapshotted; the identity is unknown (fail closed)."""


@dataclass(frozen=True)
class ConfigKey:
    name: str
    kind: str
    source: str
    choices: tuple = ()

    def __post_init__(self):
        if not isinstance(self.name, str) or not KEY_NAME.match(self.name):
            raise ConfigSnapshotError(f"invalid key name {self.name!r}")
        if self.kind not in KINDS:
            raise ConfigSnapshotError(f"{self.name}: unknown kind {self.kind!r}")
        if self.source not in SOURCES:
            raise ConfigSnapshotError(f"{self.name}: unknown source {self.source!r}")
        choices = tuple(self.choices)
        if self.kind == "enum":
            if not choices or any(not isinstance(c, str) or not c for c in choices) \
                    or len(set(choices)) != len(choices):
                raise ConfigSnapshotError(f"{self.name}: enum needs distinct string choices")
        elif choices:
            raise ConfigSnapshotError(f"{self.name}: choices are for enum keys only")
        object.__setattr__(self, "choices", choices)

    def spec(self) -> dict:
        return {"name": self.name, "kind": self.kind, "source": self.source,
                "choices": list(self.choices)}


@dataclass(frozen=True)
class ConfigSchema:
    schema_id: str
    keys: tuple

    def __post_init__(self):
        if not isinstance(self.schema_id, str) or not SCHEMA_ID.match(self.schema_id):
            raise ConfigSnapshotError(f"invalid schema_id {self.schema_id!r}")
        keys = tuple(self.keys)
        if not keys or any(not isinstance(k, ConfigKey) for k in keys):
            raise ConfigSnapshotError("a schema needs at least one ConfigKey")
        names = [k.name for k in keys]
        if len(set(names)) != len(names):
            raise ConfigSnapshotError("duplicate key in schema")
        object.__setattr__(self, "keys", tuple(sorted(keys, key=lambda k: k.name)))

    def spec(self) -> dict:
        return {"scheme": CONFIG_SCHEMA_SCHEME, "schema_id": self.schema_id,
                "keys": [k.spec() for k in self.keys]}

    @property
    def schema_hash(self) -> str:
        return canonical_hash(self.spec())


def _validated(key: ConfigKey, value: Any):
    where = f"{key.name} ({key.kind})"
    if key.kind == "bool":
        if not isinstance(value, bool):
            raise ConfigSnapshotError(f"{where}: expected bool")
        return value
    if isinstance(value, bool):
        raise ConfigSnapshotError(f"{where}: bool is not accepted")
    if key.kind == "int":
        if not isinstance(value, int):
            raise ConfigSnapshotError(f"{where}: expected int")
        return value
    if key.kind == "float":
        try:
            number = float(value) if isinstance(value, (int, float)) else math.nan
        except OverflowError:
            number = math.nan
        if not math.isfinite(number):
            raise ConfigSnapshotError(f"{where}: expected a finite number")
        return number
    if key.kind == "str":
        if not isinstance(value, str):
            raise ConfigSnapshotError(f"{where}: expected str")
        return value
    if key.kind == "enum":
        if value not in key.choices:
            raise ConfigSnapshotError(f"{where}: {value!r} not in {key.choices}")
        return value
    if key.kind == "str_list":
        if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
            raise ConfigSnapshotError(f"{where}: expected a list of str")
        return list(value)
    if not isinstance(value, Mapping):
        raise ConfigSnapshotError(f"{where}: expected a JSON object")
    try:
        return json.loads(canonical_json(dict(value)))
    except ClosureError as exc:
        raise ConfigSnapshotError(f"{where}: {exc}") from None


def _config_hash(schema_hash: str, values_json: str) -> str:
    return canonical_hash({"scheme": CONFIG_SCHEME, "schema_hash": schema_hash,
                           "values": json.loads(values_json)})


@dataclass(frozen=True)
class StrategyConfigSnapshot:
    """Immutable: values are kept as one canonical JSON string. Constructing it directly with a
    ``config_hash`` that does not match its content is refused (tamper detection)."""
    strategy_id: str
    schema_id: str
    schema_hash: str
    values_json: str
    config_hash: str

    def __post_init__(self):
        if not isinstance(self.strategy_id, str) or not STRATEGY_ID.match(self.strategy_id):
            raise ConfigSnapshotError(f"invalid strategy_id {self.strategy_id!r}")
        for name in ("schema_hash", "config_hash"):
            if not isinstance(getattr(self, name), str) or not HEX64.match(getattr(self, name)):
                raise ConfigSnapshotError(f"{name} must be 64 lowercase hex characters")
        try:
            values = json.loads(self.values_json)
        except (TypeError, ValueError):
            raise ConfigSnapshotError("values_json is not JSON") from None
        if not isinstance(values, dict) or canonical_json(values) != self.values_json:
            raise ConfigSnapshotError("values_json is not a canonical JSON object")
        if _config_hash(self.schema_hash, self.values_json) != self.config_hash:
            raise ConfigSnapshotError("config_hash does not match the snapshot content")

    def values(self) -> dict:
        return json.loads(self.values_json)

    def to_dict(self) -> dict:
        return {"strategy_id": self.strategy_id, "schema_id": self.schema_id,
                "schema_hash": self.schema_hash, "values": self.values(),
                "config_hash": self.config_hash}

    @classmethod
    def from_dict(cls, doc: Mapping) -> "StrategyConfigSnapshot":
        return cls(strategy_id=doc["strategy_id"], schema_id=doc["schema_id"],
                   schema_hash=doc["schema_hash"], values_json=canonical_json(doc["values"]),
                   config_hash=doc["config_hash"])


def snapshot_config(strategy_id: str, schema: ConfigSchema,
                    values: Mapping[str, Any]) -> StrategyConfigSnapshot:
    """Validate ``values`` against ``schema`` and freeze them. Every declared key is required;
    an undeclared key is refused."""
    if not isinstance(schema, ConfigSchema):
        raise ConfigSnapshotError("schema must be a ConfigSchema")
    if not isinstance(values, Mapping):
        raise ConfigSnapshotError("values must be a mapping")
    declared = {k.name for k in schema.keys}
    missing, extra = sorted(declared - set(values)), sorted(set(values) - declared)
    if missing:
        raise ConfigSnapshotError(f"missing decision keys: {missing}")
    if extra:
        raise ConfigSnapshotError(f"undeclared keys: {extra}")
    clean = {k.name: _validated(k, values[k.name]) for k in schema.keys}
    values_json = canonical_json(clean)
    schema_hash = schema.schema_hash
    return StrategyConfigSnapshot(strategy_id=strategy_id, schema_id=schema.schema_id,
                                  schema_hash=schema_hash, values_json=values_json,
                                  config_hash=_config_hash(schema_hash, values_json))


def changed_keys(a: StrategyConfigSnapshot, b: StrategyConfigSnapshot) -> list:
    """Keys whose canonical value differs (added and removed keys included)."""
    va, vb = a.values(), b.values()
    return sorted(k for k in set(va) | set(vb)
                  if k not in va or k not in vb or canonical_json(va[k]) != canonical_json(vb[k]))


# Key names only (R2.c: T1_CAP_POLICY and SIGNAL_INTEGRITY_MODE; R3.d: APP_VERSION is part of the
# A44 setup key; the entry, universe, spread and cost keys that current_contract() resolves from
# runtime configuration). Values are always supplied by the caller. Pending WP-A01 review.
DRAFT_CURRENT_FAMILY_SCHEMA = ConfigSchema(
    schema_id="current-families-decision-keys/draft-1",
    keys=(
        ConfigKey("T1_CAP_POLICY", "enum", "env", T1_CAP_POLICY_CHOICES),
        ConfigKey("SIGNAL_INTEGRITY_MODE", "enum", "env",
                  SIGNAL_INTEGRITY_MODE_CHOICES),
        ConfigKey("APP_VERSION", "str", "env"),
        ConfigKey("TIMEFRAMES", "str_list", "env"),
        ConfigKey("MIN_VOLUME_USDT", "float", "env"),
        ConfigKey("MIN_PRICE_CHANGE_PERCENT", "float", "code_constant"),
        ConfigKey("MOM_BREAKOUT_N", "int", "env"),
        ConfigKey("MOM_VOL_MULT", "float", "env"),
        ConfigKey("REV_RSI", "float", "env"),
        ConfigKey("REV_BB_MAX_POSITION", "float", "env"),
        ConfigKey("MAX_SPREAD_PCT", "float", "env"),
        ConfigKey("FEE_ROUNDTRIP_PCT", "float", "env"),
        ConfigKey("STOP_SLIPPAGE", "float", "env"),
        ConfigKey("DB_THRESHOLDS", "json_object", "database"),
    ),
)
