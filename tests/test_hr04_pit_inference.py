"""hr04-pit-v1 / inference / hr04-summary-v1: synthetic, deterministic tests.

SYNTHETIC ENGINEERING VALIDATION ONLY. Every panel here is generated in the test (seeded random walks with random
listing and delisting days, hand-built paths). The tests prove point-in-time timing, delisting accounting, benchmark
turnover, inference plumbing and the evidence-label guard. They say nothing about any market and no result here is
evidence for the hypothesis register. Ledgers live in pytest temp directories with evidence class SYNTHETIC only."""
import datetime as dt
import math
import pathlib
import random
import statistics
import sys
from dataclasses import replace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.mechanisms import costs as C  # noqa: E402
from research.mechanisms import simulate as M  # noqa: E402
from research.stats import inference as I  # noqa: E402
from research.stats import variant_ledger as vl  # noqa: E402
from research.strategies import daily_tsmom as D  # noqa: E402
from research.strategies import pit_universe as P  # noqa: E402
from research.strategies import result_summary as R  # noqa: E402

SHA = "b77dc7c"
COSTS = C.CostModel(half_spread=0.0004, slippage=0.0005, label="synthetic-tier-b")
RULE = P.UniverseRule(top_n=4, volume_window=10, min_history=20, statistic="sum")
CFG = {"hr04": D.HR04, "hr13": D.HR13, "hr08": D.HR08,
       "hr04-osc": replace(D.HR04, rebalance="on_signal_change")}


