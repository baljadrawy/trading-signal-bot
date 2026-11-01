"""Strategy-rule identity: a declared decision closure and deterministic StrategyVersion hashes.

Pure and dormant: no service imports this module and nothing here reads the environment, the
clock, the network or a database. Hashes are computed only over the bytes the caller passes in.

What it is for (WP2 lane A; R5.d; SE-04, SE-37, SE-61, SE-63; WP-IR-09):

* ``StrategyRuleManifest`` declares, per ``strategy_id``, every source file that can change a
  Candidate, a rejection or a position action, and named code regions inside them. The draft
  closure below covers the logic the legacy research contract hash omits (SE-04): the W3 T1-cap
  code in ``analyzer/technical_analyzer.py`` and ``shared/t1_cap.py``, ``shared/signal_identity.py``,
  the ``LIMIT 200`` candidate query of ``signal_engine/main.py`` and the cost-booking code.
* ``source_hash`` = sha256 over the sorted ``[path, sha256(normalized bytes)]`` pairs of that
  closure; ``config_hash`` comes from ``shared.strategy_config_snapshot``; ``contract_hash`` =
  sha256 over the canonical StrategyContract descriptor. All three use the research contract's
  canonical JSON (sorted keys, compact separators, ASCII), so the scheme stays comparable.
* ``StrategyVersion`` carries the five identity fields; ``lineage`` is recorded metadata and is
  excluded from every identity comparison (WP-IR-09).

What it is not:

* It never recomputes, reads or rewrites ``research/governance/research_freeze.json`` or the v1
  ``current_contract()`` hash. The historical freeze hash is a separate, unchanged artefact with
  a different scheme; ``compare_to_reference`` says so explicitly in every report.
* The closure list and the decision-key list are drafts for the WP-A01 owner review. Changing a
  version, activating identity emission or writing a boundary entry needs owner approval.

Normalization: CR LF and lone CR become LF before hashing. Python reads source with universal
newlines, so this changes no behaviour; every other byte (whitespace included) counts.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

IDENTITY_MANIFEST_SCHEMA = "tsb-strategy-identity/1"
IDENTITY_DIFF_SCHEMA = "tsb-strategy-identity-diff/1"
SOURCE_SCHEME = "tsb-strategy-source/1"
CLOSURE_SPEC_SCHEME = "tsb-strategy-closure-spec/1"
CONTRACT_SCHEME = "tsb-strategy-contract/1"
VERSION_SCHEME = "tsb-strategy-version/1"

DRAFT_STATUS = "DRAFT_PENDING_WP_A01_REVIEW"

# The nine logic files the legacy research contract hashes (research/foundation/contract.py:L68-71
# @ 46578aa). Listed for coverage reporting only; the v1 hash itself is never recomputed here.
LEGACY_CONTRACT_V1_SOURCES = (
    "analyzer/simple_entry.py", "shared/regime.py", "shared/signal_stop.py",
    "shared/triple_barrier.py", "shared/partial_exits.py", "shared/risk_management.py",
    "shared/strategy_math.py", "scanner/scanner_logic.py", "signal_engine/signal_logic.py",
)

HISTORICAL_FREEZE = MappingProxyType({
    "artifact": "research/governance/research_freeze.json",
    "field": "freeze_strategy_contract_hash",
    "status": "SEPARATE_UNCHANGED_ARTIFACT",
    "read": False,
    "recomputed": False,
    "comparable_with_source_hash": False,
    "note": ("The historical freeze hash uses the legacy 9-file contract scheme; its generator is "
             "not found (SE-05). It is referenced, never rewritten, and is not compared with "
             "source_hash (SE-39)."),
})

REQUIRED_CONTRACT_KEYS = (
    "input_spec", "output_schema_versions", "regime_providers", "cost_model_id",
    "fill_model_id", "holding_policy", "failure_criteria",
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
STRATEGY_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REGION_ID = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
QUALNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
SELECTOR_KINDS = ("def", "assign", "literal")


class ClosureError(ValueError):
    """The closure or its inputs are not well defined; callers must treat the identity as unknown."""


# ── canonical JSON and hashing ─────────────────────────────────────────────────────────────

def _check_json(value: Any, where: str = "$") -> None:
    """Refuse anything whose JSON form is not unique: non-str keys, NaN/inf, sets, objects."""
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ClosureError(f"non-finite number at {where}")
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check_json(item, f"{where}[{i}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ClosureError(f"non-string key {key!r} at {where}")
            _check_json(item, f"{where}.{key}")
        return
    raise ClosureError(f"value of type {type(value).__name__} at {where} has no canonical JSON form")


def canonical_json(value: Any) -> str:
    """The research contract's canonical form (sorted keys, compact, ASCII), strict on input."""
    _check_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def normalize_source(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray)):
        raise ClosureError("source content must be bytes")
    return bytes(data).replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def file_digest(data: bytes) -> str:
    """sha256 of the normalized bytes of one closure file."""
    return hashlib.sha256(normalize_source(data)).hexdigest()


