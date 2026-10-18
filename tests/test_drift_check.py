"""Unit tests for ops/provenance/drift_check.py (no Docker, no network: a fake host is injected)."""
import copy
import datetime as dt
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(ROOT, 'ops', 'provenance', 'drift_check.py')
_loader = importlib.machinery.SourceFileLoader('drift_check', _SCRIPT)
_spec = importlib.util.spec_from_loader('drift_check', _loader)
DC = importlib.util.module_from_spec(_spec)
_loader.exec_module(DC)
MANIFEST_PATH = os.path.join(ROOT, 'deploy', 'DEPLOYED.json')
BASE = json.load(open(MANIFEST_PATH))


class FakeHost:
    """Observations equal to the baseline unless a test changes them."""

    def __init__(self, m):
        self.m = m
        self.containers = {s['container']: dict(s['observed']) for s in m['services'].values()}
        self.paper = {s['container']: True for s in m['services'].values()}
        self.blobs = {}
        for cp in m['compose_projects'].values():
            self.blobs[os.path.join(DC.ROOT, cp['repo_path'])] = cp['git_blob']
            self.blobs[cp['production_path']] = cp['git_blob']
        self.render = {s['render_hash_service']: s['observed'].get('config_hash')
                       for s in m['services'].values() if s.get('render_hash_service')}
        self.host_rc, self.deep_rc, self.inspect_error = 0, 0, False
        self.clock = dt.datetime.fromisoformat(m['observed_at'].replace('Z', '+00:00')) + dt.timedelta(days=1)

    def inspect(self, c):
        if self.inspect_error:
            raise DC.HostError('docker unavailable')
        return copy.deepcopy(self.containers.get(c))

    def paper_trading_true(self, c):
        return self.paper.get(c)

    def file_blob(self, p):
        return self.blobs.get(p)

    def render_hash(self, project_dir, svc):
        return self.render.get(svc)

    def host_compare(self, values):
        return self.host_rc, ([] if self.host_rc == 0 else ['DIFFERENT ops/host/x'])

    def deep_verify(self, spec, manifest):
        return self.deep_rc, (['OK   analyzer'] if self.deep_rc == 0 else ['DIFF analyzer'])

    def now(self):
        return self.clock


def run(m=None, host=None, deep=False):
    m = m or copy.deepcopy(BASE)
    host = host or FakeHost(m)
    res = DC.run_checks(m, host, deep=deep)
    return DC.overall(res), res


def statuses(res, check, target=None):
    return {r['status'] for r in res if r['check'] == check and (target is None or r['target'] == target)}


class Baseline(unittest.TestCase):
    def test_committed_manifest_is_valid(self):
        self.assertEqual(DC.validate_manifest(BASE), [])

    def test_every_service_has_full_immutable_ids(self):
        for name, s in BASE['services'].items():
            self.assertRegex(s['observed']['image_id'], r'^sha256:[0-9a-f]{64}$', name)
            self.assertRegex(s['observed']['container_id'], r'^[0-9a-f]{64}$', name)

    def test_expected_components_present(self):
        self.assertEqual(set(BASE['services']), {'analyzer', 'signal_engine', 'telegram', 'trade_tracker', 'scanner',
                                                 'collector', 'postgres', 'continuous_learner'})
        self.assertEqual(BASE['services']['continuous_learner']['expected_state'], 'not_running')

    def test_no_clean_build_claims(self):
        for name, s in BASE['services'].items():
            self.assertFalse(s['reproducibility']['canonical_rebuild'], name)
            self.assertNotEqual(s['reproducibility']['level'], 'L2-canonical-rebuild', name)

    def test_manifest_contains_no_secret_like_values(self):
        raw = open(MANIFEST_PATH).read()
        self.assertNotRegex(raw, r'(?i)(password|secret|api_key|bot_token)\s*["=:]')
        self.assertNotRegex(raw, r'\b\d{8,10}:[A-Za-z0-9_-]{35}\b')
        self.assertNotIn('PAPER_TRADING=', raw)


class Validation(unittest.TestCase):
    def test_short_image_id_rejected(self):
        m = copy.deepcopy(BASE)
        m['services']['analyzer']['observed']['image_id'] = 'sha256:011f99ba451b'
        self.assertTrue(any('image_id' in p for p in DC.validate_manifest(m)))

    def test_l2_without_evidence_rejected(self):
        m = copy.deepcopy(BASE)
        m['services']['analyzer']['reproducibility'].update(level='L2-canonical-rebuild', canonical_rebuild=True)
        self.assertTrue(any('L2' in p or 'canonical_rebuild' in p for p in DC.validate_manifest(m)))

    def test_forbidden_key_rejected(self):
        m = copy.deepcopy(BASE)
        m['services']['analyzer']['observed']['db_password'] = 'x'
        self.assertTrue(any('forbidden key' in p for p in DC.validate_manifest(m)))

    def test_invalid_manifest_is_unknown_not_pass(self):
        m = copy.deepcopy(BASE)
        m['schema'] = 'other'
        ov, res = run(m)
        self.assertEqual(ov, DC.UNKNOWN)
        self.assertEqual(len(res), 1)


