"""hr04-tsmom-v1: synthetic, deterministic tests for research/strategies/daily_tsmom.py.

SYNTHETIC ENGINEERING VALIDATION ONLY. Every price series here is generated in the test (seeded martingales,
regime-switching walks, hand-built paths). The tests prove timing, accounting, cost and statistics plumbing. They say
nothing about whether HR-04, HR-08 or HR-13 earn money on any market, and no result here is evidence for the
hypothesis register. Ledgers live in pytest temp directories with evidence class SYNTHETIC only."""
import ast
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
from research.mechanisms import signals as S  # noqa: E402
from research.mechanisms import simulate as M  # noqa: E402
from research.stats import sharpe_deflation as sd  # noqa: E402
from research.stats import variant_ledger as vl  # noqa: E402
from research.strategies import daily_tsmom as D  # noqa: E402

PKG = ROOT / "research" / "strategies"
SHA = "080c7df"                         # base commit of this module's branch (ledger code_sha field)
STRESS = C.CostModel(half_spread=0.0005, slippage=0.0005, label="synthetic-stress")
CONFIGS = {"hr04": D.HR04, "hr13": D.HR13, "hr08": D.HR08}


def _clock():
    return dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc)


# --- synthetic generators (prices only; nothing is read from disk) ---------------------------------------------------

def martingale(n, sigma, seed, k):
    """Driftless in price: p[t+1] = p[t] * (1 + e), E[e] = 0, so no causal rule has positive expected gross."""
    rng, out = random.Random(seed), {}
    for i in range(k):
        p = [100.0]
        for _ in range(n - 1):
            p.append(p[-1] * (1.0 + max(-0.5, sigma * rng.gauss(0, 1))))
        out[f"A{i}"] = p
    return out


def regime_walk(n, mu, sigma, stay, seed, k):
    """Persistent two-state drift (+mu / -mu, switch probability 1 - stay per day) plus noise: an injected trend."""
    rng, out = random.Random(seed), {}
    for i in range(k):
        p, s = [100.0], (1 if rng.random() < 0.5 else -1)
        for _ in range(n - 1):
            if rng.random() > stay:
                s = -s
            p.append(p[-1] * (1.0 + s * mu + sigma * rng.gauss(0, 1)))
        out[f"A{i}"] = p
    return out


def flat_noise(n, sigma, seed):
    """No trend at all: iid noise around a fixed level, so the 14-day return keeps crossing zero."""
    rng = random.Random(seed)
    return {"A0": [100.0 * math.exp(sigma * rng.gauss(0, 1)) for _ in range(n)]}


def run(closes, config, *, costs=C.BASELINE, start=20):
    return D.run_tsmom(closes, config, costs=costs, permission=M.SYNTHETIC, start=start)


def bh(closes, *, costs=C.BASELINE, start=20):
    return D.run_buy_and_hold(closes, costs=costs, permission=M.SYNTHETIC, start=start)


def psr(xs):
    m = sd.sample_moments(xs)
    return sd.probabilistic_sharpe_ratio(m.sr, m.n, m.skew, m.kurtosis)


# --- configuration --------------------------------------------------------------------------------------------------

def test_presets_match_the_register():
    assert (D.HR04.lookback, D.HR04.band, D.HR04.weighting, D.HR04.execution_lag) == (14, None, "equal", 1)
    assert D.HR13.band == 0.01 and replace(D.HR13, band=None) == D.HR04
    assert (D.HR08.weighting, D.HR08.vol_window) == ("inverse_vol", 20) and D.HR08.warmup == 20
    assert len({c.config_hash() for c in CONFIGS.values()}) == 3


@pytest.mark.parametrize("kw", [dict(lookback=0), dict(band=-0.01), dict(band=float("nan")), dict(execution_lag=2),
                                dict(weighting="kelly"), dict(rebalance="weekly"), dict(vol_window=20),
                                dict(lookback=True)])
