"""Atomic file helpers and canonical JSON."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os


def canonical_dumps(obj) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, UTF-8, NaN/Inf forbidden."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Write via same-directory temp file + fsync + rename + dir fsync. Readers see old or new, never partial."""
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, f".{os.path.basename(path)}.tmp-{os.getpid()}")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fsync_dir(d)


def atomic_write_json(path: str, obj, *, pretty: bool = True) -> None:
    data = (json.dumps(obj, sort_keys=True, indent=2, default=str) + "\n").encode() if pretty \
        else canonical_dumps(obj)
    atomic_write_bytes(path, data)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def append_jsonl(path: str, obj) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, sort_keys=True, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
