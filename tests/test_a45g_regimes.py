"""a45g-rg-v1: synthetic, deterministic tests for research/evaluation/regimes.py.

They check the regime *engine* (no look-ahead, prefix invariance, closed-candle and as-of rules, hysteresis
turnover, recovery of a known synthetic regime path). They say nothing about returns in any regime."""
import sys

import pytest

sys.path.insert(0, ".")
from research.evaluation import net_eval as N  # noqa: E402
from research.evaluation import regimes as G  # noqa: E402
from research.evaluation import synthetic as Y  # noqa: E402

CLF = G.TrendVolRegime(trend_lookback=24, vol_window=24, vol_rank_window=120, high_vol_quantile=0.75,
                       confirm_bars=3)
MARKET = {"bull_calm": (0.002, 0.008), "bear_wild": (-0.002, 0.024)}


def market(n=3000, seed=1, stay=0.995):
    return Y.regime_switching_market(n, MARKET, stay_prob=stay, seed=seed)


def test_parameters_have_no_defaults_and_are_validated():
    with pytest.raises(TypeError):
        G.TrendVolRegime()  # noqa
    for bad in (dict(trend_lookback=0), dict(vol_window=1), dict(confirm_bars=0), dict(high_vol_quantile=1.0),
                dict(vol_rank_window=True)):
        kw = dict(trend_lookback=5, vol_window=5, vol_rank_window=5, high_vol_quantile=0.5, confirm_bars=1)
        kw.update(bad)
        with pytest.raises(G.RegimeError):
            G.TrendVolRegime(**kw)


def test_warm_up_bars_are_unlabelled():
    closes, _ = market(400)
    raw = CLF.raw_labels(closes)
    assert all(x is None for x in raw[:CLF.warmup]) and all(x is not None for x in raw[CLF.warmup:])


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_prefix_invariance(seed):
    closes, _ = market(900, seed=seed)
    full = CLF.labels(closes)
    for k in (CLF.warmup, CLF.warmup + 1, 300, 517, 899):
        assert CLF.labels(closes[:k]) == full[:k]


def test_changing_the_future_never_changes_past_labels():
    closes, _ = market(900, seed=4)
    base = CLF.labels(closes)
    t = 600
    shocked = closes[:t + 1] + [c * (0.5 if i % 2 else 3.0) for i, c in enumerate(closes[t + 1:])]
    assert CLF.labels(shocked)[:t + 1] == base[:t + 1]


def test_closed_bars_excludes_the_forming_bar_and_bad_order():
    ts, cs = [1.0, 2.0, 3.0, 4.0], [10.0, 11.0, 12.0, 13.0]
    assert G.closed_bars(ts, cs, 3.0) == ([1.0, 2.0], [10.0, 11.0])
    assert G.closed_bars(ts, cs, 3.5) == ([1.0, 2.0, 3.0], [10.0, 11.0, 12.0])
    for bad_ts in ([1.0, 1.0, 2.0, 3.0], [2.0, 1.0, 3.0, 4.0]):
        with pytest.raises(G.RegimeError):
            G.closed_bars(bad_ts, cs, 10.0)
    with pytest.raises(G.RegimeError):
        G.closed_bars(ts, [10.0, 0.0, 1.0, 2.0], 10.0)


def test_as_of_join_never_uses_the_bar_closing_at_the_decision():
    ts, labels = [10.0, 20.0, 30.0], ["a", "b", "c"]
    assert G.label_as_of(ts, labels, 10.0) is None
    assert G.label_as_of(ts, labels, 20.0) == "a"
    assert G.label_as_of(ts, labels, 20.5) == "b"
    assert G.label_as_of(ts, labels, 99.0) == "c"


def test_confirmation_with_one_bar_equals_the_raw_labels():
    closes, _ = market(800)
    one = G.TrendVolRegime(24, 24, 120, 0.75, 1)
    assert one.labels(closes) == one.raw_labels(closes)


@pytest.mark.parametrize("seed", range(5))
def test_hysteresis_never_increases_label_switching(seed):
    closes, _ = market(1500, seed=seed)
    counts = [G.switch_count(G.TrendVolRegime(24, 24, 120, 0.75, k).labels(closes)) for k in (1, 2, 4, 8)]
    assert counts[1] <= counts[0] and counts[2] <= counts[0] and counts[3] <= counts[0]
    assert counts[-1] < counts[0]


def test_known_synthetic_regimes_are_recovered_better_than_chance():
    closes, truth = market(4000, seed=7)
    labels = CLF.labels(closes)
    pairs = [(t, l) for t, l in zip(truth, labels) if l is not None]
    trend_hit = sum((t == "bull_calm") == (G.trend_of(l) == "up") for t, l in pairs) / len(pairs)
    hv = {name: [G.vol_of(l) == "high_vol" for t, l in pairs if t == name] for name in MARKET}
    assert trend_hit > 0.7
    assert sum(hv["bear_wild"]) / len(hv["bear_wild"]) > sum(hv["bull_calm"]) / len(hv["bull_calm"])


def test_constant_series_is_flat_and_not_high_volatility():
    labels = CLF.labels([100.0] * 300)
    assert set(labels[CLF.warmup + CLF.confirm_bars:]) == {"flat|normal_vol"}


def test_attach_regimes_sets_the_as_of_label_on_trades():
    closes, _ = market(600, seed=2)
    times = [3600.0 * (i + 1) for i in range(len(closes))]
    labels = CLF.labels(closes)
    trades = Y.null_entry_trades(closes, times, n_trades=50, horizon=3, seed=1, half_spread=0.0, slippage=0.0)
    tagged = G.attach_regimes(trades, times, labels, part="trend")
    for t, u in zip(trades, tagged):
        assert u.regime == G.trend_of(G.label_as_of(times, labels, t.entry_ts))
        assert (u.gross, u.fee, u.trade_id) == (t.gross, t.fee, t.trade_id)
    s = N.stratified(tagged, key=lambda t: t.regime, permission=N.DatasetPermission(
        "synthetic", True, True, "generated in tests", synthetic=True), n_resamples=100)
    assert sum(v.n_filled for v in s.values()) == 50
    with pytest.raises(G.RegimeError):
        G.attach_regimes(trades, times, labels, part="bogus")
