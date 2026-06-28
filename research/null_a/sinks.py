"""Pluggable evidence sinks. The serialization format is NOT buried inside the recorder.

    class EvidenceSink(Protocol): def write(self, batch: list[dict]) -> None: ...

PR #3c ships JsonlSink (append-only local files, no DB). ParquetSink/NullSink/ListSink
are provided so the format can be swapped without touching the recorder or the hook.
"""
import json
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class EvidenceSink(Protocol):
    def write(self, batch: list) -> None: ...


class NullSink:
    """Drops everything (for benchmarking the recorder with zero sink cost)."""
    def write(self, batch: list) -> None:
        return None


class ListSink:
    """Collects records in memory (tests / debugging)."""
    def __init__(self):
        self.records = []

    def write(self, batch: list) -> None:
        self.records.extend(batch)


class JsonlSink:
    """Append-only JSON Lines, one file per UTC day under `directory`. No DB, no I/O on
    the signal hot path (only the async flusher calls write)."""
    def __init__(self, directory: str):
        # absolute at boot so writes can't land in an unintended cwd; no I/O here
        # (mkdir is deferred to write(), which runs only in the async flusher).
        self.directory = os.path.abspath(directory)

    def _path_for(self, rec: dict) -> str:
        import datetime
        ts = rec.get("timestamp")
        day = (datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
               if isinstance(ts, (int, float)) else "undated")
        return os.path.join(self.directory, f"evidence-{day}.jsonl")

    def write(self, batch: list) -> None:
        os.makedirs(self.directory, exist_ok=True)   # idempotent; runs in the async flusher only
        by_file = {}
        for rec in batch:
            by_file.setdefault(self._path_for(rec), []).append(rec)
        for path, recs in by_file.items():
            with open(path, "a") as f:
                for rec in recs:
                    f.write(json.dumps(rec, default=str) + "\n")


class ParquetSink:
    """Columnar sink (cold tier). Requires pandas+pyarrow; imported lazily so this module
    loads without them. Not used in PR #3c (JsonlSink is the first implementation)."""
    def __init__(self, path: str):
        self.path = path
        self._buffer = []

    def write(self, batch: list) -> None:
        import pandas as pd
        self._buffer.extend(batch)
        df = pd.DataFrame(self._buffer)
        df.to_parquet(self.path)
