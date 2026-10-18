import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("lock_review", Path(__file__).resolve().parents[1] / "ops/provenance/lock_review.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_matching_transitive_lock():
    assert module.verify("aiohttp==3.14.3\n", "aiohttp==3.14.3\nyarl==1.24.5\n")[0] == []


def test_missing_direct():
    assert "missing direct distribution aiohttp" in module.verify("aiohttp==3.14.3", "yarl==1.24.5")[0]


def test_version_mismatch():
    assert any("direct version mismatch" in issue for issue in module.verify("aiohttp==3.13.5", "aiohttp==3.14.3")[0])


def test_reject_ranges():
    assert any("non-exact" in issue for issue in module.verify("aiohttp>=3", "aiohttp==3.14.3")[0])


def test_normalized_name():
    assert module.verify("typing_extensions==4.16.0", "typing-extensions==4.16.0")[0] == []


def test_duplicate_rejected():
    assert any("duplicate" in issue for issue in module.verify("aiohttp==3.14.3", "aiohttp==3.14.3\nAIOHTTP==3.14.3")[0]
