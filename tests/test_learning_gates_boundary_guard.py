"""WP-F03 test 3 (R9.d2; register R9 test 3): LEARNING_GATES_ENABLED cannot become true without a boundary record.

Design: docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md section 5 (record) and section 6.2 (G-1 to G-10).

`check_learning_gates(config, entries, gates_digest, config_hash)` is the pure guard. It reads nothing:
  config        non-secret mapping of effective values; only LEARNING_GATES_ENABLED is looked at;
  entries       parsed deploy/VERSION_BOUNDARY.md entries (`parse_boundary_entries`), in file order;
  gates_digest  the learned_gates_digest of the current rows (section 5.3), or None when not observed;
  config_hash   the strategy config_hash of the presented configuration, or None when not observed.
It returns (status, reasons) in the drift-check vocabulary (MATCH, UNKNOWN, SAFETY;
ops/provenance/drift_check.py). The presented hash is a separate argument because the guard never computes one.

Parsing is stricter than the runtime (`.lower() == 'true'`, shared/config.py:L102): only true/false in any
case is accepted; any other value is UNKNOWN (fail-closed), even though the runtime would read it as false.

Gate entries are the VERSION_BOUNDARY.md entries that carry `learning_gates_enabled_after`. With the flag true, the
latest gate entry must declare true, cite an approval, and carry 64-hex `config_hash_after` and
`learned_gates_digest` equal to the presented values; PENDING or missing fields are SAFETY. Later fenced blocks
under the same `## VB-...` heading are amendments and override earlier values (VB-2026-10-27-01 style).
These field names are the section 5.3 proposal; WP-A01 owns their final form in deploy/VERSION_BOUNDARY_TEMPLATE.md.

The static tests below apply the guard to every tracked surface that could carry the flag and that a test may read:
the runtime default in shared/config.py, every tracked Compose file and the committed non-secret configuration
snapshots. They cannot see the host .env (never read, by rule), so the runtime value is the pre-deploy check's
job: a drift-check reading of the container environment in memory, as D8 does for PAPER_TRADING (integration
point, section 6.3; an edit of an existing ops/ file under its own owner gate).
"""
import json
import pathlib
import re
from collections.abc import Mapping

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLAG = "LEARNING_GATES_ENABLED"
MATCH, UNKNOWN, SAFETY = "MATCH", "UNKNOWN", "SAFETY"
PENDING = "PENDING"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
GATE_FIELD = "learning_gates_enabled_after"

_HEADING = re.compile(r"^## (VB-\d{4}-\d{2}-\d{2}-\d{2})\b")
_FIELD = re.compile(r"^([a-z][a-z0-9_]*)\s*:\s?(.*)$")
_ABSENT = object()


# ------------------------------------------------------------------ pure guard

def parse_flag(raw):
    """(value, how): value is True, False or None (ambiguous)."""
    if raw is _ABSENT or raw is None:
        return False, "default"
    if isinstance(raw, bool):
        return raw, "literal"
    if isinstance(raw, str) and raw.lower() in ("true", "false"):
        return raw.lower() == "true", "literal"
    return None, "ambiguous"


def _first_word(value):
    return value.split()[0] if isinstance(value, str) and value.split() else ""


def _latest_gate_entry(entries):
    gate = [e for e in entries if GATE_FIELD in e]
    return gate[-1] if gate else None


