from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/r14-analyzer-ta-wheel-diagnostic.yml"


def test_diagnostic_is_dispatch_only():
    text = WORKFLOW.read_text()
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text


def test_diagnostic_does_not_mutate_runtime_or_pins():
    text = WORKFLOW.read_text()
    assert "contents: read" in text
    assert "persist-credentials: false" in text
    assert "assert pins.get(\"ta\") == \"0.11.0\"" in text
    assert "pip wheel --no-deps" in text
    assert "--dry-run --ignore-installed --only-binary=:all:" in text
    assert "docker " not in text
    assert "git push" not in text


def test_diagnostic_records_hashes_and_failure_evidence():
    text = WORKFLOW.read_text()
    assert "sha256sum evidence/source/*" in text
    assert "sha256sum evidence/wheelhouse/*" in text
    assert "if: always()" in text
    assert "retention-days: 14" in text
