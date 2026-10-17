"""Static SQL inventory of the code each container actually runs (import graph from the entry module).
Collects SQL string literals AND f-strings (dynamic SQL, reported separately with their {expressions}).
Usage: sql_inventory.py <deployed-root> <entry.py> [<entry2.py> ...]  -> JSON on stdout."""
import ast, json, os, re, sys

KW = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH')
def entries(root, mains):
    seen, todo = set(), [os.path.join(root, m) for m in mains]
    while todo:
        p = todo.pop()
        if p in seen or not os.path.exists(p): continue
        seen.add(p)
        tree = ast.parse(open(p, encoding='utf-8', errors='replace').read())
        for n in ast.walk(tree):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
            if isinstance(n, ast.ImportFrom) and n.module is None and n.level:           # from . import x
                names = [a.name for a in n.names]
            for m in names:
                for cand in (os.path.join(root, *m.split('.')) + '.py', os.path.join(root, *m.split('.'), '__init__.py')):
                    if os.path.exists(cand): todo.append(cand)
            yield p, n
def is_sql(s):
    s = s.strip(); head = s.split(None, 1)[0].upper() if s else ''
    return head in KW and len(s) > 20
def render(js):
    out = []
    for v in js.values:
        if isinstance(v, ast.Constant): out.append(str(v.value))
        else: out.append('{' + ast.unparse(v.value) + '}')
    return ''.join(out)
def collect(root, mains):
    static, dynamic, calls = [], [], set()
    for p, n in entries(root, mains):
        rel = os.path.relpath(p, root)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and is_sql(n.value):
            static.append({'file': rel, 'line': n.lineno, 'sql': n.value.strip()})
        elif isinstance(n, ast.JoinedStr):
            t = render(n)
            if is_sql(t): dynamic.append({'file': rel, 'line': n.lineno, 'sql': t.strip()})
        elif isinstance(n, ast.Call):                      # called names, to justify 'unused by design' exceptions
            f = n.func
            calls.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', ''))
    # f-string parts are also visited as Constants; drop static fragments that are pieces of an f-string
    dyn_lines = {(d['file'], d['line']) for d in dynamic}
    static = [s for s in static if (s['file'], s['line']) not in dyn_lines]
    return {'root': root, 'entries': mains, 'static': static, 'dynamic': dynamic, 'calls': sorted(calls)}


if __name__ == '__main__':
    d = collect(sys.argv[1], sys.argv[2:]); d['calls'] = len(d['calls'])
    print(json.dumps(d, indent=1))
