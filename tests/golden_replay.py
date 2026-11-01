"""WP-A04 golden replay harness (SE-71; the SE-38 PATCH/MINOR gate) — test tooling, synthetic data.

What it does
* Runs a **decision path** over committed synthetic cases and reduces each output to one
  canonical byte form (``canonical_bytes``). A path is any pure callable ``run(inputs)``:
  - the WP2 composite decision replay below (``wp2_decision_path``), built from
    ``shared.strategy_identity``, ``shared.strategy_config_snapshot``, ``shared.decision_metadata``,
    ``shared.signal_integrity_v2``, ``shared.funnel_records`` and ``shared.strategy_version_boundary``;
  - or an adapter around an existing service code path. ``golden_replay_fixtures`` registers one
    around the wired A44 enforce-mode integrity step of ``signal_engine/signal_logic.py``.
  The harness only calls a path; it never edits, patches or imports a service on its own.
* Pins, per case, an ``input_hash``, an ``output_hash`` and the canonical output itself in one
  golden file per suite under ``tests/fixtures/golden_replay/``. ``compare_to_golden`` reports a
  changed fixture input, a changed output (with the JSON pointer of the first difference) and a
  hand-edited golden file whose stored hashes no longer match its content.
* ``semver_gate`` applies SE-38 to two WP2 replays: a MINOR or PATCH step is accepted only when
  the decisions are byte-identical; ``shared.strategy_version_boundary`` classifies the identity
  change, and an identity change under an unchanged label is refused (stop condition).
* ``cross_process_outputs`` replays the suites in fresh interpreters with different
  ``PYTHONHASHSEED`` values.

Determinism
* VERIFIED by tests/test_golden_replay.py: byte-identical output across repeated runs in one
  process and across fresh processes with different hash seeds, on the machine that ran them.
* Two development machines: **NOT VERIFIED**. No second machine was available. Integer and string
  paths and the IEEE-754 shortest float repr are expected to be identical on any CPython 3
  platform, but this is not tested. Float reductions in numpy or pandas may legitimately differ
  across CPU architectures; an adapter over such code must state its own scope.

Integration use (acceptance criterion 2 of IMPLEMENTATION_WORKPLAN.md section 2.4): write an
adapter for the service code path you change, register a ``GoldenSuite`` for it in a new module,
pin its golden file once from the unchanged code with the explicit ``regenerate`` command, then
assert ``check_suite`` stays clean with your flag at its default.

Rules
* Inputs are synthetic. No market data, database, network, clock or environment is read. The
  only file read is a golden file; one is written only by the explicit ``regenerate`` command,
  never by a test.
* Times are integer UTC epoch milliseconds. A datetime is encoded as epoch microseconds, so no
  clock-format string ever enters a golden file.

Usage, from the repository root:
    python tests/golden_replay.py check [--suite MODULE:ATTR ...]   exit 0 clean, 1 mismatch, 2 error
    python tests/golden_replay.py print [--suite MODULE:ATTR ...]   canonical replay on stdout
    python tests/golden_replay.py regenerate --suite MODULE:ATTR    explicit opt-in rewrite
The default suites are ``golden_replay_fixtures:SUITES``.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import decimal
import enum
import hashlib
import importlib
import inspect
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                       # the repository root, for ``shared``
    sys.path.insert(0, str(ROOT))

from shared import decision_metadata as dm                     # noqa: E402
from shared import funnel_records as fr                        # noqa: E402
from shared import signal_integrity_v2 as siv2                 # noqa: E402
from shared import strategy_config_snapshot as scs             # noqa: E402
from shared import strategy_identity as si                     # noqa: E402
from shared import strategy_version_boundary as vbr            # noqa: E402

HARNESS_SCHEMA = "tsb-golden-replay/1"
CANONICAL_FORM = "tsb-golden-canonical/1"
GATE_SCHEMA = "tsb-golden-semver-gate/1"
WP2_OUTPUT_SCHEMA = "tsb-golden-wp2-decision-replay/1"
WP2_EXPORT_SCHEMA = "tsb-golden-wp2-export/1"
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden_replay"
DEFAULT_SUITES = "golden_replay_fixtures:SUITES"
FIXED_HASH_SEEDS = ("0", "1", "2", "4242")
NAME_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,79}$")


class HarnessError(ValueError):
    """The replay cannot be trusted; nothing may be compared or pinned."""


class GoldenFormError(HarnessError):
    """A value has no single canonical byte form."""


class HarnessInputError(HarnessError):
    """A case, scenario or argument is malformed."""


class HarnessIdentityError(HarnessError):
    """The strategy identity is missing, incomplete or conflicting (fail closed)."""


class NonDeterministicPath(HarnessError):
    """The same inputs produced different bytes, or the path mutated its inputs."""


class HarnessVerificationError(HarnessError):
    """Exported records do not verify (hash, chain, link or conservation)."""


class RegenerationRefused(HarnessError):
    """A golden file write without the explicit opt-in."""


class GoldenMismatch(HarnessError):
    """A replay differs from its golden file."""

    def __init__(self, diff: "GoldenDiff"):
        self.diff = diff
        super().__init__(diff.summary())


# ── canonical form ─────────────────────────────────────────────────────────────────────────

_TAG_KEYS = frozenset(("__float__", "__decimal__", "__utc_us__", "__timedelta_us__", "__bytes__",
                       "__set__", "__dataclass__"))
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_US = timedelta(microseconds=1)


def canonical_value(value: Any, where: str = "$") -> Any:
    """Reduce ``value`` to plain JSON with one meaning per form; anything ambiguous is refused.

    * ``None``, ``bool``, ``str`` and ``int`` stay as they are; finite floats keep their shortest
      repr. NaN and infinities become ``{"__float__": "nan" | "+inf" | "-inf"}``.
    * ``Decimal`` becomes ``{"__decimal__": str(value)}`` (its exponent is kept: an observable).
    * An aware datetime becomes ``{"__utc_us__": epoch microseconds}``; a naive one is refused.
      A timedelta becomes ``{"__timedelta_us__": microseconds}``. Bytes become hex.
    * Mappings need ``str`` keys (the tag names are reserved); lists and tuples become lists;
      sets become ``{"__set__": [...]}`` sorted by canonical text.
    * A dataclass instance becomes ``{"__dataclass__": class name, "fields": {...}}``.
    * numpy scalars and arrays go through ``tolist()``. Enums and every other type are refused:
      the adapter must convert them explicitly.
    """
    if value is None or type(value) in (bool, str, int):
        return value
    if isinstance(value, enum.Enum):
        raise GoldenFormError(f"{where}: enum {type(value).__name__} has no canonical form")
    if type(value).__module__.partition(".")[0] == "numpy" and hasattr(value, "tolist"):
        return canonical_value(value.tolist(), where)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        number = float(value)
        if math.isfinite(number):
            return number
        return {"__float__": "nan" if math.isnan(number) else ("+inf" if number > 0 else "-inf")}
    if isinstance(value, decimal.Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise GoldenFormError(f"{where}: naive datetime (its zone is unknown)")
        return {"__utc_us__": (value - _EPOCH) // _US}
    if isinstance(value, timedelta):
        return {"__timedelta_us__": value // _US}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": bytes(value).hex()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"__dataclass__": type(value).__name__,
                "fields": {f.name: canonical_value(getattr(value, f.name), f"{where}.{f.name}")
                           for f in dataclasses.fields(value)}}
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise GoldenFormError(f"{where}: non-string key {key!r}")
            if key in _TAG_KEYS:
                raise GoldenFormError(f"{where}: key {key!r} is reserved by the canonical form")
            out[str(key)] = canonical_value(item, f"{where}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [canonical_value(item, f"{where}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, (set, frozenset)):
        items = [canonical_value(item, f"{where}{{}}") for item in value]
        return {"__set__": sorted(items, key=si.canonical_json)}
    raise GoldenFormError(f"{where}: {type(value).__name__} has no canonical form")


def canonical_text(value: Any) -> str:
    """The research contract's canonical JSON (sorted keys, compact, ASCII) of ``value``."""
    return si.canonical_json(canonical_value(value))


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("ascii")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_text(doc: Any) -> str:
    """Canonical text of a document that is already canonical JSON: a replay document or a loaded
    golden file, tag objects included. Raw values go through ``canonical_value`` instead."""
    try:
        return si.canonical_json(doc)
    except si.ClosureError as exc:
        raise HarnessError(f"not canonical JSON: {exc}") from None


