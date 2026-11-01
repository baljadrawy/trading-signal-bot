"""WP-A04 golden replay harness (SE-71; the SE-38 PATCH/MINOR gate).

Synthetic fixtures only (tests/golden_replay_fixtures.py) and the committed golden files under
tests/fixtures/golden_replay/. No market data, database, network, clock or environment is read;
the A44 call-site test reads the source text of signal_engine/signal_logic.py, the code the
adapter mirrors. Determinism across two development machines is NOT VERIFIED (see the
tests/golden_replay.py docstring). These tests show engineering properties only and say nothing
about any strategy's economics.
"""
import sys; sys.path.insert(0, '.')

import builtins
import copy
import decimal
import enum
import importlib.util
import itertools
import json
import os
import pathlib
import random
import re
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

import golden_replay as gr
import golden_replay_fixtures as fx
from shared import decision_metadata as dm
from shared import funnel_records as fr
from shared import signal_identity as sid
from shared import strategy_identity as si

ROOT = pathlib.Path(__file__).resolve().parents[1]
RNG_SEED = 20261101                      # the only seed; permutations are reproducible
SUITE_IDS = [s.golden_name for s in fx.SUITES]
MIN_ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
F4_CODES = {"F4.data_quality", "F4.history_insufficient", "F4.no_setup", "F4.bar_not_closed",
            "F4.bar_stale", "F4.bar_before_version_activation", "F4.duplicate_setup",
            "F4.setup_conflict"}


def replay(inputs=None, code=fx.WP2_CODE):
    return gr.wp2_replay(fx.scenario() if inputs is None else inputs, code)


def out_bytes(result):
    return gr.canonical_bytes(result.golden_output())


def golden(suite=fx.WP2_SUITE):
    return gr.load_golden(suite.golden_file)


def subject(d):
    return d["cycle_id"], d["symbol"], d["timeframe"], d["bar_close_ms"]


@pytest.fixture(scope="module")
def baseline():
    return replay()


# ── pinned golden files ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("suite", fx.SUITES, ids=SUITE_IDS)
def test_replay_matches_the_committed_golden_byte_for_byte(suite):
    actual = gr.replay_suite(suite)
    gr.assert_matches_golden(actual, golden(suite))
    assert gr.render_golden(actual) == suite.golden_file.read_text(encoding="ascii")


def test_golden_pins_identity_chain_and_decision_hashes():
    base = golden(fx.WP2_SUITE)["cases"][0]["output"]
    patch = golden(fx.WP2_PATCH_SUITE)["cases"][0]["output"]
    for out in (base, patch):
        for name in ("source_hash", "config_hash", "contract_hash", "identity_hash", "closure_spec_hash"):
            assert re.fullmatch(r"[0-9a-f]{64}", out["strategy"][name])
        assert sorted(out["digests"]) == ["chain_head", "decision_ids_hash", "decisions_hash",
                                          "records_hash", "rejections_hash", "setup_keys_hash"]
        assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in out["digests"].values())
    assert (base["strategy"]["version"], patch["strategy"]["version"]) == ("1.0.0", "1.0.1")
    assert base["strategy"]["source_hash"] != patch["strategy"]["source_hash"]
    assert base["strategy"]["config_hash"] == patch["strategy"]["config_hash"]
    assert base["observations_hash"] == patch["observations_hash"]
    assert base["digests"]["decisions_hash"] == patch["digests"]["decisions_hash"]    # SE-38 PATCH
    assert base["digests"]["chain_head"] != patch["digests"]["chain_head"]            # identity moved
    a44 = golden(fx.A44_SUITE)
    assert a44["code_refs"] == ["shared/signal_identity.py", "signal_engine/signal_logic.py"]
    assert [c["case_id"] for c in a44["cases"]] == ["fresh_cycle", "identity_failures", "late_cycle"]


# ── reproducibility ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("suite", fx.SUITES, ids=SUITE_IDS)
def test_two_runs_are_byte_identical(suite):
    assert gr.render_golden(gr.replay_suite(suite)) == gr.render_golden(gr.replay_suite(suite, repeats=3))


def test_wp2_records_are_reproducible(baseline):
    again = replay()
    assert out_bytes(again) == out_bytes(baseline)
    assert [r.to_json() for r in again.records] == [r.to_json() for r in baseline.records]
    assert [r.to_json() for r in again.rejections] == [r.to_json() for r in baseline.rejections]