def test_invalid_config_refused(kw):
    with pytest.raises(D.TSMOMError):
        replace(D.HR04, **kw)


def test_inverse_vol_needs_window_and_cap():
    with pytest.raises(D.TSMOMError):
        replace(D.HR08, vol_cap=None)
    with pytest.raises(D.TSMOMError):
        replace(D.HR08, vol_cap=0.0)


def test_config_fields_have_no_defaults():
    with pytest.raises(TypeError):
        D.TSMOMConfig(lookback=14)


# --- signal and band ------------------------------------------------------------------------------------------------

def test_signal_state_plain_and_band():
    assert D.signal_state(False, None, None) is False
    assert D.signal_state(False, 0.001, None) and not D.signal_state(True, 0.0, None)
    assert not D.signal_state(False, 0.005, 0.01) and D.signal_state(False, 0.011, 0.01)     # enter above +1 %
    assert D.signal_state(True, -0.005, 0.01) and not D.signal_state(True, -0.011, 0.01)     # exit below -1 %


def test_tsmom_signal_matches_the_register_rule_on_a_hand_built_path():
    up = [100.0 * 1.01 ** i for i in range(30)]
    path = up + [up[-1] * 0.99 ** i for i in range(1, 31)] + [up[-1] * 0.99 ** 30 * 1.01 ** i for i in range(1, 31)]
    r = run({"A0": path}, replace(D.HR04, execution_lag=0), start=14)
    held = [bool(w) for w in r.weights]
    for j, t in enumerate(range(14, len(path) - 1)):
        assert held[j] == (path[t] / path[t - 14] - 1 > 0)


# --- costs and turnover ---------------------------------------------------------------------------------------------

def test_turnover_counts_entries_and_exits_on_a_hand_built_path():
    up = [100.0 * 1.01 ** i for i in range(30)]
    path = up + [up[-1] * 0.99 ** i for i in range(1, 31)] + [up[-1] * 0.99 ** 30 * 1.01 ** i for i in range(1, 31)]
    for cfg in (D.HR04, replace(D.HR04, execution_lag=0)):
        r = run({"A0": path}, cfg, start=14)
        assert (r.entries, r.exits) == (2, 1)
        assert r.total_turnover == pytest.approx(3.0)            # in, out, in (single asset: drift never trades)
        assert r.total_cost == pytest.approx(3.0 * C.BASELINE.per_side)
        assert sum(1 for c in r.cost if c > 0) == 3
        assert all(n == pytest.approx(g - c) for g, c, n in zip(r.gross, r.cost, r.net))
        assert r.tracker_flat_cost_total == pytest.approx(1.5 * C.TRACKER_FLAT_ROUNDTRIP)


def test_constant_signal_portfolio_pays_only_initial_entry_costs():
    rates = (0.002, 0.004, 0.006, 0.008)
    u = {f"A{i}": [100.0 * (1 + g) ** t for t in range(200)] for i, g in enumerate(rates)}
    for costs in (C.BASELINE, STRESS):
        for cfg in (replace(D.HR04, rebalance="on_signal_change"), replace(D.HR13, rebalance="on_signal_change")):
            r = run(u, cfg, costs=costs)
            assert (r.entries, r.exits) == (4, 0)
            assert r.total_turnover == pytest.approx(1.0) and r.total_cost == pytest.approx(costs.per_side)
            assert [i for i, c in enumerate(r.cost) if c > 0] == [1]             # lag 1: one entry day only
        one = run({"A0": u["A0"]}, D.HR04, costs=costs)                          # daily rebalance, single asset
        assert one.total_turnover == pytest.approx(1.0) and one.total_cost == pytest.approx(costs.per_side)
        b = bh(u, costs=costs)
        assert b.total_turnover == pytest.approx(1.0) and b.total_cost == pytest.approx(costs.per_side)
        assert [i for i, c in enumerate(b.cost) if c > 0] == [0]