def json_digest(doc: Any) -> str:
    return hashlib.sha256(json_text(doc).encode("ascii")).hexdigest()


def _repo_path(path: Any) -> str:
    pure = PurePosixPath(path) if isinstance(path, str) else None
    if (pure is None or not path or "\\" in path or pure.is_absolute() or str(pure) != path
            or any(part in ("", ".", "..") for part in pure.parts)):
        raise HarnessInputError(f"not a normalized repository-relative path: {path!r}")
    return path


# ── suites, replay and golden documents ────────────────────────────────────────────────────

@dataclass(frozen=True)
class GoldenCase:
    """One synthetic input of a path. ``inputs`` must be deep-copyable and canonicalizable."""
    case_id: str
    inputs: Any

    def __post_init__(self):
        if not isinstance(self.case_id, str) or not NAME_ID.match(self.case_id):
            raise HarnessInputError(f"invalid case_id {self.case_id!r}")


@dataclass(frozen=True)
class GoldenPath:
    """A decision path. ``run`` maps one case's inputs to its decision output and must be pure.
    ``normalize`` maps inputs to their equivalence class for ``input_hash`` (``None``: the inputs
    themselves). ``code_refs`` names the repository files whose behaviour the golden pins."""
    path_id: str
    run: Callable[[Any], Any]
    code_refs: tuple = ()
    normalize: Callable[[Any], Any] | None = None
    description: str = ""

    def __post_init__(self):
        if not isinstance(self.path_id, str) or not NAME_ID.match(self.path_id):
            raise HarnessInputError(f"invalid path_id {self.path_id!r}")
        if not callable(self.run) or (self.normalize is not None and not callable(self.normalize)):
            raise HarnessInputError(f"{self.path_id}: run and normalize must be callable")
        if isinstance(self.code_refs, str):
            raise HarnessInputError(f"{self.path_id}: code_refs must be a sequence of paths")
        object.__setattr__(self, "code_refs", tuple(sorted(_repo_path(p) for p in self.code_refs)))
        if not isinstance(self.description, str):
            raise HarnessInputError(f"{self.path_id}: description must be a string")


@dataclass(frozen=True)
class GoldenSuite:
    """A path, its cases (sorted by id) and the stem of its golden file (default: path_id)."""
    path: GoldenPath
    cases: tuple
    golden_name: str | None = None

    def __post_init__(self):
        if not isinstance(self.path, GoldenPath):
            raise HarnessInputError("suite path must be a GoldenPath")
        cases = tuple(self.cases)
        if not cases or any(not isinstance(c, GoldenCase) for c in cases):
            raise HarnessInputError(f"{self.path.path_id}: a suite needs at least one GoldenCase")
        ids = [c.case_id for c in cases]
        if len(set(ids)) != len(ids):
            raise HarnessInputError(f"{self.path.path_id}: duplicate case_id")
        object.__setattr__(self, "cases", tuple(sorted(cases, key=lambda c: c.case_id)))
        name = self.path.path_id if self.golden_name is None else self.golden_name
        if not isinstance(name, str) or not NAME_ID.match(name):
            raise HarnessInputError(f"invalid golden_name {name!r}")
        object.__setattr__(self, "golden_name", name)

    @property
    def golden_file(self) -> Path:
        return GOLDEN_DIR / f"{self.golden_name}.json"


def suite_hash(doc: Mapping) -> str:
    cases = doc.get("cases") if isinstance(doc.get("cases"), list) else []
    return json_digest({"schema": doc.get("schema"), "canonical_form": doc.get("canonical_form"),
                   "path_id": doc.get("path_id"), "code_refs": doc.get("code_refs"),
                   "cases": [[c.get("case_id"), c.get("input_hash"), c.get("output_hash")]
                             for c in cases if isinstance(c, Mapping)]})


def replay_suite(suite: GoldenSuite, *, repeats: int = 2) -> dict:
    """Run every case ``repeats`` times on a deep copy of its inputs and build the golden document.
    Differing bytes between runs, or inputs mutated by the path, raise ``NonDeterministicPath``."""
    if not isinstance(suite, GoldenSuite):
        raise HarnessInputError("replay_suite needs a GoldenSuite")
    if type(repeats) is not int or repeats < 1:
        raise HarnessInputError("repeats must be a positive integer")
    path = suite.path
    cases = []
    for case in suite.cases:
        where = f"{path.path_id}/{case.case_id}"
        normalized = path.normalize(case.inputs) if path.normalize is not None else case.inputs
        input_hash = digest(normalized)
        raw_hash = digest(case.inputs)
        produced = set()
        for _ in range(repeats):
            work = copy.deepcopy(case.inputs)
            produced.add(canonical_bytes(path.run(work)))
            if digest(work) != raw_hash:
                raise NonDeterministicPath(f"{where}: the path mutated its inputs")
        if len(produced) != 1:
            raise NonDeterministicPath(f"{where}: {len(produced)} different outputs from the same inputs")
        blob = produced.pop()
        cases.append({"case_id": case.case_id, "input_hash": input_hash,
                      "output_hash": hashlib.sha256(blob).hexdigest(), "output": json.loads(blob)})
    doc = {"schema": HARNESS_SCHEMA, "canonical_form": CANONICAL_FORM,
           "golden_name": suite.golden_name, "path_id": path.path_id,
           "code_refs": list(path.code_refs), "description": path.description, "cases": cases}
    doc["suite_hash"] = suite_hash(doc)
    return doc


