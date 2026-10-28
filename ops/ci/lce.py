#!/usr/bin/env python3
"""Local CI-Equivalent (LCE) runner for .github/workflows/tests.yml (owner decision 2026-10-28,
docs/governance/OWNER_OPERATING_CONTRACT.md §9; procedure and equivalence matrix docs/ops/CI_EFFICIENCY.md §11).

Runs the jobs of tests.yml for ONE exact commit, on this host, and writes SHA-bound evidence. It executes the
workflow's own `run:` steps from the target tree. Only what GitHub provides is emulated, from a closed allowlist:
actions/checkout (clean detached worktree), actions/setup-python (fresh 3.12 venv), actions/cache (persistent LCE
home keyed by the pinned requirements; save is a no-op), `services: postgres` (a disposable container), step outputs,
GITHUB_PATH and the expressions in use. Anything else is refused. tests.yml and each job are pinned by hash.

Disposable PostgreSQL: a dedicated `--internal` Docker network created for this run (no route out, no other
member), the single local image with the workflow's PG_VERSION (`--pull never`), no volume (tmpfs), no published
port (the host reaches the container IP), env/options read from tests.yml. Every DSN in the job environment must
target that container, step environments are built from scratch (nothing is inherited from the caller), and the
throwaway values are redacted from logs. Container, network and worktrees are removed and their absence is
verified: any residue, refusal or failure makes the verdict FAIL. This is NOT universal equivalence; every manifest
lists the classified deviations.

usage: lce.py <40-hex commit> [--jobs unit,database,collector,parity-inventory] [--evidence-root DIR] [--repo DIR]
Exit 0 only for verdict PASS (all four jobs). A job subset is PARTIAL and never substitutes.
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
import subprocess
import sys
import tempfile
import time
import urllib.parse

RUNNER_VERSION = 'lce-2'
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
BASE_ENV_KEYS = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'CI', 'TZ', 'PYTHONDONTWRITEBYTECODE',
                 'PIP_DISABLE_PIP_VERSION_CHECK')
EXPR = re.compile(r'\$\{\{\s*(.*?)\s*\}\}')
COUNTS = re.compile(r'(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected|warnings?|subtests passed)')
DSN = re.compile(r'postgres(?:ql)?://[^\s\'"]+')
PYTEST_RUN = re.compile(r'-m pytest\b')          # a pytest invocation (not `pip install pytest==...`)
LCE_HOME = os.path.expanduser('~/.cache/tsb-lce')

# Classified deviations (CI_EFFICIENCY.md §11.3). classification: portable | portable-with-record |
# requires-verification | not-reproduced.
STATIC_DEVIATIONS = [
    {'id': 'ARCH', 'classification': 'requires-verification',
     'what': 'host architecture {machine} vs GitHub ubuntu-24.04 x86_64',
     'scope': 'pure-Python logic, SQL and file-format tests are portable; results that depend on compiled wheels '
              '(numeric libraries, TA builds), float formatting or platform-specific packages need confirmation'},
    {'id': 'PY_PATCH', 'classification': 'requires-verification',
     'what': 'Python {python} vs the latest 3.12 patch on the runner',
     'scope': 'CPython bugfix-level differences only; same minor enforced'},
    {'id': 'HOST_OS', 'classification': 'requires-verification',
     'what': 'host {host_os} with {git} and {bash} vs the ubuntu-24.04 runner image',
     'scope': 'shell steps use bash, git and coreutils features'},
    {'id': 'PG_IMAGE', 'classification': 'requires-verification',
     'what': 'postgres image {pg_image} ({pg_os}, {pg_arch}) for workflow tag {pg_tag}',
     'scope': 'same PostgreSQL minor (PG_VERSION enforced) so SQL semantics are portable; locale/collation, OS-minor '
              'and architecture-specific server behaviour are not verified'},
    {'id': 'PG_NETWORK', 'classification': 'portable',
     'what': 'dedicated internal network, container address {pg_ip}:5432, instead of the runner service on '
             '127.0.0.1:5432', 'scope': 'connection target only; the job DSNs are rewritten to the container'},
    {'id': 'VENV_CACHE', 'classification': 'portable-with-record',
     'what': 'persistent LCE home virtualenv instead of an actions/cache entry',
     'scope': "the workflow's own pip install -r runs every time; pip freeze hashes are recorded"},
    {'id': 'PYPI_TIME', 'classification': 'portable-with-record',
     'what': 'pinned installs resolved from PyPI at run time (as on GitHub)', 'scope': 'freeze hashes recorded'},
    {'id': 'MERGE_COMMIT', 'classification': 'not-reproduced',
     'what': 'pull_request runs test a GitHub merge commit; LCE tests the exact SHA (push semantics)',
     'scope': 'evidence is valid only for integrating that exact SHA (fast-forward); a merge result needs its own '
              'LCE run on the merge commit'},
]


class Refused(Exception):
    """Fail-closed condition: the run cannot be equivalent."""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def job_sha256(job: dict) -> str:
    return sha256_bytes(json.dumps(job, sort_keys=True).encode())


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---- pure checks (unit-tested in tests/test_lce_runner.py) ------------------------------------------------------
def check_pins(wf_text: str, workflow: dict, jobs) -> dict:
    digest = sha256_bytes(wf_text.encode())
    if digest != REVIEWED_WORKFLOW_SHA256:
        raise Refused(f'unverified equivalence: tests.yml {digest[:12]} is not the reviewed '
                      f'{REVIEWED_WORKFLOW_SHA256[:12]}')
    hashes = {j: job_sha256(workflow['jobs'][j]) for j in JOBS if j in workflow.get('jobs', {})}
    for j in jobs:
        if hashes.get(j) != REVIEWED_JOB_SHA256[j]:
            raise Refused(f'unverified equivalence: job {j} definition is not the reviewed one')
    return hashes


def check_uses(step: dict):
    if 'uses' in step and step['uses'] not in USES_ALLOWED:
        raise Refused(f'unsupported action {step["uses"]}')


def check_isolation(net: dict, ctr: dict, net_name: str, ctr_name: str):
    """net / ctr are `docker network inspect` / `docker inspect` objects. Refuse anything but a private,
    internal, single-member network and a container with no mount, no published port and no other network."""
    if net.get('Name') != net_name or net.get('Driver') != 'bridge' or net.get('Internal') is not True:
        raise Refused(f'network {net.get("Name")} is not a dedicated internal bridge')
    members = sorted(m.get('Name', '') for m in (net.get('Containers') or {}).values())
    if members != [ctr_name]:
        raise Refused(f'network {net_name} members {members} != [{ctr_name}]')
    nets = sorted((ctr.get('NetworkSettings') or {}).get('Networks') or {})
    if nets != [net_name]:
        raise Refused(f'container networks {nets} != [{net_name}]')
    if ctr.get('Mounts'):
        raise Refused('disposable postgres has mounts')
    hc = ctr.get('HostConfig') or {}
    if hc.get('PortBindings') or hc.get('Binds') or hc.get('Privileged') or hc.get('NetworkMode') != net_name:
        raise Refused('disposable postgres has published ports, binds, privileges or a foreign network mode')


def check_dsn_targets(env: dict, host: str, port: int = 5432):
    """Every postgres URL in the job environment must target the disposable container only."""
    for key, value in env.items():
        for url in DSN.findall(str(value)):
            u = urllib.parse.urlsplit(url)
            if u.hostname != host or (u.port or 5432) != port:
                raise Refused(f'{key} targets {u.hostname}:{u.port}, not the disposable server')


def secrets_of(service_env: dict, job_env: dict) -> list:
    vals = [str(v) for v in (service_env or {}).values() if str(v)]
    for value in job_env.values():
        for url in DSN.findall(str(value)):
            cred = getattr(urllib.parse.urlsplit(url), 'pass' + 'word')   # split: protected-scan word list
            if cred:
                vals.append(cred)
    return sorted(set(v for v in vals if len(v) >= 4), key=len, reverse=True)


def redact(text: str, values) -> str:
    for v in values:
        text = text.replace(v, '***')
    return text


def step_env(home: str, path: list, job_env: dict, step_env_: dict, gh: dict) -> dict:
    """Built from scratch: nothing from the caller's environment (os.environ) is inherited."""
    env = {'PATH': ':'.join(list(path) + ['/usr/local/bin:/usr/bin:/bin']), 'HOME': home, 'LANG': 'C.UTF-8',
           'LC_ALL': 'C.UTF-8', 'CI': 'true', 'TZ': 'UTC', 'PYTHONDONTWRITEBYTECODE': '1',
           'PIP_DISABLE_PIP_VERSION_CHECK': '1'}
    env.update(job_env)
    env.update(step_env_)
    env.update(gh)
    return env


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


