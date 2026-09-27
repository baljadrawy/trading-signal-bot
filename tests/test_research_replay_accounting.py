import pandas as pd
import pytest

from research.foundation.costs import CostModel
from research.foundation.labels import excursions, forward_labels, forward_time_labels
from research.foundation.portfolio import mark_to_market, risk_fields
from research.foundation.replay_position import ReplayPosition, apply_costs
from shared.triple_barrier import TripleBarrierConfig


def _position(**cfg_values):
    values = dict(symbol="XUSDT", entry=100, target_1=102, target_2=104,
                  target_3=106, stop_loss=97, trade_amount=50,
                  expiry_h=48, t1_expiry_h=24, no_t1_expiry_h=24)
    values.update(cfg_values)
    return ReplayPosition("trade", TripleBarrierConfig(**values), 0, 97, "1h")


def _bar(ts, high, low, close, close_ms=1):
    return {"timestamp": ts, "high": high, "low": low, "close": close,
            "close_time_ms": close_ms}


def test_partial_t1_t2_then_stop_accounting():
    p = _position()
    assert p.step(_bar("1", 104.5, 102.5, 104, close_ms=0), hours=1) is None
    result = p.step(_bar("2", 104, 101, 102, close_ms=0), hours=1)
    # T1 25% + T2 50% + remaining 25% at trailing stop.
    assert result["highest_target"] == 2
    assert result["remaining_fraction"] == pytest.approx(.25)
    assert [e["reason"] for e in result["events"]].count("T1_fill") == 1
    assert [e["reason"] for e in result["events"]].count("T2_fill") == 1


def test_t3_uses_25_50_25_and_closes_all():
    result = _position().step(_bar("1", 107, 96, 106, close_ms=0), hours=1)
    # Conservative existing stop wins when both initial stop and T3 are touched.
    assert result["exit_reason"] == "stop_loss"
    clean = _position().step(_bar("1", 107, 99, 106, close_ms=0), hours=1)
    assert clean["exit_reason"] == "T3"
    assert clean["remaining_fraction"] == 0
    assert clean["gross_pct"] == pytest.approx(4.0)  # .25*2 + .50*4 + .25*6


def test_ambiguous_policy_marks_unknown_sequence():
    result = _position().step(_bar("1", 103, 96, 100), hours=1,
                              intrabar_policy="AMBIGUOUS")
    assert result["intrabar_ambiguous"]
    assert result["exit_reason"] == "intrabar_sequence_unknown"


def test_candle_invalidation_and_expiries():
    invalidated = _position().step(_bar("1", 101, 98, 96, close_ms=2), hours=1)
    assert invalidated["exit_reason"] == "signal_candle_invalidation"
    p = _position(no_t1_expiry_h=1)
    expired = p.step(_bar("1", 101, 98, 99, close_ms=0), hours=1)
    assert expired["exit_reason"] == "no_T1_expired_1h"


def test_cost_model_baseline_and_stop_slippage():
    model = CostModel(); assert model.baseline_roundtrip == pytest.approx(.003)
    result = _position().step(_bar("1", 100, 96, 97, close_ms=0), hours=1)
    assert result["exit_price"] == pytest.approx(96.903)
    net = apply_costs(result, 50, model)
    assert net["cost_usdt"] == pytest.approx(.15)


def test_forward_labels_and_excursions_are_post_decision():
    future = pd.DataFrame({"timestamp":["1","2","3"],
                           "close_time":pd.to_datetime(["2025-01-01T01:00Z","2025-01-01T04:00Z","2025-01-01T12:00Z"]),
                           "high":[102,105,103],
                           "low":[99,98,97], "close":[101,104,100]})
    assert forward_labels(100, future, (1,3))["return_1bar"] == pytest.approx(1)
    ex = excursions(100, future, before_t1=104)
    assert ex["mfe"] == pytest.approx(5); assert ex["mae"] == pytest.approx(-3)
    assert ex["mfe_before_t1"] == pytest.approx(5)
    timed = forward_time_labels(100, "2025-01-01T00:00Z", future, (1,4,12))
    assert timed == pytest.approx({"return_1h":1, "return_4h":4, "return_12h":0})


def test_mark_to_market_and_risk_accounting():
    trades = [{"symbol":"X", "entry_time":"1", "exit_time":"3", "entry_price":100,
               "notional":50, "net_usdt":5}]
    curve, metrics = mark_to_market(500, trades, {"X":{"1":100,"2":90,"3":110}})
    assert curve[1]["equity"] == pytest.approx(495)
    assert metrics["max_drawdown_pct"] == pytest.approx(1)
    risk = risk_fields(100, 97, 50, 500)
    assert risk["capital_at_risk_usdt"] == pytest.approx(1.5)