def _check_doc(doc: Any) -> Mapping:
    if not isinstance(doc, Mapping) or doc.get("schema") != HARNESS_SCHEMA \
            or not isinstance(doc.get("cases"), list):
        raise HarnessError(f"not a {HARNESS_SCHEMA} document")
    return doc


def render_golden(doc: Mapping) -> str:
    """The committed text of a golden file: sorted keys, one-space indent, ASCII, final newline."""
    _check_doc(doc)
    return json.dumps(doc, indent=1, sort_keys=True, separators=(",", ": "), ensure_ascii=True,
                      allow_nan=False) + "\n"


def load_golden(path: Path) -> dict:
    target = Path(path)
    try:
        text = target.read_text(encoding="ascii")
    except FileNotFoundError:
        raise HarnessError(f"golden file missing: {target.name} (pin it with the explicit "
                           "regenerate command)") from None
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise HarnessError(f"{target.name}: not JSON ({exc})") from None
    return dict(_check_doc(doc))


def write_golden(doc: Mapping, path: Path, *, regenerate: bool = False) -> Path:
    """Write a golden file. Refused unless ``regenerate`` is exactly True (explicit opt-in)."""
    if regenerate is not True:
        raise RegenerationRefused("golden files are written only by the explicit regenerate command")
    text = render_golden(doc)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="ascii")
    return target


# ── comparison ─────────────────────────────────────────────────────────────────────────────

_ABSENT = "<absent>"


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def first_difference(golden: Any, actual: Any, pointer: str = "") -> str | None:
    """JSON pointer (RFC 6901) of the first differing leaf, in sorted-key order; ``None`` when
    equal. Types are compared strictly: ``1``, ``1.0`` and ``True`` differ."""
    if isinstance(golden, dict) and isinstance(actual, dict):
        for key in sorted(set(golden) | set(actual)):
            here = f"{pointer}/{_escape(key)}"
            if key not in golden or key not in actual:
                return here
            found = first_difference(golden[key], actual[key], here)
            if found is not None:
                return found
        return None
    if isinstance(golden, list) and isinstance(actual, list):
        for i, (g, a) in enumerate(zip(golden, actual)):
            found = first_difference(g, a, f"{pointer}/{i}")
            if found is not None:
                return found
        return None if len(golden) == len(actual) else f"{pointer}/{min(len(golden), len(actual))}"
    if type(golden) is not type(actual) or golden != actual:
        return pointer
    return None


def resolve_pointer(doc: Any, pointer: str | None) -> Any:
    if pointer is None:
        return _ABSENT
    node = doc
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return _ABSENT
    return node


@dataclass(frozen=True)
class Mismatch:
    kind: str            # schema | path_metadata | golden_inconsistent | case_missing | case_added
    case_id: str | None  # | input_changed | output_changed | output_hash_changed | suite_hash
    pointer: str | None
    golden: Any = None
    actual: Any = None

    def as_dict(self) -> dict:
        return {"kind": self.kind, "case_id": self.case_id, "pointer": self.pointer,
                "golden": self.golden, "actual": self.actual}


@dataclass(frozen=True)
class GoldenDiff:
    mismatches: tuple = ()

    @property
    def ok(self) -> bool:
        return not self.mismatches

    @property
    def kinds(self) -> tuple:
        return tuple(sorted({m.kind for m in self.mismatches}))

    def summary(self) -> str:
        if self.ok:
            return "golden replay: identical"
        lines = [f"golden replay: {len(self.mismatches)} mismatch(es)"]
        for m in self.mismatches:
            where = f"{m.case_id or '-'} {m.pointer if m.pointer else '(root)'}"
            lines.append(f"  {m.kind}: {where}: golden={_short(m.golden)} actual={_short(m.actual)}")
        return "\n".join(lines)


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, default=repr)
    return text if len(text) <= 160 else text[:157] + "..."


def _case_map(doc: Mapping, name: str) -> dict:
    out = {}
    for case in doc.get("cases") or ():
        if not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str):
            raise HarnessError(f"{name}: malformed case entry")
        if case["case_id"] in out:
            raise HarnessError(f"{name}: duplicate case_id {case['case_id']!r}")
        out[case["case_id"]] = case
    return out


def compare_to_golden(actual: Mapping, golden: Mapping) -> GoldenDiff:
    """Field-by-field comparison of a fresh replay with a golden document. The golden file is
    also checked against itself, so an output edited without its hash (or the reverse) shows."""
    _check_doc(actual)
    _check_doc(golden)
    found = []

    def add(kind, case_id=None, pointer=None, g=None, a=None):
        found.append(Mismatch(kind, case_id, pointer, g, a))

    for key in ("schema", "canonical_form"):
        if actual.get(key) != golden.get(key):
            add("schema", None, f"/{key}", golden.get(key), actual.get(key))
    for key in ("golden_name", "path_id", "code_refs", "description"):
        if actual.get(key) != golden.get(key):
            add("path_metadata", None, f"/{key}", golden.get(key), actual.get(key))
    golden_cases, actual_cases = _case_map(golden, "golden"), _case_map(actual, "actual")
    for cid, case in sorted(golden_cases.items()):
        stored = json_digest(case.get("output"))
        if stored != case.get("output_hash"):
            add("golden_inconsistent", cid, "/output_hash", case.get("output_hash"), stored)
    if suite_hash(golden) != golden.get("suite_hash"):
        add("golden_inconsistent", None, "/suite_hash", golden.get("suite_hash"), suite_hash(golden))
    for cid in sorted(set(golden_cases) | set(actual_cases)):
        g, a = golden_cases.get(cid), actual_cases.get(cid)
        if a is None:
            add("case_missing", cid)
            continue
        if g is None:
            add("case_added", cid)
            continue
        if g.get("input_hash") != a.get("input_hash"):
            add("input_changed", cid, "/input_hash", g.get("input_hash"), a.get("input_hash"))
        if json_text(g.get("output")) != json_text(a.get("output")):
            pointer = first_difference(g.get("output"), a.get("output"))
            add("output_changed", cid, pointer, resolve_pointer(g.get("output"), pointer),
                resolve_pointer(a.get("output"), pointer))
        elif g.get("output_hash") != a.get("output_hash"):
            add("output_hash_changed", cid, "/output_hash", g.get("output_hash"), a.get("output_hash"))
    if not found and golden.get("suite_hash") != actual.get("suite_hash"):
        add("suite_hash", None, "/suite_hash", golden.get("suite_hash"), actual.get("suite_hash"))
    return GoldenDiff(tuple(found))


def assert_matches_golden(actual: Mapping, golden: Mapping) -> None:
    diff = compare_to_golden(actual, golden)
    if not diff.ok:
        raise GoldenMismatch(diff)


def check_suite(suite: GoldenSuite) -> GoldenDiff:
    """Replay ``suite`` and compare it with its committed golden file (read-only)."""
    return compare_to_golden(replay_suite(suite), load_golden(suite.golden_file))


