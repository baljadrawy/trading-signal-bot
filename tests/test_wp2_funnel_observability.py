"""WP2 funnel observability (WP-B01 data side; R6.a, R6.c, R1.f; WP-IR-01/-02/-04/-05).

Synthetic fixtures only; the only files read are the modules under test.
"""
import copy
import dataclasses
import inspect
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

import shared.funnel_records as fr
from shared.funnel_recorder import FunnelRecorder, instrumented, parse_enabled
from shared.funnel_records import (CandidateRef, EligibilityResult, RankingInput, RejectionRecord,
                                   StageCount, capacity_full_record, check_conservation,
                                   freshness_record, legacy_alphabetical_cut_record,
                                   rank_below_cap_record, resource_cap_record, validate_reason_code)
from shared.signal_identity import TIMEFRAME_MS, freshness_at

T0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
DECISION = T0 + int(timedelta(minutes=5).total_seconds() * 1000)
CYCLE = "cycle-test-1"
COMMON = dict(cycle_id=CYCLE, decision_time=DECISION, rule_ref="rule.test.v1",
              snapshot_hash="snap-h", config_hash="cfg-h")

# Transcribed from OPPORTUNITY_FUNNEL.md section 8.2 plus the WP-IR-01 "Taxonomy v1 additions".
DOCUMENTED = {
    "F0": {"snapshot_stale", "snapshot_incomplete", "clock_offset_exceeded"},
    "F1": {"status_not_trading", "quote_not_approved", "stable_or_pegged", "leveraged_product",
           "filters_missing", "min_order_infeasible", "listing_age_insufficient", "owner_excluded",
           "symbol_unsupported"},
    "F2": {"volume_below_floor", "volume_missing", "move_below_floor", "book_stale", "spread_invalid",
           "spread_above_limit", "depth_insufficient", "book_unavailable"},
    "F3": {"regime_stale", "regime_unavailable", "regime_veto:<series>", "regime_unknown_used"},
    "F4": {"history_insufficient", "data_quality", "bar_not_closed", "bar_stale", "no_setup",
           "duplicate_setup", "setup_conflict", "cooldown_active", "state_read_failed",
           "regime_stale", "regime_not_accepted", "bar_before_version_activation"},
    "F5": {"stop_missing", "stop_invalid:<reason>", "stop_risk_above_cap", "cost_above_budget",
           "bracket_invalid", "t1_not_cost_feasible"},
    "F6": {"rank_below_cap", "resource_cap", "legacy_alphabetical_cut"},
    "F7": {"paused", "capacity_full", "exposure_symbol", "exposure_strategy", "exposure_regime",
           "exposure_correlation", "risk_state_invalid", "min_notional_infeasible", "no_price",
           "entry_rejected", "entry_wait_expired", "superseded", "already_registered", "mark_stale",
           "ledger_mismatch", "ledger_event_conflict", "economic_limit:<rule>", "exposure_gross", "heat_cap"},
}


def cref(symbol="AAAUSDT", timeframe="4h", **kw):
    base = dict(symbol=symbol, strategy_id="legacy_momentum", strategy_version="sv-test",
                timeframe=timeframe, bar_close_time=T0)
    base.update(kw)
    return CandidateRef(**base)


def cand_record(code, c=None, **kw):
    c = c or cref()
    fields = dict(COMMON, stage=code.split(".")[0], scope="candidate", reason_code=code, as_of=T0,
                  symbol=c.symbol, strategy_id=c.strategy_id, strategy_version=c.strategy_version,
                  timeframe=c.timeframe, bar_close_time=c.bar_close_time, setup_key=c.setup_key)
    fields.update(kw)
    return RejectionRecord(**fields)


def sym_record(code, symbol="AAAUSDT", **kw):
    return RejectionRecord(**dict(COMMON, stage=code.split(".")[0], scope="symbol", reason_code=code,
                                  as_of=T0, symbol=symbol, **kw))


# ── taxonomy ───────────────────────────────────────────────────────────────

