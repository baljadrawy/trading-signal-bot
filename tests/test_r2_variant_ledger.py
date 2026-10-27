"""R2: synthetic, deterministic tests for research/stats (no data, database, network or production access)."""
import ast
import datetime as dt
import json
import pathlib
import random
import sys
from fractions import Fraction
from math import sqrt
from statistics import NormalDist

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.stats import alpha_budget as ab  # noqa: E402
from research.stats import familywise as fw  # noqa: E402
from research.stats import sharpe_deflation as sd  # noqa: E402
from research.stats import variant_ledger as vl  # noqa: E402

PKG = ROOT / "research" / "stats"
SHA = "cce58c3"
_PHI = NormalDist().cdf


def _clock():
    return dt.datetime(2026, 10, 26, 9, 41, 37, tzinfo=dt.timezone.utc)


def _register(led, vid, family="fam-a", **kw):
    args = dict(variant_id=vid, family=family, hypothesis_ref="H-synthetic", data_window_label="synthetic-window",
                metric="per_obs_net_return", code_sha=SHA)
    args.update(kw)
    return led.register_variant(**args)


# --- PSR / DSR ---------------------------------------------------------------------------------------------------

def test_dsr_reproduces_bailey_lopez_de_prado_2014_worked_example():
    # DSR paper, numerical example: annualized SR 2.5, T = 1250 daily obs, N = 100 trials, annualized variance of
    # trial SRs 0.5, skew -3, kurtosis 10 -> SR0 ~ 0.1132 (per day) and DSR ~ 0.9004.
    res = sd.deflated_sharpe_ratio(2.5 / sqrt(250), 1250, 100, 0.5 / 250, skew=-3, kurtosis=10)
    assert res.sr0 == pytest.approx(0.1132, abs=1e-4)
    assert res.dsr == pytest.approx(0.9004, abs=1e-4)
    assert res.dsr < 0.95                       # fails the roadmap's DSR >= 0.95 bar despite an SR of 2.5


def test_psr_matches_formula_by_hand():
    sr, n, g3, g4 = 0.1, 100, -1.0, 6.0
    se = sqrt((1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) / (n - 1))
    assert sd.probabilistic_sharpe_ratio(sr, n, g3, g4) == pytest.approx(_PHI(sr / se), abs=1e-12)
    assert sd.probabilistic_sharpe_ratio(sr, n, g3, g4) == pytest.approx(0.827246, abs=1e-6)
    # normal returns: SE = sqrt((1 + SR^2 / 2) / (n - 1))
    assert sd.probabilistic_sharpe_ratio(0.2, 50) == pytest.approx(_PHI(0.2 * sqrt(49) / sqrt(1.02)), abs=1e-12)
    assert sd.probabilistic_sharpe_ratio(0.0, 50) == pytest.approx(0.5)
    # PSR against its own SR is one half; against a higher benchmark it falls below one half
    assert sd.probabilistic_sharpe_ratio(0.2, 50, sr_benchmark=0.2) == pytest.approx(0.5)
    assert sd.probabilistic_sharpe_ratio(0.2, 50, sr_benchmark=0.3) < 0.5


def test_expected_max_sr_reference_values():
    assert sd.expected_max_sr(1, 1.0) == 0.0
    z = NormalDist().inv_cdf
    g = sd.EULER_GAMMA
    want = (1 - g) * z(1 - 1 / 1000) + g * z(1 - 1 / (1000 * 2.718281828459045))
    assert sd.expected_max_sr(1000, 1.0) == pytest.approx(want, abs=1e-12)
    assert sd.expected_max_sr(1000, 1.0) == pytest.approx(3.2551, abs=1e-4)
    assert sd.expected_max_sr(1000, 4.0) == pytest.approx(2 * sd.expected_max_sr(1000, 1.0))   # scales with sqrt(V)


def test_dsr_decreases_as_trials_increase_and_equals_psr_for_one_trial():
    sr, n, var = 0.12, 500, 0.003
    values = [sd.deflated_sharpe_ratio(sr, n, k, var).dsr for k in (1, 2, 5, 10, 50, 100, 1000, 10000)]
    assert all(a > b for a, b in zip(values, values[1:]))
    assert values[0] == pytest.approx(sd.probabilistic_sharpe_ratio(sr, n))