def load_suites(specs: Iterable[str]) -> tuple:
    """Resolve ``MODULE:ATTRIBUTE`` specs to suites (a GoldenSuite or a sequence of them)."""
    suites = []
    for spec in specs:
        module_name, sep, attr = str(spec).partition(":")
        if not sep or not module_name or not attr:
            raise HarnessInputError(f"suite spec must be MODULE:ATTRIBUTE, not {spec!r}")
        try:
            target = getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError) as exc:
            raise HarnessInputError(f"cannot load suite {spec!r}: {exc}") from None
        items = (target,) if isinstance(target, GoldenSuite) else tuple(target)
        if not items or any(not isinstance(s, GoldenSuite) for s in items):
            raise HarnessInputError(f"{spec!r} is not a GoldenSuite or a sequence of them")
        suites.extend(items)
    names = [s.golden_name for s in suites]
    if len(set(names)) != len(names):
        raise HarnessInputError(f"two suites share a golden file: {sorted(names)}")
    return tuple(suites)


def print_bytes(suites: Iterable[GoldenSuite]) -> bytes:
    """What ``golden_replay.py print`` writes: the canonical replay documents of ``suites``."""
    return json_text({s.golden_name: replay_suite(s) for s in suites}).encode("ascii") + b"\n"


def cross_process_outputs(specs: Iterable[str] = (DEFAULT_SUITES,), seeds: Iterable[str] = FIXED_HASH_SEEDS,
                          *, timeout: int = 300) -> dict:
    """Replay in a fresh interpreter per hash seed (minimal environment, repository root as cwd);
    returns ``{seed: stdout bytes}``. Seeds are fixed integers: no random seed is ever used."""
    argv = [sys.executable, str(Path(__file__).resolve()), "print"]
    for spec in specs:
        argv += ["--suite", str(spec)]
    out = {}
    for seed in seeds:
        seed = str(seed)
        if not seed.isdigit() or int(seed) > 4294967295:
            raise HarnessInputError(f"PYTHONHASHSEED must be a fixed integer, not {seed!r}")
        env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": seed}
        proc = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True, timeout=timeout,
                              check=False)
        if proc.returncode != 0:
            raise HarnessError(f"seed {seed}: exit {proc.returncode}: "
                               f"{proc.stderr.decode('utf-8', 'replace')[-2000:]}")
        out[seed] = proc.stdout
    return out


# ── WP2 composite decision path ────────────────────────────────────────────────────────────

WP2_CODE_REFS = ("shared/decision_metadata.py", "shared/funnel_records.py", "shared/signal_identity.py",
                 "shared/signal_integrity_v2.py", "shared/strategy_config_snapshot.py",
                 "shared/strategy_identity.py", "shared/strategy_version_boundary.py")
STAGE = "F4"
DIRECTION = "long"                                  # the strategy is long-only (A44 DIRECTIONS)
COMPLETENESS = ("complete", "gap", "duplicate", "insufficient_history")   # CandleSet.completeness
# The fixed order in which one observation is checked; the first failing check decides.
CHECK_ORDER = ("candle_identity", "version_boundary", "closed_bar_freshness", "input_completeness",
               "input_history", "strategy_entry", "setup_claim")
_VENUE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")      # the venue pattern of signal_integrity_v2
_CYCLE_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")

_SCENARIO_KEYS = frozenset(("scenario_id", "venue", "activation_ms", "strategy", "cycles"))
_STRATEGY_KEYS = frozenset(("strategy_id", "version", "lineage", "closure", "config_schema",
                            "config_values", "contract"))
_CLOSURE_KEYS = frozenset(("path", "role", "regions", "text"))
_SCHEMA_KEYS = frozenset(("schema_id", "keys"))
_CONFIG_KEY_KEYS = frozenset(("name", "kind", "source", "choices"))
_CYCLE_KEYS = frozenset(("cycle_id", "decision_time_ms", "observations"))
_OBSERVATION_KEYS = frozenset(("symbol", "timeframe", "bar_close_ms", "closes", "completeness"))


def _fields(value, keys, where, error=HarnessInputError, optional=()):
    if not isinstance(value, Mapping):
        raise error(f"{where}: expected a mapping")
    missing = sorted(keys - set(value) - set(optional))
    unknown = sorted(str(k) for k in set(value) - keys)
    if missing:
        raise error(f"{where}: missing {missing}")
    if unknown:
        raise error(f"{where}: unknown keys {unknown}")
    return value


def _sequence(value, where, error=HarnessInputError) -> tuple:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise error(f"{where}: expected a list")
    return tuple(value)


def _positive_int(value, where) -> int:
    if type(value) is not int or value <= 0:
        raise HarnessInputError(f"{where}: expected a positive integer")
    return value


def _text(value, where, error=HarnessInputError) -> str:
    if not isinstance(value, str) or not value:
        raise error(f"{where}: expected a non-empty string")
    return value


@dataclass(frozen=True)
class Observation:
    """One closed-bar input as the decision sees it: integer ticks, oldest first, last = decision bar."""
    symbol: str
    timeframe: str
    bar_close_ms: int
    closes: tuple
    completeness: str

    @property
    def subject(self) -> tuple:
        return (self.symbol, self.timeframe, self.bar_close_ms)

    def canonical(self) -> dict:
        return {"symbol": self.symbol, "timeframe": self.timeframe, "bar_close_ms": self.bar_close_ms,
                "closes": list(self.closes), "completeness": self.completeness}


@dataclass(frozen=True)
class Cycle:
    cycle_id: str
    decision_time_ms: int
    observations: tuple            # sorted by subject; a subject appears at most once

    def canonical(self) -> dict:
        return {"cycle_id": self.cycle_id, "decision_time_ms": self.decision_time_ms,
                "observations": [o.canonical() for o in self.observations]}


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    venue: str
    activation_ms: int
    strategy: Mapping              # normalized declaration (see ``_strategy``)
    cycles: tuple                  # sorted by decision time

    def observations_canonical(self) -> dict:
        return {"venue": self.venue, "activation_ms": self.activation_ms,
                "cycles": [c.canonical() for c in self.cycles]}

    def canonical(self) -> dict:
        return {"scenario_id": self.scenario_id, "strategy": copy.deepcopy(dict(self.strategy)),
                **self.observations_canonical()}


def _observation(raw, where) -> Observation:
    o = _fields(raw, _OBSERVATION_KEYS, where)
    closes = _sequence(o["closes"], f"{where}.closes")
    if not closes or any(type(c) is not int or c <= 0 for c in closes):
        raise HarnessInputError(f"{where}.closes: expected positive integer ticks")
    if o["completeness"] not in COMPLETENESS:
        raise HarnessInputError(f"{where}.completeness: expected one of {COMPLETENESS}")
    return Observation(_text(o["symbol"], f"{where}.symbol"), _text(o["timeframe"], f"{where}.timeframe"),
                       _positive_int(o["bar_close_ms"], f"{where}.bar_close_ms"), closes,
                       o["completeness"])


