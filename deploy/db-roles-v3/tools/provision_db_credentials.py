#!/usr/bin/env python3
"""Create per-service DB credential files and the SQL that sets the matching role passwords.

  provision_db_credentials.py --out-dir DIR [--rotate] [--roles scanner,analyzer,...] \
      | docker exec -i postgres psql -X -q -v ON_ERROR_STOP=1 -U trading_signal_bot -d trading_signals

* DIR/<service>.env (mode 600) gets POSTGRES_USER=<role> and POSTGRES_PASSWORD=<random>. An existing
  file is reused unless --rotate is given, so re-running is idempotent.
* stdout gets ALTER ROLE ... PASSWORD '<SCRAM-SHA-256 verifier>' in one transaction. The plaintext
  never reaches the server, its logs or the terminal; stdout must be a pipe.
* Nothing secret is printed: stderr only names the files written.
Standard library only.
"""
import argparse
import base64
import hashlib
import hmac
import os
import re
import secrets
import sys

SERVICE_ROLES = {'scanner': 'tsb_scanner', 'analyzer': 'tsb_analyzer', 'learner': 'tsb_learner',
                 'backup': 'tsb_backup', 'migrator': 'tsb_migrator', 'dashboard': 'tsb_dashboard_ro',
                 'signal_engine': 'tsb_signal_engine',
                 'telegram': 'tsb_telegram', 'trade_tracker': 'tsb_tracker',
                 'research': 'tsb_research_ro'}
ITERATIONS = 4096                                  # PostgreSQL 16 default scram_iterations


def scram_verifier(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    client_key = hmac.new(salted, b'Client Key', hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b'Server Key', hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode('ascii')   # noqa: E731
    return f'SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}'


def read_env(path: str) -> dict:
    out = {}
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.rstrip('\n').split('=', 1)
                out[k.strip()] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--roles', default='scanner,analyzer,signal_engine,telegram,trade_tracker')
    ap.add_argument('--rotate', action='store_true')
    args = ap.parse_args()
    if sys.stdout.isatty():
        sys.exit('refusing to print password verifiers to a terminal: pipe stdout into psql')
    services = [s.strip() for s in args.roles.split(',') if s.strip()]
    unknown = [s for s in services if s not in SERVICE_ROLES]
    if unknown:
        sys.exit(f'unknown service(s): {unknown}')
    os.makedirs(args.out_dir, mode=0o700, exist_ok=True)
    os.chmod(args.out_dir, 0o700)
    os.umask(0o077)
    statements = []
    for svc in services:
        role = SERVICE_ROLES[svc]
        assert re.fullmatch(r'tsb_[a-z_]+', role)
        path = os.path.join(args.out_dir, f'{svc}.env')
        env = read_env(path) if os.path.exists(path) and not args.rotate else {}
        if env.get('POSTGRES_USER') != role or not env.get('POSTGRES_PASSWORD'):
            env = {'POSTGRES_USER': role, 'POSTGRES_PASSWORD': secrets.token_urlsafe(32)}
            tmp = path + '.tmp'
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as fh:
                fh.write(f"POSTGRES_USER={env['POSTGRES_USER']}\nPOSTGRES_PASSWORD={env['POSTGRES_PASSWORD']}\n")
            os.replace(tmp, path)
            print(f'wrote {path} (mode 600)', file=sys.stderr)
        else:
            print(f'reused {path}', file=sys.stderr)
        statements.append(f'ALTER ROLE "{role}" PASSWORD \'{scram_verifier(env["POSTGRES_PASSWORD"])}\';')
    sys.stdout.write('BEGIN;\n' + '\n'.join(statements) + '\nCOMMIT;\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
