"""Offline checks for the Local CI-Equivalent runner (ops/ci/lce.py): pins, supported workflow constructs and the
fail-closed paths (cleanup failure, isolation failure, unsupported workflow change, incomplete execution, DSN
targets, redaction, no inherited environment). No Docker, git or database is used: commands are faked.
"""
import importlib.util
import json
import pathlib
import re
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lce', ROOT / 'ops' / 'ci' / 'lce.py')
lce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lce)
WF_TEXT = (ROOT / '.github' / 'workflows' / 'tests.yml').read_text()


def test_reviewed_workflow_file_pin_equals_tests_yml():
    # No yaml needed: runs in the pinned CI test set too.
    assert lce.sha256_bytes(WF_TEXT.encode()) == lce.REVIEWED_WORKFLOW_SHA256, (
        'tests.yml changed: review ops/ci/lce.py against it, then update REVIEWED_WORKFLOW_SHA256 and the job pins')


def _workflow():
    yaml = pytest.importorskip('yaml')    # only the checks that parse the workflow need it
    return yaml.safe_load(WF_TEXT)


# ---- pins and supported constructs ----------------------------------------------------------------------------
def test_reviewed_pins_equal_the_current_workflow_jobs():
    wf = _workflow()
    assert set(lce.JOBS) == set(wf['jobs'])
    assert lce.check_pins(WF_TEXT, wf, lce.JOBS) == lce.REVIEWED_JOB_SHA256


def test_unsupported_workflow_change_is_refused(monkeypatch):
    wf = _workflow()
    with pytest.raises(lce.Refused, match='tests.yml'):
        lce.check_pins(WF_TEXT + '\n# edit\n', wf, lce.JOBS)
    changed = json.loads(json.dumps(wf))
    changed['jobs']['unit']['steps'].append({'run': 'echo extra'})
    with pytest.raises(lce.Refused, match='job unit'):
        lce.check_pins(WF_TEXT, changed, ('unit',))     # file pin matches; the job definition does not
    with pytest.raises(lce.Refused, match='unsupported action'):
        lce.check_uses({'uses': 'actions/upload-artifact@v4'})
    lce.check_uses({'uses': 'actions/checkout@v4'})


def test_every_action_and_service_used_by_the_workflow_is_supported():
    for job in _workflow()['jobs'].values():
        for step in job['steps']:
            lce.check_uses(step)
        assert set(job.get('services', {})) <= {'postgres'}


def test_every_expression_the_runner_evaluates_is_supported():
    for job in _workflow()['jobs'].values():
        ctx = lce.Context('0' * 40, '/ws', {k: 'x' for k in job.get('env') or {}})
        texts = [str(v) for v in (job.get('env') or {}).values()]
        for step in job['steps']:
            texts += [step.get('run', '')] + [str(v) for v in (step.get('env') or {}).values()]
            if 'if' in step:
                texts.append('${{ ' + str(step['if']) + ' }}')
        for text in texts:
            ctx.substitute(text)                      # raises lce.Refused on anything unsupported


def test_expression_semantics_and_fail_closed():
    ctx = lce.Context('a' * 40, '/ws', {'PGURL': 'postgresql://u@10.0.0.2:5432/p'})
    ctx.outputs['present'] = {'run': 'true'}
    assert ctx.condition("steps.present.outputs.run == 'true'") is True
    assert ctx.condition("${{ steps.present.outputs.run != 'true' }}") is False
    assert ctx.condition("github.event_name == 'push' && github.ref == 'refs/heads/main'") is False
    assert ctx.evaluate('github.event.pull_request.base.sha || github.event.before') == ''
    assert ctx.evaluate('github.event.pull_request.head.sha || github.sha') == 'a' * 40
    for bad in ('secrets.X', 'github.actor', "fromJSON('{}')", 'vars.X'):
        with pytest.raises(lce.Refused):
            ctx.evaluate(bad)


# ---- isolation ------------------------------------------------------------------------------------------------
NET, CTR = 'lce-net-abc', 'lce-pg-abc'


def _net(**kw):
    n = {'Name': NET, 'Driver': 'bridge', 'Internal': True, 'Containers': {'id1': {'Name': CTR}}}
    n.update(kw)
    return n


def _ctr(**kw):
    c = {'Mounts': [], 'NetworkSettings': {'Networks': {NET: {'IPAddress': '172.30.0.2'}}},
         'HostConfig': {'NetworkMode': NET, 'PortBindings': {}, 'Binds': None, 'Privileged': False}}
    c.update(kw)
    return c


def test_isolation_accepts_the_private_internal_network():
    lce.check_isolation(_net(), _ctr(), NET, CTR)


