#!/usr/bin/env python3
"""Local CI-Equivalent (LCE) runner for .github/workflows/tests.yml (owner decision 2026-10-28,
docs/governance/OWNER_OPERATING_CONTRACT.md §9; procedure docs/ops/CI_EFFICIENCY.md §11).

Runs the jobs of tests.yml for ONE exact commit, on this host, and writes SHA-bound evidence.
It executes the workflow's own `run:` steps from the target tree verbatim. Only what GitHub provides is
emulated, from a closed allowlist: actions/checkout (a clean detached worktree of the SHA),
actions/setup-python (a fresh 3.12 virtualenv), actions/cache restore/save (a persistent LCE home keyed by the
pinned requirements; save is a no-op), `services:` (a disposable PostgreSQL container), step outputs, GITHUB_PATH
and the expressions used today. Anything else fails closed. The job definitions are also pinned by hash
(REVIEWED_JOB_SHA256): a changed workflow fails closed until this runner is reviewed against it.

Disposable PostgreSQL: the local image whose PG_VERSION equals the tag in tests.yml, `--pull never`, the default
`bridge` network only (refused if any non-LCE container is attached to it), no volume (data on tmpfs), the port
bound to 127.0.0.1 on a free port (the only deviation: 5432 is taken by the shared production PostgreSQL), the
throwaway environment values read from tests.yml itself, removed after the run. Never a production database.

usage: lce.py <commit> [--jobs unit,database,collector,parity-inventory] [--evidence-root DIR] [--repo DIR]
Exit 0 only for verdict PASS (all four jobs). Partial job selections can never yield PASS.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

RUNNER_VERSION = 'lce-1'
JOBS = ('unit', 'database', 'collector', 'parity-inventory')
# sha256 of json.dumps(jobs[<id>], sort_keys=True) of the reviewed tests.yml (origin/main eba90dd, 2026-10-28).
REVIEWED_JOB_SHA256 = {
    'unit': '7859f6e1aa529ab3d127a2945db9c798b68e8400dfee08859a9d2ae23362c65a',
    'database': '167412ca0a992f0406a5cd548a406ede17b4929ed0542c0d2d3bf7328da51d8d',
    'collector': 'd5333c09a64c9d13d2b3049a8816780a85dbeba15b367adc8a55dc091b25f625',
    'parity-inventory': '86fc0fc604a2ce4edb05184255858dfc9778a1851994782a86c5ec917938d174',
}
# sha256 of the whole reviewed .github/workflows/tests.yml (any change, comments included, needs a new review).
REVIEWED_WORKFLOW_SHA256 = 'f30ffb0c5e65e2f60053c3c732b160ea358b5e8a7def0887edcba1cb54158c74'
PYTHON_MINOR = '3.12'
PG_IMAGE_REPO = 'postgres'
USES_ALLOWED = {'actions/checkout@v4', 'actions/setup-python@v5', 'actions/cache/restore@v4',
                'actions/cache/save@v4'}
EXPR = re.compile(r'\$\{\{\s*(.*?)\s*\}\}')
COUNTS = re.compile(r'(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?|subtests passed)')
LCE_HOME = os.path.expanduser('~/.cache/tsb-lce')


class Refused(Exception):
    """Fail-closed condition: the run cannot be equivalent."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def job_sha256(job: dict) -> str:
    return sha256_bytes(json.dumps(job, sort_keys=True).encode())


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def pytest_counts(text: str) -> dict:
    """Counts from the last pytest summary line ('== 3 passed, 1 skipped in 0.1s ==' or the -q form)."""
    lines = [ln for ln in text.splitlines() if re.search(r'\b(passed|failed|errors?|skipped)\b', ln)
             and re.search(r'\bin [0-9.]+s', ln)]
    if not lines:
        return {}
    out = {}
    for n, kind in COUNTS.findall(lines[-1]):
        kind = {'error': 'errors', 'warning': 'warnings'}.get(kind, kind)
        out[kind] = out.get(kind, 0) + int(n)
    return out


