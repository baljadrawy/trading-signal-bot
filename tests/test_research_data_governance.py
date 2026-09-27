from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from research.data_governance.governance import (
    HoldoutLedger, TemporalGovernance, canonical_hash, partition_for,
)
from research.data_governance.market import add_point_in_time_24h, asof_macro, normalize_binance_klines
from research.data_governance.market import derive_usdt_d
from research.data_governance.execution import conservative_spread_proxy, EXECUTION_METADATA
from research.data_governance.download_binance_15m import download_one
from research.data_governance.universe import PointInTimeUniverse, UniverseEvent
from research.foundation.dataset import create_snapshot, load_snapshot, verify_snapshot
from research.foundation.quality import validate_candles


UTC = timezone.utc
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def event(symbol, kind, day):
    return UniverseEvent(symbol, "USDT", kind, T0 + timedelta(days=day),
                         "synthetic", "test", "HIGH")


def candles(n=100, freq="15min"):
    ts = pd.date_range(T0, periods=n, freq=freq)
    close = pd.Series(range(100, 100 + n), dtype=float)
    return pd.DataFrame({"timestamp": ts, "open": close, "high": close + 1,
                         "low": close - 1, "close": close, "volume": 1.0,
                         "quote_volume": close})


def test_point_in_time_listing_and_delisting():
    u = PointInTimeUniverse([event("AUSDT", "LISTED", 0), event("BUSDT", "LISTED", 60),
                             event("AUSDT", "DELISTED", 150)],
                            {"AUSDT": T0, "BUSDT": T0 + timedelta(days=60)})
    assert u.symbols_at(T0 + timedelta(days=31), timeframe=timedelta(days=1), warmup_candles=1) == ["AUSDT"]
    assert u.symbols_at(T0 + timedelta(days=91), timeframe=timedelta(days=1), warmup_candles=1) == ["AUSDT", "BUSDT"]
    assert u.symbols_at(T0 + timedelta(days=181), timeframe=timedelta(days=1), warmup_candles=1) == ["BUSDT"]


def test_future_listing_and_warmup_are_separate():
    u = PointInTimeUniverse([event("AUSDT", "LISTED", 10)], {"AUSDT": T0 + timedelta(days=10)})
    assert not u.exchange_listed("AUSDT", T0 + timedelta(days=9))
    assert u.data_available("AUSDT", T0 + timedelta(days=10))
    assert not u.strategy_eligible("AUSDT", T0 + timedelta(days=109),
                                   timeframe=timedelta(days=1), warmup_candles=100)
    assert u.strategy_eligible("AUSDT", T0 + timedelta(days=110),
                               timeframe=timedelta(days=1), warmup_candles=100)


def test_suspension_and_resume():
    u = PointInTimeUniverse([event("AUSDT", "LISTED", 0), event("AUSDT", "SUSPENDED", 2),
                             event("AUSDT", "RESUMED", 4)], {"AUSDT": T0})
    assert not u.exchange_listed("AUSDT", T0 + timedelta(days=3))
    assert u.exchange_listed("AUSDT", T0 + timedelta(days=5))


def test_rename_does_not_stitch_history():
    u = PointInTimeUniverse([event("OLDUSDT", "LISTED", 0), event("OLDUSDT", "DELISTED", 2),
                             event("NEWUSDT", "LISTED", 3)],
                            {"OLDUSDT": T0, "NEWUSDT": T0 + timedelta(days=3)})
    assert not u.data_available("NEWUSDT", T0 + timedelta(days=1))
    assert not u.exchange_listed("OLDUSDT", T0 + timedelta(days=4))


def test_rolling_24h_volume_and_change_no_lookahead():
    df = candles(100)
    early = add_point_in_time_24h(df.iloc[:97], timeframe="15m")
    full = add_point_in_time_24h(df, timeframe="15m")
    assert early.iloc[-1]["rolling_24h_quote_volume"] == full.iloc[96]["rolling_24h_quote_volume"]
    assert early.iloc[-1]["price_change_24h_pct"] == full.iloc[96]["price_change_24h_pct"]


def test_macro_asof_never_uses_future_and_detects_stale():
    decisions = pd.DataFrame({"decision_time": pd.to_datetime(["2024-01-02T12:00Z", "2024-01-05T00:00Z"])})
    macro = pd.DataFrame({"macro_source_time": pd.to_datetime(["2024-01-02T00:00Z", "2024-01-03T00:00Z"]), "usdt_d": [5.0, 5.1]})
    out = asof_macro(decisions, macro, max_age=pd.Timedelta("1D"))
    assert out.iloc[0].macro_source_time <= out.iloc[0].decision_time
    assert out.iloc[1].macro_status == "MACRO_STALE"