@pytest.mark.parametrize('net,ctr', [
    (_net(Internal=False), _ctr()),                                                     # route out possible
    (_net(Driver='host'), _ctr()),
    (_net(Containers={'a': {'Name': CTR}, 'b': {'Name': 'postgres'}}), _ctr()),          # foreign member
    (_net(), _ctr(NetworkSettings={'Networks': {NET: {}, 'shared_db_net': {}}})),        # second network
    (_net(), _ctr(Mounts=[{'Source': '/home/tradmin/trading-signal-bot'}])),             # a mount
    (_net(), _ctr(HostConfig={'NetworkMode': NET, 'PortBindings': {'5432/tcp': [{'HostPort': '5432'}]}})),
    (_net(), _ctr(HostConfig={'NetworkMode': NET, 'Privileged': True})),
    (_net(), _ctr(HostConfig={'NetworkMode': 'bridge'})),
])
def test_isolation_failures_are_refused(net, ctr):
    with pytest.raises(lce.Refused):
        lce.check_isolation(net, ctr, NET, CTR)


# ---- no production target, no inherited credentials, redaction --------------------------------------------------
@pytest.mark.parametrize('dsn', [
    'postgresql://trading_signal_bot:x@127.0.0.1:5432/trading_signals',   # the shared production server
    'postgresql://postgres:ci@postgres:5432/postgres',                     # compose service name
    'postgresql://postgres:ci@172.30.0.2:5433/postgres',                   # wrong port
])
def test_dsn_guard_refuses_anything_but_the_disposable_server(dsn):
    with pytest.raises(lce.Refused):
        lce.check_dsn_targets({'P1_DB_DSN': dsn, 'TEMPLATE': 'p1_schema'}, '172.30.0.2')


def test_dsn_guard_accepts_the_disposable_server():
    lce.check_dsn_targets({'PGURL': 'postgresql://postgres:ci@172.30.0.2:5432/postgres', 'TEMPLATE': 'x'},
                          '172.30.0.2')


def test_step_environment_inherits_nothing_from_the_caller(monkeypatch):
    monkeypatch.setenv('POSTGRES_HOST', 'host-value')
    monkeypatch.setenv('P1_DB_DSN', 'postgresql://u@127.0.0.1:5432/trading_signals')
    env = lce.step_env('/lce/home', ['/venv/bin'], {'PGURL': 'u'}, {'X': '1'}, {'GITHUB_OUTPUT': '/o'})
    assert set(env) == set(lce.BASE_ENV_KEYS) | {'PGURL', 'X', 'GITHUB_OUTPUT'}
    assert 'host-value' not in json.dumps(env) and env['HOME'] == '/lce/home'
    assert env['PATH'].startswith('/venv/bin:')


def test_throwaway_values_are_redacted():
    vals = lce.secrets_of({'SERVICE_VALUE': 'throwaway-1'},
                          {'PGURL': 'postgresql://postgres:throwaway-1@172.30.0.2:5432/postgres'})
    assert vals == ['throwaway-1']
    assert lce.redact('dsn postgresql://postgres:throwaway-1@h/x', vals) == 'dsn postgresql://postgres:***@h/x'


# ---- incomplete execution and verdict ---------------------------------------------------------------------------
def _st(**kw):
    return dict({'result': 'ok', 'pytest': True, 'counts': {'passed': 3}}, **kw)


@pytest.mark.parametrize('steps,reason', [
    ([{'result': 'ok'}], 'no pytest step'),
    ([_st(counts={})], 'no summary'),
    ([_st(result='FAILED')], 'step failed'),
    ([_st(result='FAILED (timeout-minutes exceeded)')], 'step failed'),
    ([_st(counts={'passed': 3, 'failed': 1})], 'test failures'),
    ([_st(counts={'passed': 3, 'errors': 2})], 'test failures'),
    ([_st(counts={'skipped': 9})], 'no test passed'),
    ([_st(), _st(result='skipped (if: false)', counts={})], 'no summary'),
])
def test_incomplete_or_failed_execution_fails(steps, reason):
    status, why = lce.assess_job(steps)
    assert status == 'FAIL' and reason in why


def test_complete_job_passes():
    assert lce.assess_job([{'result': 'ok'}, _st()]) == ('PASS', None)


ALL = {j: 'PASS' for j in lce.JOBS}