def test_enum_completeness_against_documented_taxonomy():
    assert fr.STAGES == ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7")
    assert {s: set(v) for s, v in fr.TAXONOMY.items()} == DOCUMENTED
    for stage, reasons in fr.TAXONOMY.items():
        assert len(reasons) == len(set(reasons)), stage            # no code listed twice
    fixed = {f"{s}.{r}" for s, rs in DOCUMENTED.items() for r in rs if ":" not in r}
    assert fr.REASON_CODES == fixed
    assert set(fr.PARAMETERISED_FAMILIES) == {"F3.regime_veto", "F5.stop_invalid", "F7.economic_limit"}
    assert set(fr.PARAMETERISED_FAMILIES["F7.economic_limit"]) == {
        "daily_loss_limit", "weekly_loss_limit", "max_drawdown_limit", "loss_streak_halt"}
    assert fr.SCOPES == ("cycle", "symbol", "candidate", "opportunity")
    assert set(fr.SUB_STAGES) == {"strategy.input", "strategy.regime", "strategy.entry", "strategy.geometry",
                                  "shared.identity", "shared.sizing", "shared.order_intent",
                                  "shared.admission"}


def test_reason_code_validation_is_closed():
    assert validate_reason_code("F6.rank_below_cap", "F6") == "F6.rank_below_cap"
    assert validate_reason_code("F3.regime_veto:btc_trend") == "F3.regime_veto:btc_trend"
    assert validate_reason_code("F5.stop_invalid:above_entry") == "F5.stop_invalid:above_entry"
    assert validate_reason_code("F7.economic_limit:daily_loss_limit")
    for bad in ("F6.not_selected_capacity", "F7.economic_limit:monthly", "F3.regime_veto:", "F3.regime_veto:X Y",
                "F9.snapshot_stale", "rank_below_cap", "", None, "F7.capacity_full:x"):
        with pytest.raises(ValueError):
            validate_reason_code(bad)
    with pytest.raises(ValueError, match="stage_mismatch"):
        validate_reason_code("F7.capacity_full", "F6")
    assert fr.stage_of("F4.regime_stale") == "F4" and fr.stage_of("F3.regime_stale") == "F3"


def test_se_name_map_is_consistent_and_complete():
    assert len(fr.SE_NAME_MAP) == 19                                 # every SE-side name of WP-IR-01, once
    for name, (stage, code, sub) in fr.SE_NAME_MAP.items():
        assert validate_reason_code(code, stage) == code, name
        assert fr.SUB_STAGE_STAGE[sub] == stage, name


def test_legacy_label_map_targets_are_valid_and_rank_is_not_capacity():
    for label, code in fr.LEGACY_LABEL_MAP.items():
        validate_reason_code(code)
    assert fr.canonical_for_legacy("not_selected_capacity") == "F6.rank_below_cap"
    assert fr.canonical_for_legacy("REJECT_RANK_CAPACITY") == "F6.rank_below_cap"
    assert fr.canonical_for_legacy("portfolio_capacity_2/2") == "F7.capacity_full"
    with pytest.raises(ValueError, match="unmapped"):
        fr.canonical_for_legacy("something_new")


def test_legacy_capacity_labels_appear_only_in_the_mapping_table():
    """WP-IT-04 test 4 (static), on the new module itself."""
    src = inspect.getsource(fr)
    start = src.index("LEGACY_LABEL_MAP = {")
    end = src.index("}", start)
    for label in ("not_selected_capacity", "REJECT_RANK_CAPACITY"):
        positions = [i for i in range(len(src)) if src.startswith(label, i)]
        assert positions and all(start < p < end for p in positions), label


# ── RejectionRecord schema ─────────────────────────────────────────────────

def test_record_is_frozen_and_detail_is_a_deep_immutable_copy():
    detail = {"spread": 0.2, "limit": {"value": 0.15}, "seen": [1, 2]}
    r = cand_record("F2.spread_above_limit", detail=detail)
    detail["spread"] = 9.0
    detail["limit"]["value"] = 9.0
    assert r.detail["spread"] == 0.2 and r.detail["limit"]["value"] == 0.15
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.reason_code = "F2.book_stale"
    with pytest.raises(TypeError):
        r.detail["spread"] = 1.0
    assert r.detail["seen"] == (1, 2)
    assert hash(r) == hash(r.record_id)