def test_daily_rebalance_pays_for_drift_and_on_change_does_not():
    rates = (0.002, 0.008)
    u = {f"A{i}": [100.0 * (1 + g) ** t for t in range(200)] for i, g in enumerate(rates)}
    daily, hold = run(u, D.HR04), run(u, replace(D.HR04, rebalance="on_signal_change"))
    assert daily.total_turnover > hold.total_turnover == pytest.approx(1.0)
    assert all(t > 0 for t in daily.turnover[2:])                               # drift is traded back every day


def test_higher_costs_never_increase_net_and_never_change_gross():
    u = martingale(400, 0.03, 7, 4)
    for cfg in CONFIGS.values():
        a, b = run(u, cfg), run(u, cfg, costs=STRESS)
        assert a.gross == b.gross and a.turnover == b.turnover
        assert all(y <= x + 1e-15 for x, y in zip(a.net, b.net))
        assert b.total_cost == pytest.approx(a.total_turnover * STRESS.per_side)


def test_discounted_fee_is_refused_by_the_reused_cost_model():
    with pytest.raises(C.CostModelError):
        C.CostModel(fee_per_side=0.00075)
    with pytest.raises(M.SimulationError):
        D.run_tsmom(martingale(60, 0.03, 0, 2), D.HR04, costs=0.001, permission=M.SYNTHETIC)


def test_hysteresis_band_reduces_turnover_on_a_noisy_series():
    plain = band = 0.0
    for seed in range(6):
        u = flat_noise(500, 0.02, seed)
        a, b = run(u, D.HR04), run(u, D.HR13)
        assert b.total_turnover < a.total_turnover and b.total_cost < a.total_cost
        plain, band = plain + a.total_turnover, band + b.total_turnover
    assert 1 - band / plain >= 0.15                                             # pooled reduction, synthetic only


# --- HR-08 sizing ---------------------------------------------------------------------------------------------------

def test_inverse_vol_weights_favour_the_lower_vol_asset_and_never_lever():
    w = D.inverse_vol_weights({"lo", "hi"}, {"lo": 0.01, "hi": 0.04}, 2, 2.0)
    assert w["lo"] > w["hi"] and sum(w.values()) == pytest.approx(1.0)        # 1.0 + 0.3125 scaled back to 1
    w = D.inverse_vol_weights({"lo"}, {"lo": 0.01, "hi": 0.04, "mid": 0.02}, 3, 2.0)
    assert w == {"lo": pytest.approx(2.0 / 3)}                                  # capped at 2 x (1/N)
    assert D.inverse_vol_weights({"a"}, {"a": None, "b": 0.02}, 2, 2.0) == {}
    rng = random.Random(3)
    for _ in range(200):
        n = rng.randint(1, 8)
        vols = {f"A{i}": rng.uniform(0.001, 0.1) for i in range(n)}
        w = D.inverse_vol_weights(set(rng.sample(sorted(vols), rng.randint(0, n))), vols, n, rng.uniform(0.5, 4))
        assert sum(w.values()) <= 1 + 1e-12 and all(x > 0 for x in w.values())


def test_hr08_portfolio_weights_sum_at_most_one_and_favour_low_vol():
    rng = random.Random(11)
    lo, hi = [100.0], [100.0]
    for _ in range(299):
        lo.append(lo[-1] * (1.004 + 0.005 * rng.gauss(0, 1)))
        hi.append(hi[-1] * (1.006 + 0.04 * rng.gauss(0, 1)))
    r = run({"LO": lo, "HI": hi}, D.HR08)
    both = [w for w in r.weights if len(w) == 2]
    assert both and all(w["LO"] > w["HI"] for w in both)
    assert all(sum(w.values()) <= 1 + 1e-9 for w in r.weights)


# --- timing / look-ahead --------------------------------------------------------------------------------------------