def check_learning_gates(config, entries, gates_digest, config_hash):
    """Pure: no clock, environment, file or network access; inputs are not mutated."""
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    flag, how = parse_flag(config.get(FLAG, _ABSENT))
    if flag is None:
        return UNKNOWN, [f"{FLAG} is neither true nor false (fail-closed)"]
    latest = _latest_gate_entry(list(entries))
    declared_raw = _first_word(latest.get(GATE_FIELD)) if latest is not None else ""
    declared = parse_flag(declared_raw)[0] if declared_raw else None
    if not flag:
        if latest is not None and declared is not False:
            return UNKNOWN, [f"latest gate entry {latest.get('boundary_id')} does not declare the gates off, "
                             "but the configuration presents false (record and runtime disagree)"]
        return MATCH, ["default (runtime default false)" if how == "default" else "flag false"]
    if latest is None:
        return SAFETY, [f"{FLAG} true without a version-boundary record"]
    reasons = []
    if declared is not True:
        reasons.append(f"latest gate entry {latest.get('boundary_id')} does not declare the gates active")
    approval = (latest.get("approval") or "").strip()
    if not approval or approval.upper().startswith(PENDING):
        reasons.append("no approval reference")
    for field, presented in (("config_hash_after", config_hash), ("learned_gates_digest", gates_digest)):
        recorded = _first_word(latest.get(field))
        if not HEX64.match(recorded):
            reasons.append(f"{field} missing or PENDING")
        elif presented is None:
            reasons.append(f"{field} cannot be verified: no current value presented")
        elif recorded != presented:
            reasons.append(f"{field} differs from the presented value")
    if reasons:
        return SAFETY, reasons
    return MATCH, [f"boundary record {latest.get('boundary_id')} matches"]


def record_completeness_status(raw, entries):
    """Tracked-file mode. CI has neither the live rows nor the live configuration hash, so for a true value the
    record must be complete and approved; equality with live values is the pre-deploy check (module docstring)."""
    latest = _latest_gate_entry(entries)
    digest = _first_word((latest or {}).get("learned_gates_digest")) or None
    cfg = _first_word((latest or {}).get("config_hash_after")) or None
    config = {} if raw is _ABSENT else {FLAG: raw}
    return check_learning_gates(config, entries, digest, cfg)


def parse_boundary_entries(text):
    """`## VB-...` entries of deploy/VERSION_BOUNDARY.md; fields from their fenced blocks, later blocks amend."""
    entries, current, in_fence, field = [], None, False, None
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m and not in_fence:
            current = {"boundary_id": m.group(1)}
            entries.append(current)
            continue
        if line.startswith("## ") and not in_fence:
            current = None
            continue
        if line.strip().startswith("```"):
            in_fence, field = not in_fence, None
            continue
        if not in_fence or current is None:
            continue
        m = _FIELD.match(line)
        if m:
            field = m.group(1)
            current[field] = m.group(2).strip()
        elif field and line.startswith(" ") and line.strip():
            current[field] = (current[field] + " " + line.strip()).strip()
    return entries


# ------------------------------------------------------------------ tracked-surface readers (no .env)

_COMPOSE_MAP = re.compile(r"^\s+" + FLAG + r"\s*:\s*(.*?)\s*(?:#.*)?$")
_COMPOSE_LIST = re.compile(r"^\s+-\s*[\"']?" + FLAG + r"=([^\"'#\s]*)[\"']?\s*(?:#.*)?$")
_INTERP = re.compile(r"^\$\{" + FLAG + r"(?::?-(.*))?\}$")