def test_record_id_is_deterministic_and_identity_only():
    a = cand_record("F5.stop_missing", detail={"x": 1}, decision_id="d1")
    b = cand_record("F5.stop_missing", detail={"x": 2}, decision_id="d2")
    assert a.record_id == b.record_id and len(a.record_id) == 64
    assert cand_record("F5.bracket_invalid").record_id != a.record_id
    assert cand_record("F5.stop_missing", cref(timeframe="1d")).record_id != a.record_id
    assert cand_record("F5.stop_missing", cycle_id="other").record_id != a.record_id


@pytest.mark.parametrize("kw, match", [
    (dict(stage="F6"), "stage_mismatch"),
    (dict(sub_stage="strategy.unknown"), "sub_stage_unknown"),
    (dict(sub_stage="shared.admission"), "sub_stage_stage_mismatch"),
    (dict(scope="everything"), "scope_unknown"),
    (dict(as_of=True), "as_of"),
    (dict(as_of=float(T0)), "as_of"),
    (dict(decision_time="1"), "decision_time"),
    (dict(rule_ref=""), "rule_ref"),
    (dict(strategy_id=None), "candidate_fields_required"),
    (dict(detail={"v": float("nan")}), "not_finite"),
    (dict(detail={"v": object()}), "detail_type"),
    (dict(detail={str(i): i for i in range(40)}), "too_large"),
    (dict(rank=3), "rank_before_F6"),
    (dict(scope="opportunity"), "opportunity_scope_before_F6"),
])
def test_record_validation_refuses(kw, match):
    with pytest.raises(ValueError, match=match):
        cand_record("F5.stop_missing", **kw)


def test_scope_rules():
    with pytest.raises(ValueError, match="subject_count"):
        RejectionRecord(**dict(COMMON, stage="F0", scope="cycle", reason_code="F0.snapshot_stale", as_of=T0))
    with pytest.raises(ValueError, match="cycle_scope_has_subject"):
        RejectionRecord(**dict(COMMON, stage="F0", scope="cycle", reason_code="F0.snapshot_stale", as_of=T0,
                               symbol="AAAUSDT", detail={"subject_count": 1}))
    with pytest.raises(ValueError, match="F0_is_cycle_scope"):
        sym_record("F0.snapshot_stale")
    with pytest.raises(ValueError, match="symbol_scope_has_candidate_fields"):
        sym_record("F1.owner_excluded", timeframe="4h")
    with pytest.raises(ValueError, match="scope_not_allowed_at_F1"):
        cand_record("F1.owner_excluded")
    per_strategy = RejectionRecord(**dict(COMMON, stage="F3", scope="cycle", reason_code="F3.regime_stale",
                                          as_of=T0, strategy_id="s1", detail={"subject_count": 4}))
    assert per_strategy.subject_count == 4 and per_strategy.subject_key() == ("cycle", "s1", None)
    with pytest.raises(ValueError, match="rank_required"):
        cand_record("F6.rank_below_cap")


def test_json_is_deterministic_and_round_trips():
    r = cand_record("F2.spread_above_limit", detail={"spread": 0.2, "limit": 0.15}, sub_stage=None)
    text = r.to_json()
    assert text == r.to_json() and " " not in text
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert data["schema"] == fr.SCHEMA and data["taxonomy_version"] == fr.TAXONOMY_VERSION
    back = RejectionRecord.from_json(text)
    assert back == r and back.to_json() == text
    data["record_id"] = "0" * 64
    with pytest.raises(ValueError, match="record_id_mismatch"):
        RejectionRecord.from_dict(data)
    data = json.loads(text)
    data["extra"] = 1
    with pytest.raises(ValueError, match="unknown_fields"):
        RejectionRecord.from_dict(data)
    data = json.loads(text)
    data["taxonomy_version"] = "v0"
    with pytest.raises(ValueError, match="schema_mismatch"):
        RejectionRecord.from_dict(data)


def test_per_timeframe_outcomes_stay_distinct():
    """R6 test 3 / WP-B02 acceptance at record level: three timeframes, three records."""
    recs = {cand_record("F4.no_setup", cref(timeframe="15m")),
            cand_record("F5.stop_missing", cref(timeframe="4h")),
            cand_record("F4.bar_stale", cref(timeframe="1d"))}
    assert len({r.record_id for r in recs}) == 3


