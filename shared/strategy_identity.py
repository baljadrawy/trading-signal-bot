"""Strategy-rule identity: a declared decision closure and deterministic StrategyVersion hashes.

Pure: nothing here reads the environment, the clock, the network or a database. Hashes are
computed only over the bytes the caller passes in. No service imports it today; the integration
points are listed in docs/design/STRATEGY_INTERFACE_v1.md section 9.

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
* The closure data below is an evidence-backed proposal for owner review (WP-A01; the call-path
  inventory is docs/design/STRATEGY_INTERFACE_v1.md section 3). Changing a version, activating
  identity emission or writing a boundary entry needs owner approval.

Classification (WP-A01): every closure file and region is ``ACTIVE`` (on a call path that can
change a decision under the runtime-verified configuration), ``DORMANT`` (reachable only behind an
off flag or an unused mode), ``POTENTIAL`` (on no call path) or ``OBSERVE_ONLY`` (telemetry or
shadow code that runs, or may be switched on, but by construction cannot change a decision or the
booked economics). Only ACTIVE entries feed ``source_hash``. The other classes are hashed
separately into ``inactive_hash``: a
reviewer sees their drift, but they cannot move the identity until a version activates them,
and that activation is itself a boundary (it flips a ``config_hash`` key or the closure spec).
A file's ``scope`` is ``file`` (all normalized bytes count; the default) or ``regions`` (only
its ACTIVE regions count; used where the decision rules are a small part of a larger file).

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
CLOSURE_DOCUMENT_SCHEMA = "tsb-strategy-closure/1"
SOURCE_SCHEME = "tsb-strategy-source/1"
CLOSURE_SPEC_SCHEME = "tsb-strategy-closure-spec/1"
CONTRACT_SCHEME = "tsb-strategy-contract/1"
VERSION_SCHEME = "tsb-strategy-version/1"

DRAFT_STATUS = "DRAFT_PENDING_WP_A01_REVIEW"
PROPOSAL_STATUS = "EVIDENCE_BACKED_PROPOSAL_PENDING_OWNER_REVIEW"
INACTIVE_SCHEME = "tsb-strategy-inactive-source/1"
REGION_SCOPE_SCHEME = "tsb-strategy-region-scope/1"

ACTIVE, DORMANT, POTENTIAL = "ACTIVE", "DORMANT", "POTENTIAL"
OBSERVE_ONLY = "OBSERVE_ONLY"
CLASSIFICATIONS = (ACTIVE, DORMANT, POTENTIAL, OBSERVE_ONLY)
FILE_SCOPE, REGIONS_SCOPE = "file", "regions"
SCOPES = (FILE_SCOPE, REGIONS_SCOPE)

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
    ``purpose`` is documentation only and does not enter any hash. ``classification`` says whether
    the region is on an active decision path (it enters the closure spec only when not ACTIVE).
    """
    region_id: str
    selector: str
    purpose: str = ""
    classification: str = ACTIVE

    def __post_init__(self):
        if self.classification not in CLASSIFICATIONS:
            raise ClosureError(f"invalid classification {self.classification!r}")
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
    """One file of the decision closure. With ``scope="file"`` (default) the whole normalized file
    is its digest; with ``scope="regions"`` the digest covers its ACTIVE regions only. Regions name
    the decision-critical parts so a report can say which of them changed, and fail closed when
    one of them disappears or becomes ambiguous. Only ACTIVE files feed ``source_hash``."""
    path: str
    role: str
    regions: tuple = ()
    classification: str = ACTIVE
    scope: str = FILE_SCOPE

    def __post_init__(self):
        _check_path(self.path)
        if self.classification not in CLASSIFICATIONS:
            raise ClosureError(f"{self.path}: invalid classification {self.classification!r}")
        if self.scope not in SCOPES:
            raise ClosureError(f"{self.path}: invalid scope {self.scope!r}")
        regions = tuple(self.regions)
        if any(not isinstance(r, RegionSpec) for r in regions):
            raise ClosureError(f"regions of {self.path} must be RegionSpec")
        if regions and not self.path.endswith(".py"):
            raise ClosureError(f"regions need a Python file: {self.path}")
        if self.scope == REGIONS_SCOPE and not any(r.classification == ACTIVE for r in regions):
            raise ClosureError(f"{self.path}: scope 'regions' needs at least one ACTIVE region")
        object.__setattr__(self, "regions", tuple(sorted(regions, key=lambda r: r.region_id)))

    @property
    def is_active(self) -> bool:
        return self.classification == ACTIVE

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
        if not any(f.is_active for f in files):
            raise ClosureError("a closure needs at least one ACTIVE file")
        object.__setattr__(self, "files", tuple(sorted(files, key=lambda f: f.path)))

    @property
    def paths(self) -> tuple:
        """Every declared path (ACTIVE and inactive): all of them must be supplied."""
        return tuple(f.path for f in self.files)

    @property
    def active_paths(self) -> tuple:
        return tuple(f.path for f in self.files if f.is_active)

    @property
    def inactive_paths(self) -> tuple:
        return tuple(f.path for f in self.files if not f.is_active)

    def file(self, path: str) -> "ClosureFile":
        for f in self.files:
            if f.path == path:
                return f
        raise ClosureError(f"{path} is not in the closure")

    def spec(self) -> dict:
        """The hashed part of the declaration (roles and purposes are documentation). Non-default
        classifications and scopes are added only when present, so an all-ACTIVE, file-scoped
        manifest keeps the spec form of tsb-strategy-closure-spec/1 unchanged."""
        files = []
        for f in self.files:
            entry = {"path": f.path,
                     "regions": [[r.region_id, r.selector] + ([r.classification]
                                                              if r.classification != ACTIVE else [])
                                 for r in f.regions]}
            if f.classification != ACTIVE:
                entry["classification"] = f.classification
            if f.scope != FILE_SCOPE:
                entry["scope"] = f.scope
            files.append(entry)
        return {"scheme": CLOSURE_SPEC_SCHEME, "strategy_id": self.strategy_id, "files": files}

    @property
    def closure_spec_hash(self) -> str:
        return canonical_hash(self.spec())

    def outside_legacy_contract_v1(self) -> tuple:
        """ACTIVE closure files the legacy 9-file contract hash cannot see (the SE-04 gap)."""
        return tuple(f.path for f in self.files if f.is_active and not f.in_legacy_contract_v1)

    def legacy_contract_v1_inactive(self) -> tuple:
        """Files the legacy contract hashes although no service call path reaches them."""
        return tuple(f.path for f in self.files if not f.is_active and f.in_legacy_contract_v1)


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
    files: tuple          # ((path, digest), ...) of ACTIVE files, sorted by path
    regions: tuple        # ((region_id, path, selector, sha256), ...) of all regions, by region_id
    source_hash: str
    inactive_files: tuple = ()     # ((path, classification, digest), ...) of DORMANT/POTENTIAL files
    inactive_hash: str | None = None

    def file_map(self) -> dict:
        """ACTIVE files only: exactly the pairs ``source_hash`` covers."""
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