def _cycle(raw, where) -> Cycle:
    c = _fields(raw, _CYCLE_KEYS, where)
    cycle_id = c["cycle_id"]
    if not isinstance(cycle_id, str) or not _CYCLE_ID.match(cycle_id):
        raise HarnessInputError(f"{where}.cycle_id: invalid {cycle_id!r}")
    observations = [_observation(o, f"{where}.observations[{i}]")
                    for i, o in enumerate(_sequence(c["observations"], f"{where}.observations"))]
    subjects = [o.subject for o in observations]
    if len(set(subjects)) != len(subjects):
        raise HarnessInputError(f"{where}: a (symbol, timeframe, bar_close_ms) subject is evaluated "
                                "twice in one cycle")
    return Cycle(cycle_id, _positive_int(c["decision_time_ms"], f"{where}.decision_time_ms"),
                 tuple(sorted(observations, key=lambda o: o.subject)))


def _strategy(raw) -> dict:
    """Validate and normalize the strategy declaration. Anything missing is a missing identity."""
    err = HarnessIdentityError
    s = _fields(raw, _STRATEGY_KEYS, "strategy", err, optional=("lineage",))
    lineage = _sequence(s.get("lineage", ()), "strategy.lineage", err)
    closure = []
    for i, f in enumerate(_sequence(s["closure"], "strategy.closure", err)):
        where = f"strategy.closure[{i}]"
        f = _fields(f, _CLOSURE_KEYS, where, err)
        regions = []
        for r in _sequence(f["regions"], f"{where}.regions", err):
            pair = _sequence(r, f"{where}.regions", err)
            if len(pair) != 2:
                raise err(f"{where}.regions: expected [region_id, selector] pairs")
            regions.append([_text(pair[0], f"{where}.region_id", err), _text(pair[1], f"{where}.selector", err)])
        if not isinstance(f["text"], str):
            raise err(f"{where}.text: closure source text is missing")
        closure.append({"path": _text(f["path"], f"{where}.path", err), "role": _text(f["role"], f"{where}.role", err),
                        "regions": sorted(regions),
                        "text": si.normalize_source(f["text"].encode("utf-8")).decode("utf-8")})
    schema = _fields(s["config_schema"], _SCHEMA_KEYS, "strategy.config_schema", err)
    keys = []
    for i, k in enumerate(_sequence(schema["keys"], "strategy.config_schema.keys", err)):
        k = _fields(k, _CONFIG_KEY_KEYS, f"strategy.config_schema.keys[{i}]", err, optional=("choices",))
        keys.append({"name": k["name"], "kind": k["kind"], "source": k["source"],
                     "choices": list(_sequence(k.get("choices", ()), "choices", err))})
    if not isinstance(s["config_values"], Mapping) or not isinstance(s["contract"], Mapping):
        raise err("strategy.config_values and strategy.contract must be mappings")
    try:
        values, contract = canonical_value(s["config_values"]), canonical_value(s["contract"])
    except GoldenFormError as exc:
        raise err(f"strategy: {exc}") from None
    return {"strategy_id": s["strategy_id"], "version": s["version"], "lineage": list(lineage),
            "closure": sorted(closure, key=lambda f: f["path"]),
            "config_schema": {"schema_id": schema["schema_id"],
                              "keys": sorted(keys, key=lambda k: str(k["name"]))},
            "config_values": values, "contract": contract}


def parse_scenario(inputs: Any) -> Scenario:
    """Validate a WP2 scenario. Order of cycles, observations, closure files, regions and keys is
    normalized, so permuted but equivalent inputs give the same Scenario."""
    if isinstance(inputs, Mapping) and "strategy" not in inputs:
        raise HarnessIdentityError("scenario: no strategy identity declared")
    s = _fields(inputs, _SCENARIO_KEYS, "scenario")
    if not isinstance(s["scenario_id"], str) or not NAME_ID.match(s["scenario_id"]):
        raise HarnessInputError(f"scenario_id: invalid {s['scenario_id']!r}")
    if not isinstance(s["venue"], str) or not _VENUE.match(s["venue"]):
        raise HarnessInputError(f"venue: invalid {s['venue']!r}")
    activation = _positive_int(s["activation_ms"], "activation_ms")
    try:
        siv2.version_boundary_reason(bar_close_ms=activation, activation_ms=activation)
    except ValueError as exc:
        raise HarnessInputError(f"activation_ms: {exc}") from None
    strategy = _strategy(s["strategy"])
    cycles = [_cycle(c, f"cycles[{i}]") for i, c in enumerate(_sequence(s["cycles"], "cycles"))]
    if not cycles:
        raise HarnessInputError("cycles: at least one cycle is required")
    if len({c.cycle_id for c in cycles}) != len(cycles):
        raise HarnessInputError("cycles: duplicate cycle_id")
    if len({c.decision_time_ms for c in cycles}) != len(cycles):
        raise HarnessInputError("cycles: two cycles share a decision time, so their order is ambiguous")
    return Scenario(s["scenario_id"], s["venue"], activation, strategy,
                    tuple(sorted(cycles, key=lambda c: c.decision_time_ms)))


@dataclass(frozen=True)
class ExecutedCode:
    """The callables a WP2 path runs and the source text each was compiled from. ``bind_code``
    reads that text once, when the path is built, so a replay itself reads no file."""
    entry: Callable
    sources: tuple                 # ((closure path, source text), ...) sorted by path


def bind_code(entry: Callable, files: Mapping[str, Callable]) -> ExecutedCode:
    """Bind the entry rule and every function it relies on to their closure paths. A scenario
    whose closure is not exactly this code is refused (the identity would not describe it)."""
    if not callable(entry) or not isinstance(files, Mapping) or not files:
        raise HarnessInputError("bind_code needs an entry callable and a {closure path: callable} map")
    if not any(fn is entry for fn in files.values()):
        raise HarnessInputError("the entry callable must be one of the bound closure files")
    texts = []
    for path in sorted(files):
        try:
            texts.append((_repo_path(path), inspect.getsource(files[path])))
        except (OSError, TypeError) as exc:
            raise HarnessIdentityError(f"{path}: source text unavailable ({exc})") from None
    return ExecutedCode(entry, tuple(texts))


def _build_identity(strategy: Mapping, code: ExecutedCode) -> tuple:
    try:
        files = tuple(si.ClosureFile(path=f["path"], role=f["role"],
                                     regions=tuple(si.RegionSpec(rid, sel) for rid, sel in f["regions"]))
                      for f in strategy["closure"])
        manifest = si.StrategyRuleManifest(strategy_id=strategy["strategy_id"], files=files)
        sources = {f["path"]: f["text"].encode("utf-8") for f in strategy["closure"]}
        schema = scs.ConfigSchema(strategy["config_schema"]["schema_id"],
                                  tuple(scs.ConfigKey(k["name"], k["kind"], k["source"], tuple(k["choices"]))
                                        for k in strategy["config_schema"]["keys"]))
        snapshot = scs.snapshot_config(strategy["strategy_id"], schema, strategy["config_values"])
        sv, doc = si.build_identity(manifest, sources, version=strategy["version"],
                                    config_snapshot=snapshot, contract_descriptor=strategy["contract"],
                                    lineage=tuple(strategy["lineage"]))
    except si.ClosureError as exc:
        raise HarnessIdentityError(f"strategy identity unavailable: {exc}") from exc
    declared = {f["path"]: si.normalize_source(f["text"].encode("utf-8")) for f in strategy["closure"]}
    executed = {p: si.normalize_source(t.encode("utf-8")) for p, t in code.sources}
    if set(declared) != set(executed):
        raise HarnessIdentityError(f"declared closure files {sorted(declared)} are not the executed "
                                   f"code files {sorted(executed)}")
    differ = sorted(p for p in declared if declared[p] != executed[p])
    if differ:
        raise HarnessIdentityError(f"declared closure text differs from the executed code: {differ}")
    return sv, doc, snapshot.values()