# ── eligibility ────────────────────────────────────────────────────────────

def test_eligibility_keeps_every_failed_rule_and_counts_one_subject():
    res = EligibilityResult("F1", "BBBUSDT", T0, ("F1.stable_or_pegged", "F1.owner_excluded",
                                                   "F1.stable_or_pegged"))
    assert not res.eligible and res.reason_codes == ("F1.owner_excluded", "F1.stable_or_pegged")
    ok = EligibilityResult("F1", "CCCUSDT", T0)
    assert ok.eligible
    refs = {"F1.owner_excluded": "f1.excl.v1", "F1.stable_or_pegged": "f1.stable.v1"}
    recs = res.to_rejections(cycle_id=CYCLE, decision_time=DECISION, rule_refs=refs,
                             snapshot_hash="s", config_hash="c")
    assert [r.reason_code for r in recs] == list(res.reason_codes)
    result = check_conservation([StageCount("F1", 2, 1)], recs)
    assert result.ok and dict(result.rejected_subjects) == {"F1": 1}
    assert dict(result.reason_counts) == {"F1.owner_excluded": 1, "F1.stable_or_pegged": 1}
    with pytest.raises(ValueError, match="rule_ref_missing"):
        res.to_rejections(cycle_id=CYCLE, decision_time=DECISION, rule_refs={}, snapshot_hash="s",
                          config_hash="c")
    with pytest.raises(ValueError, match="stage_mismatch"):
        EligibilityResult("F1", "BBBUSDT", T0, ("F2.volume_missing",))
    with pytest.raises(ValueError, match="F1_is_symbol_scope"):
        EligibilityResult("F1", "AAAUSDT", T0, (), cref())
    with pytest.raises(ValueError, match="candidate_mismatch"):
        EligibilityResult("F5", "BBBUSDT", T0, ("F5.stop_missing",), cref())
    cand = EligibilityResult("F5", "AAAUSDT", T0, ("F5.stop_missing",), cref())
    (rec,) = cand.to_rejections(cycle_id=CYCLE, decision_time=DECISION, rule_refs={"F5.stop_missing": "r"},
                                snapshot_hash="s", config_hash="c", sub_stage="strategy.geometry")
    assert rec.scope == "candidate" and rec.timeframe == "4h" and rec.sub_stage == "strategy.geometry"


