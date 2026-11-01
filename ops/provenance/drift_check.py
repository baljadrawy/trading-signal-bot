#!/usr/bin/env python3
"""Read-only drift detector: compares the recorded runtime baseline (deploy/DEPLOYED.json) with server observations.

It NEVER mutates anything and never auto-remediates. Allowed host operations:
- `docker inspect` with explicit --format templates (no environment is ever requested, except the single PAPER_TRADING
  entry for D8, whose value is compared in memory and never printed);
- `ops/compose-safe render-hash` (read-only wrapper; prints only a hash);
- `ops/host/render.py compare` (read-only);
- reading files and hashing them;
- `--deep` only: `ops/provenance/runtime_manifest.py verify` (streams `docker save`; minutes of I/O).

Checks: B0 baseline validity/staleness, D1 identity (container and image ID), D2 image content (--deep only),
D3 compose file blobs, D4 render hash vs config-hash label, D5 host definitions, D6 start time and restart count,
D7 learner not running, D8 PAPER_TRADING=true.

Statuses and exit code (worst wins): SAFETY 3 > DRIFT 1 > UNKNOWN 2 > MATCH 0. NOT_RUN (D2 without --deep) and
NOT_APPLICABLE are neutral and are always printed, so a metadata-only MATCH is never mistaken for a content check.

Usage:
  drift_check.py check   [--manifest deploy/DEPLOYED.json] [--deep] [--json REPORT] [--max-age-days 30]
                         [--strategy-identity [--identity-reference REF] [--identity-current CUR]]
  drift_check.py validate [--manifest ...]
  drift_check.py observe  [--manifest ...] [--out FILE]   # current observations (no provenance, no env), for review
  drift_check.py strategy [--identity-reference REF] [--identity-current CUR] [--json REPORT]

Strategy identity (WP2 lane A; R5.d, R5.e; report-only): `strategy`, or `check --strategy-identity`, adds the
S1/S2 section. S1 hashes the declared decision closure of each strategy family in this checkout
(shared/strategy_identity.py; read-only file reads, no Docker) and compares it with REF (a previous
`strategy --json` report, an identity manifest or a closure document). S2 classifies the version boundary
between REF and CUR when both are identity manifests (shared/strategy_version_boundary.py). The section never
changes OVERALL, COVERAGE or the exit code of `check`; `strategy` exits 0, or 2 when REF/CUR is unreadable.
Without these flags the existing modes behave exactly as before and do not import shared/.

Output and reports are INTERNAL INFRASTRUCTURE METADATA: authorized operational use only; never upload them to public
services; never commit generated observations automatically. Files written by --json/--out are mode 0600.
Every check run prints a COVERAGE line (counts per status and verification=FULL|METADATA_ONLY|INCOMPLETE); FULL is
only possible with --deep and no UNKNOWN or NOT_RUN result. A required check that yields no result becomes UNKNOWN.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MATCH, DRIFT, UNKNOWN, SAFETY, NOT_RUN, NA = 'MATCH', 'DRIFT', 'UNKNOWN', 'SAFETY', 'NOT_RUN', 'NOT_APPLICABLE'
EXIT = {MATCH: 0, DRIFT: 1, UNKNOWN: 2, SAFETY: 3}
RANK = {MATCH: 0, NOT_RUN: 0, NA: 0, UNKNOWN: 1, DRIFT: 2, SAFETY: 3}
HEX64 = re.compile(r'^[0-9a-f]{64}$')
IMAGE_ID = re.compile(r'^sha256:[0-9a-f]{64}$')
BLOB = re.compile(r'^[0-9a-f]{40}$')
LEVELS = ('L0-artifact', 'L1-content-verified', 'L2-canonical-rebuild', 'external-upstream', 'none')
SOURCE_KINDS = ('commit', 'assembled', 'upstream', 'retired')
INSPECT_FMT = ('{"container_id":"{{.Id}}","image_id":"{{.Image}}","image_ref":"{{.Config.Image}}",'
               '"state":"{{.State.Status}}","started_at":"{{.State.StartedAt}}","restart_count":{{.RestartCount}},'
               '"config_hash":"{{index .Config.Labels "com.docker.compose.config-hash"}}"}')
PAPER_FMT = ('{{range .Config.Env}}{{if eq (index (split . "=") 0) "PAPER_TRADING"}}'
             '{{index (split . "=") 1}}{{end}}{{end}}')
REQUIRED_CHECKS = ('B0', 'D1', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8')
METADATA_NOTICE = ('INTERNAL INFRASTRUCTURE METADATA (container/image identifiers, paths, operational state). No secrets '
                   'or environment values. Authorized operational use only: do not upload to public services and do '
                   'not commit generated observations automatically.')
FORBIDDEN_KEYS = re.compile(r'(?i)(password|secret|token|api_key|apikey|private|env_values?)')


class HostError(Exception):
    """The observation could not be made (daemon unavailable, tool missing)."""


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


class Host:
    """Real, read-only observations. Tests replace this with a fake."""

    def _run(self, cmd, timeout=120):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HostError(f'{cmd[0]}: {type(exc).__name__}') from None

    def inspect(self, container):
        r = self._run(['docker', 'inspect', '--type', 'container', '--format', INSPECT_FMT, container])
        if r.returncode != 0:
            if 'No such' in (r.stderr or ''):
                return None
            raise HostError('docker inspect failed')
        return json.loads(r.stdout)

    def paper_trading_true(self, container):
        """True / False / None (absent or unreadable). The value itself is never returned or printed."""
        r = self._run(['docker', 'inspect', '--type', 'container', '--format', PAPER_FMT, container])
        if r.returncode != 0:
            return None
        v = r.stdout.strip()
        return None if v == '' else v == 'true'

    def file_blob(self, path):
        try:
            with open(path, 'rb') as f:
                return git_blob(f.read())
        except OSError:
            return None

    def render_hash(self, project_dir, service):
        r = self._run([os.path.join(ROOT, 'ops', 'compose-safe'), '--project-dir', project_dir, 'render-hash', service])
        m = re.fullmatch(rf'{re.escape(service)} ([0-9a-f]{{64}})', r.stdout.strip()) if r.returncode == 0 else None
        return m.group(1) if m else None

    def host_compare(self, values):
        r = self._run([sys.executable, os.path.join(ROOT, 'ops', 'host', 'render.py'), 'compare', values])
        bad = [l.split()[0] + ' ' + l.split()[1] for l in r.stdout.splitlines()
               if l and not l.startswith(('IDENTICAL', 'PRESENT'))]
        return r.returncode, bad

    def deep_verify(self, spec, manifest):
        r = self._run([sys.executable, os.path.join(ROOT, 'ops', 'provenance', 'runtime_manifest.py'), 'verify',
                       spec, manifest, '--repo', ROOT], timeout=3600)
        return r.returncode, [l for l in r.stdout.splitlines() if l.startswith(('OK', 'DIFF'))]

    def now(self):
        return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- manifest validation
def validate_manifest(m):
    """Return a list of schema problems (empty = valid)."""
    p = []

    def need(cond, msg):
        if not cond:
            p.append(msg)
    need(m.get('schema') == 'tsb-deployed/1', 'schema must be tsb-deployed/1')
    try:
        dt.datetime.fromisoformat(str(m.get('observed_at')).replace('Z', '+00:00'))
    except ValueError:
        p.append('observed_at must be an ISO-8601 timestamp')
    need(re.match(r'^[0-9a-f]{40}$', str(m.get('repository_head', ''))) is not None,
         'repository_head must be a full 40-hex commit')
    cps = m.get('compose_projects') or {}
    need(bool(cps), 'compose_projects required')
    for name, cp in cps.items():
        need(BLOB.match(str(cp.get('git_blob', ''))) is not None, f'{name}: compose git_blob must be 40-hex')
        need(bool(cp.get('repo_path')) and bool(cp.get('production_path')), f'{name}: repo_path and production_path required')
    svcs = m.get('services') or {}
    need(bool(svcs), 'services required')
    for name, s in svcs.items():
        o, pv, rp = s.get('observed') or {}, s.get('provenance') or {}, s.get('reproducibility') or {}
        need(bool(s.get('container')), f'{name}: container required')
        need(s.get('expected_state') in ('running', 'not_running'), f'{name}: expected_state running|not_running')
        need(s.get('compose_project') in cps or s.get('compose_project') == 'external', f'{name}: unknown compose_project')
        need(HEX64.match(str(o.get('container_id', ''))) is not None, f'{name}: observed.container_id must be full 64-hex')
        need(IMAGE_ID.match(str(o.get('image_id', ''))) is not None, f'{name}: observed.image_id must be sha256:<64-hex>')
        need(isinstance(o.get('restart_count'), int), f'{name}: observed.restart_count int')
        need(bool(o.get('started_at')), f'{name}: observed.started_at required')
        if o.get('config_hash'):
            need(HEX64.match(o['config_hash']) is not None, f'{name}: observed.config_hash must be 64-hex')
        need(pv.get('source_kind') in SOURCE_KINDS, f'{name}: provenance.source_kind invalid')
        if pv.get('source_kind') == 'commit':
            need(re.match(r'^[0-9a-f]{40}$', str(pv.get('source_commit', ''))) is not None, f'{name}: source_commit full 40-hex')
        need(rp.get('level') in LEVELS, f'{name}: reproducibility.level invalid')
        need(rp.get('canonical_rebuild') is False or (rp.get('level') == 'L2-canonical-rebuild' and rp.get('rebuild_evidence')),
             f'{name}: canonical_rebuild true requires level L2 and rebuild_evidence')
        need(rp.get('level') != 'L2-canonical-rebuild' or bool(rp.get('rebuild_evidence')),
             f'{name}: L2 requires rebuild_evidence')
        for a in s.get('archives') or []:
            need(HEX64.match(str(a.get('sha256', ''))) is not None, f'{name}: archive sha256 must be 64-hex')
    for path in _walk_keys(m):
        if FORBIDDEN_KEYS.search(path):
            p.append(f'forbidden key name: {path}')
    return p


def _walk_keys(o, prefix=''):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from [f'{prefix}{k}'] + list(_walk_keys(v, f'{prefix}{k}.'))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk_keys(v, f'{prefix}{i}.')


# --------------------------------------------------------------------------- checks
def run_checks(m, host, deep=False, max_age_days=30, root=ROOT):
    res = []

    def add(check, target, status, detail):
        res.append({'check': check, 'target': target, 'status': status, 'detail': detail})

    # B0 baseline
    probs = validate_manifest(m)
    if probs:
        add('B0', 'manifest', UNKNOWN, f'schema invalid ({len(probs)} problems): ' + '; '.join(probs[:3]))
        return res
    age = host.now() - dt.datetime.fromisoformat(m['observed_at'].replace('Z', '+00:00'))
    add('B0', 'age', MATCH if age.days <= max_age_days else UNKNOWN,
        f'baseline observed {age.days} d ago (limit {max_age_days})')
    for name, cp in m['compose_projects'].items():
        rb = host.file_blob(os.path.join(root, cp['repo_path']))
        add('B0', f'compose:{name}', MATCH if rb == cp['git_blob'] else UNKNOWN,
            'baseline compose blob equals the repository file' if rb == cp['git_blob'] else
            'baseline is stale: its compose blob differs from (or is missing in) the repository')
    for ev in m.get('evidence', []):
        ok = os.path.exists(os.path.join(root, ev))
        add('B0', f'evidence:{ev}', MATCH if ok else UNKNOWN, 'referenced evidence present' if ok else 'missing')

    # D3 compose blobs
    for name, cp in m['compose_projects'].items():
        pb = host.file_blob(cp['production_path'])
        add('D3', f'compose:{name}', UNKNOWN if pb is None else (MATCH if pb == cp['git_blob'] else DRIFT),
            'production file unreadable' if pb is None else
            ('production compose equals the baseline blob' if pb == cp['git_blob'] else 'production compose differs'))

    observed = {}
    for name, s in m['services'].items():
        try:
            observed[name] = host.inspect(s['container'])
        except HostError as exc:
            observed[name] = HostError(str(exc))
    for name, s in m['services'].items():
        o, b = observed[name], s['observed']
        if isinstance(o, HostError):
            for c in ('D1', 'D6'):
                add(c, name, UNKNOWN, 'docker inspect unavailable')
            if name == m.get('learner_service'):
                add('D7', name, UNKNOWN, 'learner state unknown')
            continue
        # D7 learner
        if name == m.get('learner_service'):
            running = o is not None and o['state'] in ('running', 'restarting')
            add('D7', name, SAFETY if running else MATCH,
                'LEARNER IS RUNNING' if running else ('learner container absent (not running)' if o is None
                                                      else f'learner not running (state {o["state"]})'))
        # D1 identity
        if o is None:
            add('D1', name, DRIFT, 'container missing (the baseline records it)')
            add('D6', name, NA, 'container missing')
            continue
        diffs = [k for k in ('container_id', 'image_id') if o[k] != b[k]]
        if s['expected_state'] == 'running' and o['state'] != 'running':
            diffs.append(f'state={o["state"]}')
        add('D1', name, DRIFT if diffs else MATCH, 'identity equals baseline' if not diffs else 'changed: ' + ', '.join(diffs))
        # D6 start time and restarts
        d6 = [k for k in ('started_at', 'restart_count') if o[k] != b[k]]
        add('D6', name, DRIFT if d6 else MATCH, 'start time and restart count unchanged' if not d6 else 'changed: ' + ', '.join(d6))
        # D4 render hash
        if s.get('render_hash_service'):
            rh = host.render_hash(m['compose_projects'][s['compose_project']]['production_dir'], s['render_hash_service'])
            if rh is None:
                add('D4', name, UNKNOWN, 'render-hash unavailable')
            else:
                bad = [x for x, ok in (('label', rh == o['config_hash']), ('baseline', rh == b.get('config_hash'))) if not ok]
                add('D4', name, DRIFT if bad else MATCH,
                    'render hash equals container label and baseline' if not bad else 'render hash differs from ' + ' and '.join(bad))
        else:
            add('D4', name, NA, s.get('render_hash_note', 'not rendered by compose-safe'))
        # D8 paper trading
        if (s.get('safety') or {}).get('paper_trading_required'):
            pt = host.paper_trading_true(s['container'])
            add('D8', name, MATCH if pt is True else (SAFETY if pt is False else UNKNOWN),
                'PAPER_TRADING is true' if pt is True else
                ("PAPER_TRADING is NOT 'true' (value not shown)" if pt is False else 'PAPER_TRADING not observable'))

    # D5 host definitions
    hv = m.get('host_definitions', {}).get('values')
    if hv:
        try:
            rc, bad = host.host_compare(os.path.join(root, hv))
            add('D5', 'host-definitions', MATCH if rc == 0 else (DRIFT if rc == 1 else UNKNOWN),
                'all host definitions identical' if rc == 0 else ('differences: ' + '; '.join(bad[:5]) if rc == 1 else 'compare unavailable'))
        except HostError:
            add('D5', 'host-definitions', UNKNOWN, 'compare unavailable')

    # D2 image content
    rm = m.get('release_manifest') or {}
    if not deep:
        add('D2', 'image-content', NOT_RUN, 'not requested (run with --deep; streams docker save, minutes of I/O)')
    elif not rm:
        add('D2', 'image-content', UNKNOWN, 'no release manifest referenced')
    else:
        try:
            rc, lines = host.deep_verify(os.path.join(root, rm['spec']), os.path.join(root, rm['manifest']))
            add('D2', 'image-content', MATCH if rc == 0 else (DRIFT if rc == 1 else UNKNOWN),
                f'{len(lines)} services verified' if rc == 0 else ('; '.join(l for l in lines if l.startswith('DIFF')) or 'verify unavailable'))
        except HostError:
            add('D2', 'image-content', UNKNOWN, 'verify unavailable')
    # required-check guard: a required check family that produced no result can never pass silently
    for c in REQUIRED_CHECKS + (('D2',) if deep else ()):
        if not any(r['check'] == c for r in res):
            add(c, 'coverage', UNKNOWN, 'required check produced no result')
    return res


def coverage(results, deep):
    """Counts per status plus the verification scope. FULL only when --deep ran and nothing is UNKNOWN/NOT_RUN."""
    counts = {k: sum(1 for r in results if r['status'] == k) for k in (MATCH, DRIFT, UNKNOWN, SAFETY, NOT_RUN, NA)}
    if counts[UNKNOWN]:
        verification = 'INCOMPLETE'
    elif not deep or counts[NOT_RUN]:
        verification = 'METADATA_ONLY'
    else:
        verification = 'FULL'
    return {'counts': counts, 'verification': verification, 'deep_requested': bool(deep), 'checks_total': len(results)}


def overall(results):
    worst = max((RANK[r['status']] for r in results), default=RANK[UNKNOWN])
    return {0: MATCH, 1: UNKNOWN, 2: DRIFT, 3: SAFETY}[worst]


def observe(m, host):
    out = {}
    for name, s in m['services'].items():
        try:
            out[name] = host.inspect(s['container'])
        except HostError as exc:
            out[name] = {'error': str(exc)}
    for name, cp in m['compose_projects'].items():
        out[f'compose:{name}'] = {'production_blob': host.file_blob(cp['production_path'])}
    return out


def write_private(path, obj):
    """Write JSON with mode 0600, also tightening a pre-existing file (umask alone would not)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            fd = None
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write('\n')
    finally:
        if fd is not None:
            os.close(fd)