class Context:
    """Expression context of one job: env, step outputs and the github.* values LCE defines."""

    def __init__(self, sha, workspace, job_env):
        self.sha, self.workspace, self.env, self.outputs = sha, workspace, dict(job_env), {}

    def value(self, ref: str) -> str:
        ref = ref.strip()
        if ref.startswith("'") and ref.endswith("'"):
            return ref[1:-1]
        if ref.startswith('env.'):
            return self.env.get(ref[4:], '')
        if ref.startswith('steps.'):
            parts = ref.split('.')
            if len(parts) == 4 and parts[2] == 'outputs':
                return self.outputs.get(parts[1], {}).get(parts[3], '')
        known = {'github.workspace': self.workspace, 'github.sha': self.sha,
                 'github.event_name': 'workflow_dispatch', 'github.ref': 'refs/lce/' + self.sha,
                 'github.event.pull_request.base.sha': '', 'github.event.pull_request.head.sha': '',
                 'github.event.before': '', 'github.event.pull_request.number': '', 'github.run_id': 'lce'}
        if ref in known:
            return known[ref]
        raise Refused(f'unsupported expression reference: {ref!r}')

    def evaluate(self, expr: str):
        """Supports: ref, a || b, a == 'x', a != 'x', and && of those. Anything else is refused."""
        expr = expr.strip()
        if '&&' in expr:
            return all(self.evaluate(p) for p in expr.split('&&'))
        for op in ('==', '!='):
            if op in expr:
                a, b = (s.strip() for s in expr.split(op, 1))
                eq = self.value(a) == self.value(b)
                return eq if op == '==' else not eq
        if '||' in expr:
            for part in expr.split('||'):
                v = self.value(part)
                if v:
                    return v
            return ''
        return self.value(expr)

    def substitute(self, text: str) -> str:
        return EXPR.sub(lambda m: str(self.evaluate(m.group(1))), text)

    def condition(self, cond) -> bool:
        if cond is None:
            return True
        c = str(cond).strip()
        m = EXPR.fullmatch(c)
        return bool(self.evaluate(m.group(1) if m else c))


