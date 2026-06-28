"""Evidence Store — a snapshot tied to the decision moment (not a generic kline dump).

Two tiers (persistence wired in a later step):
  HOT  : last ~60-90 days, full OHLCV window per signal   (e.g. BTCUSDT_15m.parquet)
  COLD : compressed, feature_vector + snapshot only        (signal_snapshots.parquet)
"""
from dataclasses import dataclass, field
from typing import Optional, Any
import numpy as np

HOT_RETENTION_DAYS = 90


@dataclass
class SignalSnapshot:
    signal_id: str
    timestamp: float                 # epoch seconds at the decision moment
    symbol: str
    timeframe: str
    ohlcv_window: Any                 # (W,5) bars at decision time — HOT only
    feature_vector: dict
    market_regime: str
    confidence: float
    signal_score: float
    entry_decision: str               # long / watch / ignore
    holding_period: Optional[float] = None   # filled at close
    realized_return: Optional[float] = None  # filled at close

    def to_cold_dict(self) -> dict:
        """Cold tier: everything EXCEPT the heavy raw OHLCV window."""
        return {
            "signal_id": self.signal_id, "timestamp": self.timestamp,
            "symbol": self.symbol, "timeframe": self.timeframe,
            "feature_vector": self.feature_vector, "market_regime": self.market_regime,
            "confidence": self.confidence, "signal_score": self.signal_score,
            "entry_decision": self.entry_decision, "holding_period": self.holding_period,
            "realized_return": self.realized_return,
        }

    def to_hot_dict(self) -> dict:
        d = self.to_cold_dict()
        d["ohlcv_window"] = np.asarray(self.ohlcv_window)
        return d


def is_hot(snapshot_ts: float, now_ts: float, retention_days: int = HOT_RETENTION_DAYS) -> bool:
    """Whether a snapshot still belongs in the hot (full-OHLCV) tier."""
    return (now_ts - snapshot_ts) <= retention_days * 86400
