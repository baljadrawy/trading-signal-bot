#!/usr/bin/env python3
"""Apply ordered SQL migrations through the shared PostgreSQL container."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / 'migrations'


def psql(database: str, sql: str) -> str:
    result = subprocess.run(
        ['docker', 'exec', '-i', 'postgres', 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
         '-U', 'trading_signal_bot', '-d', database, '-At'],
        input=sql, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def apply(database: str) -> None:
    psql(database, """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        checksum CHAR(64) NOT NULL,
        applied_at TIMESTAMP NOT NULL DEFAULT NOW()
    );""")
    rows = psql(database, 'SELECT version || chr(9) || checksum FROM schema_migrations ORDER BY version;')
    applied = {}
    for row in rows.splitlines():
        if row:
            version, checksum = row.split('\t', 1)
            applied[int(version)] = checksum

    for path in sorted(MIGRATIONS.glob('[0-9][0-9][0-9]_*.sql')):
        version = int(path.name.split('_', 1)[0])
        body = path.read_text(encoding='utf-8')
        checksum = hashlib.sha256(body.encode()).hexdigest()
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(f'checksum mismatch for applied migration {path.name}')
            print(f'= {path.name}')
            continue
        record = (
            'INSERT INTO schema_migrations(version,name,checksum) VALUES('
            f'{version},{sql_literal(path.name)},{sql_literal(checksum)});')
        psql(database, f'BEGIN;\n{body}\n{record}\nCOMMIT;')
        print(f'+ {path.name}')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='trading_signals')
    args = parser.parse_args()
    try:
        apply(args.database)
    except Exception as exc:
        print(f'migration failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
