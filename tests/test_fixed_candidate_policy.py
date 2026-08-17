from signal_engine.signal_logic import SignalEngine


def candidate(symbol, spread, liquidity):
    return {
        'symbol': symbol, 'timeframe': '4h',
        'order_book': {'spread_pct': spread},
        '_selection_volume_usdt': liquidity,
    }


def test_fixed_policy_prefers_execution_quality_not_input_order():
    candidates = [
        candidate('FIRSTUSDT', 0.10, 100_000_000),
        candidate('TIGHTUSDT', 0.02, 10_000_000),
        candidate('WIDEUSDT', 0.20, 1_000_000_000),
    ]
    selected = min(candidates, key=SignalEngine._fixed_candidate_key)
    assert selected['symbol'] == 'TIGHTUSDT'


def test_fixed_policy_uses_liquidity_then_symbol_as_stable_tiebreakers():
    candidates = [
        candidate('BUSDT', 0.02, 20_000_000),
        candidate('AUSDT', 0.02, 20_000_000),
        candidate('CUSDT', 0.02, 30_000_000),
    ]
    assert min(candidates, key=SignalEngine._fixed_candidate_key)['symbol'] == 'CUSDT'
    assert sorted(candidates[:2], key=SignalEngine._fixed_candidate_key)[0]['symbol'] == 'AUSDT'
