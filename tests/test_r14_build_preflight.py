import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("preflight", Path(__file__).resolve().parents[1] / "ops/provenance/build_preflight.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)
SHA = "a" * 40
DIGEST = "b" * 64


def fixture(tmp_path, docker=None, lock="alpha==1.0\nbeta==2.0\n"):
    p = tmp_path / "scanner"
    p.mkdir()
    (p / "Dockerfile").write_text(docker or f"FROM python@sha256:{DIGEST}\nARG BUILD_REVISION\nLABEL org.opencontainers.image.revision=$BUILD_REVISION\n")
    if lock is not None:
        (p / "requirements.lock").write_text(lock)
    return tmp_path


def test_clean_synthetic(tmp_path):
    assert mod.check(fixture(tmp_path), "scanner", SHA) == []


def test_missing_lock(tmp_path):
    assert "missing committed requirements.lock" in mod.check(fixture(tmp_path, lock=None), "scanner", SHA)


def test_mutable_base(tmp_path):
    root = fixture(tmp_path, docker="FROM python:3.12-slim\nARG BUILD_REVISION\nLABEL org.opencontainers.image.revision=$BUILD_REVISION\n")
    assert any("immutable" in i for i in mod.check(root, "scanner", SHA))


def test_unknown_revision(tmp_path):
    assert any("revision" in i for i in mod.check(fixture(tmp_path), "scanner", "unknown"))


def test_loose_lock(tmp_path):
    assert any("non-exact" in i for i in mod.check(fixture(tmp_path, lock="alpha>=1\n"), "scanner", SHA))


def test_duplicate_conflict(tmp_path):
    assert any("conflicting" in i for i in mod.check(fixture(tmp_path, lock="Alpha==1\nalpha==2\n"), "scanner", SHA))


def test_missing_label(tmp_path):
    root = fixture(tmp_path, docker=f"FROM python@sha256:{DIGEST}\nARG BUILD_REVISION\n")
    assert "missing OCI revision label" in mod.check(root, "scanner", SHA)


def test_unknown_service(tmp_path):
    assert mod.check(tmp_path, "postgres", SHA) == ["unknown service"]