def test_candidate_ref_carries_only_the_risk_plan_hash():
    """WP-IR-02: risk_plan belongs to the Candidate; the funnel holds only its hash."""
    names = {f.name for f in dataclasses.fields(CandidateRef)}
    assert "risk_plan" not in names and "risk_plan_hash" in names
    c = cref(risk_plan_hash="rp-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.risk_plan_hash = "rp-2"


# ── ranking capture, rank loss vs capacity ─────────────────────────────────

def test_ranking_input_is_plain_frozen_data():
    x = RankingInput(cref(), "sel-test", "tb-1", 0, score=1.5, score_direction="lower_first",
                     components={"spread": 0.1, "liquidity": None, "a": 2})
    assert x.components == (("a", 2), ("liquidity", None), ("spread", 0.1))
    assert json.loads(fr.canonical_json(x.as_dict()))["components"][0] == ["a", 2]
    with pytest.raises(ValueError, match="score_direction_required"):
        RankingInput(cref(), "sel-test", "tb-1", 0, score=1.0)
    with pytest.raises(ValueError, match="not_finite"):
        RankingInput(cref(), "sel-test", "tb-1", 0, components={"spread": float("nan")})
    with pytest.raises(ValueError, match="score_not_finite"):
        RankingInput(cref(), "sel-test", "tb-1", 0, score=float("inf"), score_direction="higher_first")
    with pytest.raises(dataclasses.FrozenInstanceError):
        x.score = 2.0


def test_three_eligible_offer_one_gives_two_rank_records_and_no_capacity():
    """WP-IT-04 test 1 (record level)."""
    cands = [cref(f"S{i}USDT") for i in range(3)]
    recs = [rank_below_cap_record(cycle_id=CYCLE, candidate=c, rank=i + 2, offer_cap=1,
                                  selection_version="sel-test", as_of=T0, decision_time=DECISION,
                                  rule_ref="f6.cap", snapshot_hash="s", config_hash="c")
            for i, c in enumerate(cands[1:])]
    assert [r.reason_code for r in recs] == ["F6.rank_below_cap"] * 2
    assert not any(r.stage == "F7" for r in recs)
    assert recs[0].detail["offer_cap"] == 1 and recs[0].rank == 2
    assert check_conservation([StageCount("F6", 3, 1)], recs).ok
    with pytest.raises(ValueError, match="rank_within_offer_cap"):
        rank_below_cap_record(cycle_id=CYCLE, candidate=cands[0], rank=1, offer_cap=1,
                              selection_version="sel-test", as_of=T0, decision_time=DECISION,
                              rule_ref="f6.cap", snapshot_hash="s", config_hash="c")


def test_capacity_full_is_f7_with_authority_detail():
    """WP-IT-04 test 2 and the WP-IR-03 output detail; an invalid limit is not 'full'."""
    kw = dict(cycle_id=CYCLE, candidate=cref(), open_count=2, reserved=0, multiplier=1.0,
              budget_version="legacy_v1", as_of=T0, decision_time=DECISION, rule_ref="f7.cap",
              snapshot_hash="s", config_hash="c")
    r = capacity_full_record(limit=2, rank=1, **kw)
    assert (r.stage, r.reason_code, r.scope, r.sub_stage) == ("F7", "F7.capacity_full", "opportunity",
                                                             "shared.admission")
    assert dict(r.detail) == {"open": 2, "reserved": 0, "limit": 2, "multiplier": 1.0,
                              "budget_version": "legacy_v1"}
    result = check_conservation([StageCount("F6", 1, 1), StageCount("F7", 1, 0)], [r])
    assert result.ok and not any(code.startswith("F6.") for code, _ in result.reason_counts)
    for bad_limit in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="limit"):
            capacity_full_record(limit=bad_limit, **kw)
    with pytest.raises(ValueError, match="extra_detail_overrides"):
        capacity_full_record(limit=2, extra_detail={"open": 0}, **kw)


def test_legacy_cut_over_700_rows_records_every_cut_row():
    """OF-T01 fixture: more rows than today's 200 + 500 visibility; every cut row is recorded."""
    limit = 200                                       # the legacy value, passed in, not chosen here
    rows = [cref(f"X{i:04d}USDT") for i in range(750)]
    ordered = sorted(rows, key=lambda c: c.symbol)
    recs = [legacy_alphabetical_cut_record(cycle_id=CYCLE, candidate=c, position=i + 1, limit=limit,
                                           as_of=T0, decision_time=DECISION, rule_ref="legacy.limit",
                                           snapshot_hash="s", config_hash="c")
            for i, c in enumerate(ordered) if i >= limit]
    assert len(recs) == 550 and all(r.reason_code == "F6.legacy_alphabetical_cut" for r in recs)
    assert {r.symbol for r in recs} == {c.symbol for c in ordered[limit:]}
    assert check_conservation([StageCount("F6", 750, limit)], recs).ok
    with pytest.raises(ValueError, match="position_within_limit"):
        legacy_alphabetical_cut_record(cycle_id=CYCLE, candidate=rows[0], position=5, limit=limit, as_of=T0,
                                       decision_time=DECISION, rule_ref="r", snapshot_hash="s",
                                       config_hash="c")


def test_resource_cap_record():
    r = resource_cap_record(cycle_id=CYCLE, candidate=cref(), rank=9, hash_position=9, guard_bound=8,
                            as_of=T0, decision_time=DECISION, rule_ref="f6.guard", snapshot_hash="s",
                            config_hash="c")
    assert r.reason_code == "F6.resource_cap" and r.detail["guard_bound"] == 8


# ── freshness ──────────────────────────────────────────────────────────────