def inactive_hash_from(entries) -> str | None:
    """sha256 over the sorted ``[path, classification, digest]`` of the non-ACTIVE files."""
    rows = sorted([_check_path(p), c, d] for p, c, d in entries)
    return canonical_hash({"scheme": INACTIVE_SCHEME, "files": rows}) if rows else None


def compute_closure(manifest: StrategyRuleManifest, sources: Mapping[str, bytes]) -> ClosureDigest:
    """Hash exactly the declared closure. ``sources`` maps each declared path (ACTIVE and
    inactive) to its bytes; a missing or an undeclared path is refused, so nothing outside the
    closure can move the hash. Every region must resolve, whatever its classification."""
    if not isinstance(manifest, StrategyRuleManifest):
        raise ClosureError("manifest must be a StrategyRuleManifest")
    given, declared = set(sources), set(manifest.paths)
    if declared - given:
        raise ClosureError(f"closure files missing: {sorted(declared - given)}")
    if given - declared:
        raise ClosureError(f"files not in the declared closure: {sorted(given - declared)}")
    files, inactive, regions = {}, [], []
    for entry in manifest.files:
        data = normalize_source(sources[entry.path])
        digest = hashlib.sha256(data).hexdigest()
        if entry.regions:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise ClosureError(f"{entry.path}: not UTF-8") from None
            own = [(region.region_id, entry.path, region.selector,
                    region_digest(text, entry.path, region)) for region in entry.regions]
            regions.extend(own)
            if entry.scope == REGIONS_SCOPE:
                active = {r.region_id for r in entry.regions if r.classification == ACTIVE}
                digest = canonical_hash({"scheme": REGION_SCOPE_SCHEME,
                                         "regions": [[rid, sel, sha] for rid, _, sel, sha in own
                                                     if rid in active]})
        if entry.is_active:
            files[entry.path] = digest
        else:
            inactive.append((entry.path, entry.classification, digest))
    return ClosureDigest(strategy_id=manifest.strategy_id,
                         closure_spec_hash=manifest.closure_spec_hash,
                         files=tuple(sorted(files.items())),
                         regions=tuple(sorted(regions)),
                         source_hash=source_hash_from_digests(files),
                         inactive_files=tuple(sorted(inactive)),
                         inactive_hash=inactive_hash_from(inactive))


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


