"""Bounded, disabled-by-default JSONL storage for S3 shadow records (s3-shadow-store-v1).

Experimental; no production module imports it. Limits are hard: per-record size, per-file
size, file count and total bytes. Files are 0600 in a 0700 directory. Any OSError (disk full,
permission denied, read-only FS) returns a status instead of raising; after
``max_consecutive_failures`` the store degrades to disabled for the rest of the process.
Logging is rate-limited. Records carry only selector inputs/outputs (no secrets, no outcomes).
"""
from __future__ import annotations

import errno
import json
import os
from dataclasses import dataclass

STORE_VERSION = "s3-shadow-store-v1"
_PREFIX, _SUFFIX = "shadow-", ".jsonl"


@dataclass(frozen=True)
class StoreConfig:
    enabled: bool = False
    directory: str | None = None
    max_record_bytes: int = 256 * 1024
    max_file_bytes: int = 4 * 1024 * 1024
    max_files: int = 16
    max_total_bytes: int = 32 * 1024 * 1024
    max_consecutive_failures: int = 3
    log_every: int = 100

    def validate(self) -> list[str]:
        e = []
        if self.enabled and not self.directory:
            e.append("directory_required")
        if not 0 < self.max_record_bytes <= self.max_file_bytes <= self.max_total_bytes:
            e.append("size_limits_inconsistent")
        if self.max_files < 2 or self.max_consecutive_failures < 1 or self.log_every < 1:
            e.append("count_limits_out_of_range")
        return e


class ShadowStore:
    def __init__(self, config: StoreConfig = StoreConfig(), *, logger=None):
        errors = config.validate()
        if errors:
            raise ValueError("invalid_store_config:" + ",".join(errors))
        self.config, self.logger = config, logger
        self.failures = 0
        self.degraded = False
        self.counts = {"written": 0, "disabled": 0, "too_large": 0, "error": 0, "degraded": 0}
        self._logged = 0

    def _log(self, msg):
        self._logged += 1
        if self.logger is not None and (self._logged == 1 or self._logged % self.config.log_every == 0):
            self.logger.warning(f"s3-shadow-store: {msg} (event {self._logged})")

    def _files(self):
        d = self.config.directory
        names = sorted(n for n in os.listdir(d) if n.startswith(_PREFIX) and n.endswith(_SUFFIX))
        return [os.path.join(d, n) for n in names]

    def _encode(self, record) -> bytes | None:
        line = json.dumps({"store_version": STORE_VERSION, **record}, sort_keys=True, default=str)
        if len(line.encode()) > self.config.max_record_bytes and record.get("candidates"):
            line = json.dumps({"store_version": STORE_VERSION, **record, "candidates": None,
                               "candidates_truncated": True}, sort_keys=True, default=str)
        data = (line + "\n").encode()
        return data if len(data) <= self.config.max_record_bytes else None

    def append(self, record: dict) -> str:
        if not self.config.enabled:
            self.counts["disabled"] += 1
            return "disabled"
        if self.degraded:
            self.counts["degraded"] += 1
            return "degraded"
        data = self._encode(record)
        if data is None:
            self.counts["too_large"] += 1
            self._log("record over max_record_bytes dropped")
            return "too_large"
        try:
            d = self.config.directory
            os.makedirs(d, mode=0o700, exist_ok=True)
            os.chmod(d, 0o700)
            files = self._files()
            current = files[-1] if files else None
            if current is None or os.path.getsize(current) + len(data) > self.config.max_file_bytes:
                seq = int(os.path.basename(current)[len(_PREFIX):-len(_SUFFIX)]) + 1 if current else 1
                current = os.path.join(d, f"{_PREFIX}{seq:08d}{_SUFFIX}")
            fd = os.open(current, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                if os.write(fd, data) != len(data):
                    raise OSError(errno.EIO, "short write")
            finally:
                os.close(fd)
            self._retain(current)
        except OSError as exc:
            self.failures += 1
            self.counts["error"] += 1
            code = errno.errorcode.get(exc.errno, "OSError") if exc.errno else "OSError"
            if self.failures >= self.config.max_consecutive_failures:
                self.degraded = True
                self._log(f"degraded to disabled after {self.failures} failures ({code})")
            else:
                self._log(f"write failed ({code})")
            return f"error:{code}"
        self.failures = 0
        self.counts["written"] += 1
        return "written"

    def _retain(self, current):
        files = self._files()
        sizes = {f: os.path.getsize(f) for f in files}
        while len(files) > self.config.max_files or sum(sizes[f] for f in files) > self.config.max_total_bytes:
            oldest = files[0]
            if oldest == current:
                break
            os.remove(oldest)
            files.pop(0)