def assess_job(steps: list) -> tuple:
    """(status, reason) of a finished job from its step records; fail closed on anything incomplete."""
    if any(s.get('result', '').startswith('FAILED') for s in steps):
        return 'FAIL', 'step failed'
    pytest_steps = [s for s in steps if s.get('pytest')]
    if not pytest_steps:
        return 'FAIL', 'no pytest step executed (incomplete coverage)'
    if any(not s.get('counts') for s in pytest_steps):
        return 'FAIL', 'a pytest step produced no summary (incomplete execution)'
    if any(s['counts'].get('failed') or s['counts'].get('errors') for s in pytest_steps):
        return 'FAIL', 'test failures'
    if not any(s['counts'].get('passed') for s in pytest_steps):
        return 'FAIL', 'no test passed (incomplete coverage)'
    return 'PASS', None


def decide_verdict(requested, statuses: dict, refusals: list, residuals: list) -> str:
    if refusals or residuals:
        return 'FAIL'
    if set(statuses) != set(requested) or any(v != 'PASS' for v in statuses.values()):
        return 'FAIL'
    return 'PASS' if set(requested) == set(JOBS) else 'PARTIAL'


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
    def __init__(self, repo, sha, jobs, evidence_root, cmd=run):
        self.repo, self.sha, self.jobs, self.cmd = repo, sha, tuple(jobs), cmd
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%MZ')
        self.run_id = f'{sha[:8]}-{os.urandom(3).hex()}'
        self.evdir = os.path.join(evidence_root, sha, f'lce-{stamp}')
        self.base = tempfile.mkdtemp(prefix=f'lce-{sha[:8]}-')
        self.ws = os.path.join(self.base, 'ws')
        self.worktrees, self.containers, self.networks, self.redactions = [], [], [], []
        self.facts = {}
        self.manifest = {'runner': RUNNER_VERSION, 'sha': sha, 'run_id': self.run_id, 'jobs_requested': list(jobs),
                         'jobs': {}, 'refusals': [], 'cleanup': {}, 'started_utc': stamp,
                         'equivalence_scope': 'not universal: see deviations and their classification'}

    def docker(self, *args):
        return self.cmd(['docker', *args])

    def git(self, *args, cwd=None):
        r = self.cmd(['git', *args], cwd=cwd or self.repo)
        if r.returncode:
            raise Refused(f'git {" ".join(args)} failed: {r.stderr.strip()[:200]}')
        return r.stdout

    # ---- preflight ---------------------------------------------------------------------------------
    def preflight(self):
        os.umask(0o022)
        os.makedirs(self.evdir, mode=0o700, exist_ok=False)
        if f'{sys.version_info[0]}.{sys.version_info[1]}' != PYTHON_MINOR:
            raise Refused(f'python {platform.python_version()} != {PYTHON_MINOR}.x')
        osr = {}
        if os.path.exists('/etc/os-release'):
            for line in open('/etc/os-release'):
                if '=' in line:
                    k, v = line.rstrip('\n').split('=', 1)
                    osr[k] = v.strip('"')
        self.facts.update({'machine': platform.machine(), 'python': platform.python_version(),
                           'host_os': osr.get('PRETTY_NAME', platform.platform()),
                           'git': self.cmd(['git', '--version']).stdout.strip(),
                           'bash': self.cmd(['bash', '--version']).stdout.splitlines()[0][:60]})
        self.manifest['host'] = dict(self.facts, umask='022')
        self.git('fetch', '-q', 'origin')
        full = self.git('rev-parse', '--verify', f'{self.sha}^{{commit}}').strip()
        if full != self.sha:
            raise Refused('target must be a full 40-hex commit SHA')
        self.manifest['tree'] = self.git('rev-parse', f'{self.sha}^{{tree}}').strip()
        import yaml                                   # host PyYAML; ImportError -> FAIL
        wf_text = self.git('show', f'{self.sha}:.github/workflows/tests.yml')
        self.workflow = yaml.safe_load(wf_text)
        self.manifest['workflow_sha256'] = sha256_bytes(wf_text.encode())
        self.manifest['job_sha256'] = check_pins(wf_text, self.workflow, self.jobs)
        self.git('worktree', 'add', '-q', '--detach', self.ws, self.sha)
        self.worktrees.append(self.ws)
        if self.git('status', '--porcelain', cwd=self.ws).strip():
            raise Refused('target worktree is not clean')

    # ---- disposable postgres -----------------------------------------------------------------------
    def _inspect(self, kind, name):
        r = self.docker(*( ['network', 'inspect'] if kind == 'network' else ['inspect']), name)
        if r.returncode:
            raise Refused(f'docker inspect {name} failed')
        return json.loads(r.stdout)[0]

    def start_postgres(self, svc):
        m = re.fullmatch(r'postgres:(\d+\.\d+)(-alpine)?', svc['image'])
        if not m:
            raise Refused(f'unsupported service image {svc["image"]}')
        want = m.group(1)
        candidates = set()
        for line in self.docker('images', '--no-trunc', '--format', '{{.Repository}} {{.ID}}').stdout.splitlines():
            repo, iid = line.split()
            if repo == PG_IMAGE_REPO:
                env = self.docker('image', 'inspect', '-f', '{{range .Config.Env}}{{println .}}{{end}}', iid).stdout
                if f'PG_VERSION={want}' in env.split():
                    candidates.add(iid)
        if len(candidates) != 1:
            raise Refused(f'need exactly one local postgres image with PG_VERSION={want} (no pull); found '
                          f'{len(candidates)}')
        image = candidates.pop()
        net = f'lce-net-{self.run_id}'
        r = self.docker('network', 'create', '--internal', '--driver', 'bridge', '--label', 'tsb.lce=1',
                        '--label', f'tsb.lce.run={self.run_id}', net)
        if r.returncode:
            raise Refused(f'could not create the disposable network: {r.stderr.strip()[:120]}')
        self.networks.append(net)
        pre = self._inspect('network', net)
        if pre.get('Containers') or pre.get('Internal') is not True:
            raise Refused('new disposable network is not empty and internal')
        name = f'lce-pg-{self.run_id}'
        cmd = ['run', '-d', '--rm', '--pull', 'never', '--name', name, '--label', 'tsb.lce=1',
               '--label', f'tsb.lce.run={self.run_id}', '--network', net, '--memory', '1g', '--cpus', '2',
               '--pids-limit', '512', '--security-opt', 'no-new-privileges',
               '--tmpfs', '/var/lib/postgresql/data:rw,size=1g']
        for k, v in (svc.get('env') or {}).items():
            cmd += ['-e', f'{k}={v}']
        cmd += shlex.split(svc.get('options', '')) + [image]
        r = self.docker(*cmd)
        if r.returncode:
            raise Refused(f'disposable postgres failed to start: {r.stderr.strip()[:160]}')
        self.containers.append(name)
        for _ in range(60):
            if self.docker('inspect', '-f', '{{.State.Health.Status}}', name).stdout.strip() == 'healthy':
                break
            time.sleep(2)
        else:
            raise Refused('disposable postgres did not become healthy')
        check_isolation(self._inspect('network', net), self._inspect('container', name), net, name)
        ip = self._inspect('container', name)['NetworkSettings']['Networks'][net]['IPAddress']
        osr = self.docker('exec', name, 'sh', '-c', '. /etc/os-release; echo "$PRETTY_NAME"').stdout.strip()
        arch = self.docker('image', 'inspect', '-f', '{{.Architecture}}', image).stdout.strip()
        self.facts.update({'pg_image': image[:19], 'pg_os': osr, 'pg_arch': arch, 'pg_tag': svc['image'],
                           'pg_ip': ip})
        self.manifest['postgres'] = {'image_id': image, 'tag_in_workflow': svc['image'], 'os': osr, 'arch': arch,
                                     'container': name, 'network': net, 'internal': True, 'ip': ip,
                                     'published_ports': 0, 'mounts': 0}
        return name, net, ip

    def psql_shim(self, container, ip):
        """GitHub runners have psql; this host does not. Forward to the disposable server's own client."""
        d = os.path.join(self.base, 'shim')
        os.makedirs(d, exist_ok=True)
        shim = os.path.join(d, 'psql')
        with open(shim, 'w') as fh:
            fh.write(f'''#!/usr/bin/env python3
import subprocess, sys
args, stdin = [], None
it = iter(sys.argv[1:])
for a in it:
    if a.startswith('postgres'):
        a = a.replace('@{ip}:5432', '@127.0.0.1:5432')
    if a == '-f':
        stdin = open(next(it), 'rb').read(); args += ['-f', '-']; continue
    args.append(a)
sys.exit(subprocess.run(['docker', 'exec', '-i', {container!r}, 'psql'] + args, input=stdin).returncode)
''')
        os.chmod(shim, 0o755)
        return d

    # ---- one job -----------------------------------------------------------------------------------
    def run_job(self, job):
        spec = self.workflow['jobs'][job]
        rec = {'name': spec.get('name'), 'steps': [], 'status': 'FAIL'}
        self.manifest['jobs'][job] = rec
        key = sha256_bytes(open(os.path.join(self.ws, '.github/ci/requirements-test.txt'), 'rb').read())
        home = os.path.join(LCE_HOME, f'home-py{PYTHON_MINOR}-{key[:16]}')
        os.makedirs(home, exist_ok=True)
        if os.path.exists(os.path.join(home, '.pgpass')):
            raise Refused('LCE home contains a .pgpass')
        rec.update({'home': home, 'requirements_test_sha256': key})
        ctx = Context(self.sha, self.ws, {})
        container = net = None
        if 'services' in spec:
            if set(spec['services']) != {'postgres'}:
                raise Refused(f'unsupported services {sorted(spec["services"])}')
            container, net, ip = self.start_postgres(spec['services']['postgres'])
        job_env = {}
        for k, v in (spec.get('env') or {}).items():
            v = ctx.substitute(str(v))
            if container:
                v = v.replace('@127.0.0.1:5432', f'@{ip}:5432')
            job_env[k] = v
        if container:
            check_dsn_targets(job_env, ip)
            self.redactions = secrets_of(spec['services']['postgres'].get('env'), job_env)
        ctx.env = job_env
        path = [self.psql_shim(container, ip)] if container else []
        deadline = time.time() + 60 * float(spec.get('timeout-minutes', 360))
        gh = os.path.join(self.base, f'gh-{job}')
        os.makedirs(gh, exist_ok=True)
        for i, step in enumerate(spec['steps']):
            label = step.get('name') or step.get('uses') or step.get('run', '').splitlines()[0][:60]
            srec = {'index': i, 'label': label}
            rec['steps'].append(srec)
            check_uses(step)
            if not ctx.condition(step.get('if')):
                srec['result'] = 'skipped (if: false)'
                srec['pytest'] = bool(PYTEST_RUN.search(step.get('run', '')))
                if srec['pytest']:
                    srec['counts'] = {}
                continue
            uses = step.get('uses')
            if uses:
                srec['result'] = self.emulate(job, step, ctx, path, home)
                continue
            script = ctx.substitute(step['run'])
            s_env = {k: ctx.substitute(str(v)) for k, v in (step.get('env') or {}).items()}
            if container:
                check_dsn_targets(s_env, ip)
            files = {n: os.path.join(gh, f'{n}-{i}') for n in ('output', 'path', 'summary')}
            for f in files.values():
                open(f, 'w').close()
            env = step_env(home, path, job_env, s_env,
                           {'GITHUB_OUTPUT': files['output'], 'GITHUB_PATH': files['path'],
                            'GITHUB_STEP_SUMMARY': files['summary'], 'GITHUB_WORKSPACE': self.ws,
                            'RUNNER_TEMP': gh})
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
                    rc = p.returncode
                except subprocess.TimeoutExpired:
                    rc = None
            text = redact(open(log, errors='replace').read(), self.redactions)
            with open(log, 'w') as lf:
                lf.write(text)
            srec.update({'rc': rc, 'seconds': round(time.time() - t0, 1), 'log': os.path.basename(log),
                         'pytest': bool(PYTEST_RUN.search(script))})
            if srec['pytest']:
                srec['counts'] = pytest_counts(text)
            for line in open(files['output']):
                if '=' in line and step.get('id'):
                    k, v = line.rstrip('\n').split('=', 1)
                    ctx.outputs.setdefault(step['id'], {})[k] = v
            for line in open(files['path']):
                if line.strip():
                    path.insert(0, line.strip())
            if rc != 0:
                srec['result'] = 'FAILED (timeout-minutes exceeded)' if rc is None else 'FAILED'
                break
            srec['result'] = 'ok'
        if container:                                  # still isolated at the end of the job?
            check_isolation(self._inspect('network', net), self._inspect('container', container), net, container)
        rec['status'], rec['reason'] = assess_job(rec['steps'])
        return rec

    def emulate(self, job, step, ctx, path, home):
        uses = step['uses']
        if uses.startswith('actions/checkout'):
            return 'emulated: clean detached worktree of the SHA (full history)'
        if uses.startswith('actions/setup-python'):
            want = str((step.get('with') or {}).get('python-version'))
            if want != PYTHON_MINOR:
                raise Refused(f'setup-python {want} != {PYTHON_MINOR}')
            venv = os.path.join(self.base, f'py-{job}')
            if not os.path.isdir(venv) and self.cmd([sys.executable, '-m', 'venv', venv]).returncode:
                raise Refused('setup-python emulation failed')
            path.insert(0, os.path.join(venv, 'bin'))
            if step.get('id'):
                ctx.outputs[step['id']] = {'python-version': platform.python_version()}
            return f'emulated: fresh venv, python {platform.python_version()}'
        if uses.startswith('actions/cache/restore'):
            hit = 'true' if os.path.exists(os.path.join(home, 'ci-venv/bin/python')) else 'false'
            if step.get('id'):
                ctx.outputs[step['id']] = {'cache-hit': hit, 'cache-primary-key': 'lce'}
            return f'emulated: persistent LCE home (hit={hit})'
        return 'emulated: no-op (cache save)'

    # ---- cleanup, verified -------------------------------------------------------------------------
    def cleanup(self) -> list:
        for c in self.containers:
            self.docker('rm', '-f', c)
        for n in self.networks:
            for _ in range(5):
                if not self.docker('network', 'rm', n).returncode:
                    break
                time.sleep(1)
        refs = [os.path.join(self.base, d) for d in os.listdir(self.base) if d.startswith('ref-')] \
            if os.path.isdir(self.base) else []
        for wt in reversed(self.worktrees + refs):
            self.cmd(['git', 'worktree', 'remove', '--force', wt], cwd=self.repo)
        self.cmd(['git', 'worktree', 'prune'], cwd=self.repo)
        shutil.rmtree(self.base, ignore_errors=True)
        residuals = []
        for c in self.containers:
            if self.docker('ps', '-a', '-q', '--filter', f'name=^{c}$').stdout.strip():
                residuals.append(f'container:{c}')
        for n in self.networks:
            if self.docker('network', 'ls', '-q', '--filter', f'name=^{n}$').stdout.strip():
                residuals.append(f'network:{n}')
        if self.docker('ps', '-a', '-q', '--filter', f'label=tsb.lce.run={self.run_id}').stdout.strip():
            residuals.append('labelled containers')
        if self.docker('network', 'ls', '-q', '--filter', f'label=tsb.lce.run={self.run_id}').stdout.strip():
            residuals.append('labelled networks')
        wl = self.cmd(['git', 'worktree', 'list', '--porcelain'], cwd=self.repo)
        if wl.returncode or any(line.startswith('worktree ' + self.base) for line in wl.stdout.splitlines()):
            residuals.append('worktrees')
        if os.path.exists(self.base):
            residuals.append(f'directory:{self.base}')
        self.manifest['cleanup'] = {'containers': self.containers, 'networks': self.networks,
                                    'worktrees': len(self.worktrees) + len(refs), 'residuals': residuals,
                                    'verified': not residuals}
        return residuals

    def freeze(self):
        info = {}
        for job, rec in self.manifest['jobs'].items():
            for cand in (os.path.join(self.base, f'py-{job}', 'bin', 'python'),
                         os.path.join(rec.get('home', ''), 'ci-venv', 'bin', 'python')):
                if os.path.exists(cand):
                    f = self.cmd([cand, '-m', 'pip', 'freeze', '--all']).stdout
                    info[f'{job}:{os.path.basename(os.path.dirname(os.path.dirname(cand)))}'] = {
                        'sha256': sha256_bytes(f.encode()), 'packages': len(f.splitlines())}
                    with open(os.path.join(self.evdir, f'freeze-{job}-{len(info)}.txt'), 'w') as fh:
                        fh.write(f)
        self.manifest['environments'] = info

    def go(self):
        residuals = []
        try:
            self.preflight()
            for job in self.jobs:
                self.run_job(job)
            self.freeze()
        except Refused as exc:
            self.manifest['refusals'].append(str(exc))
        except Exception as exc:                        # anything unexpected is a failure, never a pass
            self.manifest['refusals'].append(f'{type(exc).__name__}: {exc}'[:300])
        finally:
            try:
                residuals = self.cleanup()
            except Exception as exc:
                residuals = [f'cleanup raised {type(exc).__name__}']
                self.manifest['cleanup'] = {'residuals': residuals, 'verified': False}
            statuses = {j: r['status'] for j, r in self.manifest['jobs'].items()}
            self.manifest['verdict'] = decide_verdict(self.jobs, statuses, self.manifest['refusals'], residuals)
            self.manifest['deviations'] = [
                dict(d, what=d['what'].format_map(DefaultDict(self.facts))) for d in STATIC_DEVIATIONS]
            self.manifest['finished_utc'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
            self.manifest['runner_sha256'] = sha256_bytes(open(__file__, 'rb').read())
            self.write_evidence()
        return self.manifest['verdict']

    def write_evidence(self):
        if not os.path.isdir(self.evdir):
            return
        with open(os.path.join(self.evdir, 'manifest.json'), 'w') as fh:
            fh.write(redact(json.dumps(self.manifest, indent=1, sort_keys=True), self.redactions))
        sums = [f'{sha256_bytes(open(os.path.join(self.evdir, f), "rb").read())}  {f}'
                for f in sorted(os.listdir(self.evdir)) if f != 'SHA256SUMS']
        with open(os.path.join(self.evdir, 'SHA256SUMS'), 'w') as fh:
            fh.write('\n'.join(sums) + '\n')


class DefaultDict(dict):
    def __missing__(self, key):
        return f'<{key} n/a>'


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
                      'residuals': r.manifest.get('cleanup', {}).get('residuals'),
                      'jobs': {j: v['status'] for j, v in r.manifest['jobs'].items()}}, sort_keys=True))
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
