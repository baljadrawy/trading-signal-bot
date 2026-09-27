from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import numpy as np

from research.foundation.contract import contract_hash, current_contract
from research.foundation.readers import NormalizedParquetReader, open_reader
from research.foundation.replay import _decision_code
from research.foundation.runtime_contract import (
    MACRO_ABLATION, MACRO_BYPASS, derive_macro_disabled, macro_only_diff,
    redact_mapping, runtime_contract,
)
from shared.config import config
from shared.strategy_math import (calculate_production_indicators,
                                  calculate_signal_levels,
                                  production_indicator_params)
from shared.triple_barrier import expiry_policy_for_timeframe


def configs():
    analyzer = {"TIMEFRAMES": ["15m", "4h", "1d"], "MIN_VOLUME_USDT": 10_000_000,
        "MIN_PRICE_CHANGE_PERCENT": 1, "MOM_BREAKOUT_N": 20, "MOM_VOL_MULT": 1.2,
        "REV_RSI": 35, "REV_BB_MAX_POSITION": .2, "MAX_SPREAD_PCT": .15}
    tracker = {"MAX_OPEN_TRADES": 10, "RISK_CANARY_MAX_OPEN_TRADES": 2,
        "RISK_CAPITAL_USDT": 500, "MAX_DAILY_LOSS_PERCENT": 3,
        "MAX_WEEKLY_LOSS_PERCENT": 10, "MAX_DRAWDOWN_PERCENT": 15,
        "MAX_GROSS_EXPOSURE_PERCENT": 80, "MAX_SYMBOL_EXPOSURE_PERCENT": 10,
        "MAX_STRATEGY_EXPOSURE_PERCENT": 40, "MAX_REGIME_EXPOSURE_PERCENT": 50,
        "STOP_ON_CONSECUTIVE_LOSSES": 7, "FEE_ROUNDTRIP_PCT": .3,
        "STOP_SLIPPAGE": .001, "TRADE_AMOUNT_USDT": 50}
    return analyzer, tracker


def test_runtime_config_not_host_defaults_and_max_open_parity():
    analyzer, tracker = configs()
    value = runtime_contract(analyzer=analyzer, tracker=tracker,
                             runtime_logic_sources={"runtime:test.py": "a" * 64})
    assert value["timeframes"] == ["15m", "4h", "1d"]
    assert value["risk"]["max_open_trades"] == 2


def test_macro_child_is_deep_copy_and_only_allowlisted_diff():
    analyzer, tracker = configs()
    parent = runtime_contract(analyzer=analyzer, tracker=tracker,
                              runtime_logic_sources={"runtime:test.py": "a" * 64})
    original = contract_hash(parent)
    child = derive_macro_disabled(parent)
    assert contract_hash(parent) == original
    assert child["macro"]["mode"] == MACRO_ABLATION
    assert child["macro"]["admission_behavior"] == MACRO_BYPASS
    assert macro_only_diff(parent, child)["status"] == "PASS"
    child["risk"]["max_open_trades"] = 9
    assert macro_only_diff(parent, child)["status"] == "FAIL — RESEARCH_CONTRACT_DRIFT"


def test_secret_redaction():
    value = redact_mapping({"API_KEY": "sensitive", "nested": {"PASSWORD": "x"}, "safe": 2})
    assert value == {"API_KEY": {"present": True, "source": "environment"},
                     "nested": {"PASSWORD": {"present": True, "source": "environment"}},
                     "safe": 2}
    assert "sensitive" not in json.dumps(value)


def _snapshot(tmp_path: Path):
    root = tmp_path / "ds-test"; path = root / "normalized" / "1h" / "BTCUSDT.parquet"
    path.parent.mkdir(parents=True)
    opens = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    frame = pd.DataFrame({"symbol": "BTCUSDT", "timeframe": "1h", "open_time": opens,
        "close_time": opens + pd.Timedelta(hours=1) - pd.Timedelta(microseconds=1),
        "open": [1., 2., 3.], "high": [2., 3., 4.], "low": [.5, 1.5, 2.5],
        "close": [1.5, 2.5, 3.5], "volume": [10., 11., 12.],
        "quote_volume": [15., 27.5, 42.], "trade_count": [1, 2, 3]})
    frame.to_parquet(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"dataset_id": "ds-test", "identity": {"normalized_files": [{
        "path": "1h/BTCUSDT.parquet", "symbol": "BTCUSDT", "timeframe": "1h",
        "sha256": digest, "rows": 3, "bytes": path.stat().st_size}]}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root, path


def test_parquet_adapter_selected_by_manifest_and_read_only(tmp_path):
    root, path = _snapshot(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = open_reader(root)
    assert isinstance(reader, NormalizedParquetReader)
    result = reader.read("BTCUSDT", "1h", verify_hash=True)
    assert list(result["timestamp"]) == list(result["open_time"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list((root / "normalized").rglob("*.csv"))


def test_parquet_adapter_rejects_missing_schema_and_future_cutoff(tmp_path):
    root, path = _snapshot(tmp_path)
    frame = pd.read_parquet(path).drop(columns=["trade_count"])
    frame.to_parquet(path, index=False)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["identity"]["normalized_files"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="DATASET_FIELD_UNAVAILABLE"):
        NormalizedParquetReader.open(root).read("BTCUSDT", "1h")


def test_macro_bypass_is_not_pass():
    contract = current_contract()
    market = {"quote_volume": 20_000_000, "change_24h_pct": 2,
              "spread": .1, "spread_data_mode": "HISTORICAL_SPREAD_PROXY",
              "macro_pass": None, "macro_admission": MACRO_BYPASS}
    code, _ = _decision_code(contract, market, True, "momentum", "bullish", True, "within_limits")
    assert code.value == "ACCEPTED"
    assert market["macro_pass"] is None
    market.pop("macro_admission")
    code, _ = _decision_code(contract, market, True, "momentum", "bullish", True, "within_limits")
    assert code.value == "REJECT_MACRO_DATA_UNAVAILABLE"


def test_one_hour_strategy_math_and_expiry_path_is_technically_valid():
    close = np.linspace(100.0, 130.0, 240)
    frame = pd.DataFrame({"open": close - .2, "high": close + 1,
                          "low": close - 1, "close": close,
                          "volume": np.linspace(1000, 2000, 240)})
    calculated = calculate_production_indicators(frame, production_indicator_params(config))
    levels = calculate_signal_levels(calculated, "1h", "momentum", breakout_n=20)
    assert levels["entry"] > levels["stop"] > 0
    assert levels["t1"] < levels["t2"] < levels["t3"]
    assert expiry_policy_for_timeframe("1h") == (48.0, 24.0, 24.0)
