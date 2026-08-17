from shared.triple_barrier import TripleBarrierConfig, TripleBarrierState, step_barrier


def _cfg(**overrides):
    values = dict(
        symbol="BTCUSDT", entry=100.0, target_1=102.0, target_2=104.0,
        target_3=106.0, stop_loss=97.0, stop_slippage=0.001,
    )
    values.update(overrides)
    return TripleBarrierConfig(**values)


def test_existing_hard_stop_wins_when_same_bar_also_touches_t3():
    result = step_barrier(_cfg(), TripleBarrierState(peak=100), 107, 96, 105)
    assert result.exit_reason == "stop_loss"
    assert result.target_reached == 0
    assert result.stop_hit is True
    assert result.exit_price == 96.903


def test_target_then_dynamic_stop_is_conservative_when_intrabar_order_unknown():
    result = step_barrier(_cfg(), TripleBarrierState(peak=100), 103, 99, 102)
    assert result.exit_reason == "break_even"
    assert result.target_reached == 1
    assert result.exit_price == 100.3
    assert result.profit_pct == 0.3
    assert result.stop_hit is False


def test_clean_t3_hit_closes_at_target():
    result = step_barrier(_cfg(), TripleBarrierState(peak=100), 107, 100.5, 106)
    assert result.exit_reason == "T3"
    assert result.exit_price == 106
    assert result.result == "WIN"


def test_no_t1_time_stop_matches_live_24_hour_policy():
    state = TripleBarrierState(peak=100, hours_open=23)
    result = step_barrier(_cfg(), state, 101, 98, 99, hours_elapsed=1)
    assert result.exit_reason == "no_T1_expired_24h"
    assert result.duration_h == 24


def test_t2_trade_uses_trailing_stop_and_can_continue_to_48_hours():
    state = TripleBarrierState(peak=104, highest_target=2, hours_open=24)
    assert step_barrier(_cfg(), state, 104.5, 103, 104, hours_elapsed=1) is None
    result = step_barrier(_cfg(), state, 104, 103, 103.5, hours_elapsed=23)
    assert result.exit_reason == "expired_48h"


def test_config_rejects_unordered_targets_and_invalid_slippage():
    assert "strictly ordered" in _cfg(target_2=101).validate()
    assert "slippage" in _cfg(stop_slippage=1).validate()
    assert "roundtrip" in _cfg(roundtrip_cost=1).validate()


def test_net_break_even_stop_is_capped_at_small_t1():
    cfg = _cfg(target_1=100.2, target_2=104, target_3=106)
    stop = TripleBarrierState(peak=100.2, highest_target=1).effective_stop(cfg)[0]
    assert stop == 100.2
