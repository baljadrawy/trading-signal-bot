"""Versioned strategy configuration: a frozen, validated snapshot of decision parameters.

Pure (WP2 lane A; R5.d, R2.c; SE-37). The snapshot holds the **effective** values of the
declared decision keys, passed in explicitly by the caller. Nothing is read from the
environment, ``shared.config`` or the database, and no key has a default: every declared key
must be supplied, and an undeclared key is refused, so the hash can never silently omit a value.

``config_hash`` = sha256 over the canonical JSON of (scheme, schema hash, values). It is a
different, narrower quantity than the evidence-v2 envelope ``config_hash``
(``shared/evidence_v2.py`` hashes every non-secret config attribute); the two are reported side
by side, never substituted for each other.

``DRAFT_CURRENT_FAMILY_SCHEMA`` lists key **names** only: an evidence-backed proposal for owner
review (docs/design/STRATEGY_INTERFACE_v1.md section 5). It chooses no value. Database-held
inputs enter as explicit ``DB_*`` keys; who may read them, and how, is an owner gate (protected
data), so this module never fetches them.
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
    read_when: tuple = ()        # (switch key, (values...)): the key is read only then; else None

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
        read_when = tuple(self.read_when)
        if read_when:
            if (len(read_when) != 2 or not isinstance(read_when[0], str)
                    or not KEY_NAME.match(read_when[0]) or read_when[0] == self.name
                    or not isinstance(read_when[1], (tuple, list)) or not read_when[1]
                    or any(not isinstance(v, (str, bool, int)) for v in read_when[1])):
                raise ConfigSnapshotError(f"{self.name}: read_when must be (switch key, (values...))")
            read_when = (read_when[0], tuple(read_when[1]))
        object.__setattr__(self, "read_when", read_when)

    def spec(self) -> dict:
        """Hashed description. ``read_when`` appears only when set, so schemas without
        conditional keys keep their tsb-strategy-config-schema/1 hash."""
        out = {"name": self.name, "kind": self.kind, "source": self.source,
               "choices": list(self.choices)}
        if self.read_when:
            out["read_when"] = [self.read_when[0], list(self.read_when[1])]
        return out


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
        by_name = {k.name: k for k in keys}
        for k in keys:
            if k.read_when and (k.read_when[0] not in by_name or by_name[k.read_when[0]].read_when):
                raise ConfigSnapshotError(f"{k.name}: read_when switch must be an unconditional "
                                          f"key of the schema")
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
    clean = {k.name: _validated(k, values[k.name]) for k in schema.keys if not k.read_when}
    for k in schema.keys:
        if not k.read_when:
            continue
        switch, active_values = k.read_when
        if clean[switch] in active_values:
            if values[k.name] is None:
                raise ConfigSnapshotError(f"{k.name} is read when {switch}={clean[switch]!r}; "
                                          f"supply its effective value")
            clean[k.name] = _validated(k, values[k.name])
        elif values[k.name] is not None:
            # Not read on this path: an unread value must not move the hash (null instead).
            raise ConfigSnapshotError(f"{k.name} is not read when {switch}={clean[switch]!r}; "
                                      f"supply None")
        else:
            clean[k.name] = None
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


SELECTION_POLICY_CHOICES = ("legacy", "rank_then_limit_v1")             # shared/selection_policy.py
COST_LABEL_POLICY_CHOICES = ("net_after_modeled_cost_v1", "net_single_count_legacy_v1")
BREAK_EVEN_POLICY_CHOICES = ("legacy_tracker_v1", "single_count_legacy_v1")  # shared/accounting_flags.py

# Key names only. Rule (STRATEGY_INTERFACE_v1.md section 6): a key is in config_hash when an ACTIVE
# closure path reads it under the runtime-verified configuration, or when it selects between an
# ACTIVE and a DORMANT path. Keys read only on DORMANT paths (APP_VERSION inside the enforce-mode
# key, MIN_SCORE_TO_SIGNAL, the learned-gate parameters) join the schema of the version that
# activates their path. Portfolio and risk-policy keys belong to the separate risk-policy identity
# (deploy/VERSION_BOUNDARY.md VB-2026-10-27-01); operational cadence and evidence keys are excluded.
# Keys with ``read_when`` are read only under the named switch values (SELECTION_VERSION and
# SELECTION_SCORE_KEY under rank_then_limit_v1): they are required then, and null otherwise, so
# the non-legacy selection version is always in config_hash (R5.d) and an unread value never is.
# Telemetry and shadow switches (FUNNEL_RECORDING, LEDGER_SHADOW, POSITION_STATE_SHADOW) cannot
# change a decision or the booked economics and are excluded.
DRAFT_CURRENT_FAMILY_SCHEMA = ConfigSchema(
    schema_id="current-families-decision-keys/proposal-2",
    keys=(
        # path-selecting switches
        ConfigKey("LIVE_LEARNING_MODE", "bool", "env"),          # live selector versus legacy score
        ConfigKey("SELECTION_POLICY", "enum", "env", SELECTION_POLICY_CHOICES),
        ConfigKey("SELECTION_VERSION", "str", "env",
                  read_when=("SELECTION_POLICY", ("rank_then_limit_v1",))),
        ConfigKey("SELECTION_SCORE_KEY", "str", "env",
                  read_when=("SELECTION_POLICY", ("rank_then_limit_v1",))),
        ConfigKey("PAPER_COST_LABEL_POLICY", "enum", "env", COST_LABEL_POLICY_CHOICES),
        ConfigKey("PAPER_BREAK_EVEN_POLICY", "enum", "env", BREAK_EVEN_POLICY_CHOICES),
        ConfigKey("SIGNAL_INTEGRITY_MODE", "enum", "env", SIGNAL_INTEGRITY_MODE_CHOICES),
        ConfigKey("T1_CAP_POLICY", "enum", "env", T1_CAP_POLICY_CHOICES),
        ConfigKey("LEARNING_GATES_ENABLED", "bool", "env"),
        ConfigKey("PRICE_STREAM_ENABLED", "bool", "env"),
        ConfigKey("PAPER_ENTRY_FILL_MODEL", "str", "env"),
        # universe and candles
        ConfigKey("TIMEFRAMES", "str_list", "env"),
        ConfigKey("MIN_VOLUME_USDT", "float", "env"),
        ConfigKey("MIN_PRICE_CHANGE_PERCENT", "float", "code_constant"),
        ConfigKey("CANDLES_TO_FETCH", "int", "code_constant"),
        # indicators (shared/config.py code constants)
        ConfigKey("RSI_PERIOD", "int", "code_constant"),
        ConfigKey("MACD_FAST", "int", "code_constant"),
        ConfigKey("MACD_SLOW", "int", "code_constant"),
        ConfigKey("MACD_SIGNAL", "int", "code_constant"),
        ConfigKey("EMA_SHORT", "int", "code_constant"),
        ConfigKey("EMA_MEDIUM", "int", "code_constant"),
        ConfigKey("EMA_LONG", "int", "code_constant"),
        ConfigKey("BB_PERIOD", "int", "code_constant"),
        ConfigKey("BB_STD", "float", "code_constant"),
        ConfigKey("ATR_PERIOD", "int", "code_constant"),
        ConfigKey("STOCH_RSI_WINDOW", "int", "code_constant"),
        ConfigKey("STOCH_K", "int", "code_constant"),
        ConfigKey("STOCH_D", "int", "code_constant"),
        # entry predicates
        ConfigKey("MOM_BREAKOUT_N", "int", "env"),
        ConfigKey("MOM_VOL_MULT", "float", "env"),
        ConfigKey("REV_RSI", "float", "env"),
        ConfigKey("REV_BB_MAX_POSITION", "float", "env"),
        # gates
        ConfigKey("MAX_SPREAD_PCT", "float", "env"),
        ConfigKey("USDTD_SPIKE_PP", "float", "env"),
        ConfigKey("MACRO_CACHE_HOURS", "int", "env"),
        ConfigKey("MACRO_MAX_STALE_HOURS", "int", "env"),
        # legacy cost terms read by the exit barrier and the booking (cost model legacy_tracker_v1)
        ConfigKey("FEE_ROUNDTRIP_PCT", "float", "env"),
        ConfigKey("STOP_SLIPPAGE", "float", "env"),
        # database-held inputs (legacy path: indicator_weights only order the candidate query)
        ConfigKey("DB_INDICATOR_WEIGHTS", "json_object", "database"),
        ConfigKey("DB_SYMBOL_BLACKLIST", "str_list", "database"),
    ),
)