def test_changing_future_prices_never_changes_past_positions():
    """Property test over seeds, cut points, configs, lags and rebalance policies."""
    rng = random.Random(2026)
    for case in range(12):
        u = martingale(160, 0.03, 100 + case, 3)
        t0 = rng.randint(30, 150)
        v = {a: s[:t0 + 1] + [x * rng.uniform(0.3, 3.0) for x in s[t0 + 1:]] for a, s in u.items()}
        for cfg in CONFIGS.values():
            for lag in (0, 1):
                for reb in D.REBALANCES:
                    c = replace(cfg, execution_lag=lag, rebalance=reb)
                    a, b = run(u, c, start=20), run(v, c, start=20)
                    k = t0 - 20 + 1                                  # steps t = 20 .. t0 are decided by data <= t0
                    assert a.weights[:k] == b.weights[:k] and a.turnover[:k] == b.turnover[:k]
                    assert a.gross[:k - 1] == b.gross[:k - 1]        # step t0's return needs close t0 + 1


def test_execution_lag_one_trades_the_previous_close_decision():
    u = martingale(200, 0.03, 5, 1)
    now, nxt = run(u, replace(D.HR04, execution_lag=0)), run(u, D.HR04)
    assert nxt.weights[0] == {} and [bool(w) for w in nxt.weights[1:]] == [bool(w) for w in now.weights[:-1]]


def test_parity_with_the_s4_accountant_for_lag_zero_daily_equal_weight():
    u = martingale(300, 0.03, 9, 5)
    ours = run(u, replace(D.HR04, execution_lag=0), start=14)
    ref = M.run(u, S.TimeSeriesMomentum(lookback=14, long_only=True, vol_window=None, target_daily_vol=None),
                costs=C.BASELINE, permission=M.SYNTHETIC, start=14, allow_short=False)
    assert ours.days == ref.days
    for x, y in ((ours.gross, ref.gross), (ours.cost, ref.cost), (ours.net, ref.net), (ours.turnover, ref.turnover)):
        assert x == pytest.approx(y, abs=1e-15)


# --- governance -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("perm", [None, "synthetic",
                                  M.DatasetPermission("binance-vision", False, True, "none"),
                                  M.DatasetPermission("binance-vision", True, False, "none"),
                                  M.DatasetPermission("market", True, True, "x", synthetic=True)])
def test_refuses_without_a_valid_data_permission(perm):
    u = martingale(60, 0.03, 0, 2)
    with pytest.raises(M.SimulationError):
        D.run_tsmom(u, D.HR04, costs=C.BASELINE, permission=perm)
    with pytest.raises(M.SimulationError):
        D.run_buy_and_hold(u, costs=C.BASELINE, permission=perm, start=20)


def test_results_are_labelled_non_confirmatory():
    u = martingale(120, 0.03, 1, 3)
    s = D.summary(run(u, D.HR04), bh(u))
    assert s["evidence_class"] == "SYNTHETIC_OR_EXPLORATORY_NOT_CONFIRMATORY"
    assert {"mean_net", "psr_net_vs_0", "mean_active_net", "max_drawdown", "benchmark_max_drawdown"} <= set(s)


def test_max_drawdown():
    assert D.max_drawdown([0.1, -0.5, 0.2]) == pytest.approx(0.5)
    assert D.max_drawdown([0.01] * 5) == 0.0


# --- engineering validation with the R2 statistics (SYNTHETIC ONLY, NOT EVIDENCE) ------------------------------------

def _evaluate(led, family, vid, closes, cfg, window_label):
    """Register BEFORE computing (roadmap §5.4), then attach the one result."""
    led.register_variant(variant_id=vid, family=family, hypothesis_ref="HR-04/08/13 synthetic engineering validation",
                         data_window_label=window_label, metric="per_obs_net_return", code_sha=SHA,
                         evidence_class=vl.SYNTHETIC, config_hash=cfg.config_hash(), cost_label=C.BASELINE.label)
    r = run(closes, cfg)
    m = sd.sample_moments(r.net)
    led.record_result(variant_id=vid, n=m.n, mean=m.mean, sd=m.sd, skew=m.skew, kurtosis=m.kurtosis)
    return r


