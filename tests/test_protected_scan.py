"""Tests for ops/provenance/protected_scan.py: the started_at exception is exact, and everything else still blocks.

Forbidden strings are assembled at runtime so that this file never matches the scan itself.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ops", "provenance"))
import protected_scan as S  # noqa: E402

C = ":"
TS = "2026-10-22T17" + C + "45" + C + "31.526552554Z"          # a container StartedAt
TS2 = "2026-10-16T22" + C + "19" + C + "12.953101358Z"
PW = "pass" + "word"


def manifest(collector_ts=TS, extra=None, learner_ts=None):
    m = {"observed_at": "2026-10-18T11" + C + "58" + C + "35Z",
         "services": {"collector": {"container": "tsb-p2-forward-collector",
                                    "observed": {"started_at": collector_ts, "restart_count": 0}},
                      "analyzer": {"container": "trading_analyzer", "observed": {"started_at": TS2}}}}
    if learner_ts:
        m["services"]["continuous_learner"] = {"container": "trading_continuous_learner",
                                               "observed": {"started_at": learner_ts}}
    if extra:
        extra(m)
    return json.dumps(m, indent=1, sort_keys=True) + "\n"


def diff(path, added):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n" + \
        "".join("+" + l + "\n" for l in added)


def run(path, added, head):
    return S.scan(diff(path, added), lambda p: head if p == path else None)


LINE = f'    "started_at": "{TS}",'


def test_exact_started_at_in_deployed_json_passes():
    assert run(S.EXEMPT_FILE, [LINE], manifest()) == []
    assert run(S.EXEMPT_FILE, [LINE.rstrip(",")], manifest()) == []


def test_same_timestamp_in_unrelated_document_blocks():
    assert run("docs/ops/NOTE.md", [f"started at {TS}"], manifest())
    assert run("deploy/rc-20261022/RECORD.md", [LINE], manifest())


def test_scientific_evidence_timestamp_blocks():
    for p in ("research/evidence/holdout_outcomes.json", "deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json"):
        assert run(p, [LINE], manifest()), p


def test_other_field_in_deployed_json_blocks():
    assert run(S.EXEMPT_FILE, [f'  "observed_at": "{TS}",'], manifest())
    assert run(S.EXEMPT_FILE, [f'  "notes": "restart at {TS}",'], manifest())


def test_started_at_under_non_enumerated_path_blocks():
    def put(m):
        m["services"]["collector"]["provenance"] = {"started_at": TS}
    head = manifest(collector_ts=TS2, extra=put)
    assert run(S.EXEMPT_FILE, [LINE], head)


def test_learner_started_at_is_never_exempt():
    head = manifest(collector_ts=TS2, learner_ts=TS)
    assert run(S.EXEMPT_FILE, [LINE], head)


def test_value_smuggled_elsewhere_in_file_blocks():
    def put(m):
        m["note"] = "copy " + TS
    assert run(S.EXEMPT_FILE, [LINE], manifest(extra=put))
    def key(m):
        m[TS] = 1
    assert run(S.EXEMPT_FILE, [LINE], manifest(extra=key))


def test_non_iso_or_invalid_calendar_values_block():
    for bad in ("2026-10-22 17" + C + "45" + C + "31Z", "2026-10-22T17" + C + "45" + C + "31+02:00",
                "2026-13-45T25" + C + "61" + C + "61Z", "2026-10-22T17" + C + "45" + C + "31.1234567890Z",
                "x 2026-10-22T17" + C + "45" + C + "31Z"):
        head = manifest(collector_ts=bad)
        assert run(S.EXEMPT_FILE, [f'    "started_at": "{bad}",'], head), bad


def test_line_with_more_content_blocks():
    assert run(S.EXEMPT_FILE, [f'    "started_at": "{TS}", "x": 1'], manifest())
    assert run(S.EXEMPT_FILE, [f'    "started_at": "{TS}" // {TS}'], manifest())


def test_value_not_in_head_blocks():
    assert run(S.EXEMPT_FILE, [f'    "started_at": "{TS2.replace("19", "20", 1)}",'], manifest())


def test_other_patterns_are_never_exempt_even_on_started_at_line():
    assert run(S.EXEMPT_FILE, [f'    "started_at": "{TS}", "{PW}": "x"'], manifest())
    assert run(S.EXEMPT_FILE, [f'  "{PW}": "x",'], manifest())


def test_unparsable_head_blocks():
    assert run(S.EXEMPT_FILE, [LINE], "{not json")


def test_scanner_and_test_sources_are_scan_clean():
    for p in (os.path.join(ROOT, "ops", "provenance", "protected_scan.py"), os.path.abspath(__file__)):
        bad = [l for l in open(p).read().splitlines() if S.PROTECTED.search(l) and not S.ALLOW.search(l)]
        assert bad == [], (p, bad[:3])


def test_verify_docker_matches_and_mismatches():
    head = manifest()
    live = {"tsb-p2-forward-collector": TS, "trading_analyzer": TS2}
    assert S.verify_docker(head, live.get) == []
    live["tsb-p2-forward-collector"] = TS2
    bad = S.verify_docker(head, live.get)
    assert [b[0] for b in bad] == ["collector"]


def test_real_deployed_json_is_eligible():
    head = open(os.path.join(ROOT, "deploy", "DEPLOYED.json")).read()
    vals = S.exempt_values(head)
    for svc, (container, v) in S.exempted_started_at(head).items():
        assert v in vals, svc