def random_panel(seed, n_days=260, n_assets=9, perturb_after=None, base=None):
    """Seeded ragged panel: random listing/delisting days, heavy-ish tailed returns, random quote volumes.
    With ``base`` and ``perturb_after``: same listing structure as ``base``, values after day ``perturb_after``
    replaced by fresh random values (future-perturbation)."""
    rng = random.Random(seed)
    series = {}
    for k in range(n_assets):
        name = f"SYN{k}"
        if base is not None:
            b = base.series[name]
            first, length = b.first, len(b.close)
        else:
            first = 0 if k < 3 else rng.randrange(0, n_days // 2)
            last = n_days - 1 if rng.random() < 0.6 else rng.randrange(first + 25, n_days)
            length = last - first + 1
        p, closes, vols = 100.0, [], []
        for i in range(length):
            t = first + i
            if base is not None and t <= perturb_after:
                closes.append(b.close[i])
                vols.append(b.quote_volume[i])
                p = b.close[i]
                continue
            p *= 1.0 + rng.gauss(0.0005, 0.03) * (2.0 if rng.random() < 0.05 else 1.0)
            p = max(p, 1e-3)
            closes.append(p)
            vols.append(rng.uniform(1e5, 1e7) * (1 + k % 3))
        tradable = base.series[name].final_price_tradable if base is not None else rng.random() < 0.7
        series[name] = P.AssetSeries(first, tuple(closes), tuple(vols), tradable)
    return P.Panel(n_days, series)


def run(panel, cfg=D.HR04, start=25, **kw):
    return P.run_pit_tsmom(panel, cfg, RULE, costs=COSTS, permission=M.SYNTHETIC, start=start, **kw)


# --- point-in-time universe ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(6))
def test_membership_uses_only_data_up_to_t(seed):
    panel = random_panel(seed)
    for t in range(panel.n_days):
        assert P.membership(panel, t, RULE) == P.membership(panel.truncated(t), t, RULE)


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("name", sorted(CFG))
def test_no_look_ahead_future_perturbation(seed, name):
    panel = random_panel(seed)
    start = 25
    base = run(panel, CFG[name], start)
    for cut in (60, 140, 220):
        alt = run(random_panel(1000 + seed, perturb_after=cut, base=panel), CFG[name], start)
        k_max = cut - start                       # steps t <= cut trade on data <= t
        assert alt.weights[:k_max + 1] == base.weights[:k_max + 1]
        assert alt.turnover[:k_max + 1] == base.turnover[:k_max + 1]
        assert alt.gross[:k_max] == base.gross[:k_max]  # step t's gross uses close t + 1 <= cut
        assert alt.member_counts[:k_max + 1] == base.member_counts[:k_max + 1]


@pytest.mark.parametrize("seed", range(4))
def test_assets_appear_and_disappear_without_survivorship(seed):
    panel = random_panel(seed)
    r = run(panel)
    delisted = [a for a, s in panel.series.items() if s.last < panel.n_days - 1]
    late = [a for a, s in panel.series.items() if s.first > 0]
    assert delisted and late                      # the panel really is ragged
    for k, w in enumerate(r.weights):
        t = r.start + k
        for a in w:
            s = panel.series[a]
            assert s.has(t) and s.last > t        # never held over a step without a next close
            assert t - s.first + 1 >= RULE.min_history
        assert len(P.membership(panel, t, RULE)) <= RULE.top_n
    assert r.forced_exits >= 0 and r.exits == r.forced_exits + r.universe_exits


def _delist_panel(tradable=True):
    """A: rising, high volume, delisted at day 40. B: falling, low volume, never held."""
    n = 60
    a = P.AssetSeries(0, tuple(100 * 1.01 ** i for i in range(41)), tuple([1e7] * 41), tradable)
    b = P.AssetSeries(0, tuple(100 * 0.99 ** i for i in range(n)), tuple([1e5] * n))
    return P.Panel(n, {"A": a, "B": b})


def test_delisting_forced_exit_pays_full_costs():
    rule = P.UniverseRule(top_n=1, volume_window=5, min_history=15, statistic="sum")
    panel = _delist_panel()
    r = P.run_pit_tsmom(panel, D.HR04, rule, costs=COSTS, permission=M.SYNTHETIC, start=15)
    k = 40 - r.start
    assert r.weights[k - 1] == {"A": 1.0} and r.weights[k] == {}
    assert r.forced_exits == 1 and r.universe_exits == 0
    assert r.turnover[k] == pytest.approx(1.0)
    assert r.cost[k] == pytest.approx(COSTS.per_side)
    assert all(w == {} for w in r.weights[k:])
    assert r.evidence_class == "SYNTHETIC"


def test_delisting_without_final_price_stress_haircut():
    rule = P.UniverseRule(top_n=1, volume_window=5, min_history=15, statistic="sum")
    panel = _delist_panel(tradable=False)
    r = P.run_pit_tsmom(panel, D.HR04, rule, costs=COSTS, permission=M.SYNTHETIC, start=15, delist_haircut=1.0)
    k = 40 - r.start
    assert r.gross[k] == pytest.approx(-1.0) and r.turnover[k] == pytest.approx(0.0)
    assert r.delist_loss == pytest.approx(1.0)
    half = P.run_pit_tsmom(panel, D.HR04, rule, costs=COSTS, permission=M.SYNTHETIC, start=15, delist_haircut=0.5)
    assert half.gross[k] == pytest.approx(-0.5) and half.turnover[k] == pytest.approx(0.5)


def test_permission_and_rule_validation():
    panel = random_panel(0)
    with pytest.raises(M.SimulationError):
        P.run_pit_tsmom(panel, D.HR04, RULE, costs=COSTS, permission=None, start=25)
    with pytest.raises(M.SimulationError):
        P.run_pit_tsmom(panel, D.HR04, RULE, costs=COSTS,
                        permission=M.DatasetPermission("vendor", False, True, "none"), start=25)
    with pytest.raises(D.TSMOMError):
        P.UniverseRule(top_n=3, volume_window=30, min_history=10, statistic="sum")
    with pytest.raises(M.SimulationError):
        P.Panel(10, {"X": P.AssetSeries(5, (1.0,) * 6, (1.0,) * 6)})   # extends past the panel end


# --- benchmark -------------------------------------------------------------------------------------------------------

def _dated(panel):
    d0 = dt.date(2021, 1, 1)
    return P.Panel(panel.n_days, panel.series, tuple(d0 + dt.timedelta(days=i) for i in range(panel.n_days)))


def test_month_start_indices():
    dates = tuple(dt.date(2021, 1, 30) + dt.timedelta(days=i) for i in range(40))
    assert P.month_start_indices(dates) == frozenset({0, 2, 30})


@pytest.mark.parametrize("seed", range(3))
def test_monthly_benchmark_pays_its_own_turnover(seed):
    panel = _dated(random_panel(seed))
    months = P.month_start_indices(panel.dates)
    start = 25
    bm = P.run_pit_benchmark(panel, RULE, rebalance_at=months, costs=COSTS, permission=M.SYNTHETIC, start=start,
                             execution_lag=1)
    once = P.run_pit_benchmark(panel, RULE, rebalance_at={start}, costs=COSTS, permission=M.SYNTHETIC, start=start,
                               execution_lag=1)
    assert bm.total_turnover > once.total_turnover > 0
    assert bm.total_cost == pytest.approx(COSTS.per_side * bm.total_turnover)
    for k, to in enumerate(bm.turnover):
        t = bm.start + k
        delist_step = any(a in bm.weights[k - 1] and panel.series[a].last == t for a in panel.series) if k else False
        if to > 1e-12:
            assert (t - 1) in months or delist_step          # trades only one close after a rebalance day
    for w in bm.weights:                                      # equal weight at most 1/N of members
        assert sum(w.values()) <= 1 + 1e-9
    s = P.run_pit_tsmom(panel, D.HR04, RULE, costs=COSTS, permission=M.SYNTHETIC, start=start)
    assert len(D.active_returns(s, bm)) == s.days


# --- inference -------------------------------------------------------------------------------------------------------

def _ar1(n, phi, mu, seed):
    rng, x, out = random.Random(seed), 0.0, []
    for _ in range(n):
        x = phi * x + rng.gauss(0, 0.01)
        out.append(mu + x)
    return out


def test_hac_equals_plain_se_at_lag_zero():
    xs = _ar1(300, 0.3, 0.001, 1)
    assert I.newey_west_se(xs, 0) == pytest.approx(I.plain_se(xs), rel=1e-12)
    assert I.newey_west_se(xs, 0, ddof=0) == pytest.approx(statistics.pstdev(xs) / math.sqrt(len(xs)), rel=1e-12)
    assert I.hac_t(xs, 0) == pytest.approx(statistics.mean(xs) / I.plain_se(xs), rel=1e-12)
    assert I.newey_west_se(xs, 7) > I.newey_west_se(xs, 0)    # positive autocorrelation widens the SE
    assert I.REGISTER_HAC_LAG == 7 and I.newey_west_lag_rule(1000) == 6
    with pytest.raises(ValueError):
        I.newey_west_se(xs[:5], 5)


def test_bootstrap_reproducible_with_seed():
    xs = _ar1(200, 0.2, 0.0005, 2)
    a = I.stationary_bootstrap_ci(xs, "mean", mean_block=10, n_resamples=200, seed=7)
    b = I.stationary_bootstrap_ci(xs, "mean", mean_block=10, n_resamples=200, seed=7)
    c = I.stationary_bootstrap_ci(xs, "mean", mean_block=10, n_resamples=200, seed=8)
    assert a == b and (a.lower, a.upper) != (c.lower, c.upper)
    s = I.stationary_bootstrap_ci(xs, "sharpe", mean_block=10, n_resamples=200, seed=7)
    assert s.lower < s.estimate < s.upper
    idx = I.stationary_bootstrap_indices(50, 5, random.Random(0))
    assert len(idx) == 50 and all(0 <= i < 50 for i in idx)


def test_bootstrap_ci_covers_true_mean_near_nominal():
    mu, hits, reps = 0.001, 0, 80
    for r in range(reps):
        xs = _ar1(150, 0.3, mu, 100 + r)
        hits += I.stationary_bootstrap_ci(xs, "mean", mean_block=8, n_resamples=150, level=0.9, seed=r).covers(mu)
    assert 0.75 <= hits / reps <= 0.99            # nominal 0.90; percentile CIs under-cover slightly in small n


# --- summary and guard -----------------------------------------------------------------------------------------------

def _clock():
    return dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)


