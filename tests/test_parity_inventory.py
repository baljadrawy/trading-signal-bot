"""Unit and negative tests for ops/provenance/parity_inventory.py (static, no Docker)."""
import copy
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader('parity_inventory', str(ROOT / 'ops' / 'provenance' / 'parity_inventory.py'))
_spec = importlib.util.spec_from_loader('parity_inventory', _loader)
PI = importlib.util.module_from_spec(_spec)
_loader.exec_module(PI)
DIGEST = 'python@sha256:' + 'a' * 64
GOOD_DOCKERFILE = f'FROM {DIGEST}\nARG BUILD_REVISION\nLABEL org.opencontainers.image.revision=$BUILD_REVISION\n'


def svc_entry(ref, kind='commit', level='L2-canonical-rebuild', rebuild=True, archive=True):
    return {'provenance': {'source_kind': kind, 'evidence': ['evidence.txt']},
            'reproducibility': {'level': level, 'canonical_rebuild': rebuild},
            'archives': [{'role': 'running image', 'sha256': 'b' * 64}] if archive else [],
            'observed': {'image_ref': ref}}


class Tree:
    """A minimal, fully 'clean' synthetic repository; tests then break one thing at a time."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / 'evidence.txt').write_text('x')
        inv = self.root / 'inv'
        inv.mkdir()
        compose = ['services:']
        self.manifest = {'observed_at': '2026-10-18T00:00:00Z', 'services': {}}
        for name, (d, csvc, invn) in PI.SERVICES.items():
            (self.root / d).mkdir(exist_ok=True)
            (self.root / d / 'Dockerfile').write_text(GOOD_DOCKERFILE)
            (self.root / d / 'requirements.txt').write_text('aiohttp==3.14.3  # pinned\n# comment\nyarl==1.24.5\n')
            (inv / f'{invn}.txt').write_text('# header\naiohttp==3.14.3\nyarl==1.24.5\npip==26.1.2\n')
            ref = f'img-{name}:tag'
            self.manifest['services'][name] = svc_entry(ref)
            if csvc:
                compose += [f'  {csvc}:', f'    image: {ref}   # comment']
        (self.root / 'docker-compose.yml').write_text('\n'.join(compose) + '\n')
        self.write()

    def write(self):
        (self.root / 'm.json').write_text(json.dumps(self.manifest))

    def run(self):
        return PI.audit(self.root, self.root / 'm.json', self.root / 'inv')

    def issues(self, out, svc):
        return [i['issue'] for r in out['services'] if r['service'] == svc for i in r['issues']]


class Positive(unittest.TestCase):
    def test_clean_tree_has_no_blockers_but_never_claims_runtime(self):
        t = Tree(); out = t.run()
        self.assertEqual(out['blockers'], [])
        self.assertFalse(out['runtime_parity_verified'])
        for r in out['services']:
            self.assertEqual(r['status'], 'REVIEW_REQUIRED')
            self.assertFalse(r['runtime_verified'])
            self.assertTrue(any('server-origin attestation' in i for i in t.issues(out, r['service'])))

    def test_inline_comments_are_ignored(self):
        t = Tree()
        pins, loose = PI.read_requirements(t.root / 'scanner' / 'requirements.txt')
        self.assertEqual((pins, loose), ({'aiohttp': '3.14.3', 'yarl': '1.24.5'}, []))


class Negative(unittest.TestCase):
    def assertBlocked(self, t, svc, needle):
        out = t.run()
        self.assertTrue(any(needle in i for i in t.issues(out, svc)), t.issues(out, svc))
        self.assertTrue(any(b.startswith(svc + ':') and needle in b for b in out['blockers']))
        self.assertEqual(next(r for r in out['services'] if r['service'] == svc)['status'], 'BLOCKED')

    def test_missing_dockerfile(self):
        t = Tree(); (t.root / 'analyzer' / 'Dockerfile').unlink()
        self.assertBlocked(t, 'analyzer', 'missing versioned Dockerfile')

    def test_unpinned_base_image(self):
        t = Tree(); (t.root / 'telegram' / 'Dockerfile').write_text(GOOD_DOCKERFILE.replace(DIGEST, 'python:3.12-slim'))
        self.assertBlocked(t, 'telegram', 'not pinned by immutable digest')

    def test_revision_default_unknown(self):
        t = Tree(); (t.root / 'scanner' / 'Dockerfile').write_text(GOOD_DOCKERFILE.replace('ARG BUILD_REVISION', 'ARG BUILD_REVISION=unknown'))
        self.assertBlocked(t, 'scanner', "defaults to 'unknown'")

    def test_loose_requirement(self):
        t = Tree(); (t.root / 'scanner' / 'requirements.txt').write_text('aiohttp>=3.0\n')
        self.assertBlocked(t, 'scanner', 'not all exact pins')

    def test_pin_differs_from_installed(self):
        t = Tree(); (t.root / 'analyzer' / 'requirements.txt').write_text('aiohttp==3.13.5\nyarl==1.24.5\n')
        self.assertBlocked(t, 'analyzer', 'aiohttp pinned 3.13.5, installed 3.14.3')

    def test_exact_direct_pins_are_not_a_lock(self):
        t = Tree(); (t.root / 'inv' / 'signal_engine.txt').write_text('aiohttp==3.14.3\nyarl==1.24.5\nnumpy==2.5.2\n')
        self.assertBlocked(t, 'signal_engine', 'no committed dependency lock: 1 installed')

    def test_committed_lock_removes_lock_gap(self):
        t = Tree(); (t.root / 'inv' / 'signal_engine.txt').write_text('aiohttp==3.14.3\nyarl==1.24.5\nnumpy==2.5.2\n')
        (t.root / 'signal_engine' / 'requirements.lock').write_text('numpy==2.5.2\n')
        self.assertFalse(any('dependency lock' in i for i in t.issues(t.run(), 'signal_engine')))

    def test_missing_inventory(self):
        t = Tree(); (t.root / 'inv' / 'telegram.txt').unlink()
        self.assertBlocked(t, 'telegram', 'no recorded installed-package inventory')

    def test_assembled_source(self):
        t = Tree(); t.manifest['services']['scanner']['provenance']['source_kind'] = 'assembled'; t.write()
        self.assertBlocked(t, 'scanner', 'not a single commit')

    def test_missing_evidence_file(self):
        t = Tree(); t.manifest['services']['trade_tracker']['provenance']['evidence'] = ['nope.txt']; t.write()
        self.assertBlocked(t, 'trade_tracker', 'per-file source evidence missing')

    def test_no_canonical_rebuild(self):
        t = Tree(); t.manifest['services']['analyzer']['reproducibility'] = {'level': 'L1-content-verified', 'canonical_rebuild': False}; t.write()
        self.assertBlocked(t, 'analyzer', 'no verified canonical rebuild')

    def test_l2_label_without_attestation_flag_still_blocked(self):
        t = Tree(); t.manifest['services']['analyzer']['reproducibility']['canonical_rebuild'] = False; t.write()
        self.assertBlocked(t, 'analyzer', 'no verified canonical rebuild')

    def test_missing_archive(self):
        t = Tree(); t.manifest['services']['collector']['archives'] = []; t.write()
        self.assertBlocked(t, 'collector', 'no checksummed archive')

    def test_compose_image_mismatch(self):
        t = Tree(); t.manifest['services']['scanner']['observed']['image_ref'] = 'other:tag'; t.write()
        self.assertBlocked(t, 'scanner', 'compose image')

    def test_service_absent_from_manifest_is_blocked_not_crash(self):
        t = Tree(); del t.manifest['services']['telegram']; t.write()
        self.assertBlocked(t, 'telegram', 'absent from deploy/DEPLOYED.json')

    def test_unreadable_manifest_exit_1(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = PI.main(['--root', '/nonexistent-dir-for-test'])
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(buf.getvalue())['runtime_parity_verified'])


class RealRepository(unittest.TestCase):
    """The committed legacy runtime must stay BLOCKED and must never be reported as runtime parity."""

    def setUp(self):
        self.out = PI.audit(ROOT)

    def test_scope_and_runtime_flag(self):
        self.assertEqual(self.out['schema'], 'tsb-r14-static-audit/2')
        self.assertEqual(self.out['scope'], 'GITHUB_STATIC_ONLY')
        self.assertFalse(self.out['runtime_parity_verified'])
        self.assertEqual({r['service'] for r in self.out['services']}, set(PI.SERVICES))

    def test_known_legacy_gaps_detected(self):
        b = '\n'.join(self.out['blockers'])
        for needle in ('analyzer: [build] requirements pins differ', 'signal_engine: [build] requirements pins differ',
                       'scanner: [source] image source is not a single commit', 'collector: [build] no checksummed archive',
                       'trade_tracker: [build] no committed dependency lock'):
            self.assertIn(needle, b)

    def test_cli_exit_code_with_blockers(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(PI.main(['--root', str(ROOT)]), 2)


if __name__ == '__main__':
    unittest.main()