class Runner:
    def __init__(self, repo, sha, jobs, evidence_root):
        self.repo, self.sha, self.jobs = repo, sha, jobs
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%MZ')
        self.evdir = os.path.join(evidence_root, sha, f'lce-{stamp}')
        self.base = tempfile.mkdtemp(prefix=f'lce-{sha[:8]}-')
        self.ws = os.path.join(self.base, 'ws')
        self.worktrees, self.containers = [], []
        self.manifest = {'runner': RUNNER_VERSION, 'sha': sha, 'jobs_requested': list(jobs), 'jobs': {},
                         'refusals': [], 'deviations': [], 'started_utc': stamp}

    # ---- environment -------------------------------------------------------------------------------
    def base_env(self, home):
        return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': home, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                'CI': 'true', 'TZ': 'UTC', 'PYTHONDONTWRITEBYTECODE': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}

    def git(self, *args, cwd=None):
        r = run(['git', *args], cwd=cwd or self.repo)
        if r.returncode:
            raise Refused(f'git {" ".join(args)} failed: {r.stderr.strip()[:200]}')
        return r.stdout

    def preflight(self):
        os.umask(0o022)
        os.makedirs(self.evdir, mode=0o700, exist_ok=False)
        self.git('fetch', '-q', 'origin')
        if f'{sys.version_info[0]}.{sys.version_info[1]}' != PYTHON_MINOR:
            raise Refused(f'python {platform.python_version()} != {PYTHON_MINOR}.x')
        self.manifest['host'] = {'python': platform.python_version(), 'machine': platform.machine(),
                                 'system': platform.platform(), 'umask': '022'}
        self.manifest['deviations'] += [
            f'python {platform.python_version()} (tests.yml: {PYTHON_MINOR} latest patch on ubuntu-24.04)',
            f'architecture {platform.machine()} (GitHub runner: x86_64)']
        full = self.git('rev-parse', '--verify', f'{self.sha}^{{commit}}').strip()
        if full != self.sha:
            raise Refused('target must be a full 40-hex commit SHA')
        self.manifest['tree'] = self.git('rev-parse', f'{self.sha}^{{tree}}').strip()
        import yaml                                   # host PyYAML; absent -> ImportError -> refused below
        wf_text = self.git('show', f'{self.sha}:.github/workflows/tests.yml')
        self.manifest['workflow_sha256'] = sha256_bytes(wf_text.encode())
        if self.manifest['workflow_sha256'] != REVIEWED_WORKFLOW_SHA256:
            raise Refused(f'unverified equivalence: tests.yml {self.manifest["workflow_sha256"][:12]} is not the '
                          f'reviewed {REVIEWED_WORKFLOW_SHA256[:12]}')
        self.workflow = yaml.safe_load(wf_text)
        hashes = {j: job_sha256(self.workflow['jobs'][j]) for j in JOBS if j in self.workflow['jobs']}
        self.manifest['job_sha256'] = hashes
        for j in self.jobs:
            if hashes.get(j) != REVIEWED_JOB_SHA256[j]:
                raise Refused(f'unverified equivalence: job {j} definition {hashes.get(j)} is not the reviewed one')
        self.git('worktree', 'add', '-q', '--detach', self.ws, self.sha)
        self.worktrees.append(self.ws)
        if self.git('status', '--porcelain', cwd=self.ws).strip():
            raise Refused('target worktree is not clean')

    # ---- emulated `uses:` --------------------------------------------------------------------------
    def setup_python(self, job, ctx, path):
        venv = os.path.join(self.base, f'py-{job}')
        if not os.path.isdir(venv):
            r = run([sys.executable, '-m', 'venv', venv])
            if r.returncode:
                raise Refused(f'setup-python emulation failed: {r.stderr[:200]}')
        path.insert(0, os.path.join(venv, 'bin'))
        return {'python-version': platform.python_version()}

    def start_postgres(self, svc):
        image_tag = svc['image']
        m = re.fullmatch(r'postgres:(\d+\.\d+)(-alpine)?', image_tag)
        if not m:
            raise Refused(f'unsupported service image {image_tag}')
        want = m.group(1)
        candidates = set()
        for line in run(['docker', 'images', '--no-trunc', '--format', '{{.Repository}} {{.ID}}']).stdout.splitlines():
            repo, iid = line.split()
            if repo != PG_IMAGE_REPO:
                continue
            env = run(['docker', 'image', 'inspect', '-f', '{{range .Config.Env}}{{println .}}{{end}}', iid]).stdout
            if f'PG_VERSION={want}' in env.split():
                candidates.add(iid)
        if len(candidates) != 1:
            raise Refused(f'need exactly one local postgres image with PG_VERSION={want} (pull is not allowed); '
                          f'found {len(candidates)}')
        image = candidates.pop()
        self.manifest['deviations'].append(
            f'postgres image {image[:19]} (PG_VERSION={want}, local, arm64) for workflow tag {image_tag}; '
            'OS variant not verified beyond PG_VERSION')
        attached = run(['docker', 'network', 'inspect', 'bridge', '-f',
                        '{{range .Containers}}{{.Name}} {{end}}']).stdout.split()
        foreign = [n for n in attached if not n.startswith('lce-pg-')]
        if foreign:
            raise Refused(f'default bridge network is shared with {foreign}; not isolated')
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        name = f'lce-pg-{self.sha[:8]}-{os.urandom(3).hex()}'
        cmd = ['docker', 'run', '-d', '--rm', '--pull', 'never', '--name', name, '--label', 'tsb.lce=1',
               '--network', 'bridge', '-p', f'127.0.0.1:{port}:5432', '--memory', '1g', '--cpus', '2',
               '--pids-limit', '512', '--tmpfs', '/var/lib/postgresql/data:rw,size=1g']
        for k, v in (svc.get('env') or {}).items():
            cmd += ['-e', f'{k}={v}']
        cmd += shlex.split(svc.get('options', '')) + [image]
        r = run(cmd)
        if r.returncode:
            raise Refused(f'disposable postgres failed to start: {r.stderr.strip()[:200]}')
        self.containers.append(name)
        for _ in range(60):
            st = run(['docker', 'inspect', '-f', '{{.State.Health.Status}}', name]).stdout.strip()
            if st == 'healthy':
                break
            time.sleep(2)
        else:
            raise Refused('disposable postgres did not become healthy')
        mounts = run(['docker', 'inspect', '-f', '{{len .Mounts}}', name]).stdout.strip()
        self.manifest['postgres'] = {'image_id': image, 'tag_in_workflow': image_tag, 'container': name,
                                     'host_port': port, 'network': 'bridge', 'mounts': mounts}
        self.manifest['deviations'].append(
            f'postgres published on 127.0.0.1:{port} instead of 5432 (5432 is the shared production server)')
        return name, port

    def psql_shim(self, container, port):
        """GitHub runners have psql; this host does not. Forward to the disposable server's own psql."""
        d = os.path.join(self.base, 'shim')
        os.makedirs(d, exist_ok=True)
        shim = os.path.join(d, 'psql')
        with open(shim, 'w') as fh:
            fh.write(f'''#!/usr/bin/env python3
import os, subprocess, sys
args, stdin = [], None
it = iter(sys.argv[1:])
for a in it:
    if a.startswith('postgresql://'):
        a = a.replace('127.0.0.1:{port}', '127.0.0.1:5432')
    if a == '-f':
        path = next(it)
        stdin = open(path, 'rb').read(); args += ['-f', '-']; continue
    args.append(a)
r = subprocess.run(['docker', 'exec', '-i', {container!r}, 'psql'] + args, input=stdin)
sys.exit(r.returncode)
''')
        os.chmod(shim, 0o755)
        return d

    # ---- one job -----------------------------------------------------------------------------------
    def run_job(self, job):
        spec = self.workflow['jobs'][job]
        rec = {'name': spec.get('name'), 'steps': [], 'status': 'FAIL'}
        self.manifest['jobs'][job] = rec
        req = os.path.join(self.ws, '.github/ci/requirements-test.txt')
        key = sha256_bytes(open(req, 'rb').read())
        home = os.path.join(LCE_HOME, f'home-py{PYTHON_MINOR}-{key[:16]}')
        os.makedirs(home, exist_ok=True)
        rec['home'] = home
        rec['requirements_test_sha256'] = key
        ctx = Context(self.sha, self.ws, {})
        container = None
        if 'services' in spec:
            if set(spec['services']) != {'postgres'}:
                raise Refused(f'unsupported services {sorted(spec["services"])}')
            container, port = self.start_postgres(spec['services']['postgres'])
        job_env = {}
        for k, v in (spec.get('env') or {}).items():
            v = ctx.substitute(str(v))
            if container and '127.0.0.1:5432' in v:
                v = v.replace('127.0.0.1:5432', f'127.0.0.1:{port}')
            job_env[k] = v
        ctx.env = job_env
        path = []
        if container:
            path.insert(0, self.psql_shim(container, port))
        deadline = time.time() + 60 * float(spec.get('timeout-minutes', 360))
        gh = os.path.join(self.base, f'gh-{job}')
        os.makedirs(gh, exist_ok=True)
        for i, step in enumerate(spec['steps']):
            label = step.get('name') or step.get('uses') or step.get('run', '').splitlines()[0][:60]
            srec = {'index': i, 'label': label}
            rec['steps'].append(srec)
            if not ctx.condition(step.get('if')):
                srec['result'] = 'skipped (if: false)'
                continue
            uses = step.get('uses')
            if uses:
                if uses not in USES_ALLOWED:
                    raise Refused(f'unsupported action {uses}')
                if uses.startswith('actions/checkout'):
                    srec['result'] = 'emulated: clean detached worktree of the SHA (full history)'
                elif uses.startswith('actions/setup-python'):
                    want = str((step.get('with') or {}).get('python-version'))
                    if want != PYTHON_MINOR:
                        raise Refused(f'setup-python {want} != {PYTHON_MINOR}')
                    out = self.setup_python(job, ctx, path)
                    if step.get('id'):
                        ctx.outputs[step['id']] = out
                    srec['result'] = f'emulated: fresh venv, python {out["python-version"]}'
                elif uses.startswith('actions/cache/restore'):
                    hit = 'true' if os.path.exists(os.path.join(home, 'ci-venv/bin/python')) else 'false'
                    if step.get('id'):
                        ctx.outputs[step['id']] = {'cache-hit': hit, 'cache-primary-key': 'lce'}
                    srec['result'] = f'emulated: persistent LCE home (hit={hit})'
                else:
                    srec['result'] = 'emulated: no-op (cache save)'
                continue
            script = ctx.substitute(step['run'])
            env = self.base_env(home)
            env.update(job_env)
            env.update({k: ctx.substitute(str(v)) for k, v in (step.get('env') or {}).items()})
            out_f, path_f, sum_f = (os.path.join(gh, f'{n}-{i}') for n in ('output', 'path', 'summary'))
            for f in (out_f, path_f, sum_f):
                open(f, 'w').close()
            env.update({'GITHUB_OUTPUT': out_f, 'GITHUB_PATH': path_f, 'GITHUB_STEP_SUMMARY': sum_f,
                        'GITHUB_WORKSPACE': self.ws, 'RUNNER_TEMP': gh})
            env['PATH'] = ':'.join(path + [env['PATH']])
            cwd = os.path.join(self.ws, step['working-directory']) if step.get('working-directory') else self.ws
            log = os.path.join(self.evdir, f'{job}-step{i:02d}.log')
            t0 = time.time()
            with open(log, 'w') as lf:
                lf.write(f'# job={job} step={i} label={label}\n# cwd={cwd}\n# script:\n{script}\n# ----\n')
                lf.flush()
                try:
                    p = subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c', script],
                                       cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT,
                                       timeout=max(1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    srec.update({'rc': None, 'result': 'FAILED (job timeout-minutes exceeded)',
                                 'log': os.path.basename(log)})
                    return rec
            srec.update({'rc': p.returncode, 'seconds': round(time.time() - t0, 1),
                         'log': os.path.basename(log)})
            text = open(log, errors='replace').read()
            if 'pytest' in script:
                srec['counts'] = pytest_counts(text)
            for line in open(out_f):
                if '=' in line and step.get('id'):
                    k, v = line.rstrip('\n').split('=', 1)
                    ctx.outputs.setdefault(step['id'], {})[k] = v
            for line in open(path_f):
                if line.strip():
                    path.insert(0, line.strip())
            if p.returncode:
                srec['result'] = 'FAILED'
                return rec
            srec['result'] = 'ok'
        ran_pytest = [s for s in rec['steps'] if 'counts' in s]
        if not any(s['counts'].get('passed') for s in ran_pytest):
            rec['status'] = 'FAIL'
            rec['reason'] = 'no test passed (incomplete coverage)'
            return rec
        if any(s['counts'].get('failed') or s['counts'].get('errors') for s in ran_pytest):
            rec['reason'] = 'test failures'
            return rec
        rec['status'] = 'PASS'
        return rec

    # ---- whole run ---------------------------------------------------------------------------------
    def cleanup(self):
        for c in self.containers:
            run(['docker', 'rm', '-f', c])
        for wt in reversed(self.worktrees + self.ref_trees()):
            run(['git', 'worktree', 'remove', '--force', wt], cwd=self.repo)
        run(['git', 'worktree', 'prune'], cwd=self.repo)
        shutil.rmtree(self.base, ignore_errors=True)

    def ref_trees(self):
        return [os.path.join(self.base, d) for d in os.listdir(self.base) if d.startswith('ref-')] \
            if os.path.isdir(self.base) else []

    def freeze(self):
        info = {}
        for job, rec in self.manifest['jobs'].items():
            for cand in [os.path.join(self.base, f'py-{job}', 'bin', 'python'),
                         os.path.join(rec.get('home', ''), 'ci-venv', 'bin', 'python')]:
                if os.path.exists(cand):
                    f = run([cand, '-m', 'pip', 'freeze', '--all']).stdout
                    info[f'{job}:{os.path.relpath(cand, "/")}'] = {'sha256': sha256_bytes(f.encode()),
                                                                   'packages': len(f.splitlines())}
                    with open(os.path.join(self.evdir, f'freeze-{job}-{len(info)}.txt'), 'w') as fh:
                        fh.write(f)
        self.manifest['environments'] = info

    def go(self):
        verdict = 'FAIL'
        try:
            self.preflight()
            for job in self.jobs:
                self.run_job(job)
            self.freeze()
            statuses = {j: r['status'] for j, r in self.manifest['jobs'].items()}
            if set(self.jobs) != set(JOBS):
                verdict = 'PARTIAL'                     # never a substitute for the full workflow
            elif all(v == 'PASS' for v in statuses.values()) and len(statuses) == len(JOBS):
                verdict = 'PASS'
        except Refused as exc:
            self.manifest['refusals'].append(str(exc))
        except Exception as exc:                        # anything unexpected is a failure, never a pass
            self.manifest['refusals'].append(f'{type(exc).__name__}: {exc}'[:300])
        finally:
            self.cleanup()
            self.manifest['verdict'] = verdict
            self.manifest['finished_utc'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
            self.manifest['runner_sha256'] = sha256_bytes(open(__file__, 'rb').read())
            if os.path.isdir(self.evdir):
                with open(os.path.join(self.evdir, 'manifest.json'), 'w') as fh:
                    json.dump(self.manifest, fh, indent=1, sort_keys=True)
                sums = []
                for f in sorted(os.listdir(self.evdir)):
                    if f != 'SHA256SUMS':
                        sums.append(f'{sha256_bytes(open(os.path.join(self.evdir, f), "rb").read())}  {f}')
                with open(os.path.join(self.evdir, 'SHA256SUMS'), 'w') as fh:
                    fh.write('\n'.join(sums) + '\n')
        return verdict


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('commit')
    ap.add_argument('--jobs', default=','.join(JOBS))
    ap.add_argument('--evidence-root', default=os.path.expanduser('~/ops/ci-evidence'))
    ap.add_argument('--repo', default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    a = ap.parse_args(argv)
    jobs = tuple(j for j in a.jobs.split(',') if j)
    if not jobs or any(j not in JOBS for j in jobs):
        ap.error(f'--jobs must be a subset of {",".join(JOBS)}')
    r = Runner(a.repo, a.commit, jobs, a.evidence_root)
    verdict = r.go()
    print(json.dumps({'verdict': verdict, 'evidence': r.evdir, 'refusals': r.manifest['refusals'],
                      'jobs': {j: v['status'] for j, v in r.manifest['jobs'].items()}}, sort_keys=True))
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
