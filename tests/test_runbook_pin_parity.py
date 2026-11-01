"""WP-F03 test 1 (R9.d2; register R9 test 1): runbook image-pin parity, static over tracked files.

The image pins of the running bot services must agree across three places:

  deploy/DEPLOYED.json  -- the observed runtime baseline (`observed.image_ref` of every service of project
                           trading-signal-bot whose `expected_state` is `running`);
  docker-compose.yml    -- the reviewed Compose blob (`image:` of the same service);
  the runbooks          -- the pin paragraph of docs/ops/COMPOSE_OPERATIONS.md (plus its Class B image gate)
                           and the pin paragraph of CLAUDE.md.

No Docker, no `compose config`, no network, no .env file. Only image references (non-secret) are compared
and printed.

How a pin paragraph is read (the grammar a runbook correction must follow):
  * The paragraph is the bullet that starts with PIN_MARKER and runs to the next bullet, heading or blank line.
  * Events are read in order: a service name (backticked or bare), a backticked image reference
    (`name:tag`, `*` stands for the service name, `sha256:` digests are ignored) or a backticked
    `deploy/.../IMAGES.md` record. An image or a record is assigned to every service named since the last
    assignment. A record claim holds when that record contains the service's DEPLOYED image reference.
  * After a rollback/historical word (STOP_WORDS) service names are not collected until the next clause
    boundary (`;`, `. `, Arabic comma or semicolon), so rollback images are never read as pins.
  * Dated notes (`*<words> (YYYY-MM-DD...):*`, the runbook's existing dated-note style) are appended without
    rewriting history. For each service the claim in the latest-dated segment wins; undated text is oldest.

Expected state today (CON-01, REP:L1454 @ 5d977f2): COMPOSE_OPERATIONS.md still states that telegram and
trade_tracker run `tsb-a561-*:rel-ea8ae4f-r2`, and its Class B image gate points to the aiohttp record, which covers
only the scanner. Those two tests are strict xfail until the WP-F01 dated correction lands (R9.c); the WP-F01 PR
must then remove the markers, because a strict xfail that starts passing fails the suite.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOYED = ROOT / "deploy" / "DEPLOYED.json"
COMPOSE = ROOT / "docker-compose.yml"
RUNBOOK = ROOT / "docs" / "ops" / "COMPOSE_OPERATIONS.md"
CLAUDE_MD = ROOT / "CLAUDE.md"
PROJECT = "trading-signal-bot"

RUNBOOK_PIN_MARKER = "- **Pinned images.**"
CLAUDE_PIN_MARKER = "- **صور مثبّتة:**"
CLASS_B_HEADING = "## Class B"

SERVICE_NAMES = ("analyzer", "scanner", "signal_engine", "telegram", "trade_tracker")
STOP_WORDS = ("rollback", "historical", "earlier", "older", "التراجع", "تاريخي")

_EVENT = re.compile(
    r"`(?P<record>deploy/[A-Za-z0-9._/-]+/IMAGES\.md)`"
    r"|`(?P<image>(?!sha256:)[a-z0-9][a-z0-9._/*-]*:[A-Za-z0-9._*-]+)`"
    r"|(?<![A-Za-z0-9_./*-])(?P<service>" + "|".join(SERVICE_NAMES) + r")(?![A-Za-z0-9_-])"
    r"|(?P<stop>\b(?:" + "|".join(w for w in STOP_WORDS if w.isascii()) + r")\b|"
    + "|".join(w for w in STOP_WORDS if not w.isascii()) + r")"
    r"|(?P<boundary>;|\.\s|،|؛)"
)
_DATED = re.compile(r"\*[^*\n]{0,80}?\((\d{4}-\d{2}-\d{2})[^)\n]*\):\*")
_BACKTICKED_REF = re.compile(r"`([a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+)`")

_loader = importlib.machinery.SourceFileLoader(
    "parity_inventory_f03", str(ROOT / "ops" / "provenance" / "parity_inventory.py"))
_spec = importlib.util.spec_from_loader("parity_inventory_f03", _loader)
PI = importlib.util.module_from_spec(_spec)
_loader.exec_module(PI)


# ------------------------------------------------------------------ pure helpers

def pinned_services(manifest):
    """service -> DEPLOYED image_ref, for the running services of the bot project."""
    out = {}
    for name, svc in manifest["services"].items():
        if svc.get("compose_project") == PROJECT and svc.get("expected_state") == "running":
            out[name] = svc["observed"]["image_ref"]
    return out


def extract_bullet(text, marker):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(marker):
            out = [line]
            for nxt in lines[i + 1:]:
                if not nxt.strip() or nxt.startswith("- ") or nxt.startswith("#"):
                    break
                out.append(nxt)
            return "\n".join(out)
    raise AssertionError(f"pin paragraph starting with {marker!r} not found")


def extract_section(text, heading):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(heading):
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith("## "):
                    break
                out.append(nxt)
            return "\n".join(out)
    raise AssertionError(f"section {heading!r} not found")


def segments(paragraph):
    """[(date or '', text)] in order; the undated text before the first dated note has date ''."""
    marks = list(_DATED.finditer(paragraph))
    if not marks:
        return [("", paragraph)]
    out = [("", paragraph[:marks[0].start()])]
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(paragraph)
        out.append((m.group(1), paragraph[m.end():end]))
    return out


def segment_claims(text):
    """service -> ('image', expanded ref) | ('record', path), in the order of the text."""
    claims, pending, suppressed = {}, [], False
    for m in _EVENT.finditer(text):
        kind = m.lastgroup
        if kind == "boundary":
            suppressed = False
        elif kind == "stop":
            suppressed, pending = True, []
        elif kind == "service":
            if not suppressed and m.group("service") not in pending:
                pending.append(m.group("service"))
        elif kind in ("image", "record") and pending:
            for svc in pending:
                if kind == "image":
                    claims[svc] = ("image", m.group("image").replace("*", svc))
                else:
                    claims[svc] = ("record", m.group("record"))
            pending = []
    return claims


def effective_claims(paragraph):
    dated = sorted(enumerate(segments(paragraph)), key=lambda item: (item[1][0], item[0]))
    out = {}
    for _, (_, text) in dated:
        out.update(segment_claims(text))
    return out


def pin_mismatches(paragraph, pinned, read_record):
    """Every pinned service must have an effective claim, and the claim must equal DEPLOYED."""
    claims = effective_claims(paragraph)
    problems = []
    for svc, ref in sorted(pinned.items()):
        claim = claims.get(svc)
        if claim is None:
            problems.append(f"{svc}: no pin statement")
        elif claim[0] == "image" and claim[1] != ref:
            problems.append(f"{svc}: runbook states {claim[1]}, DEPLOYED.json records {ref}")
        elif claim[0] == "record":
            body = read_record(claim[1])
            if body is None:
                problems.append(f"{svc}: cited record {claim[1]} does not exist")
            elif f"`{ref}`" not in body:
                problems.append(f"{svc}: cited record {claim[1]} does not record {ref}")
    return problems


def gate_uncovered(section, pinned, read_record):
    """Services whose DEPLOYED image is in none of the records the Class B section cites as an image gate.

    Citing deploy/DEPLOYED.json covers every service, because it is the canonical pin record.
    """
    if "deploy/DEPLOYED.json" in section:
        return []
    covered = set()
    for path in sorted(set(re.findall(r"deploy/[A-Za-z0-9._/-]+/IMAGES\.md", section))):
        body = read_record(path)
        if body is not None:
            covered.update(_BACKTICKED_REF.findall(body))
    return sorted(svc for svc, ref in pinned.items() if ref not in covered)


def read_repo_record(path):
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.is_file() else None


def _pinned():
    return pinned_services(json.loads(DEPLOYED.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ repository guards

def test_deployed_lists_the_five_running_bot_services():
    assert set(_pinned()) == {"analyzer", "scanner", "signal_engine", "telegram", "trade_tracker"}


def test_compose_images_equal_deployed():
    images = PI.compose_images(COMPOSE)
    problems = [f"{svc}: compose {images.get(svc)}, DEPLOYED.json {ref}"
                for svc, ref in sorted(_pinned().items()) if images.get(svc) != ref]
    assert not problems, problems


def test_deployed_provenance_records_contain_the_image():
    manifest = json.loads(DEPLOYED.read_text(encoding="utf-8"))
    problems = []
    for svc, ref in sorted(pinned_services(manifest).items()):
        records = [e for e in manifest["services"][svc]["provenance"]["evidence"] if e.endswith("IMAGES.md")]
        if not any(f"`{ref}`" in (read_repo_record(r) or "") for r in records):
            problems.append(f"{svc}: no IMAGES.md in its provenance evidence records {ref}")
    assert not problems, problems


def test_claude_md_pin_paragraph_matches_deployed():
    paragraph = extract_bullet(CLAUDE_MD.read_text(encoding="utf-8"), CLAUDE_PIN_MARKER)
    problems = pin_mismatches(paragraph, _pinned(), read_repo_record)
    assert not problems, problems


@pytest.mark.xfail(strict=True, reason=(
    "CON-01 (REP:L1454 @ 5d977f2), R9.c: COMPOSE_OPERATIONS.md L40-48 still pins telegram and trade_tracker to "
    "tsb-a561-*; fixed by the WP-F01 dated correction, whose PR must remove this marker"))
def test_runbook_pin_paragraph_matches_deployed():
    paragraph = extract_bullet(RUNBOOK.read_text(encoding="utf-8"), RUNBOOK_PIN_MARKER)
    problems = pin_mismatches(paragraph, _pinned(), read_repo_record)
    assert not problems, problems


@pytest.mark.xfail(strict=True, reason=(
    "CON-01 (REP:L1454 @ 5d977f2), R9.c: the Class B image gate (COMPOSE_OPERATIONS.md L113-115, L124-125) cites "
    "only deploy/aiohttp-3.14.3/IMAGES.md, which records the scanner alone; fixed by WP-F01"))
def test_runbook_class_b_image_gate_covers_every_running_service():
    section = extract_section(RUNBOOK.read_text(encoding="utf-8"), CLASS_B_HEADING)
    assert gate_uncovered(section, _pinned(), read_repo_record) == []


def test_runbook_mismatch_today_is_exactly_con01():
    """Pins the shape of the known stale statement, so the xfail above cannot hide a different defect."""
    paragraph = extract_bullet(RUNBOOK.read_text(encoding="utf-8"), RUNBOOK_PIN_MARKER)
    problems = pin_mismatches(paragraph, _pinned(), read_repo_record)
    assert sorted(p.split(":", 1)[0] for p in problems) in ([], ["telegram", "trade_tracker"])


# ------------------------------------------------------------------ parser behaviour (synthetic)

PINNED = {"analyzer": "tsb-a561-analyzer:r2", "telegram": "tsb-obs-telegram:o2", "scanner": "tsb-scan:s1"}
RECORDS = {"deploy/scan/IMAGES.md": "| scanner | `tsb-scan:s1` |", "deploy/old/IMAGES.md": "| x | `tsb-other:z` |"}


def _read(path):
    return RECORDS.get(path)


def test_wildcard_expansion_and_record_claim():
    text = ("- **Pinned images.** `analyzer` runs `tsb-a561-*:r2`, `telegram` runs `tsb-obs-*:o2`, "
            "and `scanner` runs the image in `deploy/scan/IMAGES.md`.")
    assert pin_mismatches(text, PINNED, _read) == []


def test_stale_pin_is_reported():
    text = "- **Pinned images.** `analyzer` and `telegram` run `tsb-a561-*:r2`; `scanner` in `deploy/scan/IMAGES.md`."
    assert pin_mismatches(text, PINNED, _read) == [
        "telegram: runbook states tsb-a561-telegram:r2, DEPLOYED.json records tsb-obs-telegram:o2"]


def test_dated_note_supersedes_the_older_statement():
    text = ("- **Pinned images.** `analyzer` and `telegram` run `tsb-a561-*:r2`; `scanner` in `deploy/scan/IMAGES.md`.\n"
            "  *Dated correction (2026-11-01):* `telegram` runs `tsb-obs-*:o2`; rollback `tsb-a561-*:r2`.")
    assert pin_mismatches(text, PINNED, _read) == []


def test_later_dated_note_wins_over_earlier_dated_note():
    text = ("- **Pinned images.** `telegram` runs `tsb-obs-*:o2`.\n"
            "  *Note (2026-12-01):* `telegram` runs `tsb-new-*:n1`.\n"
            "  *Note (2026-11-01):* `telegram` runs `tsb-obs-*:o2`.")
    assert effective_claims(text)["telegram"] == ("image", "tsb-new-telegram:n1")


def test_rollback_and_historical_images_are_not_pins():
    text = ("- **Pinned images.** `telegram` runs `tsb-obs-*:o2`. The rollback image for `analyzer` is "
            "`tsb-old-*:x`; `analyzer` runs `tsb-a561-*:r2`, and `scanner` in `deploy/scan/IMAGES.md`.")
    assert pin_mismatches(text, PINNED, _read) == []
    assert effective_claims(text)["analyzer"] == ("image", "tsb-a561-analyzer:r2")


def test_missing_service_and_bad_record_are_reported():
    text = "- **Pinned images.** `analyzer` runs `tsb-a561-*:r2`; `scanner` in `deploy/old/IMAGES.md`."
    assert pin_mismatches(text, PINNED, _read) == [
        "scanner: cited record deploy/old/IMAGES.md does not record tsb-scan:s1",
        "telegram: no pin statement"]
    text2 = "- **Pinned images.** `analyzer` runs `tsb-a561-*:r2`; `telegram` runs `tsb-obs-*:o2`; `scanner` in `deploy/none/IMAGES.md`."
    assert pin_mismatches(text2, PINNED, _read) == ["scanner: cited record deploy/none/IMAGES.md does not exist"]


def test_digests_and_flag_literals_are_not_image_refs():
    text = "`telegram` runs (`sha256:abc`, `PAPER_ECONOMIC_HALT_MODE=observe`, `image:`) `tsb-obs-*:o2`."
    assert segment_claims(text) == {"telegram": ("image", "tsb-obs-telegram:o2")}


def test_bare_arabic_service_names_are_read():
    text = "- **صور مثبّتة:** analyzer و telegram على `tsb-x-*:t1` (صور التراجع `tsb-y-*:t0`)، و scanner على `deploy/scan/IMAGES.md`."
    assert effective_claims(text) == {"analyzer": ("image", "tsb-x-analyzer:t1"),
                                      "telegram": ("image", "tsb-x-telegram:t1"),
                                      "scanner": ("record", "deploy/scan/IMAGES.md")}


def test_missing_paragraph_fails_closed():
    with pytest.raises(AssertionError):
        extract_bullet("# nothing here\n", RUNBOOK_PIN_MARKER)


def test_gate_coverage_rules():
    assert gate_uncovered("gate: `deploy/scan/IMAGES.md`", PINNED, _read) == ["analyzer", "telegram"]
    assert gate_uncovered("gate: the image recorded in `deploy/DEPLOYED.json`", PINNED, _read) == []


def test_a_wp_f01_style_dated_correction_turns_the_real_runbook_green():
    """Proves the fix path on the real paragraph: appending one dated note (no history rewritten) is enough."""
    paragraph = extract_bullet(RUNBOOK.read_text(encoding="utf-8"), RUNBOOK_PIN_MARKER)
    pinned = _pinned()
    note = "; ".join(f"`{svc}` runs `{ref}`" for svc, ref in sorted(pinned.items()))
    corrected = paragraph + f"\n  *Dated correction (2026-11-01):* {note}; rollback images stay as recorded."
    assert pin_mismatches(corrected, pinned, read_repo_record) == []