def _check_path(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ClosureError("closure path must be a non-empty string")
    pure = PurePosixPath(path)
    if ("\\" in path or pure.is_absolute() or str(pure) != path
            or any(part in ("", ".", "..") for part in pure.parts)):
        raise ClosureError(f"closure path must be a normalized repository-relative path: {path!r}")
    return path


# ── the declarative manifest ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegionSpec:
    """A named code region inside a closure file, resolved with ``ast`` (never imported or run).

    ``selector`` is one of:
      ``def:Name`` / ``def:Class.method``   a function or class (decorators included);
      ``assign:NAME``                        a module-level assignment;
      ``literal:TEXT``                       the single string constant containing TEXT.
    ``purpose`` is documentation only and does not enter any hash.
    """
    region_id: str
    selector: str
    purpose: str = ""

    def __post_init__(self):
        if not isinstance(self.region_id, str) or not REGION_ID.match(self.region_id):
            raise ClosureError(f"invalid region_id {self.region_id!r}")
        kind, sep, arg = str(self.selector).partition(":")
        if not sep or kind not in SELECTOR_KINDS or not arg:
            raise ClosureError(f"invalid selector {self.selector!r}")
        if kind in ("def", "assign") and not QUALNAME.match(arg):
            raise ClosureError(f"invalid name in selector {self.selector!r}")
        if kind == "assign" and "." in arg:
            raise ClosureError(f"assign selector takes a module-level name: {self.selector!r}")


@dataclass(frozen=True)
class ClosureFile:
    """One file of the decision closure. The whole file always enters ``source_hash``; regions
    name the decision-critical parts so a report can say which of them changed, and fail closed
    when one of them disappears or becomes ambiguous."""
    path: str
    role: str
    regions: tuple = ()

    def __post_init__(self):
        _check_path(self.path)
        regions = tuple(self.regions)
        if any(not isinstance(r, RegionSpec) for r in regions):
            raise ClosureError(f"regions of {self.path} must be RegionSpec")
        if regions and not self.path.endswith(".py"):
            raise ClosureError(f"regions need a Python file: {self.path}")
        object.__setattr__(self, "regions", tuple(sorted(regions, key=lambda r: r.region_id)))

    @property
    def in_legacy_contract_v1(self) -> bool:
        return self.path in LEGACY_CONTRACT_V1_SOURCES


@dataclass(frozen=True)
class StrategyRuleManifest:
    """The declared decision closure of one strategy_id. Order of files and regions is
    normalized, so two manifests that list the same content in another order are equal."""
    strategy_id: str
    files: tuple
    status: str = DRAFT_STATUS

    def __post_init__(self):
        if not isinstance(self.strategy_id, str) or not STRATEGY_ID.match(self.strategy_id):
            raise ClosureError(f"invalid strategy_id {self.strategy_id!r}")
        files = tuple(self.files)
        if not files or any(not isinstance(f, ClosureFile) for f in files):
            raise ClosureError("a manifest needs at least one ClosureFile")
        paths = [f.path for f in files]
        if len(set(paths)) != len(paths):
            raise ClosureError("duplicate path in closure")
        region_ids = [r.region_id for f in files for r in f.regions]
        if len(set(region_ids)) != len(region_ids):
            raise ClosureError("duplicate region_id in closure")
        object.__setattr__(self, "files", tuple(sorted(files, key=lambda f: f.path)))

    @property
    def paths(self) -> tuple:
        return tuple(f.path for f in self.files)

    def spec(self) -> dict:
        """The hashed part of the declaration (roles and purposes are documentation)."""
        return {"scheme": CLOSURE_SPEC_SCHEME, "strategy_id": self.strategy_id,
                "files": [{"path": f.path,
                           "regions": [[r.region_id, r.selector] for r in f.regions]}
                          for f in self.files]}

    @property
    def closure_spec_hash(self) -> str:
        return canonical_hash(self.spec())

    def outside_legacy_contract_v1(self) -> tuple:
        """Closure files the legacy 9-file contract hash cannot see (the SE-04 gap)."""
        return tuple(f.path for f in self.files if not f.in_legacy_contract_v1)


# ── region resolution ──────────────────────────────────────────────────────────────────────

def _lines_segment(lines: list, start: int, end: int) -> str:
    return "\n".join(lines[start - 1:end])


def _resolve_region(text: str, path: str, region: RegionSpec) -> str:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise ClosureError(f"{path}: cannot parse ({exc.msg})") from None
    lines = text.split("\n")
    kind, _, arg = region.selector.partition(":")
    where = f"{path} {region.region_id} ({region.selector})"
    if kind == "def":
        body, node = tree.body, None
        for part in arg.split("."):
            found = [n for n in body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and n.name == part]
            if len(found) != 1:
                raise ClosureError(f"{where}: {len(found)} definitions named {part!r}")
            node = found[0]
            body = node.body
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        return _lines_segment(lines, start, node.end_lineno)
    if kind == "assign":
        found = []
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == arg
                                                 for t in n.targets):
                found.append(n)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == arg:
                found.append(n)
        if len(found) != 1:
            raise ClosureError(f"{where}: {len(found)} module-level assignments")
        return _lines_segment(lines, found[0].lineno, found[0].end_lineno)
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and arg in n.value]
    if len(found) != 1:
        raise ClosureError(f"{where}: {len(found)} string constants contain the text")
    return found[0].value


