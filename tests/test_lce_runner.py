"""Offline checks for the Local CI-Equivalent runner (ops/ci/lce.py): pins, supported workflow constructs and the
fail-closed paths (cleanup failure, isolation failure, unsupported workflow change, incomplete execution, DSN
targets, redaction, no inherited environment). No Docker, git or database is used: commands are faked.
"""
import importlib.util
import json
import os
import pathlib
import re
import signal
import time
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
    """Fake subprocess runner: docker/git/systemctl calls succeed. A label+name query (the ownership lookup before
    removal) finds the run's own resource; `leave` makes a resource survive its removal; `fail` makes a
    verification query fail."""

    def __init__(self, leave=(), fail=()):
        self.leave, self.fail, self.calls = set(leave), set(fail), []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        owned_query = any(a.startswith('label=') for a in cmd) and any(a.startswith('name=') for a in cmd)
        out, rc = '', 0
        if cmd[:2] == ['docker', 'ps']:
            out = 'deadbeef\n' if owned_query or 'container' in self.leave else ''
            rc = 1 if 'container' in self.fail and not owned_query else 0
        if cmd[:3] == ['docker', 'network', 'ls']:
            out = 'cafebabe\n' if owned_query or 'network' in self.leave else ''
        if cmd[:3] == ['systemctl', '--user', 'list-units'] and 'scope' in self.leave:
            out = 'lce-step-' + cmd[-1][6:-1] + '-unit-06.scope loaded active running\n'
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr='')


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
    assert ['docker', 'rm', '-f', 'deadbeef'] in fake.calls          # removed by ID found via label + name
    assert ['docker', 'network', 'rm', 'cafebabe'] in fake.calls


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


# ---- lce-2.1: process groups, interruptions, host limits, strict cleanup ownership ---------------------------
def _gone(pgid):
    try:
        os.killpg(pgid, 0)
        return False
    except ProcessLookupError:
        return True


def test_step_timeout_terminates_the_whole_process_group():
    started = time.monotonic()
    rc, term = lce.run_group(['bash', '-c', 'sleep 30 & sleep 30 & wait'], timeout=0.5, grace=2)
    assert rc is None and term['cause'] == 'timeout' and term['group_gone'] is True
    assert term['signals'] == ['SIGTERM'] and time.monotonic() - started < 5


def test_termination_escalates_to_sigkill_and_signals_the_scope():
    sent = []
    rc, term = lce.run_group(['bash', '-c', "trap '' TERM; sleep 30 & wait"], timeout=0.5, grace=0.5,
                             on_signal=lambda sig: sent.append(sig.name))
    assert rc is None and term['group_gone'] is True
    assert term['signals'] == ['SIGTERM', 'SIGKILL'] and sent == ['SIGTERM', 'SIGKILL']


def test_interruption_terminates_the_group_before_it_propagates():
    def alarm(signum, frame):
        raise lce.Interrupted('SIGALRM')
    old = signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, 0.3)
    try:
        with pytest.raises(lce.Interrupted) as info:
            lce.run_group(['bash', '-c', 'sleep 30 & sleep 30 & wait'], timeout=30, grace=2)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
    term = info.value.lce_termination
    assert term['cause'] == 'Interrupted' and term['group_gone'] is True


def test_processes_left_by_a_finished_step_are_terminated():
    rc, term = lce.run_group(['bash', '-c', 'sleep 30 & exit 0'], timeout=10, grace=2)
    assert rc == 0 and term['cause'] == 'processes left after exit' and term['group_gone'] is True


def test_helper_command_timeout_is_refused_and_its_group_terminated():
    with pytest.raises(lce.Refused, match='timed out after 0.5s; process group terminated'):
        lce.run(['bash', '-c', 'sleep 30 & sleep 30 & wait'], timeout=0.5)
    r = lce.run(['bash', '-c', 'echo out; echo err >&2'])
    assert (r.returncode, r.stdout, r.stderr) == (0, 'out\n', 'err\n')


def test_steps_run_in_a_limited_scope_with_the_step_environment_only():
    argv = lce.scope_argv('lce-step-x-unit-06', ['bash', '-c', 'true'])
    assert argv[:5] == ['systemd-run', '--user', '--scope', '--quiet', '--unit=lce-step-x-unit-06']
    assert [a for a in argv if a.startswith('--property=')] == [f'--property={k}={v}' for k, v in lce.STEP_LIMITS]
    assert argv[argv.index('--'):] == ['--', 'env', '-u', 'XDG_RUNTIME_DIR', 'bash', '-c', 'true']
    assert set(lce.user_env()) == {'PATH', 'XDG_RUNTIME_DIR', 'LANG'}


