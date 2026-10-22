"""P1 / P2 production reference (lab/PARITY_TEST_SPEC.md): what the lab adapter must reproduce.

P1: 10,035 seeded synthetic poll paths x 3 brackets x 5 vol cells x the 15m / 4h / 1d expiry policies through
production `step_barrier`. The decision sequence is pinned by digest. A change here is a production exit-logic change
and needs the same re-review as a P5 pin change.
P2: break-even and trailing boundaries at exactly the level, one tick either side, and a gap through each.

Static, synthetic, deterministic. Nothing runs the lab.
"""
import collections
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_parity_corpus as P  # noqa: E402

from shared.triple_barrier import TripleBarrierConfig, TripleBarrierState, step_barrier  # noqa: E402

PINNED_DIGEST = "9129e6aa52c7d4a651dff8ebd3728523f54f9b7e81a9bc71c5bf024f811ef53a"
EXIT_REASONS = {"T3", "stop_loss", "break_even", "trailing_stop", "T1_expired_24h", "no_T1_expired_12h",
                "no_T1_expired_24h", "no_T1_expired_72h", "expired_48h", "expired_96h", "expired_240h"}
TICK = 1e-8


@pytest.fixture(scope="module")
def rows():
    return P.decisions()


def test_p1_corpus_size_and_digest_pinned(rows):
    assert len(rows) >= 10_000
    assert P.digest(rows) == PINNED_DIGEST, "production exit decisions changed: re-review the lab parity suite"


def test_p1_corpus_covers_every_exit_kind_and_policy(rows):
    assert {r["exit_reason"] for r in rows} == EXIT_REASONS
    by_tf = collections.defaultdict(set)
    for r in rows:
        by_tf[r["tf"]].add(r["exit_reason"])
    assert all(len(v) >= 6 for v in by_tf.values()), dict(by_tf)


def test_p1_corpus_is_deterministic():
    a, b = P.decisions(n_paths=450), P.decisions(n_paths=450)
    assert a == b


def test_p1_t1_stall_label_is_fixed_text_for_every_policy(rows):
    # Production labels the T1-stall exit 'T1_expired_24h' whatever the policy's t1 hours (48 h for 4h, 120 h for 1d).
    # The lab must reproduce the label verbatim; correcting it would be a production change.
    long_stalls = [r for r in rows if r["exit_reason"] == "T1_expired_24h" and r["tf"] in ("4h", "1d")]
    assert long_stalls and all(float(r["duration_h"]) >= 48.0 for r in long_stalls)
    assert not any(r["exit_reason"].startswith("T1_expired_") and r["exit_reason"] != "T1_expired_24h" for r in rows)


def _cfg():
    return TripleBarrierConfig(symbol="SYNUSDT", entry=100.0, target_1=101.0, target_2=102.0, target_3=103.0,
                               stop_loss=99.0)


def _after_t1():
    cfg, st = _cfg(), TripleBarrierState(peak=100.0)
    assert step_barrier(cfg, st, 101.0, 100.5, 100.9, 0.1) is None      # exactly T1 counts as reached
    assert st.highest_target == 1
    return cfg, st


def test_p2_exactly_at_t1_reaches_it_one_tick_below_does_not():
    cfg, st = _cfg(), TripleBarrierState(peak=100.0)
    step_barrier(cfg, st, 101.0 - TICK, 100.5, 100.9, 0.1)
    assert st.highest_target == 0
    _after_t1()


@pytest.mark.parametrize("delta,closes", [(0.0, True), (-TICK, True), (+TICK, False)])
def test_p2_break_even_boundary(delta, closes):
    cfg, st = _after_t1()
    be = cfg.net_break_even_stop()
    res = step_barrier(cfg, st, 100.9, be + delta, 100.9, 0.1)
    assert (res is not None) is closes
    if closes:
        assert res.exit_reason == "break_even" and res.target_reached == 1


def _after_t2(peak=102.5):
    cfg, st = _cfg(), TripleBarrierState(peak=100.0)
    assert step_barrier(cfg, st, peak, 101.5, 102.0, 0.1) is None
    assert st.highest_target == 2
    return cfg, st


@pytest.mark.parametrize("delta,closes", [(0.0, True), (-TICK, True), (+TICK, False)])
def test_p2_trailing_boundary(delta, closes):
    cfg, st = _after_t2()
    trail = max(cfg.target_1, st.peak * (1 - cfg.trail_stop_pct / 100))
    res = step_barrier(cfg, st, st.peak, trail + delta, st.peak, 0.1)
    assert (res is not None) is closes
    if closes:
        assert res.exit_reason == "trailing_stop" and res.target_reached == 2


def test_p2_gap_through_break_even_fills_at_observation_not_at_stop():
    cfg, st = _after_t1()
    res = step_barrier(cfg, st, 100.0, 95.0, 95.5, 0.1, stop_observation_price=95.5)
    assert res.exit_reason == "break_even" and res.exit_price < 100.0
    cfg2, st2 = _after_t1()
    res_plain = step_barrier(cfg2, st2, 100.0, 95.0, 95.5, 0.1)
    assert res.exit_price < res_plain.exit_price                     # observation below the stop is used


def test_p2_gap_through_trailing_fills_at_observation():
    cfg, st = _after_t2()
    res = step_barrier(cfg, st, st.peak, 90.0, 91.0, 0.1, stop_observation_price=91.0)
    assert res.exit_reason == "trailing_stop"
    assert res.exit_price <= 91.0


def test_p2_same_poll_stop_and_target_stop_wins():
    cfg, st = _cfg(), TripleBarrierState(peak=100.0)
    res = step_barrier(cfg, st, 103.5, 98.0, 100.0, 0.1)
    assert res.exit_reason == "stop_loss" and res.target_reached == 0


@pytest.mark.parametrize("delta,closes", [(0.0, True), (+TICK, False)])
def test_p2_same_poll_t1_then_dip_to_break_even(delta, closes):
    # step 6: T1 reached and the new break-even stop touched within ONE poll (the prior stop is still the SL)
    cfg, st = _cfg(), TripleBarrierState(peak=100.0)
    be = cfg.net_break_even_stop()
    res = step_barrier(cfg, st, 101.0, be + delta, 100.9, 0.1)
    assert (res is not None) is closes
    if closes:
        assert res.exit_reason == "break_even"


@pytest.mark.parametrize("delta,closes", [(0.0, True), (+TICK, False)])
def test_p2_same_poll_t2_then_dip_to_trailing(delta, closes):
    cfg, st = _cfg(), TripleBarrierState(peak=100.0)
    peak = 102.5
    trail = max(cfg.target_1, peak * (1 - cfg.trail_stop_pct / 100))
    res = step_barrier(cfg, st, peak, trail + delta, 101.5, 0.1)
    assert (res is not None) is closes
    if closes:
        assert res.exit_reason == "trailing_stop"


def test_p2_prior_stop_outranks_a_same_poll_target_upgrade():
    # the stop in force at the start of the poll wins even if the same poll also reaches T2 (step 1 priority)
    cfg, st = _after_t1()
    be = cfg.net_break_even_stop()
    res = step_barrier(cfg, st, 102.5, be, 102.0, 0.1)
    assert res.exit_reason == "break_even" and res.target_reached == 1