def _decision_inputs(params: Mapping, contract: Mapping) -> tuple:
    """Required decision inputs; none has a default (a missing one is a missing identity)."""
    raw = params.get(siv2.SETTING_FRESHNESS_MAX_AGE)
    if not isinstance(raw, str):
        raise HarnessIdentityError(f"config lacks {siv2.SETTING_FRESHNESS_MAX_AGE}: a required "
                                   "decision input with no default")
    try:
        settings = siv2.parse_integrity_settings({siv2.SETTING_FRESHNESS_MAX_AGE: raw})
    except (siv2.IntegritySettingsError, RuntimeError) as exc:
        raise HarnessIdentityError(f"freshness setting refused: {exc}") from None
    spec = contract.get("input_spec")
    min_bars = spec.get("min_closed_bars") if isinstance(spec, Mapping) else None
    if type(min_bars) is not int or min_bars < 1:
        raise HarnessIdentityError("contract input_spec.min_closed_bars must be a positive integer")
    models = []
    for name in ("cost_model_id", "fill_model_id"):
        value = contract.get(name)
        if not isinstance(value, str) or not dm.MODEL_ID.match(value):
            raise HarnessIdentityError(f"contract {name} is not a model identifier: {value!r}")
        models.append(value)
    return settings, min_bars, models[0], models[1]


@dataclass(frozen=True)
class ReplayResult:
    scenario_id: str
    strategy: si.StrategyVersion
    identity_manifest: Mapping
    observations_hash: str
    decisions: tuple               # identity-free canonical decisions, in evaluation order
    records: tuple                 # DecisionMetadata, hash-chained in the same order
    rejections: tuple              # RejectionRecord, one per rejected decision
    conservation: tuple            # ((cycle_id, StageCount, ConservationResult), ...)

    def decisions_bytes(self) -> bytes:
        """The SE-38 comparison object: what was decided, with no identity hash inside."""
        return canonical_bytes(list(self.decisions))

    def golden_output(self) -> dict:
        sv = self.strategy
        reasons: dict = {}
        for d in self.decisions:
            if d["reason_code"]:
                reasons[d["reason_code"]] = reasons.get(d["reason_code"], 0) + 1
        candidates = sum(1 for d in self.decisions if d["outcome"] == "candidate")
        return {
            "schema": WP2_OUTPUT_SCHEMA,
            "scenario_id": self.scenario_id,
            "strategy": {**sv.identity(), "identity_hash": sv.identity_hash, "identifier": sv.identifier,
                         "closure_spec_hash": self.identity_manifest["closure_spec_hash"]},
            "observations_hash": self.observations_hash,
            "decisions": [dict(d) for d in self.decisions],
            "outcome_counts": {"candidate": candidates, "rejection": len(self.decisions) - candidates},
            "reason_counts": dict(sorted(reasons.items())),
            "conservation": [{"cycle_id": cid, "counts": counts.as_dict(), **result.as_dict()}
                             for cid, counts, result in self.conservation],
            "digests": {
                "decisions_hash": hashlib.sha256(self.decisions_bytes()).hexdigest(),
                "decision_ids_hash": digest([r.decision_id for r in self.records]),
                "records_hash": digest([r.to_dict() for r in self.records]),
                "chain_head": self.records[-1].record_hash if self.records else None,
                "rejections_hash": digest([r.as_dict() for r in self.rejections]),
                "setup_keys_hash": digest([r.output()["setup_key"] for r in self.records
                                           if r.decision_type == "candidate"]),
            },
        }

    def export(self) -> dict:
        """The records as they would be stored; ``verify_export`` re-checks them from scratch."""
        return {"schema": WP2_EXPORT_SCHEMA, "strategy": self.strategy.identity(),
                "identifier": self.strategy.identifier,
                "records": [r.to_dict() for r in self.records],
                "rejections": [r.as_dict() for r in self.rejections],
                "cycles": [{"cycle_id": cid, "n_in": counts.n_in, "passed": counts.passed}
                           for cid, counts, _ in self.conservation]}


def _decide(scenario, cycle, obs, sv, code, params, settings, min_bars, state) -> tuple:
    """Evaluate one observation: (identity-free decision, setup_key or None, parent decision ids)."""
    base = {"cycle_id": cycle.cycle_id, "symbol": obs.symbol, "timeframe": obs.timeframe,
            "bar_close_ms": obs.bar_close_ms, "candle_key": None, "freshness_age_ms": None,
            "payload": None, "payload_hash": None, "claim": None}

    def reject(check, code_, sub_stage, detail, key=None, parents=()):
        return ({**base, "outcome": "rejection", "check": check, "stage": STAGE, "reason_code": code_,
                 "sub_stage": sub_stage, "detail": detail}, key, tuple(parents))

    try:
        candle = siv2.CandleRef(obs.symbol, obs.timeframe, obs.bar_close_ms)
    except siv2.IntegrityInputError as exc:
        return reject("candle_identity", siv2.DATA_QUALITY, siv2.SUB_STAGE[siv2.DATA_QUALITY],
                      {"integrity_error": str(exc)})
    base["candle_key"] = candle.key
    reason = siv2.version_boundary_reason(bar_close_ms=obs.bar_close_ms, activation_ms=scenario.activation_ms)
    if reason is not None:
        return reject("version_boundary", reason, siv2.SUB_STAGE[reason],
                      {"activation_ms": scenario.activation_ms})
    try:
        bound = settings.max_age_ms(obs.timeframe)
    except siv2.IntegritySettingsError as exc:
        raise HarnessIdentityError(f"{cycle.cycle_id}/{obs.symbol}: {exc}") from None
    fresh = siv2.closed_bar_freshness(bar_close_ms=obs.bar_close_ms, timeframe_ms=siv2.duration_of(obs.timeframe),
                                      now_ms=cycle.decision_time_ms, max_age_ms=bound)
    base["freshness_age_ms"] = fresh.age_ms
    if not fresh.admissible:
        return reject("closed_bar_freshness", fresh.reason_code, siv2.SUB_STAGE[fresh.reason_code],
                      {"age_ms": fresh.age_ms, "max_age_ms": bound})
    if obs.completeness != "complete":
        if obs.completeness == "insufficient_history":
            return reject("input_completeness", "F4.history_insufficient", "strategy.input",
                          {"strategy_code": "insufficient_history", "completeness": obs.completeness})
        return reject("input_completeness", "F4.data_quality", "strategy.input",
                      {"strategy_code": "incomplete_candles", "completeness": obs.completeness})
    if len(obs.closes) < min_bars:
        return reject("input_history", "F4.history_insufficient", "strategy.input",
                      {"strategy_code": "insufficient_history", "closed_bars": len(obs.closes),
                       "min_closed_bars": min_bars})
    payload = code.entry(obs.closes, copy.deepcopy(params))   # a rule cannot leak state
    if payload is None:
        return reject("strategy_entry", "F4.no_setup", "strategy.entry", {"strategy_code": "no_setup"})
    if not isinstance(payload, Mapping):
        raise HarnessInputError(f"the entry rule returned {type(payload).__name__}, not a mapping or None")
    try:
        payload = json.loads(si.canonical_json(dict(payload)))
        payload_hash = siv2.payload_hash(payload)
    except (si.ClosureError, siv2.IntegrityInputError) as exc:
        raise HarnessInputError(f"the entry rule returned a payload with no canonical form: {exc}") from None
    key = siv2.setup_key_v2(venue=scenario.venue, symbol=obs.symbol, strategy_id=sv.strategy_id,
                            strategy_version=sv.version, rule_hash=sv.identity_hash,
                            timeframe=obs.timeframe, bar_close_ms=obs.bar_close_ms, direction=DIRECTION)
    claim, state["seen"] = siv2.register_claim(state["seen"], key, payload_hash)
    base.update(payload=payload, payload_hash=payload_hash, claim=claim.status)
    if claim.status == siv2.NEW:
        return ({**base, "outcome": "candidate", "check": "setup_claim", "stage": None, "reason_code": None,
                 "sub_stage": None, "detail": {}}, key, ())
    first_id, first_cycle = state["first"][key]
    return reject("setup_claim", claim.reason_code, siv2.SUB_STAGE[claim.reason_code],
                  {"first_cycle_id": first_cycle, "first_payload_hash": claim.first_payload_hash,
                   "payload_hash": payload_hash}, key, (first_id,))