def compose_flag_values(text):
    """[(line number, raw value or _ABSENT)] for every non-comment line naming the flag; an unrecognised form
    raises AssertionError (fail-closed). `${FLAG}` without a default is not pinned by the blob: _ABSENT."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if FLAG not in line or line.lstrip().startswith("#"):
            continue
        m = _COMPOSE_MAP.match(line) or _COMPOSE_LIST.match(line)
        if not m:
            raise AssertionError(f"line {n}: unrecognised form naming {FLAG}")
        value = m.group(1).strip().strip("\"'")
        im = _INTERP.match(value)
        if im:
            value = _ABSENT if im.group(1) is None else im.group(1)
        out.append((n, value))
    return out


def tracked_compose_files():
    files = sorted(ROOT.glob("docker-compose*.yml*")) + sorted(ROOT.glob("*/compose*.yml"))
    return [p for p in files if p.is_file()]


def _entries():
    return parse_boundary_entries((ROOT / "deploy" / "VERSION_BOUNDARY.md").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ static guards over tracked files

def test_runtime_code_default_is_false():
    text = (ROOT / "shared" / "config.py").read_text(encoding="utf-8")
    found = re.findall(FLAG + r"\s*:\s*bool\s*=\s*os\.getenv\('" + FLAG + r"',\s*'([^']*)'\)\.lower\(\)\s*==\s*'true'",
                       text)
    assert found == ["false"], "the runtime default must stay false; a change needs a boundary record"


def test_version_boundary_file_parses():
    entries = _entries()
    assert entries and entries[0]["boundary_id"] == "VB-2026-10-27-01"
    assert entries[0]["policy_version_after"].startswith("econ-observe-v1")
    assert all(_HEADING.match("## " + e["boundary_id"]) for e in entries)


def test_compose_files_cannot_enable_gates_without_a_record():
    entries = _entries()
    files = tracked_compose_files()
    assert ROOT / "docker-compose.yml" in files
    problems = []
    seen_any = False
    for path in files:
        values = compose_flag_values(path.read_text(encoding="utf-8"))
        seen_any = seen_any or bool(values)
        for n, raw in values or [(None, _ABSENT)]:
            status, reasons = record_completeness_status(raw, entries)
            if status != MATCH:
                problems.append(f"{path.relative_to(ROOT)}:{n}: {status} {reasons}")
    assert not problems, problems


def test_committed_nonsecret_config_snapshots_cannot_show_gates_on_without_a_record():
    entries = _entries()
    snapshots = sorted((ROOT / "deploy").glob("**/*.nonsecret.json"))
    problems = []
    for path in snapshots:
        doc = json.loads(path.read_text(encoding="utf-8"))
        raw = doc.get(FLAG, _ABSENT) if isinstance(doc, dict) else _ABSENT
        status, reasons = record_completeness_status(raw, entries)
        if status != MATCH:
            problems.append(f"{path.relative_to(ROOT)}: {status} {reasons}")
    assert not problems, problems


def test_today_no_record_declares_gates_active():
    """Facts at this commit (VER-03): gates off, no gate boundary entry, so the default path is MATCH."""
    entries = _entries()
    assert _latest_gate_entry(entries) is None
    assert record_completeness_status(_ABSENT, entries) == (MATCH, ["default (runtime default false)"])


# ------------------------------------------------------------------ G-1 to G-10 (synthetic)

H_CFG, H_DIG, H_OTHER = "a" * 64, "b" * 64, "c" * 64


def _entry(**over):
    e = {"boundary_id": "VB-2099-01-01-01", GATE_FIELD: "true", "config_hash_after": H_CFG,
         "learned_gates_digest": H_DIG, "approval": "owner approval OA-1 for this activation"}
    e.update(over)
    return e


def _check(flag=_ABSENT, entries=(), digest=H_DIG, cfg=H_CFG):
    config = {} if flag is _ABSENT else {FLAG: flag}
    return check_learning_gates(config, list(entries), digest, cfg)


def test_g1_false_is_match():
    assert _check("false") == (MATCH, ["flag false"])


def test_g2_absent_is_match_by_default():
    assert _check() == (MATCH, ["default (runtime default false)"])


def test_g3_true_without_entry_is_safety():
    assert _check("true")[0] == SAFETY


def test_g4_true_any_case_without_entry_is_safety():
    for value in ("TRUE", "True", "tRuE", True):
        assert _check(value)[0] == SAFETY, value


@pytest.mark.parametrize("value", ["1", "yes", " true", "true ", "on", "", "ture", 1])
def test_g5_ambiguous_value_is_unknown(value):
    assert _check(value)[0] == UNKNOWN


def test_g6_config_hash_mismatch_is_safety():
    status, reasons = _check("true", [_entry()], cfg=H_OTHER)
    assert status == SAFETY and reasons == ["config_hash_after differs from the presented value"]


def test_g7_rows_rewritten_after_record_is_safety():
    status, reasons = _check("true", [_entry()], digest=H_OTHER)
    assert status == SAFETY and reasons == ["learned_gates_digest differs from the presented value"]


@pytest.mark.parametrize("over", [
    {"config_hash_after": "PENDING (first evidence record)"},
    {"learned_gates_digest": "PENDING"},
    {"approval": ""},
    {"approval": "PENDING owner"},
    {"config_hash_after": H_CFG[:63]},
])
def test_g8_pending_or_unapproved_entry_is_safety(over):
    assert _check("true", [_entry(**over)])[0] == SAFETY


@pytest.mark.parametrize("field", ["approval", "config_hash_after", "learned_gates_digest"])
def test_g8_missing_field_is_safety(field):
    entry = _entry()
    del entry[field]
    assert _check("true", [entry])[0] == SAFETY


def test_g9_matching_approved_entry_is_match():
    assert _check("true", [_entry()]) == (MATCH, ["boundary record VB-2099-01-01-01 matches"])


def test_g10_false_but_latest_entry_declares_active_is_unknown():
    assert _check("false", [_entry()])[0] == UNKNOWN
    assert _check(_ABSENT, [_entry()])[0] == UNKNOWN


def test_latest_gate_entry_wins_and_non_gate_entries_are_ignored():
    off = _entry(boundary_id="VB-2099-02-01-01", **{GATE_FIELD: "false"})
    unrelated = {"boundary_id": "VB-2099-03-01-01", "policy_version_after": "x"}
    assert _check("false", [_entry(), off, unrelated])[0] == MATCH
    assert _check("true", [_entry(), off, unrelated])[0] == SAFETY
    assert _check("true", [off, _entry(boundary_id="VB-2099-04-01-01")])[0] == MATCH


def test_unparseable_declared_value_never_matches():
    assert _check("true", [_entry(**{GATE_FIELD: "yes"})])[0] == SAFETY
    assert _check("false", [_entry(**{GATE_FIELD: "maybe"})])[0] == UNKNOWN
    assert _check("false", [_entry(**{GATE_FIELD: ""})])[0] == UNKNOWN


def test_unverifiable_live_values_are_safety_when_true():
    assert _check("true", [_entry()], digest=None)[0] == SAFETY
    assert _check("true", [_entry()], cfg=None)[0] == SAFETY


def test_guard_is_pure_and_validates_its_input():
    entries = [_entry()]
    snapshot = json.dumps(entries, sort_keys=True)
    _check("true", entries)
    assert json.dumps(entries, sort_keys=True) == snapshot
    with pytest.raises(TypeError):
        check_learning_gates(["true"], [], H_DIG, H_CFG)


# ------------------------------------------------------------------ readers (synthetic)

_BOUNDARY_MD = """# Paper strategy version boundaries