def test_summary_synthetic_end_to_end(tmp_path):
    panel = _dated(random_panel(3))
    led, fam = vl.VariantLedger(tmp_path / "ledger.jsonl", clock=_clock), "syn.pit"
    results = {}
    for name in ("hr04", "hr13", "hr08"):
        led.register_variant(variant_id=f"syn-pit-{name}", family=fam, hypothesis_ref="synthetic engineering only",
                             data_window_label="synthetic:pit:seed=3", metric="per_obs_net_return", code_sha=SHA,
                             config_hash=CFG[name].config_hash(), cost_label=COSTS.label)
        results[name] = run(panel, CFG[name])
    bm = P.run_pit_benchmark(panel, RULE, rebalance_at=P.month_start_indices(panel.dates), costs=COSTS,
                             permission=M.SYNTHETIC, start=25, execution_lag=1)
    s = R.build_summary(results["hr04"], benchmark=bm, evidence_class="SYNTHETIC", permission=M.SYNTHETIC,
                        n_trials=3, trial_sr_variance=1e-3, seed=11, ledger=led, family=fam, n_resamples=100)
    assert s.evidence_class == "SYNTHETIC" and s.not_a_profitability_claim and s.authorization_ref is None
    assert s.dsr_n_trials == 3 and 0 <= s.dsr <= 1 and s.net.hac_lag == 7
    assert s.trades == results["hr04"].entries and s.turnover_per_day > 0
    assert s.benchmark_total_turnover == pytest.approx(bm.total_turnover) and s.active is not None
    assert s.net.bootstrap_mean.lower <= s.net_per_day <= s.net.bootstrap_mean.upper
    with pytest.raises(R.SummaryRefused):                     # DSR N must be the full family count
        R.build_summary(results["hr04"], evidence_class="SYNTHETIC", permission=M.SYNTHETIC, n_trials=1,
                        trial_sr_variance=1e-3, seed=1, ledger=led, family=fam, n_resamples=50)


