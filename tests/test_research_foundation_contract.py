import json
from pathlib import Path

import pandas as pd
import pytest

from research.foundation.contract import compare_contracts, contract_hash, current_contract
from research.foundation.dataset import create_snapshot, load_snapshot, universe_at, verify_snapshot
from research.foundation.holdout import allow_partition
from research.foundation.opportunity import (OpportunityRecord, RejectionCode,
    assert_no_future_fields, deterministic_opportunity_id)
from research.foundation.quality import enforce_completed, validate_candles
from research.foundation.experiment import verify_reproducible_outputs
from research.foundation.experiment import ExperimentWriter
from research.foundation.runner import run_experiment
from research.foundation.contract import current_contract


def _candles(n=200):
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "close_time": ts + pd.Timedelta(minutes=15),
        "open": [100.0]*n, "high": [101.0]*n, "low": [99.0]*n,
        "close": [100.0]*n, "volume": [10.0]*n})


def test_contract_hash_is_deterministic_and_drift_is_explicit():
    live = current_contract()
    assert contract_hash(live) == contract_hash(json.loads(json.dumps(live)))
    changed = json.loads(json.dumps(live)); changed["entry"]["momentum"]["breakout_n"] = 21
    result = compare_contracts(live, changed)
    assert not result["match"]
    assert result["status"] == "RESEARCH CONTRACT DOES NOT MATCH LIVE CONTRACT"
    assert result["differences"][0]["path"] == "entry.momentum.breakout_n"


def test_dataset_content_addressing_checksum_and_immutability(tmp_path):
    raw = tmp_path / "bars.csv"; raw.write_text("a,b\n1,2\n")
    universe = [{"symbol":"BTCUSDT", "listed_at":"2020-01-01T00:00:00+00:00",
                 "delisted_at":None, "eligible_from":"2020-01-01T00:00:00+00:00",
                 "eligible_until":None, "quote_asset":"USDT", "status":"TRADING"}]
    snap = create_snapshot(sources=[raw], destination=tmp_path / "sets", source_name="fixture",
        start_time="2025-01-01T00:00:00+00:00", end_time="2025-01-02T00:00:00+00:00",
        symbols=["BTCUSDT"], timeframes=["15m"], row_counts={"bars.csv":1}, git_sha="abc",
        universe=universe, universe_completeness="PARTIAL_POINT_IN_TIME",
        created_at="2025-01-03T00:00:00+00:00")
    assert verify_snapshot(snap)["status"] == "PASS"
    same = create_snapshot(sources=[raw], destination=tmp_path / "sets", source_name="fixture",
        start_time="2025-01-01T00:00:00+00:00", end_time="2025-01-02T00:00:00+00:00",
        symbols=["BTCUSDT"], timeframes=["15m"], row_counts={"bars.csv":1}, git_sha="abc",
        universe=universe, universe_completeness="PARTIAL_POINT_IN_TIME")
    assert same.dataset_id == snap.dataset_id
    assert universe_at(universe, "2025-01-01T00:00:00+00:00") == ["BTCUSDT"]


def test_completed_candle_and_quality_guards():
    df = _candles()
    assert validate_candles(df, "15m")["status"] == "PASS"
    visible = enforce_completed(df, "2025-01-01T01:00:00+00:00")
    assert visible["close_time"].max() <= pd.Timestamp("2025-01-01T01:00:00+00:00")
    bad = pd.concat([df, df.iloc[[-1]]], ignore_index=True)
    assert validate_candles(bad, "15m")["status"] == "FAIL"


@pytest.mark.parametrize("key", ["future_return", "future_high", "MFE", "MAE", "future_label"])
def test_leakage_guard_rejects_future_fields(key):
    with pytest.raises(ValueError): assert_no_future_fields({key: 1})


