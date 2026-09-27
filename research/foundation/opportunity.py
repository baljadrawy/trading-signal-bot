"""Opportunity-set schema, deterministic IDs, decisions and future-label isolation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Mapping


class RejectionCode(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECT_UNIVERSE = "REJECT_UNIVERSE"
    REJECT_VOLUME = "REJECT_VOLUME"
    REJECT_PRICE_MOVEMENT = "REJECT_PRICE_MOVEMENT"
    REJECT_SPREAD = "REJECT_SPREAD"
    REJECT_SPREAD_DATA_UNAVAILABLE = "REJECT_SPREAD_DATA_UNAVAILABLE"
    REJECT_MACRO = "REJECT_MACRO"
    REJECT_MACRO_DATA_UNAVAILABLE = "REJECT_MACRO_DATA_UNAVAILABLE"
    REJECT_REGIME = "REJECT_REGIME"
    REJECT_ENTRY = "REJECT_ENTRY"
    REJECT_STOP_DISTANCE = "REJECT_STOP_DISTANCE"
    REJECT_OPEN_POSITION = "REJECT_OPEN_POSITION"
    REJECT_COOLDOWN = "REJECT_COOLDOWN"
    REJECT_PORTFOLIO_CAP = "REJECT_PORTFOLIO_CAP"
    REJECT_DAILY_RISK = "REJECT_DAILY_RISK"
    REJECT_WEEKLY_RISK = "REJECT_WEEKLY_RISK"
    REJECT_DRAWDOWN = "REJECT_DRAWDOWN"
    REJECT_MAX_TRADES = "REJECT_MAX_TRADES"
    REJECT_RANK_CAPACITY = "REJECT_RANK_CAPACITY"
    NOT_ELIGIBLE_INSUFFICIENT_HISTORY = "NOT_ELIGIBLE_INSUFFICIENT_HISTORY"
    REJECT_DATA_QUALITY = "REJECT_DATA_QUALITY"


FUTURE_KEYS = frozenset({"future_return", "future_high", "future_low", "mfe", "mae",
                         "future_label", "labels", "forward_labels"})


def deterministic_opportunity_id(dataset_id: str, symbol: str, timeframe: str,
                                 decision_time: str, strategy_version: str) -> str:
    raw = "|".join((dataset_id, symbol, timeframe, decision_time, strategy_version))
    return "opp-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def assert_no_future_fields(features: Mapping[str, Any]) -> None:
    offenders = []
    for key, value in features.items():
        normal = str(key).lower()
        if normal in FUTURE_KEYS or normal.startswith("future_") or normal.startswith("label_"):
            offenders.append(str(key))
        if isinstance(value, Mapping):
            try: assert_no_future_fields(value)
            except ValueError as exc: offenders.extend(str(exc).split(":" ,1)[-1].split(","))
    if offenders:
        raise ValueError("future_fields_in_decision_features:" + ",".join(sorted(set(offenders))))


@dataclass(frozen=True)
class OpportunityRecord:
    opportunity_id: str
    dataset_id: str
    experiment_id: str
    git_sha: str
    strategy_version: str
    strategy_contract_hash: str
    decision_time: str
    signal_time: str
    entry_eligible_time: str
    symbol: str
    timeframe: str
    research_partition: str
    market_context: dict[str, Any]
    liquidity: dict[str, Any]
    features: dict[str, Any]
    strategy_state: dict[str, Any]
    accepted: bool
    rejection_code: str
    rejection_detail: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_no_future_fields(self.features)
        if self.accepted != (self.rejection_code == RejectionCode.ACCEPTED.value):
            raise ValueError("accepted/rejection_code mismatch")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_record(record: OpportunityRecord) -> str:
    return json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
