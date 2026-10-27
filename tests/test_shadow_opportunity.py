"""Synthetic tests for shared.shadow_opportunity (no DB, no network, no runtime wiring)."""
import json
import os
from pathlib import Path

import pytest

from research.mechanisms.costs import CostModel as ResearchCostModel
from shared import shadow_opportunity as so
from shared.signal_quality import CostModel

H = 3_600_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % H)
REPO = Path(__file__).resolve().parents[1]


def _rec(**kw):
    base = dict(signal_id="sig-1", candidate_id="cand-1", symbol="AAAUSDT",
                trade_type="momentum", timeframe="15m", strategy_version="sv-test",
                risk_policy_version="econ-observe-v1", refusal_code="max_open_trades",
                refusal_layer=so.LAYER_ADMISSION, decision_ms=T0, planned_entry=100.0,
                stop_loss=98.0, target_1=102.0, target_2=104.0, target_3=106.0)
    base.update(kw)
    return so.build_opportunity(**base)


def _path(rows):
    """rows of (open, high, low, close) on contiguous 1h bars starting at the decision."""
    return [(T0 + i * H, o, h, lo, c) for i, (o, h, lo, c) in enumerate(rows)]


# ---- classification ----------------------------------------------------------------------
@pytest.mark.parametrize("code,layer,cls", [
    ("max_open_trades", so.LAYER_ADMISSION, "max_open_trades"),
    ("loss_streak_minimum", so.LAYER_ADMISSION, "max_open_trades"),
    ("drawdown_caution", so.LAYER_ADMISSION, "max_open_trades"),
    ("symbol_concentration_limit", so.LAYER_ADMISSION, "symbol_concentration_limit"),
    ("gross_exposure_limit", so.LAYER_ADMISSION, "gross_exposure_limit"),
    ("strategy_concentration_limit", so.LAYER_ADMISSION, "strategy_concentration_limit"),
    ("regime_concentration_limit", so.LAYER_ADMISSION, "regime_concentration_limit"),
    ("portfolio_capacity_2/2", so.LAYER_DELIVERY, "delivery_portfolio_capacity"),
])
def test_capacity_refusal_recorded(code, layer, cls):
    r = _rec(refusal_code=code, refusal_layer=layer)
    assert r["refusal_class"] == cls and r["refusal_code"] == code


@pytest.mark.parametrize("code,layer", [
    ("daily_loss_limit", so.LAYER_ADMISSION), ("weekly_loss_limit", so.LAYER_ADMISSION),
    ("max_drawdown_limit", so.LAYER_ADMISSION), ("loss_streak_halt", so.LAYER_ADMISSION),
    ("invalid_risk_state", so.LAYER_ADMISSION), ("manual_pause", so.LAYER_ADMISSION),
    ("risk_state_missing", so.LAYER_ADMISSION), ("risk:loss_streak_halt", so.LAYER_ADMISSION),
    ("observed:loss_streak_halt", so.LAYER_ADMISSION), ("within_limits", so.LAYER_ADMISSION),
    ("", so.LAYER_ADMISSION), ("trading_paused", so.LAYER_DELIVERY),
    ("operator free text", so.LAYER_DELIVERY), ("portfolio_capacity_1/2", so.LAYER_DELIVERY),
    ("portfolio_capacity_0/0", so.LAYER_DELIVERY), ("max_open_trades", so.LAYER_DELIVERY),
    ("portfolio_capacity_2/2", so.LAYER_ADMISSION),
])
def test_real_stops_not_recorded(code, layer):
    with pytest.raises(so.NotAnOpportunityError):
        _rec(refusal_code=code, refusal_layer=layer)


def test_unknown_layer_rejected():
    with pytest.raises(so.ShadowError):
        _rec(refusal_layer="scanner")


def test_record_labels_and_fields():
    r = _rec()
    assert r["record_kind"] == "shadow_opportunity" and r["record_kind"] != "trade"
    assert r["executed"] is False and r["is_executed_trade"] is False
    assert r["decision_ms"] == T0 and r["decision_minute_utc"].endswith("Z")
    assert len(r["decision_minute_utc"]) == len("2026-01-01T00:00Z")
    assert r["cost_model_version"].startswith("binance_spot_baseline_20bps")
    assert r["stream"] == so.STREAM_NAME and len(r["opportunity_id"]) == 64
    assert (r["planned_entry"], r["stop_loss"], r["target_3"]) == (100.0, 98.0, 106.0)