def test_driftless_random_walk_yields_no_significant_net_edge(tmp_path):
    """The engine must not manufacture edge: on a price martingale no variant's net PSR or DSR reaches 0.95."""
    led = vl.VariantLedger(tmp_path / "synthetic-ledger.jsonl", clock=_clock)
    fam, seeds, gross, net = "syn.hr04-martingale", range(16), [], []
    for seed in seeds:
        u, per_seed = martingale(750, 0.03, seed, 5), []
        for name, cfg in CONFIGS.items():
            r = _evaluate(led, fam, f"syn-rw-{name}-s{seed}", u, cfg, f"synthetic:martingale:seed={seed}")
            per_seed.append(r.mean_gross)
            net.extend(r.net)
            assert psr(r.net) < 0.95
            assert r.mean_net < r.mean_gross                              # costs always bite
        gross.append(statistics.mean(per_seed))                           # seeds are independent, configs are not
    assert led.trials(fam) == 48 and all(r["evidence_class"] == vl.SYNTHETIC for r in led.records()
                                         if r["event"] == "register")
    var = led.trial_sr_variance(fam)
    assert max(led.deflated_sharpe(v, var).dsr for v in led.variants(fam)) < 0.95
    assert psr(net) < 0.95                                                 # pooled across seeds and variants
    se = statistics.stdev(gross) / math.sqrt(len(gross))
    assert abs(statistics.mean(gross)) < 3 * se                           # gross ~ 0 across independent seeds


def test_injected_persistent_trend_is_detected_in_gross_returns(tmp_path):
    """SYNTHETIC ENGINEERING VALIDATION, NOT EVIDENCE: with a persistent drift injected by the generator the long/cash
    rule earns positive gross returns. This checks the plumbing can see a trend that is known to exist."""
    led = vl.VariantLedger(tmp_path / "synthetic-ledger.jsonl", clock=_clock)
    fam, pooled = "syn.hr04-regime-trend", []
    led.register_variant(variant_id="syn-trend-abandoned", family=fam, hypothesis_ref="abandoned synthetic trial",
                         data_window_label="synthetic:none", metric="per_obs_net_return", code_sha=SHA)
    for seed in range(8):
        u = regime_walk(750, 0.004, 0.02, 0.98, seed, 5)
        b = bh(u)
        for name, cfg in CONFIGS.items():
            r = _evaluate(led, fam, f"syn-trend-{name}-s{seed}", u, cfg, f"synthetic:regime:seed={seed}")
            assert r.mean_gross > 0 and r.days == b.days
            pooled.extend(r.gross)
    assert psr(pooled) > 0.95
    assert led.trials(fam) == 25 and len(led.trial_srs(fam)) == 24      # the abandoned trial still counts in N
    evaluated = [v for v, x in led.variants(fam).items() if x["result"] is not None]
    best = max(evaluated, key=lambda v: led.deflated_sharpe(v).sr)
    d = led.deflated_sharpe(best)
    assert d.n_trials == 25 and d.sr0 > 0
    res = led.variants(fam)[best]["result"]
    assert d.dsr < sd.probabilistic_sharpe_ratio(d.sr, d.n, res["skew"], res["kurtosis"])   # deflation bites


# --- package hygiene ------------------------------------------------------------------------------------------------

ALLOWED = {"__future__", "collections.abc", "dataclasses", "hashlib", "json", "math", "statistics"}


def test_package_is_stdlib_only_and_has_no_io():
    for p in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(a.name in ALLOWED for a in node.names), p.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module in ALLOWED or node.module.startswith("research."), (p.name, node.module)
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("open", "eval", "exec"):
                pytest.fail(f"{p.name}: {node.func.id}()")


def test_no_production_module_imports_the_package():
    for d in ("analyzer", "signal_engine", "trade_tracker", "telegram", "scanner", "shared"):
        for p in (ROOT / d).rglob("*.py"):
            assert "research.strategies" not in p.read_text(encoding="utf-8", errors="ignore"), p
