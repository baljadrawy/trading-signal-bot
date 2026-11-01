"""Read-only strategy version-boundary report over two identity manifests (WP2 lane A; R5.d, R5.e).

`version_boundary_report(before, after)` is a pure function over two `tsb-strategy-identity/1`
manifests (built by `shared.strategy_identity.build_identity`). It says whether the identity
moved, which hashes, files, regions and decision keys changed, whether the version label was
stepped as SE-38 requires, and drafts the SE-36 boundary fields. It never writes
deploy/VERSION_BOUNDARY.md: an entry is written only for an owner-approved activation (SE-36),
and fields that only an activation can provide stay PENDING. The historical research freeze hash
is reported as a separate, unchanged artefact; it is never read or recomputed.

Classification (SE-38; charter section 6, "unversioned strategy change"):
  NO_CHANGE          identity fields equal (lineage alone may differ: metadata, WP-IR-09)
  LABEL_ONLY         version label differs, all three hashes equal: no rule change; review
  DECLARED_CHANGE    hashes and version both differ: a boundary entry is required
                     (a MINOR/PATCH step additionally needs a byte-identical golden replay)
  UNDECLARED_CHANGE  a hash differs under the same version label: stop condition
  DIFFERENT_STRATEGY strategy_id differs: not a boundary of one strategy

`drift_status` maps the classification onto drift_check.py's vocabulary for a future check.
Wiring it into drift_check.py would edit that existing file and is BLOCKED (owner gate).

Usage: python -m shared.strategy_version_boundary BEFORE.json AFTER.json
Exit: 0 NO_CHANGE or LABEL_ONLY, 1 DECLARED_CHANGE, 3 UNDECLARED_CHANGE, 2 invalid or
DIFFERENT_STRATEGY. Output is canonical JSON on stdout; nothing is written.
"""
import json
import sys

from shared.strategy_identity import (HEX64, HISTORICAL_FREEZE, IDENTITY_MANIFEST_SCHEMA,
                                      SEMVER, ClosureError, canonical_json, compare_to_reference)

REPORT_SCHEMA = 'tsb-version-boundary-report/1'
NO_CHANGE, LABEL_ONLY, DECLARED, UNDECLARED, OTHER = (
    'NO_CHANGE', 'LABEL_ONLY', 'DECLARED_CHANGE', 'UNDECLARED_CHANGE', 'DIFFERENT_STRATEGY')
DRIFT_STATUS = {NO_CHANGE: 'MATCH', LABEL_ONLY: 'DRIFT', DECLARED: 'DRIFT', UNDECLARED: 'SAFETY',
                OTHER: 'UNKNOWN'}
EXIT = {NO_CHANGE: 0, LABEL_ONLY: 0, DECLARED: 1, UNDECLARED: 3, OTHER: 2}
HASHES = ('source_hash', 'config_hash', 'contract_hash')
PENDING = 'PENDING'
STRATIFICATION_RULE = ('outcomes before and after activation_utc_minute must never be pooled without '
                       'stratification; no retroactive attribution (deploy/VERSION_BOUNDARY.md rules)')


class ReportError(ValueError):
    """An input is not a valid identity manifest."""


def _check(doc, name):
    if not isinstance(doc, dict) or doc.get('schema') != IDENTITY_MANIFEST_SCHEMA:
        raise ReportError(f'{name}: not a {IDENTITY_MANIFEST_SCHEMA} manifest')
    if not isinstance(doc.get('version'), str) or not SEMVER.match(doc['version']):
        raise ReportError(f'{name}: invalid version')
    for h in HASHES + ('identity_hash',):
        if not isinstance(doc.get(h), str) or not HEX64.match(doc[h]):
            raise ReportError(f'{name}: invalid {h}')


def _step(before, after):
    a = tuple(int(x) for x in before.split('.'))
    b = tuple(int(x) for x in after.split('.'))
    if b == a:
        return 'NONE'
    if b < a:
        return 'REGRESSION'
    if b[0] > a[0]:
        return 'MAJOR'
    if b[1] > a[1]:
        return 'MINOR'
    return 'PATCH'


def _config_keys_changed(before, after):
    va = (before.get('config') or {}).get('values') or {}
    vb = (after.get('config') or {}).get('values') or {}
    return sorted(k for k in set(va) | set(vb)
                  if k not in va or k not in vb or canonical_json(va[k]) != canonical_json(vb[k]))