def test_step_limits_stay_small_for_a_host_shared_with_production():
    lim = dict(lce.STEP_LIMITS)
    assert int(lim['CPUQuota'].rstrip('%')) <= 400 and lim['CPUWeight'] == 'idle' and lim['MemorySwapMax'] == '0'
    assert int(lim['MemoryMax'].rstrip('G')) <= 8 and int(lim['TasksMax']) <= 1024
    assert lce.EXPECTED_SCOPE == {'cpu.max': f'{int(lim["CPUQuota"][:-1]) * 1000} 100000',
                                  'memory.max': str(int(lim['MemoryMax'][:-1]) * 1024 ** 3),
                                  'memory.swap.max': '0', 'pids.max': lim['TasksMax']}


GOOD_PROBE = 'cpu.max=200000 100000\nmemory.max=4294967296\nmemory.swap.max=0\npids.max=512\n'


@pytest.mark.parametrize('probe', [
    GOOD_PROBE.replace('memory.max=4294967296', 'memory.max=max'),        # memory controller not delegated
    GOOD_PROBE.replace('200000 100000', 'max 100000'),                    # no CPU quota
    GOOD_PROBE.replace('memory.swap.max=0\n', ''),                         # swap limit missing
    GOOD_PROBE.replace('pids.max=512', 'pids.max=max'),
    '',
])
def test_unenforced_host_limits_are_refused(probe):
    lce.check_scope_limits(GOOD_PROBE)
    with pytest.raises(lce.Refused, match='not enforced'):
        lce.check_scope_limits(probe)