def _closure_fields(manifest: StrategyRuleManifest, digest: ClosureDigest) -> dict:
    legacy = {f.path: f.in_legacy_contract_v1 for f in manifest.files}
    scope = {f.path: f.scope for f in manifest.files}
    region_class = {r.region_id: r.classification for f in manifest.files for r in f.regions}
    return {
        "closure_status": manifest.status,
        "closure_spec_hash": digest.closure_spec_hash,
        "files": {path: {"sha256": sha, "in_legacy_contract_v1": legacy[path], "scope": scope[path]}
                  for path, sha in digest.files},
        "inactive_files": {path: {"sha256": sha, "classification": cls,
                                  "in_legacy_contract_v1": legacy[path], "scope": scope[path]}
                           for path, cls, sha in digest.inactive_files},
        "inactive_hash": digest.inactive_hash,
        "regions": {rid: {"path": path, "selector": sel, "sha256": sha,
                          "classification": region_class[rid]}
                    for rid, path, sel, sha in digest.regions},
    }


def closure_document(manifest: StrategyRuleManifest, sources: Mapping[str, bytes]) -> dict:
    """The source side of an identity manifest, without config or contract: what a checkout
    alone can prove (used by the drift_check ``strategy`` report)."""
    digest = compute_closure(manifest, sources)
    doc = {"schema": CLOSURE_DOCUMENT_SCHEMA, "strategy_id": manifest.strategy_id,
           "source_hash": digest.source_hash, **_closure_fields(manifest, digest),
           "historical_freeze": dict(HISTORICAL_FREEZE)}
    canonical_json(doc)
    return doc


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
    doc = {
        "schema": IDENTITY_MANIFEST_SCHEMA,
        **sv.identity(),
        "identity_hash": sv.identity_hash,
        "lineage": list(sv.lineage),
        **_closure_fields(manifest, digest),
        "config": config_snapshot.to_dict(),
        "contract_descriptor": json.loads(canonical_json(dict(contract_descriptor))),
        "historical_freeze": dict(HISTORICAL_FREEZE),
    }
    canonical_json(doc)
    return sv, doc


# ── comparison with a reference ────────────────────────────────────────────────────────────

