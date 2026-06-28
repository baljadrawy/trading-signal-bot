"""Known-answer tests for the Conditional Null-A generator + distribution-match gate.

Central invariant of the whole chain: the comparison reference (the null) must NOT be
biased or weaker than the strategy. A naive null (random across all market conditions)
must FAIL the match gate when the strategy's signals cluster in a regime/volatility/
session; a CONDITIONAL null matched on those buckets must PASS.
"""
import sys; sys.path.insert(0, '.')
import numpy as np

from research.null_a.buckets import Bucketer, time_of_day_bucket
from research.null_a.conditional_null import generate_conditional_null, signal_profile
from research.null_a.quality import null_quality
from research.null_a.evidence_store import SignalSnapshot


# ---------------- bucketing ----------------
def test_bucketer_terciles():
    b = Bucketer.fit([float(x) for x in range(100)], n=3)
    assert b.assign(5) == 0 and b.assign(50) == 1 and b.assign(95) == 2


def test_time_of_day_bucket():
    # 03:00 UTC -> asia, 10:00 -> europe, 15:00 -> us
    assert time_of_day_bucket(3 * 3600) == "asia"
    assert time_of_day_bucket(10 * 3600) == "europe"
    assert time_of_day_bucket(15 * 3600) == "us"


# ---------------- conditional matching ----------------
def _cand(sym, vol, liq, hp, regime, fut, ts=0):
    return {"symbol": sym, "volatility": vol, "liquidity": liq, "holding_period": hp,
            "regime": regime, "timestamp": ts, "future_return": fut}


def test_conditional_null_matches_buckets():
    rng = np.random.default_rng(0)
    # real signals: all HIGH volatility, "bull"
    real = [{"symbol": "BTCUSDT", "volatility": 0.9, "liquidity": 0.8, "holding_period": 10,
             "regime": "bull", "timestamp": 15 * 3600} for _ in range(40)]
    # pool: a MIX of high/low vol; high-vol candidates are "bull", low-vol are "bear"
    pool = []
    for i in range(400):
        hv = i % 2 == 0
        pool.append(_cand("BTCUSDT", 0.9 if hv else 0.1, 0.8, 10,
                          "bull" if hv else "bear", 0.0 if hv else 0.5,
                          ts=15 * 3600 if hv else 3 * 3600))
    nullret, sel, unmatched = generate_conditional_null(
        real, pool, match_on=["volatility", "regime"], rng=rng, return_selected=True)
    assert unmatched == 0
    # every selected candidate must share the real bucket profile (high-vol, bull)
    assert len(nullret) == 40
    assert all(s["regime"] == "bull" and s["volatility"] > 0.5 for s in sel)


# ---------------- the mandatory distribution-match gate ----------------
def test_null_distribution_matches_real():
    rng = np.random.default_rng(1)
    # strategy clusters in HIGH volatility + long holding
    real = [{"volatility": rng.normal(0.9, 0.03), "holding_period": rng.normal(20, 1),
             "regime": "bull"} for _ in range(200)]
    # NAIVE null: drawn from the whole market (low vol, short holding, mixed regime)
    naive = [{"volatility": rng.normal(0.3, 0.1), "holding_period": rng.normal(5, 1),
              "regime": rng.choice(["bull", "bear", "flat"])} for _ in range(200)]
    q_naive = null_quality(real, naive)
    assert q_naive["quality"] == "FAILED"          # biased/weaker null -> rejected

    # CONDITIONAL null: matched on vol/holding/regime
    cond = [{"volatility": rng.normal(0.9, 0.03), "holding_period": rng.normal(20, 1),
             "regime": "bull"} for _ in range(200)]
    q_cond = null_quality(real, cond)
    assert q_cond["quality"] == "PASS"


# ---------------- evidence store snapshot ----------------
def test_signal_snapshot_roundtrip(tmp_path):
    snap = SignalSnapshot(
        signal_id="s1", timestamp=1750000000.0, symbol="BTCUSDT", timeframe="15m",
        ohlcv_window=np.zeros((50, 5)), feature_vector={"rsi": 30.0, "vol": 0.9},
        market_regime="bull", confidence=0.82, signal_score=3.1, entry_decision="long")
    d = snap.to_cold_dict()
    assert "ohlcv_window" not in d and d["feature_vector"]["rsi"] == 30.0
    assert d["signal_id"] == "s1" and d["market_regime"] == "bull"