def region_digest(text: str, path: str, region: RegionSpec) -> str:
    return hashlib.sha256(_resolve_region(text, path, region).encode("utf-8")).hexdigest()


# ── closure digest ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClosureDigest:
    strategy_id: str
    closure_spec_hash: str
    files: tuple          # ((path, sha256), ...) sorted by path
    regions: tuple        # ((region_id, path, selector, sha256), ...) sorted by region_id
    source_hash: str

    def file_map(self) -> dict:
        return dict(self.files)


def source_hash_from_digests(file_digests: Mapping[str, str]) -> str:
    pairs = []
    for path in sorted(file_digests):
        digest = file_digests[path]
        if not isinstance(digest, str) or not HEX64.match(digest):
            raise ClosureError(f"invalid digest for {path}")
        pairs.append([_check_path(path), digest])
    if not pairs:
        raise ClosureError("empty closure")
    return canonical_hash({"scheme": SOURCE_SCHEME, "files": pairs})


def compute_closure(manifest: StrategyRuleManifest, sources: Mapping[str, bytes]) -> ClosureDigest:
    """Hash exactly the declared closure. ``sources`` maps each declared path to its bytes; a
    missing or an undeclared path is refused, so nothing outside the closure can move the hash."""
    if not isinstance(manifest, StrategyRuleManifest):
        raise ClosureError("manifest must be a StrategyRuleManifest")
    given, declared = set(sources), set(manifest.paths)
    if declared - given:
        raise ClosureError(f"closure files missing: {sorted(declared - given)}")
    if given - declared:
        raise ClosureError(f"files not in the declared closure: {sorted(given - declared)}")
    files, regions = {}, []
    for entry in manifest.files:
        data = normalize_source(sources[entry.path])
        files[entry.path] = hashlib.sha256(data).hexdigest()
        if entry.regions:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise ClosureError(f"{entry.path}: not UTF-8") from None
            for region in entry.regions:
                regions.append((region.region_id, entry.path, region.selector,
                                region_digest(text, entry.path, region)))
    return ClosureDigest(strategy_id=manifest.strategy_id,
                         closure_spec_hash=manifest.closure_spec_hash,
                         files=tuple(sorted(files.items())),
                         regions=tuple(sorted(regions)),
                         source_hash=source_hash_from_digests(files))


