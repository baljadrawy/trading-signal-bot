from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/r14-ta-wheel-reproducibility.yml"


def test_manual_disposable_only():
    text = WORKFLOW.read_text()
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "contents: read" in text
    assert "persist-credentials: false" in text


def test_same_source_two_builds_and_comparison():
    text = WORKFLOW.read_text()
    assert 'pins.get("ta") == "0.11.0"' in text
    assert "SOURCE_DATE_EPOCH: '1704067200'" in text
    assert "evidence/build-a evidence/source/*" in text
    assert "evidence/build-b evidence/source/*" in text
    assert 'result["byte_identical"]' in text
    assert '"member_content_identical"' in text


def test_failure_artifacts_and_no_deployment():
    text = WORKFLOW.read_text()
    assert "if: always()" in text
    assert "retention-days: 14" in text
    assert "sha256sum evidence/source/*" in text
    assert "docker " not in text
    assert "git push" not in text