def test_freshness_wraps_the_reference_rule():
    step = TIMEFRAME_MS["4h"]
    close = T0 + step - 1
    c = cref(bar_close_time=close)
    kw = dict(cycle_id=CYCLE, candidate=c, rule_ref="f4.fresh", snapshot_hash="s", config_hash="c")
    forming = freshness_at("4h", close, close - 1000)
    stale = freshness_at("4h", close, close + step + 10)
    fresh = freshness_at("4h", close, close + 60_000)
    r1 = freshness_record(freshness=forming, decision_time=close - 1000, **kw)
    r2 = freshness_record(freshness=stale, decision_time=close + step + 10, **kw)
    assert r1.reason_code == "F4.bar_not_closed" and r1.detail["age_ms"] < 0
    assert r2.reason_code == "F4.bar_stale" and r2.as_of == close
    assert freshness_record(freshness=fresh, decision_time=close + 60_000, **kw) is None
    with pytest.raises(ValueError, match="unmapped"):
        freshness_record(freshness=freshness_at("2h", close, close + 1), decision_time=close + 1, **kw)
    with pytest.raises(ValueError, match="freshness_required"):
        freshness_record(freshness={"admissible": False}, decision_time=close + 1, **kw)


# ── conservation ───────────────────────────────────────────────────────────

def _full_cycle():
    """Every stage rejects at least one subject (OF-T01 test)."""
    recs = [
        RejectionRecord(**dict(COMMON, stage="F0", scope="cycle", reason_code="F0.clock_offset_exceeded",
                               as_of=T0, detail={"subject_count": 0})),
        sym_record("F1.owner_excluded", "A1USDT"), sym_record("F1.stable_or_pegged", "A1USDT"),
        sym_record("F2.volume_below_floor", "A2USDT"),
        RejectionRecord(**dict(COMMON, stage="F3", scope="cycle", reason_code="F3.regime_stale", as_of=T0,
                               strategy_id="strat_b", detail={"subject_count": 2})),
        cand_record("F4.no_setup", cref("A3USDT", "15m")), cand_record("F4.no_setup", cref("A3USDT", "1d")),
        cand_record("F5.stop_missing", cref("A4USDT", "4h")),
        rank_below_cap_record(cycle_id=CYCLE, candidate=cref("A5USDT"), rank=2, offer_cap=1,
                              selection_version="sel-test", as_of=T0, decision_time=DECISION, rule_ref="r",
                              snapshot_hash="s", config_hash="c"),
        capacity_full_record(cycle_id=CYCLE, candidate=cref("A6USDT"), open_count=1, reserved=0, limit=1,
                             multiplier=1.0, budget_version="legacy_v1", as_of=T0, decision_time=DECISION,
                             rule_ref="r", snapshot_hash="s", config_hash="c", rank=1),
        cand_record("F3.regime_unknown_used", cref("A7USDT")),           # annotation, not a drop
    ]
    counts = [StageCount("F0", 0, 0), StageCount("F1", 10, 9), StageCount("F2", 9, 8),
              StageCount("F3", 8, 6), StageCount("F4", 12, 10, expanded_from=6),
              StageCount("F5", 10, 9), StageCount("F6", 9, 8), StageCount("F7", 8, 6, held=1)]
    return counts, recs


def test_conservation_holds_on_a_full_cycle_and_annotations_are_not_drops():
    counts, recs = _full_cycle()
    res = check_conservation(counts[1:], recs, chain=("F1", "F2", "F3", "F4", "F5", "F6", "F7"))
    assert res.violations == () and res.ok
    assert dict(res.annotation_counts) == {"F3.regime_unknown_used": 1}
    assert dict(res.rejected_subjects)["F3"] == 2


def test_silent_drop_inside_a_stage_is_detected():
    counts, recs = _full_cycle()
    counts[5] = StageCount("F5", 10, 8)                       # one candidate vanished without a record
    res = check_conservation(counts, recs)
    assert not res.ok
    assert [(v.stage, v.kind, v.expected, v.observed) for v in res.violations] == [("F5", "stage_equation",
                                                                                     10, 9)]


def test_silent_drop_between_stages_and_unbacked_records_are_detected():
    counts, recs = _full_cycle()
    counts[5] = StageCount("F5", 9, 8)                        # F4 passed 10, F5 received 9
    res = check_conservation(counts, recs, chain=("F4", "F5"))
    assert {(v.stage, v.kind) for v in res.violations} == {("F5", "chain_link")}
    res = check_conservation([], [sym_record("F1.owner_excluded")])
    assert [(v.stage, v.kind) for v in res.violations] == [("F1", "records_without_counts")]
    res = check_conservation([StageCount("F1", 1, 1)], [], chain=("F1", "F2"))
    assert [(v.stage, v.kind) for v in res.violations] == [("F2", "chain_stage_missing")]