def test_sample_moments_on_synthetic_series():
    rng = random.Random(11)
    xs = [rng.gauss(0.001, 0.02) for _ in range(4000)]
    m = sd.sample_moments(xs)
    assert m.n == 4000 and m.mean == pytest.approx(sum(xs) / 4000)
    assert m.skew == pytest.approx(0.0, abs=0.15) and m.kurtosis == pytest.approx(3.0, abs=0.3)
    scipy_stats = pytest.importorskip("scipy.stats")
    assert m.skew == pytest.approx(float(scipy_stats.skew(xs)), rel=1e-9)
    assert m.kurtosis == pytest.approx(float(scipy_stats.kurtosis(xs, fisher=False)), rel=1e-9)


@pytest.mark.parametrize("bad", [dict(sr=float("nan"), n=10), dict(sr=0.1, n=1), dict(sr=0.1, n=True)])
def test_psr_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        sd.probabilistic_sharpe_ratio(**bad)


# --- Holm and Romano-Wolf -----------------------------------------------------------------------------------------

def test_holm_known_example():
    ps = [0.01, 0.04, 0.03, 0.005]
    # sorted 0.005*4 = 0.02, 0.01*3 = 0.03, 0.03*2 = 0.06, 0.04*1 = 0.04 -> monotone 0.06
    assert fw.holm_adjust(ps) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert fw.holm_reject(ps, 0.05) == [True, False, False, True]
    assert fw.holm_adjust([0.6, 0.9]) == [1.0, 1.0]                     # capped at 1


def test_holm_matches_statsmodels_when_available():
    mt = pytest.importorskip("statsmodels.stats.multitest")
    rng = random.Random(3)
    ps = [rng.random() ** 3 for _ in range(12)]
    want = mt.multipletests(ps, alpha=0.05, method="holm")[1]
    assert fw.holm_adjust(ps) == pytest.approx(list(want), abs=1e-12)


def _paired_series(seed, means, t_len=250):
    rng = random.Random(seed)
    common = [rng.gauss(0, 1) for _ in range(t_len)]                   # shared factor: dependent hypotheses
    return [[mu + 0.6 * c + rng.gauss(0, 1) for c in common] for mu in means]


def test_romano_wolf_reproducible_with_seed_and_detects_only_the_real_effect():
    data = _paired_series(5, [0.4, 0.0, 0.0])
    a = fw.romano_wolf_stepdown(data, n_boot=400, seed=20261026)
    b = fw.romano_wolf_stepdown(data, n_boot=400, seed=20261026)
    c = fw.romano_wolf_stepdown(data, n_boot=400, seed=7)
    assert a == b
    assert a.adjusted_p != c.adjusted_p
    assert a.rejected(0.05) == [True, False, False]
    assert all(0 < p <= 1 for p in a.adjusted_p)
    # step-down monotonicity: a larger t-statistic never has a larger adjusted p-value
    order = sorted(range(3), key=lambda k: -a.t_stats[k])
    assert [a.adjusted_p[k] for k in order] == sorted(a.adjusted_p)


def test_romano_wolf_block_bootstrap_and_validation():
    data = _paired_series(9, [0.3, 0.05])
    res = fw.romano_wolf_stepdown(data, n_boot=200, seed=1, block_length=7)
    assert res.block_length == 7 and len(res.adjusted_p) == 2
    with pytest.raises(ValueError):
        fw.romano_wolf_stepdown(data, n_boot=200, seed=None)
    with pytest.raises(ValueError):
        fw.romano_wolf_stepdown([[1.0, 2.0, 3.0], [1.0, 2.0]], seed=1)


def test_romano_wolf_controls_familywise_error_under_the_global_null():
    # 3 null hypotheses x 60 synthetic replications: family-wise false rejections at 0.10 stay near or below 0.10
    false = 0
    for rep in range(60):
        res = fw.romano_wolf_stepdown(_paired_series(1000 + rep, [0.0, 0.0, 0.0], t_len=120), n_boot=199, seed=rep)
        false += any(res.rejected(0.10))
    assert false / 60 <= 0.22


