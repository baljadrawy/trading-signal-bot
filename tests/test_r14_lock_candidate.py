import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "ops/provenance"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("lock_candidate", ROOT / "lock_candidate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report(*entries):
    return {"version": "1", "install": [
        {"metadata": {"name": name, "version": version},
         "download_info": {"url": f"https://example.org/{name}-{version}-py3-none-any.whl"}}
        for name, version in entries]}


def test_candidate_contains_transitives():
    assert module.convert("aiohttp==3.14.3\n", report(("aiohttp", "3.14.3"), ("yarl", "1.24.5"))) == "aiohttp==3.14.3\nyarl==1.24.5\n"


def test_direct_mismatch_fails():
    import pytest
    with pytest.raises(ValueError, match="mismatch"):
        module.convert("aiohttp==3.13.5", report(("aiohttp", "3.14.3")))


def test_missing_direct_fails():
    import pytest
    with pytest.raises(ValueError, match="missing direct"):
        module.convert("aiohttp==3.14.3", report(("yarl", "1.24.5")))


def test_reject_source_distribution():
    import pytest
    data = report(("aiohttp", "3.14.3"))
    data["install"][0]["download_info"]["url"] = "https://example.org/aiohttp.tar.gz"
    with pytest.raises(ValueError, match="non-wheel"):
        module.convert("aiohttp==3.14.3", data)


def test_reject_non_https():
    import pytest
    data = report(("aiohttp", "3.14.3"))
    data["install"][0]["download_info"]["url"] = "http://example.org/aiohttp.whl"
    with pytest.raises(ValueError, match="non-HTTPS"):
        module.convert("aiohttp==3.14.3", data)


def test_reject_duplicate():
    import pytest
    with pytest.raises(ValueError, match="duplicate"):
        module.convert("aiohttp==3.14.3", report(("aiohttp", "3.14.3"), ("AIOHTTP", "3.14.3")))


def test_reject_empty():
    import pytest
    with pytest.raises(ValueError, match="empty"):
        module.convert("aiohttp==3.14.3", {"version": "1", "install": []})