def test_guard_refuses_non_synthetic_labels_without_authorization():
    r = run(random_panel(1))
    real = M.DatasetPermission("licensed-vendor-fixture", True, True, "OD-DF-1 fixture")
    for label in ("EXPLORATORY_NOT_CONFIRMATORY", "CONFIRMATORY", "REAL", ""):
        with pytest.raises(R.SummaryRefused):
            R.build_summary(r, evidence_class=label, permission=M.SYNTHETIC, n_trials=1, trial_sr_variance=0.0,
                            seed=1, n_resamples=50)
    with pytest.raises(R.SummaryRefused):
        R.authorize_label("EXPLORATORY_NOT_CONFIRMATORY", real, None)
    with pytest.raises(R.SummaryRefused):
        R.authorize_label("SYNTHETIC", real)                 # real data cannot pose as synthetic
    with pytest.raises(R.SummaryRefused):
        R.authorize_label("CONFIRMATORY", real, "OD-X")       # D1/D2 HOLD
    with pytest.raises(R.SummaryRefused):
        R.authorize_label("EXPLORATORY_NOT_CONFIRMATORY", M.DatasetPermission("v", False, True, "x"), "OD-X")
    assert R.authorize_label("EXPLORATORY_NOT_CONFIRMATORY", real, "OD-DF-1 fixture") == R.EXPLORATORY
    with pytest.raises(R.SummaryRefused):                    # a synthetic-run result cannot be relabelled
        R.build_summary(r, evidence_class="EXPLORATORY_NOT_CONFIRMATORY", permission=real,
                        authorization_ref="OD-DF-1 fixture", n_trials=1, trial_sr_variance=0.0, seed=1,
                        n_resamples=50)