def test_cleanup_removes_only_resources_of_this_run(tmp_path):
    fake = FakeCmd()
    r = lce.Runner(str(tmp_path), 'c' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    r.containers, r.networks = ['lce-pg-x'], ['lce-net-x']
    assert r.cleanup() == []
    lookups = [c for c in fake.calls if c[:2] == ['docker', 'ps'] or c[:3] == ['docker', 'network', 'ls']]
    owned = [c for c in lookups if f'label=tsb.lce.run={r.run_id}' in c and 'name=^lce-pg-x$' in c]
    assert owned, 'a container is removed only after a lookup by this run label AND its exact name'
    removals = [c for c in fake.calls if c[:3] in (['docker', 'rm', '-f'], ['docker', 'network', 'rm'])]
    assert removals == [['docker', 'rm', '-f', 'deadbeef'], ['docker', 'network', 'rm', 'cafebabe']]
    assert not any(w in c for c in fake.calls for w in ('prune', 'system')) or all(
        c[:3] == ['git', 'worktree', 'prune'] for c in fake.calls if 'prune' in c)


def test_a_cleanup_check_that_cannot_run_is_a_residue(tmp_path):
    r = lce.Runner(str(tmp_path), 'd' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=FakeCmd(fail=('container',)))
    r.containers = ['lce-pg-x']
    residuals = r.cleanup()
    assert 'unverifiable:container:lce-pg-x' in residuals and r.manifest['cleanup']['verified'] is False
    assert lce.decide_verdict(lce.JOBS, ALL, [], residuals) == 'FAIL'


def test_cleanup_never_removes_a_directory_outside_its_own_temp_base(tmp_path):
    r = lce.Runner(str(tmp_path), 'e' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=FakeCmd())
    os.rmdir(r.base)
    foreign = tmp_path / f'lce-{"e" * 8}-foreign'
    foreign.mkdir()
    r.base = str(foreign)                               # not directly under the system temp directory
    residuals = r.cleanup()
    assert foreign.exists() and any(x.startswith('cleanup-error:directory') for x in residuals)
    assert f'directory:{foreign}' in residuals


def test_worktree_ownership_is_exact(tmp_path):
    fake = FakeCmd()
    r = lce.Runner(str(tmp_path), 'f' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    base = r.base
    listing = f'worktree {base}-sibling\nworktree {base}/ws\nworktree {base}/ref-prod\nworktree /home/x/repo\n'

    def cmd(c, **kw):
        res = fake(c, **kw)
        if c[:3] == ['git', 'worktree', 'list']:
            res.stdout = listing
        return res
    r.cmd = cmd
    residuals = r.cleanup()
    removed = [c[-1] for c in fake.calls if c[:3] == ['git', 'worktree', 'remove']]
    assert sorted(removed) == sorted([f'{base}/ws', f'{base}/ref-prod'])
    assert 'worktrees' in residuals                     # the fake keeps listing them, so they count as left over


def test_a_leftover_scope_of_this_run_is_a_residue_and_is_killed(tmp_path):
    fake = FakeCmd(leave=('scope',))
    r = lce.Runner(str(tmp_path), '1' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    assert 'scopes' in r.cleanup()
    kills = [c for c in fake.calls if c[:3] == ['systemctl', '--user', 'kill']]
    assert kills and all(r.run_id in c[-1] and c[3] == '--signal=SIGKILL' for c in kills)


def test_surviving_step_processes_make_the_run_fail(tmp_path):
    r = lce.Runner(str(tmp_path), '2' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=FakeCmd())
    r.process_residuals = ['processes:lce-step-x-unit-06']
    residuals = r.cleanup()
    assert 'processes:lce-step-x-unit-06' in residuals and r.manifest['cleanup']['verified'] is False


def test_an_interrupted_run_still_cleans_up_and_fails(tmp_path):
    r = lce.Runner(str(tmp_path), '3' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=FakeCmd())

    def interrupted():
        raise lce.Interrupted('SIGTERM')
    r.preflight = interrupted
    assert r.go() == 'FAIL'
    assert any('interrupted: Interrupted SIGTERM' in x for x in r.manifest['refusals'])
    assert r.manifest['cleanup']['verified'] is True and not os.path.exists(r.base)


def test_evidence_logs_are_redacted_even_after_an_interrupted_step(tmp_path):
    r = lce.Runner(str(tmp_path), '4' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=FakeCmd())
    os.makedirs(r.evdir)
    (pathlib.Path(r.evdir) / 'database-step08.log').write_text('dsn postgresql://postgres:throwaway-1@h/x\n')
    r.redactions = ['throwaway-1']
    r.write_evidence()
    assert 'throwaway-1' not in (pathlib.Path(r.evdir) / 'database-step08.log').read_text()
    assert 'throwaway-1' not in (pathlib.Path(r.evdir) / 'SHA256SUMS').read_text()
    os.rmdir(r.base)


# ---- lce-2.2 (re-review R2): scope signalling, recorded cleanup failures, per-step limit read-back --------------
class ScriptedCmd(FakeCmd):
    """FakeCmd whose answers can be overridden per command prefix: rules = [(prefix, rc, stdout), ...]; a rule
    given as a callable is called with the command."""

    def __init__(self, rules=(), **kw):
        super().__init__(**kw)
        self.rules = list(rules)

    def __call__(self, cmd, **kw):
        res = super().__call__(cmd, **kw)
        for prefix, rc, out in self.rules:
            if cmd[:len(prefix)] == prefix:
                out = out(cmd) if callable(out) else out
                return types.SimpleNamespace(returncode=rc, stdout=out, stderr='simulated failure')
        return res


KILL, SHOW = ['systemctl', '--user', 'kill'], ['systemctl', '--user', 'show']


@pytest.mark.parametrize('kill_rc,show_out,expect', [
    (0, '', 'signalled'),
    (1, 'LoadState=not-found\nActiveState=inactive\n', 'absent'),          # already gone: not an error
    (1, 'LoadState=loaded\nActiveState=inactive\n', 'inactive'),
])
def test_kill_scope_accepts_an_absent_scope(tmp_path, kill_rc, show_out, expect):
    r = lce.Runner(str(tmp_path), '5' * 40, lce.JOBS, str(tmp_path / 'ev'),
                   cmd=ScriptedCmd([(KILL, kill_rc, ''), (SHOW, 0, show_out)]))
    assert r.kill_scope('lce-step-x', signal.SIGTERM) == expect


@pytest.mark.parametrize('rules', [
    [(KILL, 1, ''), (SHOW, 0, 'LoadState=loaded\nActiveState=active\n')],  # still running: a real failure
    [(KILL, 1, ''), (SHOW, 1, '')],                                          # systemd cannot be asked
])
def test_kill_scope_failure_raises(tmp_path, rules):
    r = lce.Runner(str(tmp_path), '6' * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=ScriptedCmd(rules))
    with pytest.raises(lce.Refused):
        r.kill_scope('lce-step-x', signal.SIGKILL)


def test_a_scope_signal_error_counts_as_surviving_processes():
    assert lce.termination_ok(None) and lce.termination_ok({'group_gone': True, 'signals': ['SIGTERM']})
    assert not lce.termination_ok({'group_gone': True, 'errors': ['SIGKILL scope: Refused']})
    assert not lce.termination_ok({'group_gone': False})
    rc, term = lce.run_group(['bash', '-c', 'sleep 30 & wait'], timeout=0.3, grace=1,
                             on_signal=lambda sig: (_ for _ in ()).throw(lce.Refused('scope still active')))
    assert rc is None and term['group_gone'] is True and term['errors'] and not lce.termination_ok(term)


def _cleanup_with(tmp_path, rules, sha):
    fake = ScriptedCmd(rules)
    r = lce.Runner(str(tmp_path), sha * 40, lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    r.containers, r.networks = ['lce-pg-x'], ['lce-net-x']
    return r, r.cleanup(), fake


def test_failed_container_removal_is_recorded_while_it_still_exists(tmp_path):
    r, residuals, _ = _cleanup_with(tmp_path, [(['docker', 'rm', '-f'], 1, '')], '7')
    assert any(x.startswith('cleanup-error:container lce-pg-x') for x in residuals)
    assert r.manifest['cleanup']['verified'] is False


def test_failed_removal_of_an_already_absent_resource_is_not_an_error(tmp_path):
    state = {'removed': False}

    def owned_ps(cmd):                                  # the container disappears (docker --rm race)
        if any(a.startswith('label=') for a in cmd) and any(a.startswith('name=') for a in cmd):
            if state['removed']:
                return ''
            return 'deadbeef\n'
        return ''

    def rm(cmd):
        state['removed'] = True
        return ''
    r, residuals, _ = _cleanup_with(tmp_path, [(['docker', 'rm', '-f'], 1, rm), (['docker', 'ps'], 0, owned_ps)], '8')
    assert not any('container' in x for x in residuals)


def test_failed_network_removal_is_retried_then_recorded(tmp_path):
    r, residuals, fake = _cleanup_with(tmp_path, [(['docker', 'network', 'rm'], 1, '')], '9')
    assert sum(1 for c in fake.calls if c[:3] == ['docker', 'network', 'rm']) == 5
    assert any(x.startswith('cleanup-error:network lce-net-x') for x in residuals)


def test_failed_worktree_commands_are_recorded_and_ownership_stays_exact(tmp_path):
    fake = ScriptedCmd([(['git', 'worktree', 'remove'], 1, ''), (['git', 'worktree', 'prune'], 1, '')])
    r = lce.Runner(str(tmp_path), 'a1'.ljust(40, '0'), lce.JOBS, str(tmp_path / 'ev'), cmd=fake)
    listing = f'worktree {r.base}/ws\nworktree {r.base}-other\nworktree /home/x/repo\n'
    fake.rules.append((['git', 'worktree', 'list'], 0, listing))
    residuals = r.cleanup()
    assert any(x.startswith(f'cleanup-error:worktree {r.base}/ws') for x in residuals)
    assert any(x.startswith('cleanup-error:worktree prune') for x in residuals)
    removed = [c[-1] for c in fake.calls if c[:3] == ['git', 'worktree', 'remove']]
    assert removed == [f'{r.base}/ws']                  # never the sibling or the repository itself


def test_a_failed_scope_listing_or_kill_is_recorded(tmp_path):
    r, residuals, _ = _cleanup_with(tmp_path, [(['systemctl', '--user', 'list-units'], 1, '')], 'b')
    assert any(x.startswith('cleanup-error:scopes list') for x in residuals) and 'unverifiable:scopes' in residuals


def test_step_scope_limits_are_read_back_and_checked(tmp_path):
    for name, value in (('cpu.max', '200000 100000'), ('memory.max', '4294967296'), ('memory.swap.max', '0'),
                        ('pids.max', '512')):
        (tmp_path / name).write_text(value + '\n')
    lce.check_scope_limits(lce.read_scope_limits(str(tmp_path)))
    (tmp_path / 'memory.max').write_text('max\n')       # a scope created without its memory limit
    with pytest.raises(lce.Refused, match='memory.max'):
        lce.check_scope_limits(lce.read_scope_limits(str(tmp_path)))