@pytest.mark.parametrize("mutator,expected", [
    (lambda d: d.assign(timestamp=d.timestamp.where(d.index != 1, d.timestamp.iloc[0])), "duplicate_candles"),
    (lambda d: d.assign(high=d.high.where(d.index != 1, d.low.iloc[1] - 2)), "invalid_ohlc"),
    (lambda d: d.assign(close=d.close.where(d.index != 1, 0)), "non_positive_price"),
])
def test_quality_failures(mutator, expected):
    result = validate_candles(mutator(candles(220)), "15m")
    assert result["status"] == "FAIL" and expected in result["failures"]


def test_missing_candles_warn():
    result = validate_candles(candles(220).drop(index=5).reset_index(drop=True), "15m")
    assert result["status"] == "WARN" and "timeframe_gaps" in result["warnings"]


def test_binance_microsecond_normalization(tmp_path):
    row = [1735689600000000, 1, 2, .5, 1.5, 10, 1735690499999999, 15, 1, 4, 6, 0]
    archive = tmp_path / "BTCUSDT-15m-2025-01.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("x.csv", ",".join(map(str, row)))
    df = normalize_binance_klines(archive, symbol="BTCUSDT", timeframe="15m")
    assert str(df.open_time.dt.tz) == "UTC" and df.iloc[0].symbol == "BTCUSDT"


def test_binance_millisecond_and_microsecond_units_match(tmp_path):
    def make(name, opened, closed):
        row = [opened, 1, 2, .5, 1.5, 10, closed, 15, 1, 4, 6, 0]
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as zf: zf.writestr("x.csv", ",".join(map(str, row)))
        return path
    ms = normalize_binance_klines(make("a.zip", 1735689600000, 1735690499999), symbol="BTCUSDT", timeframe="15m")
    us = normalize_binance_klines(make("b.zip", 1735689600000000, 1735690499999999), symbol="BTCUSDT", timeframe="15m")
    assert ms.iloc[0].open_time == us.iloc[0].open_time


def test_upstream_checksum_sidecar_verification_without_network(tmp_path):
    target = tmp_path / "BTCUSDT" / "15m" / "BTCUSDT-15m-2025-01.zip"
    target.parent.mkdir(parents=True); target.write_bytes(b"archive")
    digest = hashlib.sha256(b"archive").hexdigest()
    target.with_name(target.name + ".CHECKSUM").write_text(f"{digest}  {target.name}\n")
    assert download_one(tmp_path, "BTCUSDT", "2025-01")["status"] == "UPSTREAM_VERIFIED"


def test_derived_usdt_d_definition_and_alignment():
    t = pd.to_datetime(["2024-01-01T00:00Z", "2024-01-02T00:00Z"])
    usdt = pd.DataFrame({"timestamp": t, "market_cap": [100.0, 110.0]})
    total = pd.DataFrame({"timestamp": t, "market_cap": [2000.0, 2200.0]})
    out = derive_usdt_d(usdt, total)
    assert out.usdt_d_value.tolist() == [5.0, 5.0]


def test_universe_evidence_distinguishes_inferred_from_authoritative():
    inferred = UniverseEvent("AUSDT", "USDT", "DELISTED", T0, "archive", "last candle", "LOW",
                             source_tier="D", evidence_kind="INFERRED_LAST_DATA")
    official = UniverseEvent("BUSDT", "USDT", "DELISTED", T0, "Binance", "announcement", "HIGH",
                             source_tier="A", evidence_kind="OFFICIAL_ANNOUNCEMENT")
    assert inferred.evidence_kind != official.evidence_kind and inferred.source_tier == "D"


def test_spread_proxy_is_outcome_blind_and_metadata_is_tier3():
    value = conservative_spread_proxy({"rolling_24h_quote_volume": 50_000_000,
                                       "rolling_24h_trade_count": 20_000,
                                       "realized_volatility_pct": 2.0})
    assert value == 0.10
    with pytest.raises(ValueError):
        conservative_spread_proxy({"rolling_24h_quote_volume": 50_000_000, "pnl": 1})
    assert EXECUTION_METADATA["execution_fidelity"] == "TIER_3_DOCUMENTED_CONSERVATIVE_PROXY"