def wp2_replay(inputs: Any, code: ExecutedCode) -> ReplayResult:
    """Replay one WP2 scenario: build the StrategyVersion from the synthetic closure, evaluate every
    observation in a fixed order, record each decision (hash-chained DecisionMetadata) and each
    drop (RejectionRecord), and check conservation per cycle. Pure: no clock, file or network."""
    if not isinstance(code, ExecutedCode):
        raise HarnessInputError("wp2_replay needs the ExecutedCode of bind_code")
    scenario = parse_scenario(inputs)
    sv, manifest, params = _build_identity(scenario.strategy, code)
    settings, min_bars, cost_id, fill_id = _decision_inputs(params, scenario.strategy["contract"])
    state = {"seen": {}, "first": {}}
    decisions, records, rejections, conservation = [], [], [], []
    prev = None
    for cycle in scenario.cycles:
        dropped, passed = [], 0
        for obs in cycle.observations:
            decision, key, parents = _decide(scenario, cycle, obs, sv, code, params, settings, min_bars, state)
            record = dm.make_decision(
                decision_type="candidate" if decision["outcome"] == "candidate" else "rejection",
                strategy=sv, input_hashes={"candles": digest(obs.canonical())},
                input_facts={"cycle_id": cycle.cycle_id, "symbol": obs.symbol,
                             "timeframe": obs.timeframe, "venue": scenario.venue},
                bar_close_time_ms=obs.bar_close_ms, decision_time_ms=cycle.decision_time_ms,
                output={**decision, "setup_key": key}, runtime=dict.fromkeys(dm.RUNTIME_KEYS),
                cost_model_id=cost_id, fill_model_id=fill_id, parent_decision_ids=parents,
                prev_record_hash=prev)
            prev = record.record_hash
            if decision["outcome"] == "candidate":
                passed += 1
                state["first"][key] = (record.decision_id, cycle.cycle_id)
            else:
                dropped.append(fr.RejectionRecord(
                    cycle_id=cycle.cycle_id, stage=STAGE, scope="candidate",
                    reason_code=decision["reason_code"], as_of=obs.bar_close_ms,
                    decision_time=cycle.decision_time_ms, rule_ref=f"golden_replay.wp2/{decision['check']}",
                    snapshot_hash=record.input_hashes[0][1], config_hash=sv.config_hash,
                    sub_stage=decision["sub_stage"], symbol=obs.symbol, timeframe=obs.timeframe,
                    strategy_id=sv.strategy_id, strategy_version=sv.identifier, setup_key=key,
                    bar_close_time=obs.bar_close_ms, detail=decision["detail"],
                    decision_id=record.decision_id))
            decisions.append(decision)
            records.append(record)
        counts = fr.StageCount(STAGE, len(cycle.observations), passed)
        result = fr.check_conservation([counts], dropped)
        if not result.ok:
            raise HarnessVerificationError(f"{cycle.cycle_id}: conservation violated "
                                           f"{[v.as_dict() for v in result.violations]}")
        conservation.append((cycle.cycle_id, counts, result))
        rejections.extend(dropped)
    return ReplayResult(scenario.scenario_id, sv, manifest, digest(scenario.observations_canonical()),
                        tuple(decisions), tuple(records), tuple(rejections), tuple(conservation))


def wp2_decision_path(path_id: str, code: ExecutedCode, *, description: str = "") -> GoldenPath:
    """A GoldenPath over ``wp2_replay`` bound to ``code``; inputs are normalized by ``parse_scenario``."""
    if not isinstance(code, ExecutedCode):
        raise HarnessInputError("wp2_decision_path needs the ExecutedCode of bind_code")
    return GoldenPath(path_id=path_id, run=lambda inputs: wp2_replay(inputs, code).golden_output(),
                      code_refs=WP2_CODE_REFS, normalize=lambda inputs: parse_scenario(inputs).canonical(),
                      description=description)


