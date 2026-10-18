from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/r14-analyzer-isolated-install.yml"


def test_manual_only_read_only():
    text = WORKFLOW.read_text()
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "contents: read" in text
    assert "persist-credentials: false" in text


def test_preserves_pins_and_isolates_install():
    text = WORKFLOW.read_text()
    assert 'pins["ta"] == "0.11.0"' in text
    assert 'pins["aiohttp"] == "3.13.5"' in text
    assert "python -m venv /tmp/r14-analyzer-venv" in text
    assert "--only-binary=:all:" in text
    assert "pip check" in text
    assert "import ta" in text
    assert "import aiohttp" in text


def test_records_evidence_without_deployment():
    text = WORKFLOW.read_text()
    assert "sha256sum evidence/source/*" in text
    assert "sha256sum evidence/wheelhouse/*" in text
    assert "install-report.json" in text
    assert "inventory-comparison.json" in text
    assert "if: always()" in text
    assert "docker " not in text
    assert "git push" not in text
