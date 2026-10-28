"""Offline checks for the Local CI-Equivalent runner (ops/ci/lce.py).

The runner refuses any tests.yml job it was not reviewed against. These tests make a workflow change that is
not mirrored in the runner fail the suite, so the runner is reviewed together with every workflow change.
"""
import importlib.util
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lce', ROOT / 'ops' / 'ci' / 'lce.py')
lce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lce)



def test_reviewed_workflow_file_pin_equals_tests_yml():
    # No yaml needed: runs in the pinned CI test set too.
    digest = lce.sha256_bytes((ROOT / '.github' / 'workflows' / 'tests.yml').read_bytes())
    assert digest == lce.REVIEWED_WORKFLOW_SHA256, (
        'tests.yml changed: review ops/ci/lce.py against it, then update REVIEWED_WORKFLOW_SHA256 and the job pins')


def _workflow():
    yaml = pytest.importorskip('yaml')    # only the checks that parse the workflow need it
    return yaml.safe_load((ROOT / '.github' / 'workflows' / 'tests.yml').read_text())


def test_reviewed_pins_equal_the_current_workflow_jobs():
    WORKFLOW = _workflow()
    assert set(lce.JOBS) == set(WORKFLOW['jobs'])
    for job in lce.JOBS:
        assert lce.job_sha256(WORKFLOW['jobs'][job]) == lce.REVIEWED_JOB_SHA256[job], (
            f'tests.yml job {job} changed: review ops/ci/lce.py against it, then update REVIEWED_JOB_SHA256')


def test_every_action_used_by_the_workflow_is_emulated():
    WORKFLOW = _workflow()
    used = {s['uses'] for j in WORKFLOW['jobs'].values() for s in j['steps'] if 'uses' in s}
    assert used <= lce.USES_ALLOWED
    for job in WORKFLOW['jobs'].values():
        assert set(job.get('services', {})) <= {'postgres'}


def _executed_strings(job):
    """The fields LCE evaluates: run scripts, job/step env values and if conditions (not cache keys)."""
    yield from (str(v) for v in (job.get('env') or {}).values())
    for step in job['steps']:
        if 'run' in step:
            yield step['run']
        yield from (str(v) for v in (step.get('env') or {}).values())
        if 'if' in step:
            yield '${{ ' + str(step['if']) + ' }}'


def test_every_expression_the_runner_evaluates_is_supported():
    WORKFLOW = _workflow()
    for name, job in WORKFLOW['jobs'].items():
        ctx = lce.Context('0' * 40, '/ws', {k: 'x' for k in job.get('env') or {}})
        for text in _executed_strings(job):
            ctx.substitute(text)                      # raises lce.Refused on anything unsupported


def test_expression_semantics_and_fail_closed():
    ctx = lce.Context('a' * 40, '/ws', {'PGURL': 'postgresql://u@127.0.0.1:1/p'})
    ctx.outputs['present'] = {'run': 'true'}
    assert ctx.condition("steps.present.outputs.run == 'true'") is True
    assert ctx.condition("${{ steps.present.outputs.run != 'true' }}") is False
    assert ctx.condition("github.event_name == 'push' && github.ref == 'refs/heads/main'") is False
    assert ctx.evaluate('github.event.pull_request.base.sha || github.event.before') == ''
    assert ctx.evaluate('github.event.pull_request.head.sha || github.sha') == 'a' * 40
    assert ctx.substitute('${{ env.PGURL }}/x') == 'postgresql://u@127.0.0.1:1/p/x'
    for bad in ('secrets.X', 'github.actor', "fromJSON('{}')", 'vars.X'):
        with pytest.raises(lce.Refused):
            ctx.evaluate(bad)


@pytest.mark.parametrize('text,expected', [
    ('1800 passed, 847 skipped, 46 subtests passed in 161.06s (0:02:41)',
     {'passed': 1800, 'skipped': 847, 'subtests passed': 46}),
    ('=== 1 failed, 465 passed, 1 skipped, 1 warning in 718.36s ===',
     {'failed': 1, 'passed': 465, 'skipped': 1, 'warnings': 1}),
    ('22 errors in 1.51s', {'errors': 22}),
    ('no summary here', {}),
])
def test_pytest_summary_counts(text, expected):
    assert lce.pytest_counts('noise\n' + text + '\n') == expected


def test_partial_job_selection_is_rejected_or_never_pass(capsys):
    with pytest.raises(SystemExit):
        lce.main(['0' * 40, '--jobs', 'unit,bogus'])


def test_runner_never_names_credentials_or_production_targets():
    src = (ROOT / 'ops' / 'ci' / 'lce.py').read_text()
    assert not re.search(r"trading_signals|trading_signal_bot|['\"/ ]\.env\b|shared_db_net", src)
    assert "'--pull', 'never'" in src and "'127.0.0.1:" in src and '--tmpfs' in src
    assert '-v ' not in src and "'--volume'" not in src and "'-v'" not in src


def test_reviewed_pins_are_documented():
    doc = (ROOT / 'docs' / 'ops' / 'CI_EFFICIENCY.md').read_text()
    for job, digest in lce.REVIEWED_JOB_SHA256.items():
        assert digest[:12] in doc, job
    assert json.dumps(sorted(lce.JOBS))
