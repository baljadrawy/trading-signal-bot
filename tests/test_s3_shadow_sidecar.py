"""S3 shadow sidecar + bounded JSONL store: disabled defaults, budgets, rotation/retention,
permissions, fault injection (disk full, permission denied), degradation, the read-only sidecar
path, and isolation. Engineering properties only; no outcomes are read anywhere."""
import errno
import json
import logging
import os
import pathlib
import re
import stat
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')

import pytest

from shared.s3_shadow import ShadowConfig
from shared.s3_shadow_store import ShadowStore, StoreConfig
from shared.s3_shadow_sidecar import cycle_record, main
from test_s3_signal_selection import cand

ROOT = pathlib.Path(__file__).resolve().parents[1]


def store(tmp_path, **kw):
    return ShadowStore(StoreConfig(enabled=True, directory=str(tmp_path / "s"), **kw))


def test_disabled_by_default_writes_nothing(tmp_path):
    s = ShadowStore()
    assert s.append({"x": 1}) == "disabled" and not (tmp_path / "s").exists()
    assert main([]) == 2                                            # sidecar refuses without --enable
    assert main(["--enable"]) == 2                                  # and without dsn/dir/bounds


def test_permissions_versioning_and_rotation(tmp_path):
    s = store(tmp_path, max_record_bytes=400, max_file_bytes=1000, max_total_bytes=10_000, max_files=4)
    for i in range(12):
        assert s.append({"i": i, "pad": "x" * 200}) == "written"
    files = sorted((tmp_path / "s").iterdir())
    assert 1 < len(files) <= 4                                       # rotated and retained
    assert stat.S_IMODE((tmp_path / "s").stat().st_mode) == 0o700
    assert all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files)
    assert all(f.stat().st_size <= 1000 for f in files)
    last = [json.loads(l) for l in files[-1].read_text().splitlines()]
    assert last[-1]["i"] == 11 and last[-1]["store_version"] == "s3-shadow-store-v1"


def test_total_disk_budget_is_enforced(tmp_path):
    s = store(tmp_path, max_record_bytes=300, max_file_bytes=600, max_total_bytes=1500, max_files=50)
    for i in range(40):
        s.append({"i": i, "pad": "y" * 200})
    assert sum(f.stat().st_size for f in (tmp_path / "s").iterdir()) <= 1500 + 600


def test_oversized_records_shed_candidates_then_drop(tmp_path):
    s = store(tmp_path, max_record_bytes=500, max_file_bytes=5000, max_total_bytes=50_000)
    assert s.append({"k": 1, "candidates": ["z" * 2000]}) == "written"
    rec = json.loads(next((tmp_path / "s").iterdir()).read_text())
    assert rec["candidates"] is None and rec["candidates_truncated"] is True
    assert s.append({"k": 2, "blob": "z" * 2000}) == "too_large"


@pytest.mark.parametrize("err", [errno.ENOSPC, errno.EACCES, errno.EROFS])
def test_disk_full_and_permission_errors_degrade_without_raising(tmp_path, monkeypatch, caplog, err):
    s = store(tmp_path, max_consecutive_failures=3, log_every=1000)

    def boom(*a, **k):
        raise OSError(err, os.strerror(err))
    monkeypatch.setattr(os, "write", boom)
    s.logger = logging.getLogger("t")
    with caplog.at_level(logging.WARNING):
        out = [s.append({"i": i}) for i in range(6)]
    assert out[:3] == [f"error:{errno.errorcode[err]}"] * 3 and out[3:] == ["degraded"] * 3
    assert s.degraded and len(caplog.records) <= 2                   # rate-limited logging