@pytest.mark.parametrize('requested,statuses,refusals,residuals,verdict', [
    (lce.JOBS, ALL, [], [], 'PASS'),
    (lce.JOBS, ALL, [], ['network:lce-net-x'], 'FAIL'),             # cleanup left a resource
    (lce.JOBS, ALL, ['cleanup raised OSError'], [], 'FAIL'),
    (lce.JOBS, dict(ALL, collector='FAIL'), [], [], 'FAIL'),
    (lce.JOBS, {'unit': 'PASS'}, [], [], 'FAIL'),                   # a requested job never ran
    (('unit',), {'unit': 'PASS'}, [], [], 'PARTIAL'),
    (('unit',), {'unit': 'PASS'}, [], ['worktrees'], 'FAIL'),
])
def test_verdict_is_fail_closed(requested, statuses, refusals, residuals, verdict):
    assert lce.decide_verdict(requested, statuses, refusals, residuals) == verdict


class FakeCmd:
    """Fake subprocess runner: docker/git calls succeed; `leave` makes a resource survive its removal."""

    def __init__(self, leave=()):
        self.leave, self.calls = set(leave), []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = ''
        if cmd[:2] == ['docker', 'ps'] and 'container' in self.leave:
            out = 'deadbeef\n'
        if cmd[:3] == ['docker', 'network', 'ls'] and 'network' in self.leave:
            out = 'cafebabe\n'
        return types.SimpleNamespace(returncode=0, stdout=out, stderr='')


@pytest.mark.parametrize('leave,expect', [((), None), (('container',), 'container:'), (('network',), 'network:')])
def test_cleanup_is_verified(tmp_path, leave, expect):
    fake = FakeCmd(leave)
    r = lce.Runner(str(tmp_path), 'a' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    r.containers, r.networks = ['lce-pg-x'], ['lce-net-x']
    residuals = r.cleanup()
    if expect is None:
        assert residuals == [] and r.manifest['cleanup']['verified'] is True
    else:
        assert any(x.startswith(expect) for x in residuals) and r.manifest['cleanup']['verified'] is False
        assert lce.decide_verdict(lce.JOBS, ALL, [], residuals) == 'FAIL'
    assert ['docker', 'rm', '-f', 'lce-pg-x'] in fake.calls
    assert ['docker', 'network', 'rm', 'lce-net-x'] in fake.calls


def test_cleanup_detects_a_leftover_worktree(tmp_path):
    fake = FakeCmd()
    r = lce.Runner(str(tmp_path), 'b' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    base = r.base

    def leaky(cmd, **kw):
        res = fake(cmd, **kw)
        if cmd[:3] == ['git', 'worktree', 'list']:
            res.stdout = f'worktree {base}/ws\n'
        return res
    r.cmd = leaky
    assert 'worktrees' in r.cleanup()


def test_runner_source_never_targets_production():
    src = (ROOT / 'ops' / 'ci' / 'lce.py').read_text()
    assert not re.search(r"trading_signals|trading_signal_bot|shared_db_net|['\"/ ]\.env\b", src)
    assert "'--internal'" in src and "'--pull', 'never'" in src and '--tmpfs' in src
    assert "'-p'" not in src and "'--publish'" not in src and "'-v'" not in src and "'--volume'" not in src
    assert 'os.environ' not in src.replace("nothing from the caller's environment (os.environ)", '')


def test_pytest_summary_counts():
    assert lce.pytest_counts('x\n1800 passed, 847 skipped, 46 subtests passed in 161.06s (0:02:41)\n') == {
        'passed': 1800, 'skipped': 847, 'subtests passed': 46}
    assert lce.pytest_counts('=== 1 failed, 465 passed, 1 warning in 718.36s ===') == {
        'failed': 1, 'passed': 465, 'warnings': 1}
    assert lce.pytest_counts('22 errors in 1.51s') == {'errors': 22}
    assert lce.pytest_counts('no summary') == {}


def test_partial_job_selection_argument_validation():
    with pytest.raises(SystemExit):
        lce.main(['0' * 40, '--jobs', 'unit,bogus'])


def test_reviewed_pins_and_deviation_classes_are_documented():
    doc = (ROOT / 'docs' / 'ops' / 'CI_EFFICIENCY.md').read_text()
    for digest in lce.REVIEWED_JOB_SHA256.values():
        assert digest[:12] in doc
    for d in lce.STATIC_DEVIATIONS:
        assert d['id'] in doc and d['classification'] in doc
    assert {d['classification'] for d in lce.STATIC_DEVIATIONS} <= {
        'portable', 'portable-with-record', 'requires-verification', 'not-reproduced'}


def test_pytest_step_detection_ignores_installs():
    wf_install = 'python -m pip install "$(grep -E \'^pytest==\' .github/ci/requirements-test.txt)"\npython -m pip check'
    assert not lce.PYTEST_RUN.search(wf_install)
    assert lce.PYTEST_RUN.search('python -m pytest -q -p no:cacheprovider -rs tests')
    for job in _workflow()['jobs'].values():          # every job keeps at least one real pytest step
        assert any(lce.PYTEST_RUN.search(s.get('run', '')) for s in job['steps'])
