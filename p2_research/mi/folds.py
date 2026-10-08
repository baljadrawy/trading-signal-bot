"""MI-ML development folds and K1 fold-boundary assertions (contract MI-C v1.0). Calendar arithmetic only - no data.

Eligibility of a TRAINING row for an evaluation fold starting at F (purge + embargo, both required):
    decision bar inside the training window, decision_time <= F - embargo(task), label_end(decision_time) <= F.
An EVALUATION row of fold [F, G) has its decision bar inside [F, G); if its label window ends after G it is censored.
"""
from __future__ import annotations

from . import timeline as TL

DEV_EVAL_START = TL.ms(2021, 1, 1)
DEV_END = TL.ms(2025, 1, 1)            # = HLE start
HLE_START, HLE_END = TL.ms(2025, 1, 1), TL.ms(2026, 6, 1)
N_FOLDS = 16
MIN_TRAIN_SPAN_MS = 730 * TL.D
TRAIN_START = {"S-MAJ": TL.ms(2018, 1, 1), "S-ALT": TL.ms(2019, 1, 1)}    # B1 resolution (owner, 2026-10-08)
EMBARGO_MS = {"T1": 1 * TL.D, "T2": 1 * TL.D, "T3": 7 * TL.D}
STEP_MS = {"T1": TL.TF_MS["4h"], "T2": TL.TF_MS["4h"], "T3": TL.D}
DECISION_BAR_MS = {"T1": TL.TF_MS["4h"], "T2": TL.TF_MS["4h"], "T3": TL.D}
# coverage precondition (certified ds-0928 manifest metadata, read 2026-10-08): first open of BTCUSDT / ETHUSDT
SMAJ_FIRST_DATA = TL.ms(2017, 8, 17)
MAX_FEATURE_LOOKBACK_MS = 61 * TL.D      # T3 sigma60 needs 61 closed 1d bars; every T1/T2 feature needs <= 5 days


class FoldAssertionError(AssertionError):
    pass


def quarter_starts(start: int, n: int) -> list:
    import datetime as dt
    d = dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc)
    out = []
    y, m = d.year, d.month
    for _ in range(n + 1):
        out.append(TL.ms(y, m, 1))
        m += 3
        if m > 12:
            m -= 12
            y += 1
    return out


def folds() -> list:
    q = quarter_starts(DEV_EVAL_START, N_FOLDS)
    return [(q[i], q[i + 1]) for i in range(N_FOLDS)]


def first_decision(task: str, window_start: int) -> int:
    return window_start + DECISION_BAR_MS[task]


def last_eligible_training(task: str, F: int, embargo: int | None = None) -> int:
    emb = EMBARGO_MS[task] if embargo is None else embargo
    t = F - (F % STEP_MS[task])
    while t > 0:
        if t <= F - emb and TL.label_end(task, t) <= F:
            return t
        t -= STEP_MS[task]
    raise FoldAssertionError("no eligible training row")


def eval_rows(task: str, F: int, G: int) -> dict:
    """Counts of evaluation decisions in [F, G) and how many are censored at G (label window crosses G)."""
    t, n, cens, last_ok = first_decision(task, F), 0, 0, None
    while t <= G:
        n += 1
        if TL.label_end(task, t) > G:
            cens += 1
        else:
            last_ok = t
        t += STEP_MS[task]
    return {"decisions": n, "censored": cens, "last_uncensored": last_ok,
            "max_label_end_included": TL.label_end(task, last_ok) if last_ok else None}


def assert_k1(task: str, scope: str) -> dict:
    fs = folds()
    rep = {"task": task, "scope": scope, "train_start": TRAIN_START[scope], "folds": []}
    # 6: exactly 16 contiguous, non-overlapping quarterly folds 2021-Q1 .. 2024-Q4
    if len(fs) != N_FOLDS or fs[0][0] != DEV_EVAL_START or fs[-1][1] != DEV_END:
        raise FoldAssertionError("fold calendar is not 16 quarters 2021-Q1..2024-Q4")
    for (a, b), (c, _) in zip(fs, fs[1:]):
        if b != c or not a < b:
            raise FoldAssertionError("folds not contiguous / ordered")
    if scope == "S-MAJ" and TRAIN_START[scope] - SMAJ_FIRST_DATA < MAX_FEATURE_LOOKBACK_MS:
        raise FoldAssertionError("insufficient certified lookback before the S-MAJ training start")
    for F, G in fs:
        first = first_decision(task, TRAIN_START[scope])
        last = last_eligible_training(task, F)
        span = last - first
        # 1: >= 730 days eligible training span (inferential scope only; S-ALT is exploratory)
        if scope == "S-MAJ" and span < MIN_TRAIN_SPAN_MS:
            raise FoldAssertionError(f"{task} fold {F}: training span {span / TL.D:.2f} d < 730 d")
        # 2: no training label reaches the fold
        if TL.label_end(task, last) > F:
            raise FoldAssertionError("training label crosses the fold start")
        ev = eval_rows(task, F, G)
        # 3: included evaluation labels end within the fold
        if ev["max_label_end_included"] is not None and ev["max_label_end_included"] > G:
            raise FoldAssertionError("evaluation label crosses the fold end")
        rep["folds"].append({"fold_start": F, "fold_end": G, "train_span_days": round(span / TL.D, 3),
                             "eval_decisions": ev["decisions"], "eval_censored": ev["censored"]})
    # 4: last dev fold labels end before the HLE; HLE labels end before 2026-06-01
    if eval_rows(task, *fs[-1])["max_label_end_included"] > HLE_START:
        raise FoldAssertionError("development labels reach the HLE")
    if eval_rows(task, HLE_START, HLE_END)["max_label_end_included"] > HLE_END:
        raise FoldAssertionError("HLE labels reach 2026-06-01")
    # 5: the final HLE model trains only on development rows with labels ending <= HLE start - embargo
    hle_last = last_eligible_training(task, HLE_START)
    if not (hle_last <= HLE_START - EMBARGO_MS[task] and TL.label_end(task, hle_last) <= HLE_START):
        raise FoldAssertionError("final HLE model training crosses the HLE boundary")
    rep["min_train_span_days"] = min(f["train_span_days"] for f in rep["folds"])
    return rep
