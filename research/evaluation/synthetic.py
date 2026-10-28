"""Seeded synthetic inputs for engine tests of ``net_eval`` and ``regimes`` (a45g-syn-v1). SYNTHETIC only.

* ``regime_switching_market``: a Markov-switching log-normal close series with a known regime path.
* ``null_entry_trades``: random-time entries with a fixed holding horizon, priced with ``trade_from_prices``.
  The entry time is independent of future prices, so in expectation the gross edge equals the drift of the
  bars held and the net result is that drift minus costs. It exists to check that the evaluator recovers a
  known cost drag and uncertainty; it is a null model, not a strategy, and says nothing about real markets.
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence

from research.evaluation.net_eval import TradeRecord, trade_from_prices

VERSION = "a45g-syn-v1"


def regime_switching_market(n: int, regimes: Mapping[str, tuple], *, stay_prob: float, seed: int,
                            p0: float = 100.0) -> tuple[list, list]:
    """``regimes`` maps a name to (drift per bar, volatility per bar). Returns (closes, true_regime) where
    true_regime[i] generated the return from bar i - 1 to bar i (true_regime[0] is the initial state)."""
    if n < 2 or not regimes or not 0 <= stay_prob <= 1:
        raise ValueError("need n >= 2, at least one regime and stay_prob in [0, 1]")
    names = sorted(regimes)
    rng = random.Random(seed)
    state = names[rng.randrange(len(names))]
    closes, path = [float(p0)], [state]
    for _ in range(n - 1):
        if len(names) > 1 and rng.random() >= stay_prob:
            others = [x for x in names if x != state]
            state = others[rng.randrange(len(others))]
        mu, sigma = regimes[state]
        closes.append(closes[-1] * math.exp(mu - 0.5 * sigma * sigma + sigma * rng.gauss(0.0, 1.0)))
        path.append(state)
    return closes, path


def null_entry_trades(closes: Sequence[float], close_times: Sequence[float], *, n_trades: int, horizon: int,
                      seed: int, half_spread: float, slippage: float, first_index: int = 0,
                      symbol: str = "SYN") -> list[TradeRecord]:
    """Entries at the close of randomly chosen bars (never using later prices), exits ``horizon`` bars later
    at that close; both legs taker with the given half-spread and slippage, fee 0.10 % per side."""
    if horizon < 1 or n_trades < 1 or len(closes) != len(close_times):
        raise ValueError("invalid null-entry parameters")
    last = len(closes) - 1 - horizon
    if last < first_index:
        raise ValueError("series too short for the horizon")
    rng = random.Random(seed)
    out = []
    for j in range(n_trades):
        i = rng.randint(first_index, last)
        out.append(trade_from_prices(f"{symbol}-{j}", symbol, close_times[i], close_times[i + horizon],
                                     entry_ref=closes[i], exit_ref=closes[i + horizon],
                                     half_spread_entry=half_spread, half_spread_exit=half_spread,
                                     slippage_entry=slippage, slippage_exit=slippage))
    return out