# --------------------------------------------------------------------------- strategy identity (report-only)
STRATEGY_REPORT_SCHEMA = 'tsb-strategy-closure-report/1'


def _strategy_modules():
    """Imported lazily, so check/validate/observe never load shared/ unless the section is requested."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from shared import strategy_identity as si
    from shared import strategy_version_boundary as vb
    return si, vb


def _strategy_refs(reference, si):
    """{strategy_id: document} from a previous report, one identity manifest or one closure document."""
    if not isinstance(reference, dict):
        raise ValueError('reference must be a JSON object')
    if reference.get('schema') == STRATEGY_REPORT_SCHEMA:
        fams = reference.get('families')
        if not isinstance(fams, dict):
            raise ValueError('reference report has no families')
        return fams
    if reference.get('schema') in (si.IDENTITY_MANIFEST_SCHEMA, si.CLOSURE_DOCUMENT_SCHEMA):
        return {reference.get('strategy_id'): reference}
    raise ValueError('unrecognized reference schema')


def strategy_report(root=ROOT, reference=None, identity_current=None, manifests=None):
    """S1 closure comparison and S2 boundary classification. Pure apart from reading the declared
    closure files under `root`; deterministic (no clock, environment, Docker or network)."""
    si, vb = _strategy_modules()
    manifests = si.DRAFT_MANIFESTS if manifests is None else manifests
    refs = _strategy_refs(reference, si) if reference is not None else {}
    rows, families = [], {}

    def add(check, target, status, detail):
        rows.append({'check': check, 'target': target, 'status': status, 'detail': detail})

    for sid in sorted(manifests):
        manifest = manifests[sid]
        try:
            doc = si.closure_document(manifest, si.read_closure_sources(root, manifest))
        except si.ClosureError as exc:
            add('S1', sid, UNKNOWN, f'closure unresolved: {exc}')
            continue
        families[sid] = doc
        size = f"{len(doc['files'])} ACTIVE, {len(doc['inactive_files'])} inactive files"
        ref = refs.get(sid)
        if reference is None:
            add('S1', sid, NOT_RUN, f"source_hash {doc['source_hash'][:16]} ({size}); no reference supplied")
            continue
        if not isinstance(ref, dict):
            add('S1', sid, UNKNOWN, 'reference has no entry for this strategy')
            continue
        try:
            diff = si.compare_to_reference(doc, ref)
        except si.ClosureError as exc:
            add('S1', sid, UNKNOWN, f'reference invalid: {exc}')
            continue
        moved = diff['files_changed'] + diff['files_added'] + diff['files_removed']
        same_spec = diff.get('closure_spec_equal', True)
        inactive = diff.get('inactive_files_changed', []) + diff.get('inactive_files_added', [])
        if diff['source_hash_equal'] and same_spec:
            add('S1', sid, MATCH, f'ACTIVE closure equals the reference ({size})'
                + (f"; inactive files changed: {', '.join(inactive[:5])}" if inactive else ''))
        else:
            add('S1', sid, DRIFT, 'changed: ' + (', '.join(moved[:5]) or 'none')
                + ('; declared closure changed' if not same_spec else ''))
    boundary = None
    if identity_current is not None:
        sid = identity_current.get('strategy_id') if isinstance(identity_current, dict) else None
        ref = refs.get(sid)
        if not isinstance(identity_current, dict) or identity_current.get('schema') != si.IDENTITY_MANIFEST_SCHEMA:
            add('S2', str(sid), UNKNOWN, 'current is not an identity manifest')
        elif not isinstance(ref, dict) or ref.get('schema') != si.IDENTITY_MANIFEST_SCHEMA:
            add('S2', sid, UNKNOWN, 'a boundary needs an identity manifest on both sides')
        elif sid not in families:
            add('S2', sid, UNKNOWN, 'strategy not in this checkout\'s closure')
        else:
            here = si.compare_to_reference(families[sid], identity_current)
            if not (here['source_hash_equal'] and here.get('closure_spec_equal', True)):
                add('S2', sid, UNKNOWN, 'current identity manifest does not describe this checkout')
            else:
                try:
                    boundary = vb.version_boundary_report(ref, identity_current)
                except (vb.ReportError, si.ClosureError) as exc:
                    add('S2', sid, UNKNOWN, f'boundary report refused: {exc}')
                else:
                    add('S2', sid, boundary['drift_status'],
                        f"{boundary['classification']} {boundary['version_before']} -> {boundary['version_after']}"
                        f"; boundary_required={boundary['boundary_required']}")
    return {'schema': STRATEGY_REPORT_SCHEMA, 'report_only': True, 'results': rows, 'families': families,
            'boundary': boundary, 'historical_freeze': dict(si.HISTORICAL_FREEZE)}


def _load_optional_json(path):
    if path is None:
        return None
    with open(path) as f:
        return json.load(f)


def print_strategy_section(report):
    for r in report['results']:
        print(f"{r['check']:3} {r['status']:15} {r['target']:28} {r['detail']}")
    print('STRATEGY report-only (excluded from OVERALL and COVERAGE); historical freeze hash not read or recomputed')


def main(argv=None, host=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('mode', choices=['check', 'validate', 'observe', 'strategy'])
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'deploy', 'DEPLOYED.json'))
    ap.add_argument('--deep', action='store_true')
    ap.add_argument('--json', help='write the check report (mode 0600)')
    ap.add_argument('--out', help='observe: write observations to this file (mode 0600) instead of stdout')
    ap.add_argument('--max-age-days', type=int, default=30)
    ap.add_argument('--strategy-identity', action='store_true',
                    help='check: add the report-only strategy identity section (S1/S2)')
    ap.add_argument('--identity-reference', help='strategy section: reference report or identity manifest')
    ap.add_argument('--identity-current', help='strategy section: identity manifest of this checkout')
    a = ap.parse_args(argv)
    if a.mode == 'strategy':
        try:
            report = strategy_report(reference=_load_optional_json(a.identity_reference),
                                     identity_current=_load_optional_json(a.identity_current))
        except (OSError, ValueError) as exc:
            print(f'UNKNOWN strategy identity inputs unreadable: {type(exc).__name__}')
            return EXIT[UNKNOWN]
        print_strategy_section(report)
        if a.json:
            write_private(a.json, report)
        return 0
    host = host or Host()
    try:
        m = json.load(open(a.manifest))
    except (OSError, ValueError) as exc:
        print(f'UNKNOWN manifest unreadable: {type(exc).__name__}')
        return EXIT[UNKNOWN]
    if a.mode == 'validate':
        probs = validate_manifest(m)
        print('valid' if not probs else '\n'.join(probs))
        return 0 if not probs else EXIT[UNKNOWN]
    if a.mode == 'observe':
        obs = {'_notice': METADATA_NOTICE, 'observations': observe(m, host)}
        if a.out:
            write_private(a.out, obs)
            print(f'observations written to {a.out} (mode 0600)')
        else:
            print(json.dumps(obs, indent=1, sort_keys=True))
        return 0
    results = run_checks(m, host, deep=a.deep, max_age_days=a.max_age_days)
    for r in results:
        print(f"{r['check']:3} {r['status']:15} {r['target']:28} {r['detail']}")
    ov = overall(results)
    cov = coverage(results, a.deep)
    scope = {'FULL': 'metadata + image content', 'METADATA_ONLY': 'metadata only (image content NOT verified)',
             'INCOMPLETE': 'INCOMPLETE (some required evidence unavailable)'}[cov['verification']]
    print('COVERAGE ' + ' '.join(f'{k}={v}' for k, v in cov['counts'].items()) + f" verification={cov['verification']}")
    print(f'OVERALL {ov} ({scope}); no remediation performed')
    strategy = None
    if a.strategy_identity:
        try:
            strategy = strategy_report(reference=_load_optional_json(a.identity_reference),
                                       identity_current=_load_optional_json(a.identity_current))
        except (OSError, ValueError) as exc:
            strategy = {'schema': STRATEGY_REPORT_SCHEMA, 'report_only': True, 'families': {}, 'boundary': None,
                        'results': [{'check': 'S1', 'target': 'inputs', 'status': UNKNOWN,
                                     'detail': f'strategy identity inputs unreadable: {type(exc).__name__}'}]}
        print_strategy_section(strategy)
    if a.json:
        report = {'_notice': METADATA_NOTICE, 'overall': ov, 'scope': scope, 'coverage': cov,
                  'manifest_observed_at': m.get('observed_at'), 'checked_at': host.now().isoformat(),
                  'results': results}
        if strategy is not None:
            report['strategy_identity'] = strategy
        write_private(a.json, report)
    return EXIT[ov]


if __name__ == '__main__':
    sys.exit(main())