def test_a_nondeterministic_or_mutating_path_is_refused():
    counter = itertools.count()
    flaky = gr.GoldenSuite(gr.GoldenPath("flaky", lambda inputs: next(counter)), (gr.GoldenCase("one", {}),))
    with pytest.raises(gr.NonDeterministicPath, match="different outputs"):
        gr.replay_suite(flaky)

    def mutate(inputs):
        inputs["seen"] = True
        return {}
    mutating = gr.GoldenSuite(gr.GoldenPath("mutating", mutate), (gr.GoldenCase("one", {}),))
    with pytest.raises(gr.NonDeterministicPath, match="mutated its inputs"):
        gr.replay_suite(mutating)


def test_fresh_processes_with_different_hash_seeds_give_identical_bytes():
    outputs = gr.cross_process_outputs()
    assert sorted(outputs) == sorted(gr.FIXED_HASH_SEEDS)
    assert len(set(outputs.values())) == 1
    assert outputs["0"] == gr.print_bytes(fx.SUITES)


def test_check_command_in_a_fresh_process_is_clean_and_read_only():
    before = {s.golden_name: s.golden_file.read_bytes() for s in fx.SUITES}
    proc = subprocess.run([sys.executable, "tests/golden_replay.py", "check"], cwd=ROOT,
                          env={**MIN_ENV, "PYTHONHASHSEED": "3"}, capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines() == [f"{name}: OK" for name in SUITE_IDS]
    assert {s.golden_name: s.golden_file.read_bytes() for s in fx.SUITES} == before


# ── ordering and equivalent inputs ─────────────────────────────────────────────────────────

def _permuted(inputs, rng):
    s = copy.deepcopy(inputs)
    rng.shuffle(s["cycles"])
    for cycle in s["cycles"]:
        rng.shuffle(cycle["observations"])
    st = s["strategy"]
    rng.shuffle(st["closure"])
    rng.shuffle(st["config_schema"]["keys"])
    st["config_values"] = dict(reversed(list(st["config_values"].items())))
    st["contract"] = dict(reversed(list(st["contract"].items())))
    return dict(reversed(list(s.items())))


def test_permuted_equivalent_inputs_give_identical_canonical_output(baseline):
    rng = random.Random(RNG_SEED)
    normalize = fx.WP2_SUITE.path.normalize
    want_out, want_in = out_bytes(baseline), gr.digest(normalize(fx.scenario()))
    original = [c["cycle_id"] for c in fx.scenario()["cycles"]]
    moved = 0
    for _ in range(6):
        s = _permuted(fx.scenario(), rng)
        moved += [c["cycle_id"] for c in s["cycles"]] != original
        assert out_bytes(replay(s)) == want_out
        assert gr.digest(normalize(s)) == want_in
    assert moved                                  # the permutations were not all identities


def test_equivalent_input_forms_give_identical_output(baseline):
    s = fx.scenario()
    s["cycles"] = tuple({**c, "observations": tuple({**o, "closes": tuple(o["closes"])}
                                                    for o in c["observations"])} for c in s["cycles"])
    st = s["strategy"]
    st["config_values"] = MappingProxyType(dict(st["config_values"]))
    st["closure"] = [{**f, "text": f["text"].replace("\n", "\r\n")} for f in st["closure"]]   # CRLF
    st["lineage"] = ["synthetic_golden/0.9.0"]      # lineage is metadata, never identity
    result = replay(s)
    assert out_bytes(result) == out_bytes(baseline)
    assert result.strategy == baseline.strategy and result.strategy.lineage != baseline.strategy.lineage


def test_a_closure_written_under_tmp_path_reads_back_to_the_same_identity(tmp_path, baseline):
    s = fx.scenario()
    closure = s["strategy"]["closure"]
    manifest = si.StrategyRuleManifest(fx.STRATEGY_ID, tuple(
        si.ClosureFile(f["path"], f["role"], tuple(si.RegionSpec(*r) for r in f["regions"])) for f in closure))
    for f in closure:
        target = tmp_path / f["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f["text"], encoding="utf-8")
    sources = si.read_closure_sources(tmp_path, manifest)
    s["strategy"]["closure"] = [{**f, "text": sources[f["path"]].decode("utf-8")} for f in closure]
    result = replay(s)
    assert result.strategy.source_hash == si.compute_closure(manifest, sources).source_hash
    assert result.strategy == baseline.strategy
    assert out_bytes(result) == out_bytes(baseline)


def test_a44_output_ignores_mapping_order_and_keeps_candidate_order():
    case = copy.deepcopy(fx.a44_cases()[0].inputs)
    reordered = {k: case[k] for k in reversed(list(case))}
    reordered["candidates"] = [dict(reversed(list(c.items()))) for c in case["candidates"]]
    reordered["emitted"] = list(reversed(case["emitted"]))
    assert gr.canonical_bytes(fx.a44_enforce_integrity_step(reordered)) == \
        gr.canonical_bytes(fx.a44_enforce_integrity_step(case))
    swapped = copy.deepcopy(case)
    swapped["candidates"].reverse()                 # production order is query order: kept as given
    rows = fx.a44_enforce_integrity_step(swapped)["rows"]
    assert [r["symbol"] for r in rows] == [c["symbol"] for c in swapped["candidates"]]


# ── duplicates and conflicts ───────────────────────────────────────────────────────────────

def test_duplicate_and_conflict_handling_is_insert_once(baseline):
    by = {subject(d): d for d in baseline.decisions}
    first, dup, conflict, again = (by[(c, "SYNTHA", "1h", fx.H5)] for c in ("c1", "c2", "c3", "c4"))
    assert (first["outcome"], first["claim"]) == ("candidate", "new")
    assert (dup["reason_code"], dup["claim"]) == ("F4.duplicate_setup", "duplicate")
    assert (conflict["reason_code"], conflict["claim"]) == ("F4.setup_conflict", "conflict")
    assert (again["reason_code"], again["claim"]) == ("F4.duplicate_setup", "duplicate")
    assert dup["payload_hash"] == again["payload_hash"] == first["payload_hash"] != conflict["payload_hash"]
    for d in (dup, conflict, again):                # the first payload is never overwritten
        assert d["detail"]["first_payload_hash"] == first["payload_hash"]
        assert d["detail"]["first_cycle_id"] == "c1" and d["sub_stage"] == "shared.identity"
    records = {subject(r.output()): r for r in baseline.records}
    parent = records[subject(first)]
    for d in (dup, conflict, again):
        record = records[subject(d)]
        assert record.parent_decision_ids == (parent.decision_id,)
        assert record.output()["setup_key"] == parent.output()["setup_key"]
    keys = {r.setup_key for r in baseline.rejections if r.reason_code in ("F4.duplicate_setup", "F4.setup_conflict")}
    assert keys == {parent.output()["setup_key"]}


def test_a_subject_twice_in_one_cycle_is_refused():
    s = fx.scenario()
    s["cycles"][0]["observations"].append(copy.deepcopy(s["cycles"][0]["observations"][0]))
    with pytest.raises(gr.HarnessInputError, match="twice in one cycle"):
        replay(s)


@pytest.mark.parametrize("field, value, match", [
    ("cycle_id", "c1", "duplicate cycle_id"),
    ("decision_time_ms", fx.T0 + 5 * fx.HOUR + 5 * fx.MINUTE, "share a decision time"),
])
def test_ambiguous_cycles_are_refused(field, value, match):
    s = fx.scenario()
    s["cycles"][1][field] = value
    with pytest.raises(gr.HarnessInputError, match=match):
        replay(s)


def test_duplicate_case_ids_and_shared_golden_files_are_refused():
    with pytest.raises(gr.HarnessInputError, match="duplicate case_id"):
        gr.GoldenSuite(fx.A44_PATH, (gr.GoldenCase("a", {}), gr.GoldenCase("a", {})))
    with pytest.raises(gr.HarnessInputError, match="share a golden file"):
        gr.load_suites(["golden_replay_fixtures:SUITES", "golden_replay_fixtures:A44_SUITE"])


# ── coverage, conservation and record verification ─────────────────────────────────────────

def test_every_f4_reason_and_check_of_the_path_is_exercised(baseline):
    codes = {d["reason_code"] for d in baseline.decisions if d["reason_code"]}
    assert codes == F4_CODES
    assert all(fr.validate_reason_code(code, "F4") == code for code in codes)
    assert {d["check"] for d in baseline.decisions} == set(gr.CHECK_ORDER)
    assert {d["outcome"] for d in baseline.decisions} == {"candidate", "rejection"}
    a44 = {r["decision"] for c in golden(fx.A44_SUITE)["cases"] for r in c["output"]["rows"]}
    assert {"admissible", "rejected_duplicate_setup", "rejected_freshness:decision_before_candle_close",
            "rejected_freshness:superseded_by_newer_candle", "rejected_identity:candle_identity_missing",
            "rejected_identity:timeframe_unknown"} <= a44


def test_conservation_holds_in_every_cycle(baseline):
    assert all(result.ok for _, _, result in baseline.conservation)
    assert sum(counts.n_in for _, counts, _ in baseline.conservation) == len(baseline.decisions)
    assert sum(counts.passed for _, counts, _ in baseline.conservation) == \
        sum(d["outcome"] == "candidate" for d in baseline.decisions)
    assert len(baseline.rejections) == sum(d["outcome"] == "rejection" for d in baseline.decisions)


def test_exported_records_verify_and_carry_no_runtime_or_wall_clock(baseline):
    summary = gr.verify_export(baseline.export())
    assert summary == {"records": len(baseline.records), "rejections": len(baseline.rejections),
                       "chain_head": baseline.records[-1].record_hash}
    for record in baseline.records:
        assert dict(record.runtime) == dict.fromkeys(dm.RUNTIME_KEYS) and record.recorded_at_ms is None
    for rejection in baseline.rejections:
        assert rejection.strategy_version == baseline.strategy.identifier


def _other_identity_record(export):
    other = replay(fx.scenario(version="2.0.0", WINDOW=2)).export()["records"][0]
    export["records"][0] = other


TAMPERS = {
    "edited_output": (lambda e: e["records"][0]["output"].update(reason_code="F4.no_setup"),
                      gr.HarnessVerificationError),
    "swapped_records": (lambda e: e["records"].insert(1, e["records"].pop(2)), gr.HarnessVerificationError),
    "dropped_rejection": (lambda e: e["rejections"].pop(), gr.HarnessVerificationError),
    "record_without_source_hash": (lambda e: e["records"][0]["strategy"].pop("source_hash"),
                                   gr.HarnessVerificationError),
    "record_under_other_identity": (_other_identity_record, gr.HarnessIdentityError),
    "rejection_under_other_config": (lambda e: e["rejections"][0].update(config_hash="0" * 64),
                                     gr.HarnessIdentityError),
    "export_without_identity": (lambda e: e["strategy"].pop("config_hash"), gr.HarnessIdentityError),
    "export_with_other_identifier": (lambda e: e.update(identifier="synthetic_golden/9.9.9/x"),
                                     gr.HarnessIdentityError),
}


@pytest.mark.parametrize("name", sorted(TAMPERS))
def test_tampered_exports_fail_explicitly(baseline, name):
    export = copy.deepcopy(baseline.export())
    tamper, error = TAMPERS[name]
    tamper(export)
    with pytest.raises(error):
        gr.verify_export(export)


# ── missing or conflicting identity ────────────────────────────────────────────────────────

def _drop_freshness(s):
    s["strategy"]["config_values"].pop("SIGNAL_FRESHNESS_MAX_AGE_MS")
    s["strategy"]["config_schema"]["keys"] = [k for k in s["strategy"]["config_schema"]["keys"]
                                              if k["name"] != "SIGNAL_FRESHNESS_MAX_AGE_MS"]


IDENTITY_FAILURES = {
    "no_strategy_block": (lambda s: s.pop("strategy"), "no strategy identity declared"),
    "no_closure": (lambda s: s["strategy"].pop("closure"), r"missing \['closure'\]"),
    "empty_closure": (lambda s: s["strategy"].update(closure=[]), "at least one"),
    "closure_text_missing": (lambda s: s["strategy"]["closure"][0].pop("text"), r"missing \['text'\]"),
    "config_key_missing": (lambda s: s["strategy"]["config_values"].pop("WINDOW"), "missing decision keys"),
    "config_key_undeclared": (lambda s: s["strategy"]["config_values"].update(EXTRA=1), "undeclared keys"),
    "freshness_input_missing": (_drop_freshness, "lacks SIGNAL_FRESHNESS_MAX_AGE_MS"),
    "freshness_bound_missing": (lambda s: s["strategy"]["config_values"].update(
        SIGNAL_FRESHNESS_MAX_AGE_MS="1h=1800000"), "no freshness bound declared for timeframe '15m'"),
    "contract_key_missing": (lambda s: s["strategy"]["contract"].pop("cost_model_id"),
                             "contract descriptor missing keys"),
    "min_closed_bars_missing": (lambda s: s["strategy"]["contract"]["input_spec"].pop("min_closed_bars"),
                                "min_closed_bars"),
    "release_label_as_version": (lambda s: s["strategy"].update(version="rel-ea8ae4f"), "MAJOR.MINOR.PATCH"),
    "region_not_found": (lambda s: s["strategy"]["closure"][0].update(
        regions=[["entry_rule", "def:no_such_function"]]), "0 definitions"),
    "closure_file_not_executed": (lambda s: s["strategy"]["closure"].pop(1), "not the executed code files"),
    "closure_text_not_executed": (lambda s: s["strategy"]["closure"][0].update(
        text=s["strategy"]["closure"][0]["text"] + "# edited\n"), "differs from the executed code"),
}


@pytest.mark.parametrize("name", sorted(IDENTITY_FAILURES))
def test_missing_or_conflicting_identity_fails_closed(name):
    s = fx.scenario()
    mutate, match = IDENTITY_FAILURES[name]
    mutate(s)
    with pytest.raises(gr.HarnessIdentityError, match=match):
        replay(s)


def test_a_behaviour_change_cannot_hide_behind_an_unchanged_closure():
    with pytest.raises(gr.HarnessIdentityError, match="differs from the executed code"):
        replay(fx.scenario(), code=fx.WP2_CHANGED_CODE)


def test_identity_registry_refuses_one_label_with_two_identities():
    docs = [golden(s) for s in fx.SUITES]
    gr.check_identity_registry(docs)               # the committed golden files are consistent
    rogue = gr.replay_suite(gr.GoldenSuite(
        gr.wp2_decision_path("rogue", fx.WP2_PATCH_CODE),
        (gr.GoldenCase("same_label", fx.scenario(entry=fx.synthetic_rule_refactored)),)))
    with pytest.raises(gr.HarnessIdentityError, match="several identities"):
        gr.check_identity_registry(docs + [rogue])


# ── SE-38 PATCH/MINOR gate ─────────────────────────────────────────────────────────────────

def test_the_patch_gate_passes_on_byte_identical_decisions(baseline):
    gate = gr.semver_gate(baseline, gr.wp2_replay(fx.patch_scenario(), fx.WP2_PATCH_CODE))
    assert gate["verdict"] == "PASS_PATCH_MINOR"
    assert (gate["classification"], gate["version_step"]) == ("DECLARED_CHANGE", "PATCH")
    assert gate["decisions_identical"] is True and gate["first_difference"] is None
    assert gate["hash_changed"] == {"source_hash": True, "config_hash": False, "contract_hash": False}
    assert gate["boundary_required"] == "CONDITIONAL_ON_GOLDEN_REPLAY"


@pytest.mark.parametrize("kw, code, verdict, identical", [
    (dict(version="1.1.0", entry=fx.synthetic_rule_changed), fx.WP2_CHANGED_CODE, "FAIL_REQUIRES_MAJOR", False),
    (dict(version="1.0.1", WINDOW=2), fx.WP2_CODE, "FAIL_REQUIRES_MAJOR", False),
    (dict(version="2.0.0", entry=fx.synthetic_rule_changed), fx.WP2_CHANGED_CODE, "MAJOR_BOUNDARY_REQUIRED", False),
    (dict(version="2.0.0", entry=fx.synthetic_rule_refactored), fx.WP2_PATCH_CODE, "MAJOR_BOUNDARY_REQUIRED", True),
    (dict(version="0.9.0", entry=fx.synthetic_rule_refactored), fx.WP2_PATCH_CODE, "FAIL_VERSION_REGRESSION", True),
    (dict(version="1.0.1"), fx.WP2_CODE, "LABEL_ONLY_REVIEW", True),
    (dict(lineage=("synthetic_golden/0.1.0",)), fx.WP2_CODE, "NO_CHANGE", True),
], ids=["minor_changes_decisions", "patch_changes_config", "major_changes_decisions",
        "major_same_decisions", "version_regression", "label_only", "lineage_only"])
def test_semver_gate_verdicts(baseline, kw, code, verdict, identical):
    gate = gr.semver_gate(baseline, gr.wp2_replay(fx.scenario(**kw), code))
    assert (gate["verdict"], gate["decisions_identical"]) == (verdict, identical)
    assert (gate["first_difference"] is None) is identical


@pytest.mark.parametrize("kw, code", [
    (dict(entry=fx.synthetic_rule_refactored), fx.WP2_PATCH_CODE),
    (dict(WINDOW=2), fx.WP2_CODE),
], ids=["source_changed", "config_changed"])
def test_an_identity_change_under_the_same_label_is_a_stop(baseline, kw, code):
    with pytest.raises(gr.HarnessIdentityError, match="unchanged version label"):
        gr.semver_gate(baseline, gr.wp2_replay(fx.scenario(**kw), code))


def test_the_gate_refuses_another_strategy_or_other_observations(baseline):
    other = fx.scenario()
    other["strategy"]["strategy_id"] = "synthetic_other"
    with pytest.raises(gr.HarnessIdentityError, match="different strategy_id"):
        gr.semver_gate(baseline, replay(other))
    moved = fx.scenario()
    moved["cycles"][0]["observations"][0]["closes"][-1] += 1
    with pytest.raises(gr.HarnessInputError, match="different observations"):
        gr.semver_gate(baseline, replay(moved))


# ── detection of a deliberately changed fixture output (the WP-A04 acceptance criterion) ───

def _rehash(doc):
    for case in doc["cases"]:
        case["output_hash"] = gr.json_digest(case["output"])
    doc["suite_hash"] = gr.suite_hash(doc)


OUTPUT_EDITS = {
    "decision_reason": lambda o: o["decisions"][3].update(reason_code="F4.bar_stale"),
    "payload_value": lambda o: next(d for d in o["decisions"] if d["payload"])["payload"].update(upper=999),
    "identity_hash": lambda o: o["strategy"].update(identity_hash="0" * 64),
    "chain_head": lambda o: o["digests"].update(chain_head="f" * 64),
    "decision_dropped": lambda o: o["decisions"].pop(),
    "int_became_float": lambda o: o["decisions"][0].update(bar_close_ms=float(o["decisions"][0]["bar_close_ms"])),
    "conservation_count": lambda o: o["conservation"][0]["counts"].update(passed=3),
}


@pytest.mark.parametrize("rehash", [False, True], ids=["hand_edit", "rehashed_edit"])
@pytest.mark.parametrize("name", sorted(OUTPUT_EDITS))
def test_a_deliberately_changed_golden_output_is_detected(name, rehash):
    actual = gr.replay_suite(fx.WP2_SUITE)
    edited = copy.deepcopy(golden())
    OUTPUT_EDITS[name](edited["cases"][0]["output"])
    if rehash:
        _rehash(edited)
    diff = gr.compare_to_golden(actual, edited)
    assert not diff.ok and "output_changed" in diff.kinds
    assert ("golden_inconsistent" in diff.kinds) is (not rehash)
    mismatch = next(m for m in diff.mismatches if m.kind == "output_changed")
    assert mismatch.case_id == "baseline" and mismatch.pointer
    assert gr.json_text(gr.resolve_pointer(edited["cases"][0]["output"], mismatch.pointer)) == \
        gr.json_text(mismatch.golden)
    with pytest.raises(gr.GoldenMismatch, match="output_changed"):
        gr.assert_matches_golden(actual, edited)


def test_a_changed_integrated_path_output_is_detected():
    actual = gr.replay_suite(fx.A44_SUITE)
    edited = copy.deepcopy(golden(fx.A44_SUITE))
    edited["cases"][0]["output"]["rows"][1]["eligible"] = False
    _rehash(edited)
    diff = gr.compare_to_golden(actual, edited)
    assert diff.kinds == ("output_changed",)
    assert diff.mismatches[0].pointer == "/rows/1/eligible"


def test_golden_structure_changes_are_detected():
    actual, base = gr.replay_suite(fx.A44_SUITE), golden(fx.A44_SUITE)
    edits = {
        "case_added": lambda g: g["cases"].pop(),
        "case_missing": lambda g: g["cases"].append({**copy.deepcopy(g["cases"][0]), "case_id": "zz_extra"}),
        "path_metadata": lambda g: g.update(code_refs=["shared/signal_identity.py"]),
        "schema": lambda g: g.update(canonical_form="tsb-golden-canonical/0"),
        "input_changed": lambda g: g["cases"][0].update(input_hash="0" * 64),
    }
    for kind, edit in edits.items():
        g = copy.deepcopy(base)
        edit(g)
        _rehash(g)
        assert kind in gr.compare_to_golden(actual, g).kinds, kind


def test_a_changed_fixture_input_is_detected():
    s = fx.scenario()
    s["cycles"][0]["observations"][1]["closes"][-1] = 54          # SYNTHA 15m: a different payload
    diff = gr.compare_to_golden(gr.replay_suite(gr.GoldenSuite(fx.WP2_SUITE.path, (gr.GoldenCase("baseline", s),))),
                                golden())
    assert diff.kinds == ("input_changed", "output_changed")
    assert diff.mismatches[1].pointer.startswith("/decisions/")
    quiet = fx.scenario()
    quiet["cycles"][0]["observations"][3]["closes"][0] = 99      # SYNTHC (gap): the rule never reads it
    diff = gr.compare_to_golden(gr.replay_suite(gr.GoldenSuite(fx.WP2_SUITE.path,
                                                               (gr.GoldenCase("baseline", quiet),))), golden())
    assert diff.kinds == ("input_changed", "output_changed")
    assert diff.mismatches[1].pointer.startswith("/digests/")   # same decisions, other record hashes


def test_a_behaviour_change_in_the_wired_module_is_detected(monkeypatch):
    real = sid.freshness_at
    monkeypatch.setattr(sid, "freshness_at", lambda tf, close, decision_ms, *, max_age_bars=1.0:
                        real(tf, close, decision_ms, max_age_bars=0.5))
    diff = gr.check_suite(fx.A44_SUITE)
    assert diff.kinds == ("output_changed",)


# ── the integrated A44 path is the production call ─────────────────────────────────────────

def test_the_a44_adapter_calls_the_wired_function_with_production_arguments(monkeypatch):
    calls, real = [], sid.integrity_check

    def spy(data, **kw):
        calls.append(sorted(kw.items(), key=lambda kv: kv[0]))
        return real(data, **kw)
    monkeypatch.setattr(sid, "integrity_check", spy)
    gr.replay_suite(fx.A44_SUITE, repeats=1)
    assert len(calls) == sum(len(c.inputs["candidates"]) for c in fx.A44_SUITE.cases)
    assert {tuple(k for k, _ in kw) for kw in calls} == {
        ("allow_pit_fallback", "decision_ms", "emitted_keys", "strategy_version")}
    assert all(dict(kw)["allow_pit_fallback"] is False for kw in calls)


def test_the_mirrored_call_site_still_reads_as_the_adapter_assumes():
    text = (ROOT / "signal_engine" / "signal_logic.py").read_text(encoding="utf-8")
    assert re.search(r"verdict = integrity_check\(data, decision_ms=decision_ms,\s+strategy_version=config\.APP_VERSION,"
                     r" emitted_keys=emitted,\s+allow_pit_fallback=False\)", text)
    assert "reason = verdict.reasons[0]" in text
    assert re.search(r"'bracket_hash': bracket_hash\(data\)", text)


# ── canonical form ─────────────────────────────────────────────────────────────────────────

def test_canonical_value_encodings():
    cv = gr.canonical_value
    assert cv((1, [2.5, None, True], "x")) == [1, [2.5, None, True], "x"]
    assert [cv(float(v)) for v in ("nan", "inf", "-inf")] == [
        {"__float__": "nan"}, {"__float__": "+inf"}, {"__float__": "-inf"}]
    assert cv(decimal.Decimal("1.50")) == {"__decimal__": "1.50"}
    assert cv(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=1)) == {"__utc_us__": 1_000_000}
    assert cv(timedelta(milliseconds=3)) == {"__timedelta_us__": 3000}
    assert cv(b"\x00\xff") == {"__bytes__": "00ff"}
    assert cv({3, 1, 2}) == {"__set__": [1, 2, 3]}
    assert cv(sid.Freshness(True, None, 5, 0.5)) == {"__dataclass__": "Freshness", "fields": {
        "admissible": True, "reason": None, "age_ms": 5, "age_bars": 0.5}}
    assert cv(MappingProxyType({"b": (1,)})) == {"b": [1]}
    assert gr.canonical_bytes({"b": 1, "a": [2, 1]}) == b'{"a":[2,1],"b":1}'


class _Color(enum.Enum):
    RED = 1


@pytest.mark.parametrize("bad", [datetime(2026, 1, 1), {1: "x"}, {"__float__": 1}, object(), _Color.RED,
                                 datetime(2026, 1, 1).date()],
                         ids=["naive_datetime", "int_key", "reserved_key", "object", "enum", "date"])
def test_values_without_a_canonical_form_are_refused(bad):
    with pytest.raises(gr.GoldenFormError):
        gr.canonical_value(bad)


def test_numpy_values_reduce_to_plain_json():
    np = pytest.importorskip("numpy")
    assert type(gr.canonical_value(np.float64(1.5))) is float
    assert type(gr.canonical_value(np.int64(7))) is int
    assert gr.canonical_value(np.bool_(True)) is True
    assert gr.canonical_value(np.array([[1, 2]])) == [[1, 2]]
    assert gr.canonical_value(np.float64("nan")) == {"__float__": "nan"}


def test_first_difference_is_strict_and_deterministic():
    fd = gr.first_difference
    assert fd({"a": 1}, {"a": 1.0}) == "/a"
    assert fd({"a": True}, {"a": 1}) == "/a"
    assert fd([1, 2], [1, 2, 3]) == "/2"
    assert fd({"b": 1, "a/x": 2}, {"b": 2, "a/x": 3}) == "/a~1x"
    assert fd({"x": [1, {"y": None}]}, {"x": [1, {"y": None}]}) is None
    assert gr.resolve_pointer({"a/x": [5]}, "/a~1x/0") == 5


# ── regeneration is an explicit opt-in; the CLI ────────────────────────────────────────────

def test_regeneration_is_an_explicit_opt_in(tmp_path, capsys):
    doc = gr.replay_suite(fx.A44_SUITE)
    for flag in (False, None, 1, "yes"):
        with pytest.raises(gr.RegenerationRefused):
            gr.write_golden(doc, tmp_path / "x.json", regenerate=flag)
    assert not (tmp_path / "x.json").exists()
    before = {s.golden_name: s.golden_file.read_bytes() for s in fx.SUITES}
    assert gr.main(["regenerate"]) == 2                          # no suite named: nothing written
    assert "name each suite explicitly" in capsys.readouterr().err
    assert {s.golden_name: s.golden_file.read_bytes() for s in fx.SUITES} == before


def test_check_reports_a_mismatch_and_a_missing_golden(tmp_path, monkeypatch, capsys):
    edited = golden(fx.A44_SUITE)
    edited["cases"][0]["output"]["rows"][0]["decision"] = "admissible"
    _rehash(edited)
    (tmp_path / "a44_enforce_integrity_step.json").write_text(gr.render_golden(edited), encoding="ascii")
    monkeypatch.setattr(gr, "GOLDEN_DIR", tmp_path)
    assert gr.main(["check", "--suite", "golden_replay_fixtures:A44_SUITE"]) == 1
    out = capsys.readouterr().out
    assert "a44_enforce_integrity_step: MISMATCH" in out and "/rows/0/decision" in out
    assert gr.main(["check", "--suite", "golden_replay_fixtures:WP2_SUITE"]) == 2
    assert "golden file missing" in capsys.readouterr().err


def test_suite_specs_are_validated():
    assert gr.load_suites(["golden_replay_fixtures:A44_SUITE"]) == (fx.A44_SUITE,)
    for bad in ("golden_replay_fixtures", "no_such_module_x:SUITES", "golden_replay_fixtures:NOPE",
                "golden_replay_fixtures:STRATEGY_ID"):
        with pytest.raises(gr.HarnessInputError):
            gr.load_suites([bad])


# ── purity, isolation and the protected scan ───────────────────────────────────────────────

def test_replays_touch_no_file_clock_environment_or_network(monkeypatch):
    base_in, patch_in = fx.scenario(), fx.patch_scenario()       # built before the refusals

    def refuse(*_a, **_k):
        raise AssertionError("forbidden side effect")

    class RefusingEnviron(dict):
        def __getitem__(self, key):
            refuse()
        get = __contains__ = keys = items = __iter__ = __getitem__

    for target, name in ((builtins, "open"), (socket, "socket"), (socket, "create_connection"),
                         (time, "time"), (time, "time_ns"), (time, "monotonic"), (os, "getenv"),
                         (pathlib.Path, "read_bytes"), (pathlib.Path, "read_text"),
                         (pathlib.Path, "write_bytes"), (pathlib.Path, "write_text"), (pathlib.Path, "open"),
                         (subprocess, "run"), (subprocess, "Popen")):
        monkeypatch.setattr(target, name, refuse)
    monkeypatch.setattr(os, "environ", RefusingEnviron())
    for suite in fx.SUITES:
        gr.replay_suite(suite)
    before, after = gr.wp2_replay(base_in, fx.WP2_CODE), gr.wp2_replay(patch_in, fx.WP2_PATCH_CODE)
    assert gr.semver_gate(before, after)["verdict"] == "PASS_PATCH_MINOR"
    gr.verify_export(before.export())


def test_the_harness_imports_no_service_or_io_module():
    code = ('import json, sys; sys.path[:0] = [".", "tests"]; import golden_replay, golden_replay_fixtures; '
            'bad = sorted(m for m in sys.modules if m.split(".")[0] in ("analyzer", "scanner", "signal_engine", '
            '"telegram", "trade_tracker", "research", "asyncpg", "aiohttp", "pandas", "numpy") or m in '
            '("shared.config", "shared.database", "shared.evidence_v2")); print(json.dumps(bad))')
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env=MIN_ENV, check=True, timeout=120)
    assert json.loads(out.stdout) == []


def test_committed_files_pass_the_repository_protected_scan():
    spec = importlib.util.spec_from_file_location("protected_scan_for_golden_tests",
                                                  ROOT / "ops" / "provenance" / "protected_scan.py")
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    files = [s.golden_file for s in fx.SUITES] + [ROOT / "tests" / "golden_replay.py",
                                                  ROOT / "tests" / "golden_replay_fixtures.py",
                                                  pathlib.Path(__file__)]
    hits = [(f.name, n) for f in files
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if scan.PROTECTED.search(line)]
    assert hits == []
