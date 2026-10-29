"""Provenance guards for the sealed-safe monitoring signals (docs/ops/SEALED_SAFE_MONITORING.md).

`ops/compose-safe health` reports Docker health status. That status is sealed-safe only while each healthcheck reads
liveness data and nothing from the sealed FORWARD_HOLDOUT (OD-7). These tests fail if a healthcheck starts reading
anything else, so the monitoring design is reviewed again before such a change ships.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER_SERVICES = ("scanner", "analyzer", "signal_engine", "trade_tracker", "telegram")


def _function_strings(path, name):
    tree = ast.parse(path.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == name)
    return [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_paper_healthcheck_query_reads_only_heartbeat_liveness_columns():
    sql = [s for s in _function_strings(ROOT / "shared" / "health.py", "check") if "SELECT" in s.upper()]
    assert len(sql) == 1
    query = " ".join(sql[0].split()).lower()
    assert re.findall(r"\bfrom\s+(\w+)", query) == ["service_heartbeats"]
    assert " join " not in query
    selected = query.split("select", 1)[1].rsplit(" from service_heartbeats", 1)[0]
    assert set(re.findall(r"[a-z_]+", selected)) == {"last_success_at", "consecutive_errors", "extract",
                                                     "epoch", "from", "now", "as", "age_seconds"}
    for column in ("metadata", "last_error"):
        assert column not in selected


def _service_blocks(text):
    blocks, name = {}, None
    for line in text.splitlines():
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            name = m.group(1)
            blocks[name] = []
        elif name and (line.startswith("    ") or not line.strip()):
            blocks[name].append(line)
        elif not line.startswith(" "):
            name = None
    return {k: "\n".join(v) for k, v in blocks.items()}


def test_paper_services_use_the_shared_heartbeat_healthcheck():
    blocks = _service_blocks((ROOT / "docker-compose.yml").read_text())
    for svc in PAPER_SERVICES:
        block = blocks[svc]
        assert 'test: ["CMD", "python", "-m", "shared.health"]' in block, svc
        assert re.search(rf"^\s+SERVICE_NAME: {svc}\s*$", block, re.M), svc


def test_collector_healthcheck_reads_only_health_file_age_and_state():
    dockerfile = (ROOT / "p2_forward" / "Dockerfile").read_text()
    cmd = dockerfile.split("HEALTHCHECK", 1)[1].split("ENTRYPOINT", 1)[0]
    assert re.findall(r"open\('([^']+)'\)", cmd) == ["/data/health/collector_health.json"]
    assert set(re.findall(r"h\['([a-z_]+)'\]", cmd)) == {"ts_ms", "state"}
