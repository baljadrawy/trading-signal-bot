"""drift_check.py strategy-identity section (WP2 lane A; WP-A01, R5.d, R5.e): report-only.

No Docker, network, database or environment: the existing FakeHost of tests/test_drift_check.py
is reused for `check`, and every other case runs on synthetic closures written under tmp_path.
The real-tree cases read only the declared closure source files of this checkout.
"""
import copy
import io
import json
import os
import stat
import subprocess
import sys
from contextlib import redirect_stdout

import pytest

sys.path.insert(0, '.')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_drift_check as base                       # noqa: E402  (loads drift_check and FakeHost)
from shared import strategy_config_snapshot as scs     # noqa: E402
from shared import strategy_identity as si             # noqa: E402

DC = base.DC
ROOT = DC.ROOT

ENTRY = b'CAP = 0.99\n\n\ndef levels(x):\n    return min(x, CAP)\n\n\ndef other():\n    return 1\n'
RULES = b'def rule(x):\n    return x > 1\n'
GATE = b'def gate():\n    return False\n'
SOURCES = {'pkg/entry.py': ENTRY, 'pkg/rules.py': RULES, 'pkg/gate.py': GATE}
SCHEMA = scs.ConfigSchema('synthetic/drift-1', (scs.ConfigKey('LEVEL', 'float', 'env'),))
CONTRACT = {k: f'declared-{k}' for k in si.REQUIRED_CONTRACT_KEYS}


def synthetic_manifests():
    m = si.StrategyRuleManifest('synthetic_strategy', (
        si.ClosureFile('pkg/entry.py', 'geometry', (si.RegionSpec('entry_levels', 'def:levels'),
                                                    si.RegionSpec('entry_cap', 'assign:CAP'))),
        si.ClosureFile('pkg/rules.py', 'entry'),
        si.ClosureFile('pkg/gate.py', 'gate behind an off flag', classification=si.DORMANT),
    ))
    return {m.strategy_id: m}


def write_tree(root, sources):
    for path, data in sources.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)


def identity(root, version, level=1.5):
    m = synthetic_manifests()['synthetic_strategy']
    snap = scs.snapshot_config('synthetic_strategy', SCHEMA, {'LEVEL': level})
    return si.build_identity(m, si.read_closure_sources(root, m), version=version,
                             config_snapshot=snap, contract_descriptor=CONTRACT)[1]


def status(report, check='S1'):
    return [(r['target'], r['status']) for r in report['results'] if r['check'] == check]


def run_main(argv, host=None):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = DC.main(argv, host=host)
    return rc, out.getvalue()


# ── existing behaviour is unchanged without the flag ───────────────────────────────────────

def test_existing_modes_do_not_load_shared_modules():
    code = ('import sys, io, copy, json, contextlib; sys.path.insert(0, "tests"); '
            'import test_drift_check as t; '
            'buf = io.StringIO(); '
            'ctx = contextlib.redirect_stdout(buf); ctx.__enter__(); '
            't.DC.main(["validate"]); t.DC.main(["check"], host=t.FakeHost(copy.deepcopy(t.BASE))); '
            'ctx.__exit__(None, None, None); '
            'print(json.dumps(sorted(m for m in sys.modules if m.startswith("shared"))))')
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
                         env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_check_output_json_and_exit_unchanged_without_the_flag(tmp_path):
    plain_json, flag_json = tmp_path / 'plain.json', tmp_path / 'flag.json'
    rc1, out1 = run_main(['check', '--json', str(plain_json)], host=base.FakeHost(copy.deepcopy(base.BASE)))
    rc2, out2 = run_main(['check', '--strategy-identity', '--json', str(flag_json)],
                         host=base.FakeHost(copy.deepcopy(base.BASE)))
    assert rc1 == rc2 and out2.startswith(out1)
    extra = out2[len(out1):].splitlines()
    assert extra[-1].startswith('STRATEGY report-only')
    assert all(line.startswith('S1') for line in extra[:-1]) and len(extra) == 3
    plain, flagged = json.loads(plain_json.read_text()), json.loads(flag_json.read_text())
    assert 'strategy_identity' not in plain
    assert {k: v for k, v in flagged.items() if k not in ('strategy_identity', 'checked_at')} == \
        {k: v for k, v in plain.items() if k != 'checked_at'}
    assert flagged['strategy_identity']['report_only'] is True


def test_check_with_unreadable_reference_keeps_the_exit_code(tmp_path):
    rc1, _ = run_main(['check'], host=base.FakeHost(copy.deepcopy(base.BASE)))
    rc2, out = run_main(['check', '--strategy-identity', '--identity-reference', str(tmp_path / 'none.json')],
                        host=base.FakeHost(copy.deepcopy(base.BASE)))
    assert rc1 == rc2
    assert any(line.startswith('S1') and 'UNKNOWN' in line for line in out.splitlines())


# ── the strategy mode on this checkout ─────────────────────────────────────────────────────

