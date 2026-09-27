"""Event-sourced point-in-time universe with separate listing/data/eligibility states."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(frozen=True)
class UniverseEvent:
    symbol: str
    quote_asset: str
    event_type: str
    event_time: datetime
    source: str
    source_reference: str
    confidence: str
    source_tier: str = "D"
    evidence_timestamp: datetime | None = None
    evidence_kind: str = "INFERRED_LAST_DATA"

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None:
            raise ValueError("universe event timestamps must be timezone-aware")
        if self.event_type not in {"LISTED", "DELISTED", "RENAMED", "MIGRATED", "SUSPENDED", "RESUMED"}:
            raise ValueError("invalid universe event type")
        if self.confidence not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise ValueError("invalid universe confidence")
        if self.source_tier not in {"A", "B", "C", "D"}:
            raise ValueError("invalid source tier")
        if self.evidence_timestamp is not None and self.evidence_timestamp.tzinfo is None:
            raise ValueError("evidence timestamp must be timezone-aware")


class PointInTimeUniverse:
    def __init__(self, events: Iterable[UniverseEvent], first_candle: dict[str, datetime] | None = None):
        self.events = sorted(events, key=lambda e: (e.event_time, e.symbol, e.event_type))
        self.first_candle = first_candle or {}

    def exchange_listed(self, symbol: str, at: datetime) -> bool:
        active = False
        for event in self.events:
            if event.symbol != symbol or event.event_time > at:
                continue
            if event.event_type in {"LISTED", "RESUMED"}: active = True
            elif event.event_type in {"DELISTED", "SUSPENDED"}: active = False
        return active

    def data_available(self, symbol: str, at: datetime) -> bool:
        first = self.first_candle.get(symbol)
        return first is not None and first <= at

    def strategy_eligible(self, symbol: str, at: datetime, *, timeframe: timedelta,
                          warmup_candles: int) -> bool:
        first = self.first_candle.get(symbol)
        return bool(self.exchange_listed(symbol, at) and first is not None
                    and first + timeframe * warmup_candles <= at)

    def symbols_at(self, at: datetime, *, timeframe: timedelta, warmup_candles: int) -> list[str]:
        symbols = {e.symbol for e in self.events}
        return sorted(s for s in symbols if self.strategy_eligible(
            s, at, timeframe=timeframe, warmup_candles=warmup_candles))

    def confidence_summary(self) -> dict[str, int]:
        result = {k: 0 for k in ("HIGH", "MEDIUM", "LOW", "UNKNOWN")}
        per_symbol: dict[str, str] = {}
        rank = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
        for event in self.events:
            previous = per_symbol.get(event.symbol, "UNKNOWN")
            if rank[event.confidence] > rank[previous]:
                per_symbol[event.symbol] = event.confidence
        for confidence in per_symbol.values(): result[confidence] += 1
        return result


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
