"""Probabilistic Sharpe Ratio (PSR) and Deflated Sharpe Ratio (DSR). Standard library only.

References:
* Bailey, D. H. and Lopez de Prado, M. (2012), "The Sharpe Ratio Efficient Frontier", J. of Risk 15(2): PSR.
* Bailey, D. H. and Lopez de Prado, M. (2014), "The Deflated Sharpe Ratio", J. of Portfolio Management 40(5): DSR.

Units: every Sharpe ratio here is PER OBSERVATION (not annualized): sr = mean / sd of the same return series that
gives n, skew and kurtosis. ``trial_sr_variance`` must be in the same per-observation units (an annualized variance
V_ann corresponds to V_ann / periods_per_year). Kurtosis is NON-excess (normal = 3).

The formulas match the ad-hoc ``psr`` in research/skill_application/scripts/run_dsr_d2.py and the external
walk-forward-validation ``overfit_detector.deflated_sharpe_ratio``; unlike the latter, the expected maximum Sharpe
ratio under the null is scaled by the standard deviation of the trial Sharpe ratios, as in the 2014 paper (eq. 2).
"""
from dataclasses import dataclass
from math import e, isfinite, sqrt
from statistics import NormalDist

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def _finite(name, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v):
        raise ValueError(f"{name} must be a finite number")
    return float(v)


def _count(name, v, minimum):
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ValueError(f"{name} must be an int >= {minimum}")
    return v


@dataclass(frozen=True)
class Moments:
    n: int
    mean: float
    sd: float            # sample standard deviation (ddof = 1)
    skew: float          # population (biased) skewness, scipy.stats.skew default
    kurtosis: float      # population (biased) NON-excess kurtosis, scipy.stats.kurtosis(fisher=False) default

    @property
    def sr(self) -> float:
        return sharpe_ratio(self.mean, self.sd)


def sample_moments(xs) -> Moments:
    """Moments of a return series in the convention the PSR/DSR papers use (skew and non-excess kurtosis)."""
    xs = [_finite("observation", x) for x in xs]
    n = len(xs)
    if n < 2:
        raise ValueError("need at least 2 observations")
    mu = sum(xs) / n
    m2 = sum((x - mu) ** 2 for x in xs) / n
    if m2 <= 0:
        raise ValueError("series has zero variance")
    m3 = sum((x - mu) ** 3 for x in xs) / n
    m4 = sum((x - mu) ** 4 for x in xs) / n
    sd = sqrt(m2 * n / (n - 1))
    return Moments(n, mu, sd, m3 / m2 ** 1.5, m4 / m2 ** 2)


def sharpe_ratio(mean, sd) -> float:
    mean, sd = _finite("mean", mean), _finite("sd", sd)
    if sd <= 0:
        raise ValueError("sd must be > 0")
    return mean / sd


def sr_standard_error(sr, n, skew=0.0, kurtosis=3.0) -> float:
    """Standard error of the estimated Sharpe ratio under non-normal returns (Mertens 2002; Bailey & LdP 2012)."""
    sr, skew, kurtosis = _finite("sr", sr), _finite("skew", skew), _finite("kurtosis", kurtosis)
    n = _count("n", n, 2)
    v = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    if v <= 0:
        raise ValueError("non-positive Sharpe-ratio variance for these moments")
    return sqrt(v / (n - 1))


def probabilistic_sharpe_ratio(sr, n, skew=0.0, kurtosis=3.0, sr_benchmark=0.0) -> float:
    """PSR(SR*) = Phi((SR - SR*) * sqrt(n - 1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2)): P(true SR > SR*)."""
    sr_benchmark = _finite("sr_benchmark", sr_benchmark)
    return _N.cdf((_finite("sr", sr) - sr_benchmark) / sr_standard_error(sr, n, skew, kurtosis))


def expected_max_sr(n_trials, trial_sr_variance) -> float:
    """E[max of n_trials Sharpe ratios] when every true SR is 0 (DSR paper eq. 2, False Strategy theorem):
    sqrt(V) * ((1 - gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e))). Zero for a single trial."""
    n_trials = _count("n_trials", n_trials, 1)
    v = _finite("trial_sr_variance", trial_sr_variance)
    if v < 0:
        raise ValueError("trial_sr_variance must be >= 0")
    if n_trials == 1:
        return 0.0
    z1 = _N.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1.0 - 1.0 / (n_trials * e))
    return sqrt(v) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


@dataclass(frozen=True)
class DeflatedSharpe:
    dsr: float               # P(true SR > expected max SR of N null trials); compare with 0.95 (roadmap §1.4 b)
    sr: float
    sr0: float               # deflated benchmark = expected_max_sr(n_trials, trial_sr_variance)
    n_trials: int
    trial_sr_variance: float
    n: int


def deflated_sharpe_ratio(sr, n, n_trials, trial_sr_variance, skew=0.0, kurtosis=3.0) -> DeflatedSharpe:
    """DSR = PSR(SR0) with SR0 the expected maximum Sharpe ratio of ``n_trials`` independent null trials.

    ``n_trials`` must count EVERY variant tried in the family, including abandoned ones (roadmap §5.4)."""
    sr0 = expected_max_sr(n_trials, trial_sr_variance)
    p = probabilistic_sharpe_ratio(sr, n, skew, kurtosis, sr_benchmark=sr0)
    return DeflatedSharpe(p, float(sr), sr0, n_trials, float(trial_sr_variance), n)
