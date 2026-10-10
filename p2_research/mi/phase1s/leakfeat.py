"""AM-4-A leak-feature construction and surrogate designs (Stage A development code).

Feature-level leak truth class ("the label enters one feature with weight w"), fixed w_f = 2 (owner directive):
    binary (T1 / T2):  x_i     = w_f (2 y_i - 1) + e_i,       e_i    iid N(0, 1)
    T3:                x_{i,k} = w_f 1[k = y_i] + e_{i,k},    e_{i,k} iid N(0, 1), K = 6 alternatives
The Gaussian draws use the frozen generator's ``normals`` (read-only import) so that seeds are reproducible with the
same inverse-CDF mapping as the rest of Phase 1S. w_f is a fixed design constant here; it is not tunable by any
argument of the public functions.

Designs (no intercept, no baseline column; the baseline enters as a fixed offset):
    binary rows:  [x_i, z_{1,i}, ..., z_{m,i}]      offset_i   = logit(b_i)
    T3 rows:      C[i][k] = [x_{i,k}, z_{1,k,i}, ..., z_{m,k,i}]   logb[i][k] = log b_{i,k}
"""
from __future__ import annotations

import math

from . import gen as G
from .firth import EPS

W_F = 2.0
K_T3 = 6


def leak_feature_binary(rng, y: list) -> list:
    e = G.normals(rng, len(y))
    return [W_F * (2 * yy - 1) + ee for yy, ee in zip(y, e)]


def leak_feature_multi(rng, y: list, K: int = K_T3) -> list:
    n = len(y)
    e = G.normals(rng, n * K)
    return [[W_F * (1.0 if k == yy else 0.0) + e[i * K + k] for k in range(K)] for i, yy in enumerate(y)]


def logit_clipped(p: float) -> float:
    p = EPS if p < EPS else (1.0 - EPS if p > 1.0 - EPS else p)
    return math.log(p / (1.0 - p))


def log_clipped(p: float) -> float:
    return math.log(EPS if p < EPS else p)


def binary_design(x: list, noise_sets: list) -> list:
    """noise_sets: list of m series (each length n). Returns rows [x_i, z_1i, ..., z_mi]."""
    return [[x[i]] + [z[i] for z in noise_sets] for i in range(len(x))]


def binary_offset(b: list) -> list:
    return [logit_clipped(v) for v in b]


def t3_design(x_rows: list, noise_sets: list) -> list:
    """noise_sets: list of m sets, each a list of K series (length n). Returns C[i][k] = [x_ik, z_1ki, ..., z_mki]."""
    n, K = len(x_rows), len(x_rows[0])
    return [[[x_rows[i][k]] + [z[k][i] for z in noise_sets] for k in range(K)] for i in range(n)]


def t3_offset(b_rows: list) -> list:
    return [[log_clipped(v) for v in row] for row in b_rows]
