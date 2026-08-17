import math

import numpy as np

from research.entry_hypothesis_review import classify_path, half_life, variance_ratio


def test_stationary_process_has_finite_half_life_and_mean_reversion_classification():
    rng = np.random.default_rng(7)
    values = [100.0]
    for shock in rng.normal(0, 0.3, 1000):
        values.append(100 + 0.75 * (values[-1] - 100) + shock)
    assert 1 < half_life(values) < 10
    assert variance_ratio(values, 5) < 1
    assert classify_path(0.3, 0.7, half_life(values)) == 'mean_reverting'


def test_random_walk_is_not_mislabeled_mean_reverting_without_joint_evidence():
    rng = np.random.default_rng(9)
    prices = np.exp(np.cumsum(rng.normal(0, 0.01, 1000)) + math.log(100))
    assert classify_path(0.5, variance_ratio(prices, 5), half_life(prices)) == 'unconfirmed'