def test_opportunity_id_and_rejected_record_are_deterministic():
    oid = deterministic_opportunity_id("ds", "BTCUSDT", "4h", "t", "v")
    assert oid == deterministic_opportunity_id("ds", "BTCUSDT", "4h", "t", "v")
    record = OpportunityRecord(oid, "ds", "exp", "sha", "v", "hash", "t", "t", "t",
        "BTCUSDT", "4h", "DISCOVERY", {}, {}, {"rsi": 30}, {}, False,
        RejectionCode.REJECT_ENTRY.value)
    assert not record.accepted


def test_holdout_is_locked_by_default():
    with pytest.raises(PermissionError): allow_partition("HOLDOUT", purpose="discovery")
    allow_partition("HOLDOUT", purpose="audit", unlock_holdout=True)


def test_reproducibility_comparator_is_byte_exact(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir(); second.mkdir()
    names = ("opportunities.jsonl", "trades.jsonl", "trade_events.jsonl", "metrics.json")
    for name in names:
        (first / name).write_text('{"fixed":1}\n')
        (second / name).write_text('{"fixed":1}\n')
    assert verify_reproducible_outputs(first, second)["deterministic"]
    (second / "metrics.json").write_text('{"fixed":2}\n')
    assert not verify_reproducible_outputs(first, second)["deterministic"]


def test_same_snapshot_config_sha_seed_produces_identical_replay(tmp_path):
    n = 202; ts = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series([100 + i * .1 for i in range(n)]); close.iloc[-2] = 123
    bars = pd.DataFrame({"symbol":"XUSDT", "timeframe":"4h", "timestamp":ts,
        "close_time":ts + pd.Timedelta(hours=4), "open":close-.1, "high":close+.2,
        "low":close-.2, "close":close, "volume":[100.]*(n-2)+[300.,100.],
        "quote_volume":20_000_000, "change_24h_pct":2., "macro_pass":True,
        "spread":.1, "spread_data_mode":"HISTORICAL_SPREAD_PROXY"})
    raw = tmp_path / "bars.csv"; bars.to_csv(raw, index=False)
    universe = [{"symbol":"XUSDT", "listed_at":"2020-01-01T00:00:00+00:00",
        "delisted_at":None, "eligible_from":"2020-01-01T00:00:00+00:00",
        "eligible_until":None, "quote_asset":"USDT", "status":"TRADING"}]
    snap = create_snapshot(sources=[raw], destination=tmp_path / "datasets", source_name="synthetic",
        start_time=ts[0].isoformat(), end_time=ts[-1].isoformat(), symbols=["XUSDT"],
        timeframes=["4h"], row_counts={"bars.csv":n}, git_sha="fixture", universe=universe,
        universe_completeness="FULL_POINT_IN_TIME", created_at="2025-02-01T00:00:00+00:00")
    params = {"rsi_period":14,"macd_fast":12,"macd_slow":26,"macd_signal":9,
        "ema_short":20,"ema_medium":50,"ema_long":200,"bb_period":20,"bb_std":2.,
        "atr_period":14,"stoch_rsi_window":14,"stoch_k":3,"stoch_d":3}
    cfg = {"strategy_version":"fixture", "random_seed":7, "research_partition":"DISCOVERY",
           "intrabar_policy":"CONSERVATIVE", "label_horizon_bars":24,
           "indicator_params":params, "cost_model":{}}
    repo = Path(__file__).resolve().parents[1]; contract = current_contract()
    roots = []
    for name in ("run_a", "run_b"):
        writer = ExperimentWriter(runs_root=tmp_path/name, dataset=snap, config=cfg,
            contract=contract, repo=repo, seed=7, created_at="2025-02-01T00:00:00+00:00",
            git_sha_override="fixed-sha", git_dirty_override=False)
        # The production research CLI reads Git directly; the minimal analyzer test
        # image intentionally has no git binary, so pin the same state explicitly.
        run_experiment(dataset=snap, writer=writer, indicator_params=params, config=cfg)
        roots.append(writer.root)
    assert verify_reproducible_outputs(*roots)["deterministic"]