def read_closure_sources(root: Path, manifest: StrategyRuleManifest) -> dict:
    """Read-only helper for an explicit checkout root: the declared files only, never outside
    ``root``. Pure hashing (``compute_closure``) does not call it."""
    base = Path(root).resolve()
    out = {}
    for path in manifest.paths:
        target = (base / path).resolve()
        if base != target and base not in target.parents:
            raise ClosureError(f"{path} resolves outside the root")
        if not target.is_file():
            raise ClosureError(f"closure file not found: {path}")
        out[path] = target.read_bytes()
    return out


# ── StrategyVersion ────────────────────────────────────────────────────────────────────────

def contract_descriptor_hash(descriptor: Mapping) -> str:
    """sha256 over the canonical StrategyContract descriptor (SE-37). Every required key must be
    present; values are the caller's declaration and are not interpreted here."""
    if not isinstance(descriptor, Mapping):
        raise ClosureError("contract descriptor must be a mapping")
    missing = [k for k in REQUIRED_CONTRACT_KEYS if k not in descriptor]
    if missing:
        raise ClosureError(f"contract descriptor missing keys: {missing}")
    return canonical_hash({"scheme": CONTRACT_SCHEME, "descriptor": dict(descriptor)})


@dataclass(frozen=True)
class StrategyVersion:
    """The five identity fields (WP-IR-09) plus ``lineage`` as metadata."""
    strategy_id: str
    version: str
    source_hash: str
    config_hash: str
    contract_hash: str
    lineage: tuple = field(default=(), compare=False)

    def __post_init__(self):
        if not isinstance(self.strategy_id, str) or not STRATEGY_ID.match(self.strategy_id):
            raise ClosureError(f"invalid strategy_id {self.strategy_id!r}")
        if not isinstance(self.version, str) or not SEMVER.match(self.version):
            raise ClosureError(f"version must be MAJOR.MINOR.PATCH: {self.version!r}")
        for name in ("source_hash", "config_hash", "contract_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not HEX64.match(value):
                raise ClosureError(f"{name} must be 64 lowercase hex characters")
        lineage = tuple(self.lineage)
        if any(not isinstance(x, str) or not x for x in lineage):
            raise ClosureError("lineage entries must be non-empty strings")
        object.__setattr__(self, "lineage", lineage)

    def identity(self) -> dict:
        return {"strategy_id": self.strategy_id, "version": self.version,
                "source_hash": self.source_hash, "config_hash": self.config_hash,
                "contract_hash": self.contract_hash}

    @property
    def identity_hash(self) -> str:
        return canonical_hash({"scheme": VERSION_SCHEME, **self.identity()})

    @property
    def identifier(self) -> str:
        """Compact identifier for records (lineage excluded)."""
        return f"{self.strategy_id}/{self.version}/{self.identity_hash[:16]}"


def build_identity(manifest: StrategyRuleManifest, sources: Mapping[str, bytes], *, version: str,
                   config_snapshot, contract_descriptor: Mapping, lineage=()) -> tuple:
    """Compute ``(StrategyVersion, identity manifest dict)`` from explicit inputs only.

    ``config_snapshot`` is a ``shared.strategy_config_snapshot.StrategyConfigSnapshot`` for the
    same strategy_id. ``version`` and ``lineage`` are the caller's declaration; nothing is
    defaulted from configuration or ``APP_VERSION``."""
    digest = compute_closure(manifest, sources)
    if getattr(config_snapshot, "strategy_id", None) != manifest.strategy_id:
        raise ClosureError("config snapshot belongs to another strategy_id")
    config_hash = getattr(config_snapshot, "config_hash", None)
    sv = StrategyVersion(strategy_id=manifest.strategy_id, version=version,
                         source_hash=digest.source_hash, config_hash=config_hash,
                         contract_hash=contract_descriptor_hash(contract_descriptor),
                         lineage=tuple(lineage))
    legacy = {f.path: f.in_legacy_contract_v1 for f in manifest.files}
    doc = {
        "schema": IDENTITY_MANIFEST_SCHEMA,
        **sv.identity(),
        "identity_hash": sv.identity_hash,
        "lineage": list(sv.lineage),
        "closure_status": manifest.status,
        "closure_spec_hash": digest.closure_spec_hash,
        "files": {path: {"sha256": sha, "in_legacy_contract_v1": legacy[path]}
                  for path, sha in digest.files},
        "regions": {rid: {"path": path, "selector": sel, "sha256": sha}
                    for rid, path, sel, sha in digest.regions},
        "config": config_snapshot.to_dict(),
        "contract_descriptor": json.loads(canonical_json(dict(contract_descriptor))),
        "historical_freeze": dict(HISTORICAL_FREEZE),
    }
    canonical_json(doc)
    return sv, doc


# ── comparison with a reference ────────────────────────────────────────────────────────────

def _file_digests_of(doc: Mapping) -> dict:
    if doc.get("schema") == IDENTITY_MANIFEST_SCHEMA:
        files = doc.get("files")
        if not isinstance(files, Mapping):
            raise ClosureError("identity manifest without files")
        out = {p: (v.get("sha256") if isinstance(v, Mapping) else None) for p, v in files.items()}
    else:
        out = dict(doc)
    for path, sha in out.items():
        _check_path(path)
        if not isinstance(sha, str) or not HEX64.match(sha):
            raise ClosureError(f"invalid digest for {path}")
    return out


def compare_to_reference(current: Mapping, reference: Mapping) -> dict:
    """Report which closure files (and regions) differ from a reference.

    ``current`` is an identity manifest; ``reference`` is an identity manifest or a plain
    ``{path: sha256}`` mapping. Pure and deterministic. The historical research freeze hash is
    reported as a separate, unchanged artefact: it is never read, recomputed or compared."""
    if not isinstance(current, Mapping) or current.get("schema") != IDENTITY_MANIFEST_SCHEMA:
        raise ClosureError("current must be an identity manifest")
    if not isinstance(reference, Mapping):
        raise ClosureError("reference must be a mapping")
    cur, ref = _file_digests_of(current), _file_digests_of(reference)
    full_ref = reference.get("schema") == IDENTITY_MANIFEST_SCHEMA
    changed = sorted(p for p in cur.keys() & ref.keys() if cur[p] != ref[p])
    legacy = {p: bool((current["files"].get(p) or {}).get("in_legacy_contract_v1",
                                                         p in LEGACY_CONTRACT_V1_SOURCES))
              for p in cur}
    report = {
        "schema": IDENTITY_DIFF_SCHEMA,
        "strategy_id": current.get("strategy_id"),
        "reference_kind": "identity_manifest" if full_ref else "file_digests",
        "files_changed": changed,
        "files_added": sorted(cur.keys() - ref.keys()),
        "files_removed": sorted(ref.keys() - cur.keys()),
        "files_unchanged": len(cur.keys() & ref.keys()) - len(changed),
        "changed_outside_legacy_contract_v1": sorted(
            p for p in changed + sorted(cur.keys() - ref.keys()) if not legacy.get(p)),
        "source_hash_equal": source_hash_from_digests(cur) == source_hash_from_digests(ref)
                             if ref else False,
        "historical_freeze": dict(HISTORICAL_FREEZE),
    }
    if full_ref:
        cr, rr = current.get("regions") or {}, reference.get("regions") or {}
        report.update({
            "strategy_id_equal": current.get("strategy_id") == reference.get("strategy_id"),
            "regions_changed": sorted(r for r in cr.keys() & rr.keys()
                                      if cr[r] != rr[r]),
            "regions_added": sorted(cr.keys() - rr.keys()),
            "regions_removed": sorted(rr.keys() - cr.keys()),
            "closure_spec_equal": current.get("closure_spec_hash") == reference.get("closure_spec_hash"),
        })
        for name in ("config_hash", "contract_hash", "identity_hash"):
            report[f"{name}_equal"] = current.get(name) == reference.get(name)
    return report


# ── draft closure for the frozen 1.0.0 families (SE-39), pending WP-A01 owner review ───────

def _legacy(path: str, role: str) -> ClosureFile:
    return ClosureFile(path=path, role=role)


_CURRENT_FAMILY_FILES = (
    _legacy("analyzer/simple_entry.py", "entry predicates"),
    _legacy("shared/regime.py", "regime provider (classify_regime)"),
    _legacy("shared/signal_stop.py", "stop geometry"),
    _legacy("shared/triple_barrier.py", "exit barriers and holding expiry"),
    _legacy("shared/partial_exits.py", "partial exits"),
    _legacy("shared/risk_management.py", "risk checks"),
    _legacy("shared/strategy_math.py", "strategy arithmetic"),
    _legacy("scanner/scanner_logic.py", "universe filter"),
    _legacy("signal_engine/signal_logic.py", "signal decision and emission"),
    ClosureFile("analyzer/technical_analyzer.py", "geometry and T1 cap call site (W3); scores", (
        RegionSpec("analyzer_calculate_levels", "def:TechnicalAnalyzer._calculate_levels",
                   "W3: bracket and T1 cap applied through shared.t1_cap"),
        RegionSpec("analyzer_calculate_scores", "def:TechnicalAnalyzer._calculate_scores",
                   "total_score, which orders the candidate query"),
    )),
    ClosureFile("shared/t1_cap.py", "T1 resistance-cap policy (W3)", (
        RegionSpec("t1_cap_fill", "assign:RESISTANCE_FILL", "cap factor"),
        RegionSpec("t1_cap_window", "assign:WINDOW", "legacy window length"),
        RegionSpec("t1_cap_policies", "assign:T1_CAP_POLICIES", "selectable policies"),
        RegionSpec("t1_cap_policy_select", "def:t1_cap_policy", "fail-closed policy selection"),
        RegionSpec("t1_cap_legacy_window", "def:legacy_window_resistance", "legacy_window_v1"),
        RegionSpec("t1_cap_independent_swing", "def:independent_swing_resistance",
                   "independent_swing_v1"),
        RegionSpec("t1_cap_resistance_for", "def:resistance_for", "policy dispatch"),
        RegionSpec("t1_cap_capped_t1", "def:capped_t1", "the cap itself"),
    )),
    ClosureFile("shared/signal_identity.py", "setup identity, freshness, integrity mode", (
        RegionSpec("sid_identity_version", "assign:IDENTITY_VERSION", "key version"),
        RegionSpec("sid_integrity_mode", "def:integrity_mode", "SIGNAL_INTEGRITY_MODE"),
        RegionSpec("sid_setup_identity", "def:SetupIdentity", "setup_key composition"),
        RegionSpec("sid_freshness_at", "def:freshness_at", "one-bar freshness bound"),
        RegionSpec("sid_integrity_check", "def:integrity_check", "enforce-mode verdict"),
    )),
    ClosureFile("signal_engine/main.py", "candidate selection", (
        RegionSpec("selection_limit_constant", "assign:SELECTION_LIMIT", "the selection LIMIT"),
        RegionSpec("selection_candidate_query", "literal:LIMIT 200",
                   "ordering and alphabetical LIMIT 200 cut of the candidate query"),
    )),
    ClosureFile("shared/macro_context.py", "macro veto regime input (SE-06; B5)"),
    ClosureFile("shared/fees.py", "cost booking", (
        RegionSpec("fees_economic_close", "def:economic_close", "net-of-cost booking"),
        RegionSpec("fees_fee_usdt", "def:fee_usdt", "modeled roundtrip cost"),
    )),
    ClosureFile("trade_tracker/main.py", "exits, holding and cost booking", (
        RegionSpec("tracker_evaluate_trade", "def:evaluate_trade", "exit rules (manage)"),
        RegionSpec("tracker_close_trade_barrier", "def:close_trade_barrier", "cost booking at close"),
        RegionSpec("tracker_assess_new_trade_risk", "def:assess_new_trade_risk",
                   "net-of-cost admission snapshot"),
    )),
)

DRAFT_MANIFESTS = MappingProxyType({
    sid: StrategyRuleManifest(strategy_id=sid, files=_CURRENT_FAMILY_FILES)
    for sid in ("momentum_breakout", "reversion_rsi_bb")
})