def test_strategy_mode_on_this_checkout(tmp_path):
    report_path = tmp_path / 'ref.json'
    rc, out = run_main(['strategy', '--json', str(report_path)])
    assert rc == 0 and out.count('NOT_RUN') == 2
    assert stat.S_IMODE(os.stat(report_path).st_mode) == 0o600
    report = json.loads(report_path.read_text())
    assert report['schema'] == DC.STRATEGY_REPORT_SCHEMA and set(report['families']) == set(si.DRAFT_MANIFESTS)
    assert report['historical_freeze']['recomputed'] is False
    rc, out = run_main(['strategy', '--identity-reference', str(report_path)])
    assert rc == 0 and out.count(' MATCH ') == 2


@pytest.mark.parametrize('content', [None, '{', '{"schema": "other/1"}', '[]'])
def test_strategy_mode_refuses_unreadable_inputs(tmp_path, content):
    path = tmp_path / 'ref.json'
    if content is not None:
        path.write_text(content)
    rc, out = run_main(['strategy', '--identity-reference', str(path)])
    assert rc == DC.EXIT[DC.UNKNOWN] and out.startswith('UNKNOWN')


# ── synthetic closures: S1 drift and S2 boundary ───────────────────────────────────────────

def test_s1_reports_active_drift_inactive_drift_and_unresolved_regions(tmp_path):
    write_tree(tmp_path, SOURCES)
    ref = DC.strategy_report(root=tmp_path, manifests=synthetic_manifests())
    assert status(ref) == [('synthetic_strategy', DC.NOT_RUN)]
    same = DC.strategy_report(root=tmp_path, reference=ref, manifests=synthetic_manifests())
    assert status(same) == [('synthetic_strategy', DC.MATCH)]
    (tmp_path / 'pkg/gate.py').write_bytes(GATE.replace(b'False', b'True'))
    dormant = DC.strategy_report(root=tmp_path, reference=ref, manifests=synthetic_manifests())
    assert status(dormant) == [('synthetic_strategy', DC.MATCH)]
    assert 'inactive files changed: pkg/gate.py' in dormant['results'][0]['detail']
    (tmp_path / 'pkg/rules.py').write_bytes(RULES.replace(b'> 1', b'> 2'))
    active = DC.strategy_report(root=tmp_path, reference=ref, manifests=synthetic_manifests())
    assert status(active) == [('synthetic_strategy', DC.DRIFT)]
    assert 'pkg/rules.py' in active['results'][0]['detail']
    (tmp_path / 'pkg/entry.py').write_bytes(ENTRY.replace(b'def levels', b'def levels_v2'))
    broken = DC.strategy_report(root=tmp_path, reference=ref, manifests=synthetic_manifests())
    assert status(broken) == [('synthetic_strategy', DC.UNKNOWN)]
    (tmp_path / 'pkg/entry.py').write_bytes(ENTRY)
    other = DC.strategy_report(root=tmp_path, reference={'schema': DC.STRATEGY_REPORT_SCHEMA, 'families': {}},
                               manifests=synthetic_manifests())
    assert other['results'][0]['detail'] == 'reference has no entry for this strategy'


def test_s2_classifies_the_version_boundary(tmp_path):
    write_tree(tmp_path, SOURCES)
    before = identity(tmp_path, '1.0.0')
    (tmp_path / 'pkg/rules.py').write_bytes(RULES.replace(b'> 1', b'> 2'))
    cases = ((identity(tmp_path, '2.0.0'), DC.DRIFT, 'DECLARED_CHANGE'),
             (identity(tmp_path, '1.0.0'), DC.SAFETY, 'UNDECLARED_CHANGE'))
    for current, want, cls in cases:
        report = DC.strategy_report(root=tmp_path, reference=before, identity_current=current,
                                    manifests=synthetic_manifests())
        assert status(report, 'S2') == [('synthetic_strategy', want)]
        assert report['boundary']['classification'] == cls
        assert report['boundary']['boundary_entry_draft']['activation_utc_minute'] == 'PENDING'
    stale = identity(tmp_path, '2.0.0')
    (tmp_path / 'pkg/rules.py').write_bytes(RULES)
    report = DC.strategy_report(root=tmp_path, reference=before, identity_current=stale,
                                manifests=synthetic_manifests())
    assert report['results'][-1]['detail'] == 'current identity manifest does not describe this checkout'
    closure_only = si.closure_document(synthetic_manifests()['synthetic_strategy'],
                                       si.read_closure_sources(tmp_path, synthetic_manifests()['synthetic_strategy']))
    report = DC.strategy_report(root=tmp_path, reference=closure_only, identity_current=before,
                                manifests=synthetic_manifests())
    assert report['results'][-1]['detail'] == 'a boundary needs an identity manifest on both sides'
    assert report['boundary'] is None


def test_strategy_report_is_deterministic_and_leaves_inputs_unchanged(tmp_path):
    write_tree(tmp_path, SOURCES)
    ref = DC.strategy_report(root=tmp_path, manifests=synthetic_manifests())
    ref0 = copy.deepcopy(ref)
    one = DC.strategy_report(root=tmp_path, reference=ref, manifests=synthetic_manifests())
    two = DC.strategy_report(root=tmp_path, reference=ref, manifests=synthetic_manifests())
    assert si.canonical_json(one) == si.canonical_json(two) and ref == ref0