@pytest.mark.parametrize("bad", [dict(planned_entry=float("nan")), dict(stop_loss=0),
                                 dict(signal_id=""), dict(decision_ms=0),
                                 dict(target_1=True)])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(so.ShadowError):
        _rec(**bad)


# ---- ledger ------------------------------------------------------------------------------
def test_ledger_append_only_and_tamper_detection(tmp_path):
    led = so.ShadowOpportunityLedger(str(tmp_path / so.DEFAULT_FILENAME))
    a, b = _rec(), _rec(signal_id="sig-2", candidate_id="cand-2")
    led.append_opportunity(a)
    led.append_opportunity(b)
    with pytest.raises(so.ShadowError):
        led.append_opportunity(a)                       # duplicate opportunity
    assert [r["signal_id"] for r in led.opportunities()] == ["sig-1", "sig-2"]
    lines = Path(led.path).read_text().splitlines()
    assert json.loads(lines[1])["body"]["opportunity_id"] == b["opportunity_id"]

    tampered = json.loads(lines[0])
    tampered["body"]["planned_entry"] = 99.0
    Path(led.path).write_text(json.dumps(tampered) + "\n" + lines[1] + "\n")
    with pytest.raises(so.LedgerTamperError):
        led.verify()
    Path(led.path).write_text(lines[1] + "\n")          # deleting a row breaks the chain
    with pytest.raises(so.LedgerTamperError):
        list(led.opportunities())


def test_ledger_rejects_relabelled_row_even_with_valid_hash(tmp_path):
    led = so.ShadowOpportunityLedger(str(tmp_path / so.DEFAULT_FILENAME))
    body = dict(_rec(), executed=True)
    h = so._entry_hash(0, so.GENESIS_HASH, body)
    Path(led.path).write_text(json.dumps(
        {"seq": 0, "prev_hash": so.GENESIS_HASH, "body": body, "entry_hash": h}) + "\n")
    with pytest.raises(so.LedgerTamperError):
        led.verify()


@pytest.mark.parametrize("name", ["paper_trades.jsonl", "shadow_opportunity_trades.jsonl",
                                  "shadow_opportunity.csv", "ledger.jsonl"])
def test_ledger_file_name_separate_from_trade_store(tmp_path, name):
    with pytest.raises(so.ShadowError):
        so.ShadowOpportunityLedger(str(tmp_path / name))


def test_ledger_never_returns_trades(tmp_path):
    led = so.ShadowOpportunityLedger(str(tmp_path / so.DEFAULT_FILENAME))
    led.append_opportunity(_rec())
    with pytest.raises(so.NotATradeError):
        led.trades()
    with pytest.raises(so.ShadowError):
        led.append_opportunity({"record_kind": "trade", "executed": True})
    for r in led.opportunities():
        with pytest.raises(so.NotATradeError):
            so.assert_not_shadow(r)


def test_outcome_requires_known_opportunity(tmp_path):
    led = so.ShadowOpportunityLedger(str(tmp_path / so.DEFAULT_FILENAME))
    rec = _rec()
    out = so.resolve_outcome(rec, _path([(100, 107, 99.5, 106.5)]), bar_timeframe="1h")
    with pytest.raises(so.ShadowError):
        led.append_outcome(out)
    led.append_opportunity(rec)
    led.append_outcome(out)
    with pytest.raises(so.ShadowError):
        led.append_outcome(out)
    assert [o["opportunity_id"] for o in led.outcomes()] == [rec["opportunity_id"]]


# ---- outcome resolution ------------------------------------------------------------------
def test_outcome_target_hit_net_of_costs():
    out = so.resolve_outcome(_rec(), _path([(100, 107, 99.5, 106.5)]), bar_timeframe="1h")
    assert out["record_kind"] == "shadow_outcome" and out["is_executed_trade"] is False
    assert out["executed"] is False and out["outcome_model"] == so.REPLAY_MODEL_VERSION
    assert out["status"] == "closed" and out["target_reached"] == 3
    assert out["gross_pct"] > 0
    assert out["net_pct"] == pytest.approx(out["gross_pct"] - 0.20)


