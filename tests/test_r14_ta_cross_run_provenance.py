from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/r14-ta-cross-run-provenance.yml"


def test_manual_only_and_read_only():
    s = WORKFLOW.read_text()
    assert "workflow_dispatch:" in s
    assert "pull_request:" not in s
    assert "push:" not in s
    assert "contents: read" in s
    assert "persist-credentials: false" in s


def test_two_independent_build_jobs_and_fail_closed_comparison():
    s = WORKFLOW.read_text()
    assert "attempt: [a, b]" in s
    assert "needs: build" in s
    assert "SOURCE_DATE_EPOCH: '1704067200'" in s
    assert 'pins.get("ta") == "0.11.0"' in s
    assert 'assert result["source_match"]' in s
    assert 'assert result["wheel_match"]' in s
    assert "if: always()" in s


def test_no_production_or_unearned_certification():
    s = WORKFLOW.read_text()
    assert '"certification": "NONE' in s
    assert "docker " not in s
    assert "git push" not in s