def test_duplicate_records_are_not_double_counted():
    r = sym_record("F1.owner_excluded")
    assert check_conservation([StageCount("F1", 2, 1)], [r, r, sym_record("F1.owner_excluded")]).ok


def test_stage_count_validation():
    with pytest.raises(ValueError, match="held_only_at_F7"):
        StageCount("F5", 2, 1, held=1)
    with pytest.raises(ValueError):
        StageCount("F8", 1, 1)
    with pytest.raises(ValueError):
        StageCount("F1", -1, 0)


# ── recorder ───────────────────────────────────────────────────────────────

TFS = ("15m", "4h", "1d")


def _synthetic(rng, n):
    rows = [{"symbol": f"S{i:04d}USDT", "tf": rng.choice(TFS),
             "spread": rng.choice([None, round(rng.random(), 4)]), "vol": round(rng.random() * 1e7, 2),
             "stop_valid": rng.choice([True, True, False, None])} for i in range(n)]
    rng.shuffle(rows)
    return rows


def _ref(row):
    return cref(row["symbol"], row["tf"])


def _pipeline(rows, rec):
    """A synthetic decision flow instrumented at three stages. The decisions are the test's
    own fixture logic; the recorder only observes them."""
    want = rec is not None and rec.enabled
    f2 = [r for r in rows if r["spread"] is not None and r["spread"] <= 0.5]
    f2_rej = [cand_record("F2.spread_invalid" if r["spread"] is None else "F2.spread_above_limit", _ref(r))
              for r in rows if want and r not in f2]
    f2 = instrumented(rec, "F2", rows, f2, f2_rej)
    f5 = [r for r in f2 if r["stop_valid"] is True]
    f5_rej = [cand_record("F5.stop_missing" if r["stop_valid"] is None else "F5.stop_invalid:legacy", _ref(r))
              for r in f2 if want and r["stop_valid"] is not True]
    f5 = instrumented(rec, "F5", f2, f5, f5_rej)
    ranked = sorted(f5, key=lambda r: (r["spread"], -r["vol"], r["symbol"], r["tf"]))
    if rec is not None:
        rec.capture_ranking([RankingInput(_ref(r), "sel-test", f"tb-{r['symbol']}", i, score=r["spread"],
                                          score_direction="lower_first",
                                          components={"spread": r["spread"], "vol": r["vol"]})
                             for i, r in enumerate(f5)] if want else [])
    chosen = ranked[:1]
    f6_rej = [rank_below_cap_record(cycle_id=CYCLE, candidate=_ref(r), rank=i + 1, offer_cap=1,
                                    selection_version="sel-test", as_of=T0, decision_time=DECISION,
                                    rule_ref="r", snapshot_hash="s", config_hash="c")
              for i, r in enumerate(ranked) if want and i >= 1]
    return instrumented(rec, "F6", ranked, chosen, f6_rej)


@pytest.mark.parametrize("seed", range(25))
def test_property_instrumented_pass_through_equals_uninstrumented(seed):
    rng = random.Random(seed)
    rows = _synthetic(rng, rng.choice([0, 1, 2, 7, 40, 199, 201]))
    pristine = copy.deepcopy(rows)
    ids = [id(r) for r in rows]
    baseline = _pipeline(rows, None)
    off = FunnelRecorder(enabled=False, cycle_id=CYCLE)
    on = FunnelRecorder(enabled=True, cycle_id=CYCLE)
    out_off, out_on = _pipeline(rows, off), _pipeline(rows, on)
    assert out_off == baseline == out_on
    assert [id(r) for r in out_on] == [id(r) for r in baseline]
    assert rows == pristine and [id(r) for r in rows] == ids         # inputs untouched
    assert off.report() is None and off.failure_count == 0
    report = on.report(chain=("F2", "F5", "F6"))
    assert report.valid, report.conservation.violations
    assert len(report.ranking_inputs) == len([r for r in rows if r["spread"] is not None
                                              and r["spread"] <= 0.5 and r["stop_valid"] is True])