# --- alpha budget -------------------------------------------------------------------------------------------------

def test_governed_budget_defaults_and_exhaustion():
    bud = ab.governed_admission_budget()
    assert bud.per_test == Fraction(1, 240) and bud.total == Fraction(1, 20) and bud.remaining_tests == 12
    for i in range(12):
        assert bud.spend(f"admission-{i}") == Fraction(1, 240)
    assert bud.remaining == 0
    with pytest.raises(ab.AlphaBudgetExhausted):
        bud.spend("admission-12")


def test_governed_constants_equal_the_power_package():
    from research.power import ladder_power as lp
    assert ab.GOVERNED_ALPHA_PER_ADMISSION == lp.ALPHA_SCENARIOS["A33_EQUAL_1_240_CAL_1_276"].alpha_main
    assert ab.GOVERNED_PROGRAM_ADMISSIONS == lp.PROGRAM_MAX_ADMISSIONS
    assert ab.GOVERNED_PROGRAM_FWER == lp.PROGRAM_FWER
    assert ab.GOVERNED_ALPHA_PER_ADMISSION * ab.GOVERNED_PROGRAM_ADMISSIONS == ab.GOVERNED_PROGRAM_FWER


def test_exploratory_family_budget_and_no_reuse():
    bud = ab.exploratory_family_budget("S4")
    assert bud.per_test == Fraction(1, 60) and bud.remaining_tests == 3       # 0.05 / 3
    bud.spend("H1")
    with pytest.raises(ab.AlphaReuseRefused):
        bud.spend("H1")
    bud.spend("H2")
    bud.spend("H3")
    with pytest.raises(ab.AlphaBudgetExhausted):
        bud.spend("H4")
    replay = ab.exploratory_family_budget("S4", spent_labels=("H1", "H2"))
    assert replay.remaining_tests == 1
    with pytest.raises(ValueError):
        ab.AlphaBudget("x", 0.05, Fraction(1, 60))                           # floats refused: exact arithmetic only


# --- variant ledger -----------------------------------------------------------------------------------------------

def test_ledger_records_fields_to_the_minute_and_counts_per_family(tmp_path):
    led = vl.VariantLedger(tmp_path / "ledger.jsonl", clock=_clock)
    rec = _register(led, "v1")
    assert rec["recorded_at"] == "2026-10-26T09:41Z" and rec["seq"] == 0 and rec["prev"] == vl.GENESIS
    led.record_result(variant_id="v1", n=500, mean=0.001, sd=0.02, skew=-0.5, kurtosis=4.0)
    _register(led, "v2")                                                       # abandoned: never evaluated
    _register(led, "w1", family="fam-b")
    assert led.family_counts() == {"fam-a": 2, "fam-b": 1}
    assert led.trials("fam-a") == 2 and led.trials("nobody") == 0
    view = led.variants("fam-a")
    assert set(view) == {"v1", "v2"} and view["v2"]["result"] is None
    for line in (tmp_path / "ledger.jsonl").read_text().splitlines():
        assert set(json.loads(line)) >= {"seq", "prev", "hash", "event", "recorded_at", "variant_id"}


def test_ledger_has_no_edit_or_delete_and_refuses_rewrites_through_the_api(tmp_path):
    led = vl.VariantLedger(tmp_path / "l.jsonl", clock=_clock)
    for name in ("update", "edit", "delete", "remove", "amend", "replace", "rewrite"):
        assert not hasattr(led, name)
    _register(led, "v1")
    with pytest.raises(vl.LedgerRefused):
        _register(led, "v1", hypothesis_ref="H-other")
    with pytest.raises(vl.LedgerRefused):
        led.record_result(variant_id="ghost", n=10, mean=0.1, sd=1.0, skew=0.0, kurtosis=3.0)
    led.record_result(variant_id="v1", n=10, mean=0.1, sd=1.0, skew=0.0, kurtosis=3.0)
    with pytest.raises(vl.LedgerRefused):
        led.record_result(variant_id="v1", n=10, mean=0.9, sd=1.0, skew=0.0, kurtosis=3.0)