class Checks(unittest.TestCase):
    def test_all_match_metadata_only(self):
        ov, res = run()
        self.assertEqual(ov, DC.MATCH)
        self.assertEqual(statuses(res, 'D2'), {DC.NOT_RUN})

    def test_deep_match_and_drift(self):
        self.assertEqual(run(deep=True)[0], DC.MATCH)
        m = copy.deepcopy(BASE); h = FakeHost(m); h.deep_rc = 1
        ov, res = run(m, h, deep=True)
        self.assertEqual(ov, DC.DRIFT)
        self.assertEqual(statuses(res, 'D2'), {DC.DRIFT})

    def test_image_change_is_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.containers['trading_analyzer']['image_id'] = 'sha256:' + '0' * 64
        ov, res = run(m, h)
        self.assertEqual(ov, DC.DRIFT)
        self.assertEqual(statuses(res, 'D1', 'analyzer'), {DC.DRIFT})

    def test_restart_is_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.containers['trading_tracker']['restart_count'] += 1
        self.assertEqual(statuses(run(m, h)[1], 'D6', 'trade_tracker'), {DC.DRIFT})

    def test_missing_container_is_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        del h.containers['trading_scanner']
        ov, res = run(m, h)
        self.assertEqual(ov, DC.DRIFT)
        self.assertEqual(statuses(res, 'D1', 'scanner'), {DC.DRIFT})

    def test_docker_unavailable_is_unknown(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.inspect_error = True
        ov, res = run(m, h)
        self.assertEqual(ov, DC.UNKNOWN)
        self.assertNotIn(DC.MATCH, statuses(res, 'D1'))

    def test_render_hash_unavailable_is_unknown(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.render['telegram'] = None
        ov, res = run(m, h)
        self.assertEqual(statuses(res, 'D4', 'telegram'), {DC.UNKNOWN})
        self.assertEqual(ov, DC.UNKNOWN)

    def test_render_hash_change_is_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.render['analyzer'] = 'f' * 64
        self.assertEqual(statuses(run(m, h)[1], 'D4', 'analyzer'), {DC.DRIFT})

    def test_production_compose_edit_is_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.blobs[m['compose_projects']['trading-signal-bot']['production_path']] = 'a' * 40
        self.assertEqual(statuses(run(m, h)[1], 'D3', 'compose:trading-signal-bot'), {DC.DRIFT})

    def test_host_definition_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.host_rc = 1
        self.assertEqual(statuses(run(m, h)[1], 'D5'), {DC.DRIFT})

    def test_stale_baseline_old(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.clock += dt.timedelta(days=60)
        ov, res = run(m, h)
        self.assertEqual(ov, DC.UNKNOWN)
        self.assertEqual(statuses(res, 'B0', 'age'), {DC.UNKNOWN})

    def test_stale_baseline_repository_moved_on(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.blobs[os.path.join(DC.ROOT, 'docker-compose.yml')] = 'b' * 40
        self.assertEqual(statuses(run(m, h)[1], 'B0', 'compose:trading-signal-bot'), {DC.UNKNOWN})

    def test_learner_running_is_safety(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.containers['trading_continuous_learner']['state'] = 'running'
        ov, res = run(m, h)
        self.assertEqual(ov, DC.SAFETY)
        self.assertEqual(statuses(res, 'D7'), {DC.SAFETY})

    def test_learner_container_absent_is_safe_but_reported(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        del h.containers['trading_continuous_learner']
        ov, res = run(m, h)
        self.assertEqual(statuses(res, 'D7'), {DC.MATCH})
        self.assertEqual(statuses(res, 'D1', 'continuous_learner'), {DC.DRIFT})

    def test_paper_trading_false_is_safety_and_beats_drift(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.paper['trading_signal_engine'] = False
        h.containers['trading_analyzer']['restart_count'] += 1
        ov, res = run(m, h)
        self.assertEqual(ov, DC.SAFETY)

    def test_paper_trading_unobservable_is_unknown(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.paper['trading_telegram'] = None
        self.assertEqual(statuses(run(m, h)[1], 'D8', 'telegram'), {DC.UNKNOWN})

    def test_exit_codes(self):
        self.assertEqual([DC.EXIT[s] for s in (DC.MATCH, DC.DRIFT, DC.UNKNOWN, DC.SAFETY)], [0, 1, 2, 3])


class NoEnvironmentLeak(unittest.TestCase):
    def test_real_host_never_returns_or_prints_value(self):
        sentinel = 'false-SENTINEL-VALUE-123'
        host = DC.Host()
        with mock.patch.object(DC.subprocess, 'run',
                               return_value=subprocess.CompletedProcess([], 0, stdout=sentinel + '\n', stderr='')):
            self.assertIs(host.paper_trading_true('trading_scanner'), False)
        m = copy.deepcopy(BASE); fake = FakeHost(m); fake.paper['trading_scanner'] = False
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = DC.main(['check', '--manifest', MANIFEST_PATH], host=fake)
        self.assertEqual(rc, 3)
        self.assertNotIn(sentinel, buf.getvalue())
        self.assertIn("PAPER_TRADING is NOT 'true' (value not shown)", buf.getvalue())

    def test_inspect_format_requests_no_environment(self):
        self.assertNotIn('Env', DC.INSPECT_FMT)
        self.assertIn('"PAPER_TRADING"', DC.PAPER_FMT)
        self.assertEqual(len(re.findall(r'\.Config\.Env', DC.PAPER_FMT)), 1)


class Coverage(unittest.TestCase):
    def _cov(self, m=None, host=None, deep=False):
        m = m or copy.deepcopy(BASE)
        res = DC.run_checks(m, host or FakeHost(m), deep=deep)
        return DC.overall(res), DC.coverage(res, deep)

    def test_metadata_only_is_never_full(self):
        ov, cov = self._cov()
        self.assertEqual(ov, DC.MATCH)
        self.assertEqual(cov['verification'], 'METADATA_ONLY')
        self.assertEqual(cov['counts'][DC.NOT_RUN], 1)
        self.assertGreater(cov['counts'][DC.NA], 0)

    def test_deep_match_is_full(self):
        ov, cov = self._cov(deep=True)
        self.assertEqual((ov, cov['verification'], cov['counts'][DC.NOT_RUN]), (DC.MATCH, 'FULL', 0))

    def test_missing_required_check_is_unknown_not_pass(self):
        m = copy.deepcopy(BASE)
        del m['host_definitions']                      # D5 cannot run: partial execution
        ov, cov = self._cov(m, deep=True)
        self.assertEqual(ov, DC.UNKNOWN)
        self.assertEqual(cov['verification'], 'INCOMPLETE')

    def test_unknown_makes_incomplete(self):
        m = copy.deepcopy(BASE); h = FakeHost(m); h.render['analyzer'] = None
        ov, cov = self._cov(m, h, deep=True)
        self.assertEqual((ov, cov['verification']), (DC.UNKNOWN, 'INCOMPLETE'))

    def test_safety_precedence_unchanged_and_counted(self):
        m = copy.deepcopy(BASE); h = FakeHost(m)
        h.containers['trading_continuous_learner']['state'] = 'running'
        h.render['analyzer'] = None                       # UNKNOWN present too
        h.containers['trading_tracker']['restart_count'] += 1   # DRIFT present too
        ov, cov = self._cov(m, h)
        self.assertEqual(ov, DC.SAFETY)
        self.assertEqual(DC.EXIT[ov], 3)
        self.assertGreaterEqual(min(cov['counts'][DC.SAFETY], cov['counts'][DC.DRIFT], cov['counts'][DC.UNKNOWN]), 1)

    def test_counts_cover_every_result(self):
        m = copy.deepcopy(BASE)
        res = DC.run_checks(m, FakeHost(m))
        self.assertEqual(sum(DC.coverage(res, False)['counts'].values()), len(res))

    def test_human_and_json_output_expose_coverage(self):
        import tempfile
        m = copy.deepcopy(BASE)
        with tempfile.TemporaryDirectory() as d:
            rp = os.path.join(d, 'r.json')
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = DC.main(['check', '--manifest', MANIFEST_PATH, '--json', rp], host=FakeHost(m))
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn('COVERAGE MATCH=', out)
            self.assertIn('verification=METADATA_ONLY', out)
            self.assertIn('image content NOT verified', out)
            rep = json.load(open(rp))
            self.assertEqual(rep['coverage']['verification'], 'METADATA_ONLY')
            self.assertIn('INTERNAL INFRASTRUCTURE METADATA', rep['_notice'])


class MetadataHandling(unittest.TestCase):
    def test_report_written_0600_even_if_preexisting(self):
        import stat, tempfile
        m = copy.deepcopy(BASE)
        with tempfile.TemporaryDirectory() as d:
            rp = os.path.join(d, 'r.json')
            open(rp, 'w').close(); os.chmod(rp, 0o644)
            with redirect_stdout(io.StringIO()):
                DC.main(['check', '--manifest', MANIFEST_PATH, '--json', rp], host=FakeHost(m))
            self.assertEqual(stat.S_IMODE(os.stat(rp).st_mode), 0o600)

    def test_observe_has_notice_no_env_and_private_file(self):
        import stat, tempfile
        m = copy.deepcopy(BASE)
        buf = io.StringIO()
        with redirect_stdout(buf):
            DC.main(['observe', '--manifest', MANIFEST_PATH], host=FakeHost(m))
        obs = json.loads(buf.getvalue())
        self.assertIn('INTERNAL INFRASTRUCTURE METADATA', obs['_notice'])
        raw = json.dumps(obs)
        self.assertNotIn('Env', raw)
        self.assertNotIn('PAPER_TRADING', raw)
        with tempfile.TemporaryDirectory() as d:
            op = os.path.join(d, 'o.json')
            with redirect_stdout(io.StringIO()):
                DC.main(['observe', '--manifest', MANIFEST_PATH, '--out', op], host=FakeHost(m))
            self.assertEqual(stat.S_IMODE(os.stat(op).st_mode), 0o600)


if __name__ == '__main__':
    unittest.main()