def test_observing_calls_return_the_same_object():
    rec = FunnelRecorder(enabled=True, cycle_id=CYCLE)
    xs, ys = [1, 2], [1]
    recs = [sym_record("F1.owner_excluded")]
    assert rec.observe_stage("F1", xs, ys, recs) is ys
    assert rec.record(recs[0]) is recs[0] and rec.record_many(recs) is recs
    ranking = (RankingInput(cref(), "sel", "tb", 0),)
    assert rec.capture_ranking(ranking) is ranking
    assert rec.report().duplicate_records == 2


def test_disabled_recorder_is_a_strict_no_op():
    rec = FunnelRecorder(enabled=False, cycle_id=CYCLE)
    gen = (i for i in range(3))
    assert rec.observe_stage("BAD", gen, gen, "not-a-list") is gen
    assert list(gen) == [0, 1, 2]
    assert rec.record("junk") == "junk" and rec.capture_ranking(None) is None
    rec.observe_counts("F1", n_in=-5, passed=0)
    assert rec.failure_count == 0 and rec.report() is None
    assert rec._counts == [] and rec._records == {} and rec._ranking == []


def test_recording_never_raises_and_counts_failures():
    rec = FunnelRecorder(enabled=True, cycle_id=CYCLE)
    gen = (i for i in range(3))
    out = [0]
    assert rec.observe_stage("F1", gen, out) is out
    assert list(gen) == [0, 1, 2]                               # a one-shot iterator is not consumed
    assert rec.observe_stage("F9", [1], [1]) == [1]
    assert rec.record("junk") == "junk"
    other = RejectionRecord(**dict(COMMON, cycle_id="other", stage="F1", scope="symbol",
                                   reason_code="F1.owner_excluded", as_of=T0, symbol="AAAUSDT"))
    rec.record(other)
    rec.record_many(r for r in [other])
    rec.capture_ranking(["junk"])
    rec.observe_counts("F1", n_in=1, passed=2)                  # passed > in is still counted, then flagged
    kinds = rec.failure_kinds
    assert kinds["unsized_stage_io"] == 1 and kinds["ValueError"] == 1
    assert kinds["not_a_rejection_record"] == 1 and kinds["cycle_mismatch"] == 1
    assert kinds["records_not_list"] == 1 and kinds["not_a_ranking_input"] == 1
    report = rec.report()
    assert not report.valid and report.failure_count == 6


def test_broken_writer_does_not_alter_decisions(monkeypatch):
    rows = _synthetic(random.Random(7), 30)
    baseline = _pipeline(rows, None)
    rec = FunnelRecorder(enabled=True, cycle_id=CYCLE)

    def broken(_record):
        raise RuntimeError("writer down")

    monkeypatch.setattr(rec, "_add_record", broken)
    assert _pipeline(rows, rec) == baseline
    assert rec.failure_kinds["RuntimeError"] >= 1
    assert not rec.report().valid


def test_report_json_is_deterministic_and_independent_of_call_order():
    _, recs = _full_cycle()
    counts, _ = _full_cycle()
    texts = set()
    for seed in range(5):
        order = list(recs)
        random.Random(seed).shuffle(order)
        rec = FunnelRecorder(enabled=True, cycle_id=CYCLE)
        for c in reversed(counts) if seed % 2 else counts:
            rec.observe_counts(c.stage, n_in=c.n_in, passed=c.passed, held=c.held,
                               expanded_from=c.expanded_from)
        rec.record_many(order)
        texts.add(rec.report().to_json())
    assert len(texts) == 1
    report = json.loads(texts.pop())
    assert report["valid"] is True and report["taxonomy_version"] == fr.TAXONOMY_VERSION
    assert [r["stage"] for r in report["records"]] == sorted(r["stage"] for r in report["records"])


def test_flag_parsing_refuses_unknown_values():
    assert parse_enabled(True) is True and parse_enabled("false") is False and parse_enabled("1") is True
    for bad in ("maybe", "", None, 2.0, "enabled"):
        with pytest.raises(RuntimeError):
            parse_enabled(bad)
    with pytest.raises(TypeError):
        FunnelRecorder(enabled="true", cycle_id=CYCLE)
    with pytest.raises(ValueError):
        FunnelRecorder(enabled=True, cycle_id="")