_SOURCE_DOCS = (IDENTITY_MANIFEST_SCHEMA, CLOSURE_DOCUMENT_SCHEMA)


def _file_digests_of(doc: Mapping) -> dict:
    if doc.get("schema") in _SOURCE_DOCS:
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

    ``current`` is an identity manifest or a closure document (``closure_document``);
    ``reference`` is either of those or a plain ``{path: sha256}`` mapping. Pure and
    deterministic. Config, contract and identity equality are reported only when both sides are
    identity manifests. The historical research freeze hash is reported as a separate, unchanged
    artefact: it is never read, recomputed or compared."""
    if not isinstance(current, Mapping) or current.get("schema") not in _SOURCE_DOCS:
        raise ClosureError("current must be an identity manifest or a closure document")
    if not isinstance(reference, Mapping):
        raise ClosureError("reference must be a mapping")
    cur, ref = _file_digests_of(current), _file_digests_of(reference)
    full_ref = reference.get("schema") in _SOURCE_DOCS
    changed = sorted(p for p in cur.keys() & ref.keys() if cur[p] != ref[p])
    legacy = {p: bool((current["files"].get(p) or {}).get("in_legacy_contract_v1",
                                                         p in LEGACY_CONTRACT_V1_SOURCES))
              for p in cur}
    report = {
        "schema": IDENTITY_DIFF_SCHEMA,
        "strategy_id": current.get("strategy_id"),
        "reference_kind": ({IDENTITY_MANIFEST_SCHEMA: "identity_manifest",
                            CLOSURE_DOCUMENT_SCHEMA: "closure_document"}[reference["schema"]]
                           if full_ref else "file_digests"),
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
        both_identity = (current.get("schema") == reference.get("schema")
                         == IDENTITY_MANIFEST_SCHEMA)
        for name in ("config_hash", "contract_hash", "identity_hash"):
            report[f"{name}_equal"] = (current.get(name) == reference.get(name)
                                       if both_identity else None)
        ci = {p: (v or {}).get("sha256") for p, v in (current.get("inactive_files") or {}).items()}
        ri = {p: (v or {}).get("sha256") for p, v in (reference.get("inactive_files") or {}).items()}
        report.update({
            "inactive_files_changed": sorted(p for p in ci.keys() & ri.keys() if ci[p] != ri[p]),
            "inactive_files_added": sorted(ci.keys() - ri.keys()),
            "inactive_files_removed": sorted(ri.keys() - ci.keys()),
            "inactive_hash_equal": current.get("inactive_hash") == reference.get("inactive_hash"),
        })
    return report


# ── closure of the frozen 1.0.0 families (SE-39): evidence-backed proposal, owner review ──
# Classification from source-level call paths at a03efdd under the runtime-verified configuration
# (LIVE_LEARNING_MODE=true, SIGNAL_INTEGRITY_MODE off, LEARNING_GATES_ENABLED false, T1_CAP_POLICY
# unset, PAPER_ECONOMIC_HALT_MODE observe; OPPORTUNITY_FUNNEL.md OF-02). The call paths, line
# citations and the differences at the deployed commits ea8ae4f / bb7825f are in
# docs/design/STRATEGY_INTERFACE_v1.md section 3. Both families run through one shared pipeline
# (the analyzer sets trade_type; every later stage is common), so they share one closure; the
# split is an identity mapping only (SE-39).

def _f(path, role, *regions, classification=ACTIVE, scope=FILE_SCOPE) -> ClosureFile:
    return ClosureFile(path=path, role=role, regions=tuple(regions),
                       classification=classification, scope=scope)


def _r(region_id, selector, purpose, classification=ACTIVE) -> RegionSpec:
    return RegionSpec(region_id, selector, purpose, classification)


_CURRENT_FAMILY_FILES = (
    # scanner: universe, pause gate, retention
    _f("scanner/scanner_logic.py", "universe filter, pause gate, scanner BTC trend"),
    _f("scanner/main.py", "scan loop and pipeline retention call"),
    _f("shared/trading_state.py", "pause decision read (scanner, delivery, admission)",
       _r("pause_state", "def:get_pause_state", "fail-closed pause gate")),
    _f("shared/maintenance.py", "row expiry and retention",
       _r("maintain_pipeline", "def:maintain_pipeline", "expires and deletes funnel rows")),
    _f("shared/ohlcv.py", "closed-bar selection and candle validation",
       _r("ohlcv_closed_klines", "def:closed_klines", "closed-bar rule"),
       _r("ohlcv_prepare", "def:prepare_ohlcv", "history and data-quality rejection")),
    _f("shared/candle.py", "candle interval arithmetic (closed bar, same-candle admission guard)"),
    # analyzer: history, indicators, regime, setup, levels, order book
    _f("analyzer/main.py", "intake, per-timeframe loop, order-book reuse, upsert reset",
       _r("analyzer_intake_query", "literal:LIMIT 50", "newest-first intake of 50 rows"),
       _r("analyzer_symbol_all_timeframes", "def:analyze_symbol_all_timeframes",
          "upsert resets signal_generated (same-bar re-fire)")),
    _f("analyzer/technical_analyzer.py", "indicators, scores, setup call, levels and T1 cap (W3)",
       _r("analyzer_warmup", "def:indicator_warmup_bars", "minimum history"),
       _r("analyzer_analyze", "def:TechnicalAnalyzer.analyze", "per-timeframe analysis"),
       _r("analyzer_indicators", "def:TechnicalAnalyzer._calculate_indicators", "indicators"),
       _r("analyzer_weights", "def:TechnicalAnalyzer._get_indicator_weights",
          "database-held indicator_weights (legacy path, total_score only)"),
       _r("analyzer_calculate_scores", "def:TechnicalAnalyzer._calculate_scores",
          "total_score, which orders the candidate query"),
       _r("analyzer_calculate_levels", "def:TechnicalAnalyzer._calculate_levels",
          "W3: bracket and T1 cap applied through shared.t1_cap")),
    _f("analyzer/simple_entry.py", "entry predicates (momentum, reversion)"),
    _f("analyzer/orderbook_analyzer.py", "order-book validity and spread",
       _r("orderbook_analyze", "def:OrderBookAnalyzer.analyze", "valid flag and spread_pct")),
    _f("shared/regime.py", "regime provider (classify_regime)"),
    _f("shared/signal_stop.py", "stop geometry and candle invalidation"),
    _f("shared/t1_cap.py", "T1 resistance-cap policy (W3)",
       _r("t1_cap_fill", "assign:RESISTANCE_FILL", "cap factor"),
       _r("t1_cap_window", "assign:WINDOW", "legacy window length"),
       _r("t1_cap_policies", "assign:T1_CAP_POLICIES", "selectable policies"),
       _r("t1_cap_policy_select", "def:t1_cap_policy", "fail-closed policy selection"),
       _r("t1_cap_legacy_window", "def:legacy_window_resistance", "legacy_window_v1"),
       _r("t1_cap_independent_swing", "def:independent_swing_resistance",
          "independent_swing_v1 (T1_CAP_POLICY unset)", DORMANT),
       _r("t1_cap_resistance_for", "def:resistance_for", "policy dispatch"),
       _r("t1_cap_capped_t1", "def:capped_t1", "the cap itself")),
    # signal engine: selection, gates, ranking, emission
    _f("signal_engine/main.py", "selection query, selector dispatch, emit and mark",
       _r("selection_limit_constant", "assign:SELECTION_LIMIT", "the selection LIMIT"),
       _r("selection_candidate_query", "literal:LIMIT 200",
          "ordering and alphabetical LIMIT 200 cut of the candidate query")),
    _f("shared/selection_policy.py", "SELECTION_POLICY parse and the rank-then-limit selector",
       _r("selection_policies", "assign:SELECTION_POLICIES", "selectable policies"),
       _r("selection_policy_from_env", "def:selection_policy_from_env",
          "fail-closed policy parse; selects the legacy query at the default"),
       _r("selection_rank_then_limit", "def:rank_then_limit",
          "R1 ranking (SELECTION_POLICY=legacy)", DORMANT),
       _r("selection_tie_break_key", "def:tie_break_key", "R1 tie-break", DORMANT),
       _r("selection_score_of", "def:score_of", "R1 score read", DORMANT)),
    _f("signal_engine/signal_logic.py", "gates, ranking and signal emission",
       _r("signal_live_selector", "def:SignalEngine.find_best_signal_live", "live selector"),
       _r("signal_fixed_rank_key", "def:SignalEngine._fixed_candidate_key", "ranking key"),
       _r("signal_cooldown_sql", "assign:COOLDOWN_SQL", "2 h symbol cooldown"),
       _r("signal_cooldown_set", "def:SignalEngine._get_symbol_cooldown_set",
          "cooldown read (fails open)"),
       _r("signal_save", "def:SignalEngine.save_signal", "insert and signal.ready"),
       _r("signal_legacy_selector", "def:SignalEngine.find_best_signal",
          "legacy score selector (LIVE_LEARNING_MODE=true)", DORMANT)),
    _f("shared/macro_context.py", "cycle-wide macro veto (both families)",
       _r("macro_should_block_now", "def:MacroContext.should_block_now", "veto and stale block"),
       _r("macro_should_block", "def:should_block", "veto rule"),
       _r("macro_btc_trend", "def:_trend_from_change", "BTC/ETH trend labels"),
       _r("macro_usdtd_trend", "def:classify_usdtd_trend", "USDT.D trend label"),
       _r("macro_refresh", "def:MacroContext.refresh", "inputs and fail-closed refresh"),
       _r("macro_fresh", "def:MacroContext.data_is_fresh", "staleness bound"),
       _r("macro_state_key", "def:MacroContext.macro_state_key",
          "learned-gate cell key (gates off)", DORMANT)),
    _f("shared/signal_readiness.py", "signal completeness and delivery readiness",
       _r("ready_sql_predicate", "assign:READY_SQL_PREDICATE", "admission readiness"),
       _r("ready_deliverable", "def:is_deliverable_for_event", "delivery readiness"),
       _r("ready_complete", "def:assert_signal_complete", "emission completeness")),
    _f("shared/signal_identity.py", "integrity mode switch; enforce-mode identity (off)",
       _r("sid_integrity_mode", "def:integrity_mode", "SIGNAL_INTEGRITY_MODE path switch"),
       _r("sid_identity_version", "assign:IDENTITY_VERSION", "key version", DORMANT),
       _r("sid_setup_identity", "def:SetupIdentity", "setup_key composition", DORMANT),
       _r("sid_freshness_at", "def:freshness_at", "one-bar freshness bound", DORMANT),
       _r("sid_integrity_check", "def:integrity_check", "enforce-mode verdict", DORMANT)),
    # delivery (telegram): gate and acknowledgement semantics
    _f("telegram/main.py", "delivery gate; the rest of the file is notification formatting",
       _r("delivery_handle_candidate", "def:handle_candidate_event", "deliver, refuse or skip"),
       _r("delivery_failure", "def:_candidate_failure", "retry and dead-letter semantics"),
       _r("delivery_send_direct", "def:send_signal_direct", "hand-off to admission"),
       _r("delivery_gate", "def:can_deliver_candidate", "pause and capacity refusal"),
       _r("delivery_mark_delivered", "def:mark_delivered", "signal.delivered transaction"),
       scope=REGIONS_SCOPE),
    _f("telegram/whitelist.py", "approval routing",
       _r("approval_process_signal", "def:ApprovalManager.process_signal",
          "manual approval disabled: unconditional sent_direct")),
    # admission, entry, exits, costs (trade_tracker)
    _f("trade_tracker/main.py", "admission, entry, exits, holding and cost booking",
       _r("tracker_register_new_signals", "def:register_new_signals", "admission loop"),
       _r("tracker_integrity_refusal", "def:integrity_admission_refusal",
          "enforce-mode freshness refusal", DORMANT),
       _r("tracker_assess_new_trade_risk", "def:assess_new_trade_risk",
          "net-of-cost admission snapshot and capacity"),
       _r("tracker_track_open_trades", "def:track_open_trades", "REST backup and invalidation"),
       _r("tracker_evaluate_trade", "def:evaluate_trade", "exit rules (manage)"),
       _r("tracker_close_trade_barrier", "def:close_trade_barrier", "cost booking at close"),
       _r("tracker_usable_price", "def:usable_price", "price validity"),
       _r("tracker_enforce_max_open", "def:enforce_max_open_trades", "capacity enforcement"),
       _r("tracker_close_blacklisted", "def:close_blacklisted_trades", "blacklist closes")),
    _f("trade_tracker/binance_price_stream.py", "tick ordering and validity for exit evaluation",
       _r("stream_handle", "def:BinancePriceStream._handle", "tick filter")),
    _f("shared/entry_execution.py", "entry decision and paper fill model",
       _r("entry_decide", "def:decide_long_entry", "entry decision"),
       _r("entry_fill", "def:resolve_entry_fill", "fill resolution"),
       _r("entry_fill_models", "assign:FILL_MODELS", "selectable fill models")),
    _f("shared/execution.py", "bracket rebase on fill",
       _r("bracket_rebase", "def:rebase_long_bracket", "bracket rebase")),
    _f("shared/triple_barrier.py", "exit barriers and holding expiry"),
    _f("shared/partial_exits.py", "partial exits"),
    _f("shared/risk_management.py", "portfolio admission rules (evaluate_new_trade)"),
    _f("shared/economic_halt_policy.py", "observe/enforce wrapper around evaluate_new_trade",
       _r("halt_evaluate_with_policy", "def:evaluate_with_policy", "policy wrapper"),
       _r("halt_mode", "def:economic_halt_mode", "PAPER_ECONOMIC_HALT_MODE")),
    _f("shared/risk_epoch.py", "risk epoch and loss-streak halt",
       _r("epoch_effective_start", "def:effective_risk_start", "which closes count"),
       _r("epoch_loss_streak_halt", "def:loss_streak_halt_active", "loss-streak halt")),
    _f("shared/capacity_authority.py", "delivery gate, tracker capacity pre-checks, risk limits",
       _r("cap_slot_limit", "def:legacy_slot_limit", "min(MAX_OPEN_TRADES, canary) slots"),
       _r("cap_risk_limits", "def:legacy_risk_limits", "RiskLimits built from config"),
       _r("cap_decide", "def:decide_capacity", "wraps evaluate_with_policy for admission"),
       _r("cap_tracker_precheck", "def:tracker_precheck", "tracker loop and per-signal checks"),
       _r("cap_delivery_gate", "def:delivery_gate", "pause and capacity refusal at delivery"),
       _r("cap_compare_shadow", "def:compare_shadow", "shadow comparison (unused)", POTENTIAL),
       _r("cap_admission_queue", "def:legacy_admission_queue", "queue model (unused)", POTENTIAL)),
    _f("shared/admission_capacity.py", "risk-decision routing; the rest is funnel telemetry",
       _r("admission_routed_risk", "def:routed_risk_decision",
          "returns evaluate_with_policy's own decision; errors before it propagate"),
       _r("admission_tracker_funnel", "def:TrackerAdmissionFunnel", "F7 records", OBSERVE_ONLY),
       _r("admission_delivery_refusal", "def:record_delivery_refusal", "F7 record", OBSERVE_ONLY),
       _r("admission_funnel_service", "def:funnel_service", "recorder factory", OBSERVE_ONLY),
       scope=REGIONS_SCOPE),
    _f("shared/accounting_flags.py", "PAPER_COST_LABEL_POLICY / PAPER_BREAK_EVEN_POLICY parse",
       _r("acct_resolve", "def:resolve_accounting_flags", "fail-closed flag parse")),
    _f("shared/cost_label_policy.py", "cost binding, close booking and break-even cost",
       _r("cost_bound", "def:bound_costs", "legacy_tracker_v1 from config"),
       _r("cost_validate", "def:validate_policies", "fail-closed cost validation"),
       _r("cost_close_booking", "def:close_booking", "booked close economics"),
       _r("cost_barrier_kwargs", "def:barrier_cost_kwargs", "exit-barrier cost terms"),
       _r("cost_single_count_close", "def:single_count_close",
          "per-leg booking (PAPER_COST_LABEL_POLICY at its default)", DORMANT)),
    _f("shared/cost_models.py", "legacy_tracker_v1 model (delegates to shared/fees.py)",
       _r("cost_legacy_tracker_v1", "def:LegacyTrackerV1", "bound legacy cost model"),
       _r("cost_legacy_from_config", "def:legacy_tracker_v1_from_config", "binding"),
       _r("cost_research_pricer", "def:ResearchPricer", "research pricing (no service)", POTENTIAL)),
    _f("shared/fees.py", "cost booking",
       _r("fees_economic_close", "def:economic_close", "net-of-cost booking"),
       _r("fees_fee_usdt", "def:fee_usdt", "modeled roundtrip cost")),
    # OBSERVE_ONLY: telemetry and shadows; they cannot change a decision or a booked figure
    _f("shared/funnel_flags.py", "FUNNEL_RECORDING parse (telemetry switch)", classification=OBSERVE_ONLY),
    _f("shared/funnel_hooks.py", "funnel taps; the ranking-key wrapper returns the key unchanged",
       classification=OBSERVE_ONLY),
    _f("shared/funnel_records.py", "RejectionRecord schema and conservation", classification=OBSERVE_ONLY),
    _f("shared/funnel_recorder.py", "funnel record writer", classification=OBSERVE_ONLY),
    _f("shared/ledger_legacy_adapter.py", "LEDGER_SHADOW reconciliation", classification=OBSERVE_ONLY),
    _f("shared/portfolio_ledger.py", "ledger used by the reconciliation shadow",
       classification=OBSERVE_ONLY),
    _f("shared/position_state_shadow.py", "POSITION_STATE_SHADOW validation",
       classification=OBSERVE_ONLY),
    _f("shared/position_state.py", "state machine used by the position-state shadow",
       classification=OBSERVE_ONLY),
    # DORMANT: reachable only behind an off flag or an unused mode
    _f("shared/learning_governance.py", "learned-gate exploration (LEARNING_GATES_ENABLED false)",
       classification=DORMANT),
    _f("shared/dependency_safety.py", "enforce-mode fail-closed reads (integrity off)",
       classification=DORMANT),
    _f("research/continuous_learner.py", "out-of-band learned_gates writer (learner stopped)",
       classification=DORMANT),
    # POTENTIAL: on no service call path (hashed by the legacy contract, executed by no service)
    _f("shared/strategy_math.py", "research copy of stop/T1 arithmetic (shared.trade_geometry only)",
       classification=POTENTIAL),
)

CURRENT_FAMILY_IDS = ("momentum_breakout", "reversion_rsi_bb")

DRAFT_MANIFESTS = MappingProxyType({
    sid: StrategyRuleManifest(strategy_id=sid, files=_CURRENT_FAMILY_FILES, status=PROPOSAL_STATUS)
    for sid in CURRENT_FAMILY_IDS
})