def test_real_permission_denied_directory(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        s = ShadowStore(StoreConfig(enabled=True, directory=str(ro / "sub"), max_consecutive_failures=1))
        assert s.append({"i": 1}).startswith("error:") and s.append({"i": 2}) == "degraded"
    finally:
        ro.chmod(0o700)


def test_invalid_store_config_is_rejected():
    for kw in ({"enabled": True}, {"max_record_bytes": 0}, {"max_files": 1}):
        with pytest.raises(ValueError):
            ShadowStore(StoreConfig(**kw))


def _rows(*specs, reason=None):
    return [{"symbol": c["symbol"], "timeframe": c["timeframe"], "analysis_data": c,
             "decision_reason": reason} for c in specs]


def test_cycle_record_is_bounded_and_cross_checks_engine_symbols():
    cfg = ShadowConfig(enabled=True, max_candidates=2)
    rows = _rows(cand("AUSDT", risk=2.0), cand("BUSDT", spread=0.05), cand("CUSDT"))
    rec = cycle_record(rows, {"AUSDT": 1e6, "BUSDT": 1e6}, {"AUSDT"}, decision_ms=1, shadow=cfg)
    assert rec["status"] == "OK" and rec["candidate_count"] == 2          # capped
    assert rec["replica"]["pick"] == ["AUSDT", "4h"] and rec["engine_symbol_agrees_with_replica"]
    cool = cycle_record(_rows(cand("AUSDT"), reason="symbol_cooldown"), {"AUSDT": 1e6}, set(),
                        decision_ms=1, shadow=cfg)
    assert cool["classification"] == "AGREE_NO_TRADE" and cool["engine_symbol_agrees_with_replica"]


def test_cycle_record_never_raises_on_bad_rows():
    rec = cycle_record([{"symbol": "X", "timeframe": "4h", "analysis_data": {"order_book": "bad"}}],
                       {}, set(), decision_ms=1, shadow=ShadowConfig(enabled=True))
    assert rec["status"] in ("OK", "ERROR")


def test_sidecar_and_store_are_not_imported_by_production_and_sql_is_read_only():
    from experimental_modules import EXPERIMENTAL_SHARED
    assert "s3_shadow_store" in EXPERIMENTAL_SHARED
    for path in ROOT.glob("*/*.py"):
        if path.parts[-2] in ("tests", "research", "docs", "colab") or (
                path.parent.name == "shared" and path.stem in EXPERIMENTAL_SHARED):
            continue
        assert not re.search(r"\b(s3_shadow_store|s3_shadow_sidecar)\b",
                             path.read_text(encoding="utf-8", errors="ignore")), path
    import shared.s3_shadow_sidecar as sc
    for q in (sc.FRESH_SQL, sc.SELECTED_SQL, sc.VOLUME_SQL):
        assert re.match(r"\s*SELECT\b", q) and not re.search(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|signals|trade_results|evidence)\b", q, re.I)


def test_sidecar_against_a_disposable_database(tmp_path, monkeypatch):
    e2e = pytest.importorskip("test_p1r_cr2_e2e")
    if not e2e.DSN:
        pytest.skip("P1R_TEST_DSN not set (disposable PostgreSQL required)")
    import asyncio
    from shared.s3_shadow_sidecar import run

    async def go():
        async with e2e.Env("after", "off", monkeypatch, tmp_path / "db") as env:
            await env.sql("INSERT INTO analysis_results (symbol, timeframe, analysis_data, analyzed_at, "
                          "signal_generated) VALUES ('AUSDT','4h',$1::jsonb,NOW(),false)", json.dumps(cand("AUSDT")))
            await env.sql("INSERT INTO scan_candidates (symbol, data) VALUES ('AUSDT', $1::jsonb)",
                          json.dumps({"volume_usdt": 2e6}))
            dsn = e2e.DSN.rsplit("/", 1)[0] + "/" + env.db
            st = store(tmp_path)
            res = await run(dsn, st, cycles=1, interval=0, shadow=ShadowConfig(enabled=True))
            return res, st
    res, st = asyncio.run(go())
    assert res == {"cycles": 1, "statuses": {"written": 1}}
    rec = json.loads(next((tmp_path / "s").iterdir()).read_text())
    assert rec["status"] == "OK" and rec["replica"]["pick"] == ["AUSDT", "4h"] and rec["source"] == "sidecar_read_only"
