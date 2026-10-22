"""Static inventory of every code path by which a service image could change the Paper halt / pause state.

Run inside an image (read-only, --network none): prints JSON. Two images whose inventories are identical cannot
differ in how they write the halt inputs. Pure source scan: no database, no network, no import of application code.

Halt inputs (shared/risk_epoch.py, shared/trading_state.py): trade_results, risk_recovery_events, risk_management,
active_trades. Recorded per file: write statements on those tables (normalised SQL text), imports of the halt/pause
modules, and the sha256 of each file that contains any of them.
"""
import hashlib
import json
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/app"
TABLES = ("trade_results", "risk_recovery_events", "risk_management", "active_trades")
WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|DROP\s+TABLE)\s+(" + "|".join(TABLES) + r")\b",
                   re.I)
STRINGS = re.compile(r'("""|\'\'\'|"|\')(.*?)(\1)', re.S)
IMPORT = re.compile(r"^\s*(from\s+shared(\.|\s+import\s+)\s*(risk_epoch|trading_state)|import\s+shared\.(risk_epoch|trading_state))",
                    re.M)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


inv = {}
for dp, dn, fn in os.walk(ROOT):
    dn[:] = sorted(d for d in dn if d not in ("__pycache__", "tests", ".git"))
    for f in sorted(fn):
        if not f.endswith(".py"):
            continue
        p = os.path.join(dp, f)
        try:
            src = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        writes = sorted({norm(m.group(2)) for m in STRINGS.finditer(src) if WRITE.search(m.group(2))})
        imports = sorted({norm(m.group(0)) for m in IMPORT.finditer(src)})
        if writes or imports:
            inv[os.path.relpath(p, ROOT)] = {"writes": writes, "imports": imports,
                                             "sha256": hashlib.sha256(src.encode()).hexdigest()}
print(json.dumps(inv, sort_keys=True))