def test_ledger_detects_in_place_edit_deletion_and_reorder(tmp_path):
    path = tmp_path / "l.jsonl"
    led = vl.VariantLedger(path, clock=_clock)
    for i in range(3):
        _register(led, f"v{i}")
        led.record_result(variant_id=f"v{i}", n=100, mean=0.01 * i, sd=1.0, skew=0.0, kurtosis=3.0)
    original = path.read_text()
    lines = original.splitlines(keepends=True)

    path.write_text(original.replace('"mean":0.02', '"mean":0.5'))             # edit a result
    with pytest.raises(vl.LedgerTamper):
        led.records()
    with pytest.raises(vl.LedgerTamper):
        _register(led, "v9")                                                   # appends refuse a broken chain

    edited = json.loads(lines[1])
    edited["mean"] = 0.5
    edited["hash"] = vl._digest(edited)                                        # even with a recomputed hash
    path.write_text(lines[0] + vl._canonical(edited).decode() + "\n" + "".join(lines[2:]))
    with pytest.raises(vl.LedgerTamper):
        led.records()

    path.write_text("".join(lines[:2] + lines[3:]))                            # delete a middle line
    with pytest.raises(vl.LedgerTamper):
        led.records()

    path.write_text("".join([lines[1], lines[0]] + lines[2:]))                 # reorder
    with pytest.raises(vl.LedgerTamper):
        led.records()

    path.write_text(original[:-5])                                             # torn tail
    with pytest.raises(vl.LedgerTamper):
        led.records()

    path.write_text(original)
    assert len(led.records()) == 6


def test_ledger_tail_truncation_detected_against_recorded_head(tmp_path):
    path = tmp_path / "l.jsonl"
    led = vl.VariantLedger(path, clock=_clock)
    _register(led, "v1")
    _register(led, "v2")
    head = led.head()
    assert head[0] == 2
    _register(led, "v3")
    assert led.verify(expected_head=head)[0] == 3                              # growth is fine
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(lines[:1]))                                        # drop the last two lines
    led.verify()                                                               # chain alone looks valid ...
    with pytest.raises(vl.LedgerTamper):
        led.verify(expected_head=head)                                         # ... the recorded head catches it


def test_non_synthetic_evidence_requires_authorization(tmp_path):
    led = vl.VariantLedger(tmp_path / "l.jsonl", clock=_clock)
    with pytest.raises(vl.LedgerRefused):
        _register(led, "v1", evidence_class="GOVERNED")
    with pytest.raises(ValueError):
        _register(led, "v1", code_sha="not-a-sha")
    assert led.records() == []


def test_ledger_dsr_uses_every_registered_variant_including_abandoned(tmp_path):
    led = vl.VariantLedger(tmp_path / "l.jsonl", clock=_clock)
    rng = random.Random(42)
    for i in range(5):
        _register(led, f"v{i}")
        m = sd.sample_moments([rng.gauss(0.0005 * i, 0.01) for _ in range(300)])
        led.record_result(variant_id=f"v{i}", n=m.n, mean=m.mean, sd=m.sd, skew=m.skew, kurtosis=m.kurtosis)
    before = led.deflated_sharpe("v4")
    assert before.n_trials == 5
    assert before.trial_sr_variance == pytest.approx(sd.sample_moments(led.trial_srs("fam-a")).sd ** 2)
    for i in range(20):
        _register(led, f"abandoned-{i}")                                       # tried, never evaluated
    after = led.deflated_sharpe("v4")
    assert after.n_trials == 25 and after.dsr < before.dsr
    assert led.deflated_sharpe("v4", trial_sr_variance=0.0).dsr == pytest.approx(
        sd.probabilistic_sharpe_ratio(after.sr, 300, *_moments_of(led, "v4")))


def _moments_of(led, vid):
    res = led.variants()[vid]["result"]
    return res["skew"], res["kurtosis"]


# --- purity ---------------------------------------------------------------------------------------------------------

def test_package_imports_only_stdlib_and_research():
    allowed = {"dataclasses", "datetime", "fcntl", "fractions", "hashlib", "json", "math", "os", "random", "re",
               "statistics"}
    for py in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert all(n in allowed or n == "research" for n in names), (py.name, names)