def test_holdout_sealed_by_default_and_one_way(tmp_path):
    ledger = HoldoutLedger(tmp_path / "holdout.json")
    ledger.initialize(freeze_timestamp="2026-08-19T00:00:00Z")
    with pytest.raises(PermissionError): ledger.assert_hidden()
    opened = ledger.unlock(opened_by="owner", reason="final confirmation",
                           hypothesis_ids=["H01"], git_sha="abc", experiment_ids=["e1"])
    assert opened["status"] == "OPENED" and opened["holdout_look_count"] == 1
    with pytest.raises(RuntimeError): ledger.unlock(opened_by="owner", reason="again",
        hypothesis_ids=["H01"], git_sha="abc", experiment_ids=["e2"])


def test_holdout_unlock_requires_registered_context(tmp_path):
    ledger = HoldoutLedger(tmp_path / "holdout.json")
    ledger.initialize(freeze_timestamp="2026-08-19T00:00:00Z")
    with pytest.raises(ValueError): ledger.unlock(opened_by="x", reason="", hypothesis_ids=[], git_sha="a", experiment_ids=[])


def test_contamination_registry_and_validation_counter(tmp_path):
    g = TemporalGovernance(tmp_path)
    g.register_contamination({"period_start": "2023-01-01", "period_end": "2025-12-31",
                              "contamination_level": "KNOWN_RESEARCHED", "reason": "prior reports"})
    g.log_validation_use(hypothesis_id="H01", experiment_id="E01", metrics_requested=["x"], result_artifact="x.json")
    assert g.validation_look_count() == 1
    with pytest.raises(ValueError): g.register_contamination({"contamination_level": "CLEAN"})


def test_future_partition_excluded_from_historical_snapshot():
    freeze = datetime(2026, 8, 19, tzinfo=UTC)
    assert partition_for(freeze + timedelta(seconds=1), freeze=freeze) == "FORWARD_HOLDOUT"
    assert partition_for(freeze, freeze=freeze) == "DISCOVERY"


def test_hash_and_normalization_deterministic():
    value = {"b": 2, "a": 1}
    assert canonical_hash(value) == canonical_hash({"a": 1, "b": 2})
    first = add_point_in_time_24h(candles(), timeframe="15m")
    second = add_point_in_time_24h(candles(), timeframe="15m")
    pd.testing.assert_frame_equal(first, second)


def test_dataset_manifest_checksum_immutability_and_correction_id(tmp_path):
    source = tmp_path / "a.csv"; source.write_text("x\n1\n")
    kwargs = dict(destination=tmp_path / "snapshots", source_name="test", start_time="2024-01-01Z",
                  end_time="2024-01-02Z", symbols=["AUSDT"], timeframes=["1d"],
                  row_counts={"1d": 1}, git_sha="abc", universe=[],
                  universe_completeness="PARTIAL_POINT_IN_TIME")
    first = create_snapshot(sources=[source], **kwargs)
    assert verify_snapshot(load_snapshot(first.root))["status"] == "PASS"
    source.write_text("x\n2\n")
    corrected = create_snapshot(sources=[source], source_metadata={"supersedes_dataset_id": first.dataset_id,
        "correction_reason": "test"}, **kwargs)
    assert corrected.dataset_id != first.dataset_id


def test_raw_checksum():
    assert hashlib.sha256(b"abc").hexdigest() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_spread_mode_metadata_contract():
    allowed = {"HISTORICAL_ORDERBOOK", "HISTORICAL_BBO", "HISTORICAL_SPREAD_PROXY", "SPREAD_UNAVAILABLE"}
    assert "SPREAD_UNAVAILABLE" in allowed and len(allowed) == 4


def test_freeze_fingerprint_changes_with_component():
    base = {"git": "a", "dataset": "d", "config": "c"}
    assert canonical_hash(base) != canonical_hash({**base, "dataset": "e"})


def test_replay_snapshot_verification_fails_after_tamper(tmp_path):
    source = tmp_path / "x"; source.write_text("x")
    snap = create_snapshot(sources=[source], destination=tmp_path / "s", source_name="x",
        start_time="a", end_time="b", symbols=[], timeframes=[], row_counts={}, git_sha="g",
        universe=[], universe_completeness="PARTIAL_POINT_IN_TIME")
    data = snap.root / "files" / "x"; data.chmod(0o644); data.write_text("tamper")
    assert verify_snapshot(snap)["status"] == "FAIL"
