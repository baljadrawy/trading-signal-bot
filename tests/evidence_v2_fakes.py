"""Shared synthetic inputs for the P1 evidence-v2 tests (no network, no exchange, no real data)."""
import numpy as np

from shared import evidence_v2 as ev2

TF_MS = {'15m': 900_000, '4h': 14_400_000, '1d': 86_400_000}
IDENT = {'strategy_version': 'sb-test', 'code_sha': 'c' * 64, 'config_hash': 'h' * 64,
         'build_revision': 'unknown', 'phase_id': None}


def synthetic_klines(timeframe='15m', n_closed=230, seed=7, now_ms=None, open_candle_close=None):
    """Binance-shaped kline rows: n_closed closed candles plus the still-open current candle."""
    step = TF_MS[timeframe]
    now_ms = now_ms or ev2.now_ms()
    current_open = now_ms - now_ms % step
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for i in range(n_closed, 0, -1):
        o = current_open - i * step
        close = price * float(np.exp(rng.normal(0, 0.01)))
        high = max(price, close) * (1 + abs(rng.normal(0, 0.003)))
        low = min(price, close) * (1 - abs(rng.normal(0, 0.003)))
        vol = float(abs(rng.normal(1000, 200)))
        rows.append([o, f"{price:.8f}", f"{high:.8f}", f"{low:.8f}", f"{close:.8f}", f"{vol:.4f}",
                     o + step - 1, f"{vol * close:.4f}", 100, "1", "1", "0"])
        price = close
    oc = open_candle_close if open_candle_close is not None else price
    rows.append([current_open, f"{price:.8f}", f"{max(price, oc) * 1.001:.8f}",
                 f"{min(price, oc) * 0.999:.8f}", f"{oc:.8f}", "10.0", current_open + step - 1,
                 "1000", 10, "1", "1", "0"])                          # still open
    return rows, current_open


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    async def get_klines(self, symbol, interval, limit):
        return self.rows[-limit:]


class FakeMacro:
    def __init__(self, blocked=False, state='flat', age_s=60.0):
        self.blocked, self._s, self.age_s = blocked, state, age_s
        self._last_valid_ts = ev2.now_ms() / 1000 - age_s

    async def should_block_now(self):
        return self.blocked

    def macro_state_key(self):
        return f"usdtd_{self._s}"

    def snapshot(self):
        return {'btc_trend': 'neutral', 'macro_data_valid': True, 'macro_age_seconds': self.age_s}

    def state(self):
        return {'usdtd_trend': self._s}


def inject_recorder(monkeypatch, service, **kw):
    """Enable v2 and install an in-memory recorder for `service`. Returns (recorder, sink)."""
    from shared.config import config
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', True)
    ev2.reset_for_tests()
    sink = ev2.ListSink()
    rec = ev2.RecorderV2(service, sink, IDENT, **kw)
    ev2._RECORDERS[service] = rec
    return rec, sink


def analysis_row(symbol, timeframe='15m', trade_type='momentum', spread=0.01, valid=True,
                 stop_valid=True, candle_open_ms=None, entry=100.0, extra=None):
    """An analysis_results row as the signal engine reads it (with a P1 pit block)."""
    candle_open_ms = candle_open_ms if candle_open_ms is not None else (
        ev2.now_ms() - ev2.now_ms() % TF_MS[timeframe] - TF_MS[timeframe])
    cid = ev2.candle_id(symbol, timeframe, candle_open_ms)
    now = ev2.now_ms()
    data = {
        'symbol': symbol, 'timeframe': timeframe, 'trade_type': trade_type,
        'order_book': {'valid': valid, 'spread_pct': spread, 'score': 1},
        'stop_valid': stop_valid, 'stop_reject_reason': None if stop_valid else 'risk_exceeds_cap',
        'entry_price': entry, 'target_1': entry * 1.02, 'target_2': entry * 1.036,
        'target_3': entry * 1.044, 'stop_loss': entry * 0.98, 'stop_invalidation': entry * 0.985,
        'stop_risk_pct': 2.0, 'stop_policy': 'invalidation_atr_v1', 'total_score': 5.0,
        'features': {'rsi': 55.0}, 'research_features': {'rsi': 55.0},
        'pit': {'pit_version': 1, 'candle_open_time_ms': candle_open_ms,
                'candle_close_time_ms': candle_open_ms + TF_MS[timeframe] - 1,
                'klines_fetched_at_ms': now - 2000, 'analyzed_at_ms': now - 1000,
                'orderbook_fetched_at_ms': now - 1500, 'candle_id': cid,
                'candidate_id': ev2.candidate_id(cid, trade_type, 'sb-test'),
                'strategy_version': 'sb-test', 'code_sha': 'a' * 64, 'config_hash': 'b' * 64},
        **(extra or {}),
    }
    return {'symbol': symbol, 'timeframe': timeframe, 'analysis_data': data}