def verify_export(export: Mapping) -> dict:
    """Re-verify exported records from scratch: every record hash, the chain, the parent and
    decision links, the identity on every record and conservation per cycle."""
    if not isinstance(export, Mapping) or export.get("schema") != WP2_EXPORT_SCHEMA:
        raise HarnessVerificationError(f"not a {WP2_EXPORT_SCHEMA} export")
    try:
        sv = si.StrategyVersion(**export["strategy"])
    except (KeyError, TypeError, si.ClosureError) as exc:
        raise HarnessIdentityError(f"export strategy identity missing or invalid: {exc!r}") from None
    if export.get("identifier") != sv.identifier:
        raise HarnessIdentityError("export identifier does not match its strategy identity")
    by_id, prev = {}, None
    for i, doc in enumerate(export.get("records") or ()):
        try:
            record = dm.DecisionMetadata.from_dict(doc)
        except si.ClosureError as exc:
            raise HarnessVerificationError(f"record {i}: {exc}") from exc
        if record.strategy_identity() != sv.identity():
            raise HarnessIdentityError(f"record {i} was decided under another strategy identity")
        if record.prev_record_hash != prev:
            raise HarnessVerificationError(f"record {i}: hash chain broken")
        for parent in record.parent_decision_ids:
            if parent not in by_id or by_id[parent].decision_type != "candidate":
                raise HarnessVerificationError(f"record {i}: parent {parent[:12]} is not an earlier candidate")
        if record.decision_id in by_id:
            raise HarnessVerificationError(f"record {i}: decision_id repeated")
        by_id[record.decision_id] = record
        prev = record.record_hash
    per_cycle: dict = {}
    for i, doc in enumerate(export.get("rejections") or ()):
        try:
            rejection = fr.RejectionRecord.from_dict(doc)
        except (KeyError, TypeError, ValueError) as exc:
            raise HarnessVerificationError(f"rejection {i}: {exc}") from None
        record = by_id.get(rejection.decision_id)
        if record is None or record.decision_type != "rejection" \
                or record.output().get("reason_code") != rejection.reason_code:
            raise HarnessVerificationError(f"rejection {i}: no matching rejection decision")
        if (rejection.strategy_id, rejection.strategy_version, rejection.config_hash) != \
                (sv.strategy_id, sv.identifier, sv.config_hash):
            raise HarnessIdentityError(f"rejection {i} names another strategy identity")
        per_cycle.setdefault(rejection.cycle_id, []).append(rejection)
    rejected = sum(1 for r in by_id.values() if r.decision_type == "rejection")
    if rejected != sum(len(v) for v in per_cycle.values()):
        raise HarnessVerificationError("rejection decisions and RejectionRecords do not pair up")
    cycles = export.get("cycles") or ()
    if sum(c["n_in"] for c in cycles) != len(by_id):
        raise HarnessVerificationError("cycle input counts do not cover every record")
    for c in cycles:
        result = fr.check_conservation([fr.StageCount(STAGE, c["n_in"], c["passed"])],
                                       per_cycle.get(c["cycle_id"], ()))
        if not result.ok:
            raise HarnessVerificationError(f"{c['cycle_id']}: conservation violated")
    return {"records": len(by_id), "rejections": rejected, "chain_head": prev}


# ── SE-38 PATCH/MINOR gate and identity registry ───────────────────────────────────────────

def semver_gate(before: ReplayResult, after: ReplayResult) -> dict:
    """SE-38 on two replays of the same observations. MINOR/PATCH passes only with byte-identical
    decisions; an identity change under an unchanged label, a different strategy, or decisions
    that differ under an unchanged identity are refused (``HarnessIdentityError``)."""
    if not isinstance(before, ReplayResult) or not isinstance(after, ReplayResult):
        raise HarnessInputError("semver_gate compares two ReplayResult objects")
    if before.observations_hash != after.observations_hash:
        raise HarnessInputError("the replays saw different observations; SE-38 compares decisions on "
                                "identical inputs only")
    try:
        report = vbr.version_boundary_report(before.identity_manifest, after.identity_manifest)
    except vbr.ReportError as exc:
        raise HarnessIdentityError(f"identity manifests refused: {exc}") from None
    a, b = before.decisions_bytes(), after.decisions_bytes()
    identical = a == b
    cls, step = report["classification"], report["version_step"]
    if cls == vbr.OTHER:
        raise HarnessIdentityError("different strategy_id: not a version step of one strategy")
    if cls == vbr.UNDECLARED:
        raise HarnessIdentityError("identity hash changed under an unchanged version label "
                                   "(SE-38 stop condition)")
    if cls in (vbr.NO_CHANGE, vbr.LABEL_ONLY) and not identical:
        raise HarnessIdentityError("decisions differ under an unchanged identity: the declared closure "
                                   "does not cover what changed")
    if cls == vbr.NO_CHANGE:
        verdict = "NO_CHANGE"
    elif cls == vbr.LABEL_ONLY:
        verdict = "LABEL_ONLY_REVIEW"
    elif step == "REGRESSION":
        verdict = "FAIL_VERSION_REGRESSION"
    elif step in ("MINOR", "PATCH"):
        verdict = "PASS_PATCH_MINOR" if identical else "FAIL_REQUIRES_MAJOR"
    else:
        verdict = "MAJOR_BOUNDARY_REQUIRED"
    return {"schema": GATE_SCHEMA, "verdict": verdict, "classification": cls, "version_step": step,
            "version_before": report["version_before"], "version_after": report["version_after"],
            "decisions_identical": identical,
            "first_difference": None if identical else first_difference(json.loads(a), json.loads(b)),
            "boundary_required": report["boundary_required"], "hash_changed": report["hash_changed"],
            "flags": report["flags"]}


def identity_conflicts(identities: Iterable[Mapping]) -> list:
    """``[[strategy_id, version, [identity hashes]], ...]`` for labels that name several identities."""
    by_label: dict = {}
    for ident in identities:
        by_label.setdefault((ident["strategy_id"], ident["version"]), set()).add(ident["identity_hash"])
    return sorted([sid, ver, sorted(hashes)] for (sid, ver), hashes in by_label.items() if len(hashes) > 1)


def check_identity_registry(docs: Iterable[Mapping]) -> None:
    """Refuse golden documents in which one (strategy_id, version) label names two identities."""
    identities = [case["output"]["strategy"] for doc in docs for case in doc.get("cases") or ()
                  if isinstance(case.get("output"), Mapping)
                  and case["output"].get("schema") == WP2_OUTPUT_SCHEMA]
    conflicts = identity_conflicts(identities)
    if conflicts:
        raise HarnessIdentityError(f"one version label names several identities (SE-38 stop "
                                   f"condition): {conflicts}")


# ── command line ───────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="golden_replay.py", description="WP-A04 golden replay harness")
    parser.add_argument("command", choices=("check", "print", "regenerate"))
    parser.add_argument("--suite", action="append", metavar="MODULE:ATTR",
                        help=f"suites to use (default {DEFAULT_SUITES}; required for regenerate)")
    args = parser.parse_args(argv)
    if args.command == "regenerate" and not args.suite:
        print("regenerate rewrites golden files: name each suite explicitly with --suite", file=sys.stderr)
        return 2
    try:
        suites = load_suites(args.suite or (DEFAULT_SUITES,))
        if args.command == "print":
            sys.stdout.buffer.write(print_bytes(suites))
            return 0
        if args.command == "regenerate":
            for suite in suites:
                print(write_golden(replay_suite(suite), suite.golden_file, regenerate=True))
            return 0
        docs, clean = [], True
        for suite in suites:
            actual = replay_suite(suite)
            docs.append(actual)
            diff = compare_to_golden(actual, load_golden(suite.golden_file))
            clean = clean and diff.ok
            print(f"{suite.golden_name}: {'OK' if diff.ok else 'MISMATCH'}")
            if not diff.ok:
                print(diff.summary())
        check_identity_registry(docs)
        return 0 if clean else 1
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    import golden_replay as _harness          # one module object for the suites and the CLI
    sys.exit(_harness.main())