## VB-2099-01-01-01: gates on

```
learning_gates_enabled_after : true
config_hash_after     : PENDING (filled by amendment)
learned_gates_digest  : {dig}
approval              : owner approval OA-1
rule                  : no pooling across the boundary;
                        no retroactive attribution
```

Amendment:

```
config_hash_after     : {cfg}
```

## Notes

```
learning_gates_enabled_after : false
```
""".format(dig=H_DIG, cfg=H_CFG)


def test_boundary_parser_reads_fields_continuations_and_amendments():
    entries = parse_boundary_entries(_BOUNDARY_MD)
    assert [e["boundary_id"] for e in entries] == ["VB-2099-01-01-01"]
    e = entries[0]
    assert e["config_hash_after"] == H_CFG
    assert e["rule"] == "no pooling across the boundary; no retroactive attribution"
    assert record_completeness_status("true", entries) == (MATCH, ["boundary record VB-2099-01-01-01 matches"])
    assert check_learning_gates({FLAG: "true"}, entries, H_OTHER, H_CFG)[0] == SAFETY


def test_compose_reader_forms():
    text = ("services:\n  signal_engine:\n    environment:\n"
            "      LEARNING_GATES_ENABLED: \"false\"   # pinned\n"
            "      # LEARNING_GATES_ENABLED: true  (comment only)\n"
            "  other:\n    environment:\n"
            "      - LEARNING_GATES_ENABLED=true\n"
            "      LEARNING_GATES_ENABLED: ${LEARNING_GATES_ENABLED:-TRUE}\n"
            "      LEARNING_GATES_ENABLED: ${LEARNING_GATES_ENABLED}\n")
    assert compose_flag_values(text) == [(4, "false"), (8, "true"), (9, "TRUE"), (10, _ABSENT)]
    with pytest.raises(AssertionError):
        compose_flag_values("x: [LEARNING_GATES_ENABLED=true]\n")


def test_compose_true_without_record_fails_the_static_guard():
    values = compose_flag_values("    environment:\n      LEARNING_GATES_ENABLED: \"true\"\n")
    assert record_completeness_status(values[0][1], _entries())[0] == SAFETY