def test_outcome_stop_hit_with_slippage_and_spread():
    cost = CostModel(entry_slippage_pct=0.05, exit_slippage_pct=0.05, include_spread=True)
    rec = _rec(cost=cost)
    out = so.resolve_outcome(rec, _path([(100, 100.5, 97.0, 97.5)]), bar_timeframe="1h",
                             spread_pct=0.04)
    assert out["status"] == "closed" and out["target_reached"] == 0
    assert out["exit_price"] == pytest.approx(98.0 * (1 - 0.001))
    assert out["cost_roundtrip_pct"] == pytest.approx(0.20 + 0.10 + 0.04)
    assert out["net_pct"] == pytest.approx(out["gross_pct"] - 0.34)
    assert out["net_pct"] < -2.0
    with pytest.raises(ValueError):                         # spread is required, never assumed
        so.resolve_outcome(rec, _path([(100, 100.5, 97.0, 97.5)]), bar_timeframe="1h")


def test_outcome_expiry_on_flat_path():
    flat = [(100, 100.4, 99.6, 100.0)] * 60
    out = so.resolve_outcome(_rec(), _path(flat), bar_timeframe="1h")
    assert out["status"] == "closed" and out["target_reached"] == 0
    assert out["exit_reason"] not in ("stop_loss", "target_1", "target_2", "target_3")
    assert "expir" in str(out["exit_reason"]) or "time" in str(out["exit_reason"])
    assert out["net_pct"] == pytest.approx(out["gross_pct"] - 0.20)


def test_outcome_short_path_open_at_end_and_lookahead_guard():
    out = so.resolve_outcome(_rec(), _path([(100, 100.4, 99.6, 100.0)] * 3), bar_timeframe="1h")
    assert out["status"] == "open_at_end" and out["net_pct"] is None
    early = [(T0 - H, 100, 100.4, 99.6, 100.0)]
    with pytest.raises(so.ShadowError):
        so.resolve_outcome(_rec(), early, bar_timeframe="1h")


def test_four_tuple_path_supported():
    path = [(T0, 107, 99.5, 106.5)]
    out = so.resolve_outcome(_rec(), path, bar_timeframe="1h")
    assert out["open_source"] == "prev_close" and out["status"] == "closed"


def test_unsupported_trade_type_uses_flagged_approximation():
    rec = _rec(trade_type="breakout")
    win = so.resolve_outcome(rec, _path([(100, 102.5, 99.5, 102.2)]), bar_timeframe="1h")
    assert win["outcome_model"] == so.APPROX_MODEL and win["exit_reason"] == "target_1"
    assert win["net_pct"] == pytest.approx(2.0 - 0.20)
    both = so.resolve_outcome(rec, _path([(100, 103, 97.5, 101)]), bar_timeframe="1h")
    assert both["exit_reason"] == "stop_loss"                    # stop checked first
    assert both["net_pct"] == pytest.approx((98 * 0.999 / 100 - 1) * 100 - 0.20)


def test_cost_model_matches_research_cost_model():
    sq = CostModel(entry_slippage_pct=0.03, exit_slippage_pct=0.03)
    rm = ResearchCostModel(fee_per_side=0.001, slippage=0.0003)
    assert sq.roundtrip_pct() == pytest.approx(rm.round_trip * 100)


# ---- aggregation -------------------------------------------------------------------------
def test_aggregation_keeps_populations_separate():
    rec = _rec()
    outs = [so.resolve_outcome(rec, _path([(100, 107, 99.5, 106.5)]), bar_timeframe="1h"),
            so.resolve_outcome(rec, _path([(100, 100.5, 97.0, 97.5)]), bar_timeframe="1h")]
    executed = [{"trade_id": 1, "gross_pct": 1.0, "net_pct": 0.8}]
    agg = so.aggregate(outs, executed)
    assert agg["shadow"]["n_closed"] == 2 and agg["executed"]["n_closed"] == 1
    assert agg["pooled"] is None and agg["shadow"]["counted_as_paper_performance"] is False
    assert agg["executed"]["mean_net_pct"] == pytest.approx(0.8)
    with pytest.raises(so.MixedPopulationError):
        so.aggregate(outs, executed + [outs[0]])
    with pytest.raises(so.MixedPopulationError):
        so.aggregate(outs + executed, [])
    with pytest.raises(so.MixedPopulationError):
        so.merge_populations(agg["shadow"], agg["executed"])


# ---- no runtime wiring -------------------------------------------------------------------
def test_no_runtime_service_imports_the_module():
    hits = []
    for svc in ("trade_tracker", "telegram", "scanner", "signal_engine", "analyzer",
                "optimizer", "claude_review", "p2_forward"):
        root = REPO / svc
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith(".py"):
                    p = Path(dirpath) / f
                    if "shadow_opportunity" in p.read_text(encoding="utf-8", errors="ignore"):
                        hits.append(str(p.relative_to(REPO)))
    assert hits == []