def version_boundary_report(before, after):
    """Pure: no clock, environment, file or network access; inputs are not mutated."""
    _check(before, 'before')
    _check(after, 'after')
    hash_changed = {h: before[h] != after[h] for h in HASHES}
    version_changed = before['version'] != after['version']
    step = _step(before['version'], after['version'])
    if before.get('strategy_id') != after.get('strategy_id'):
        cls = OTHER
    elif any(hash_changed.values()):
        cls = DECLARED if version_changed else UNDECLARED
    else:
        cls = LABEL_ONLY if version_changed else NO_CHANGE
    try:
        diff = compare_to_reference(after, before)
    except ClosureError as exc:
        raise ReportError(str(exc)) from None
    flags = []
    if cls == UNDECLARED:
        flags.append('identity hash changed under an unchanged version label (SE-38 stop condition)')
    if cls == LABEL_ONLY:
        flags.append('version label changed without any rule, config or contract change')
    if step == 'REGRESSION':
        flags.append('version label decreased')
    if not diff.get('closure_spec_equal', True):
        flags.append('declared closure changed (files or regions added, removed or re-selected)')
    golden = cls == DECLARED and step in ('MINOR', 'PATCH')
    if golden:
        flags.append('MINOR/PATCH step: a byte-identical golden replay (SE-71) is required, '
                     'otherwise the change is MAJOR')
    if cls == DECLARED:
        required = 'CONDITIONAL_ON_GOLDEN_REPLAY' if golden else 'YES'
    elif cls == UNDECLARED:
        required = 'STOP'
    elif cls == OTHER:
        required = 'NOT_APPLICABLE'
    else:
        required = 'NO'
    entry = None
    if cls in (DECLARED, UNDECLARED):
        entry = {
            'boundary_id': PENDING,
            'strategy_id': after['strategy_id'],
            'version_before': before['version'], 'version_after': after['version'],
            **{f'{h}_before': before[h] for h in HASHES},
            **{f'{h}_after': after[h] for h in HASHES},
            'cost_model_id': (after.get('contract_descriptor') or {}).get('cost_model_id', PENDING),
            'fill_model_id': (after.get('contract_descriptor') or {}).get('fill_model_id', PENDING),
            'activation_utc_minute': PENDING,
            'admission_authority_service': PENDING,
            'images': PENDING,
            'stratification_rule': STRATIFICATION_RULE,
            'write_status': 'NOT_WRITTEN: an entry is written only for an owner-approved activation (SE-36)',
        }
    report = {
        'schema': REPORT_SCHEMA,
        'classification': cls,
        'drift_status': DRIFT_STATUS[cls],
        'boundary_required': required,
        'strategy_id_before': before.get('strategy_id'),
        'strategy_id_after': after.get('strategy_id'),
        'version_before': before['version'], 'version_after': after['version'],
        'version_step': step,
        'hash_changed': hash_changed,
        'identity_hash_before': before['identity_hash'], 'identity_hash_after': after['identity_hash'],
        'lineage_changed': list(before.get('lineage') or []) != list(after.get('lineage') or []),
        'files_changed': diff['files_changed'],
        'files_added': diff['files_added'],
        'files_removed': diff['files_removed'],
        'changed_outside_legacy_contract_v1': diff['changed_outside_legacy_contract_v1'],
        'regions_changed': diff.get('regions_changed', []),
        'regions_added': diff.get('regions_added', []),
        'regions_removed': diff.get('regions_removed', []),
        'config_keys_changed': _config_keys_changed(before, after),
        'flags': flags,
        'boundary_entry_draft': entry,
        'historical_freeze': dict(HISTORICAL_FREEZE),
    }
    canonical_json(report)
    return report


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print('usage: python -m shared.strategy_version_boundary BEFORE.json AFTER.json', file=sys.stderr)
        return 2
    try:
        docs = []
        for path in args:
            with open(path, encoding='utf-8') as fh:
                docs.append(json.load(fh))
        report = version_boundary_report(*docs)
    except (OSError, ValueError) as exc:
        print(f'invalid input: {exc}', file=sys.stderr)
        return 2
    print(canonical_json(report))
    return EXIT[report['classification']]


if __name__ == '__main__':
    sys.exit(main())
