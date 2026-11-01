"""WP2 funnel recorder: an observe-only shadow writer for one cycle — pure; no production caller.

Contract (WP-B01; OF-T01 acceptance (c) "decisions byte-identical with the writer on and off"):

* the flag is explicit: ``FunnelRecorder(enabled=...)`` takes a real ``bool`` and
  ``parse_enabled`` refuses any unknown flag value, so a bad flag stops start-up instead of
  silently changing mode. Construction is the only call that may raise;
* disabled is a strict no-op: no counting, no storage, ``report()`` returns ``None``;
* every observing call returns the very object it received (``out is outputs``). It never
  sorts, filters, copies into, iterates a one-shot iterator of, or otherwise touches the
  candidate list. Only ``len()`` of a sized container is read;
* recording never raises into the caller. Any internal error increments ``failure_count``
  (by exception class) and the cycle report is then marked invalid, never silently clean;
* records are append-only: a second record with the same ``record_id`` is kept out and
  counted in ``duplicate_records``, so a subject is never counted twice.

Not wired anywhere (BLOCKED, see ``shared/funnel_records.py``).
"""
from __future__ import annotations

from collections.abc import Sized
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from shared.funnel_records import (TAXONOMY_VERSION, ConservationResult, RankingInput, RejectionRecord,
                                   StageCount, canonical_json, check_conservation, merge_stage_counts)

REPORT_SCHEMA = "tsb.funnel.cycle_report"
REPORT_SCHEMA_VERSION = 1
_TRUE, _FALSE = ("true", "1", "on", "yes"), ("false", "0", "off", "no")


def parse_enabled(value: Any) -> bool:
    """Strict flag parsing: a bool or one of the listed spellings; anything else refuses."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if isinstance(value, (str, int)) else None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise RuntimeError(f"unknown funnel recorder flag value {value!r}")


@dataclass(frozen=True)
class FunnelCycleReport:
    """Everything the recorder saw in one cycle, in a canonical order (not call order)."""
    cycle_id: str
    stage_counts: tuple
    records: tuple
    ranking_inputs: tuple
    conservation: ConservationResult | None
    failure_count: int
    failure_kinds: tuple
    duplicate_records: int

    @property
    def valid(self) -> bool:
        """Evidence-valid only if conservation holds and the recorder itself never failed."""
        return self.conservation is not None and self.conservation.ok and self.failure_count == 0

    def as_dict(self) -> dict:
        return {"schema": REPORT_SCHEMA, "schema_version": REPORT_SCHEMA_VERSION,
                "taxonomy_version": TAXONOMY_VERSION, "cycle_id": self.cycle_id,
                "stage_counts": [c.as_dict() for c in self.stage_counts],
                "records": [r.as_dict() for r in self.records],
                "ranking_inputs": [x.as_dict() for x in self.ranking_inputs],
                "conservation": self.conservation.as_dict() if self.conservation is not None else None,
                "failure_count": self.failure_count,
                "failure_kinds": [list(x) for x in self.failure_kinds],
                "duplicate_records": self.duplicate_records, "valid": self.valid}

    def to_json(self) -> str:
        return canonical_json(self.as_dict())


class FunnelRecorder:
    """Shadow recorder for one cycle. Observes; never decides."""

    def __init__(self, *, enabled: bool, cycle_id: str):
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool; use parse_enabled for flag text")
        if not isinstance(cycle_id, str) or not cycle_id:
            raise ValueError("cycle_id_required")
        self._enabled = enabled
        self._cycle_id = cycle_id
        self._counts: list = []
        self._records: dict = {}
        self._ranking: list = []
        self._failures: dict = {}
        self._duplicates = 0

    # ── state ──
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def cycle_id(self) -> str:
        return self._cycle_id

    @property
    def failure_count(self) -> int:
        return sum(self._failures.values())

    @property
    def failure_kinds(self) -> dict:
        return dict(self._failures)

    def _fail(self, kind: str) -> None:
        try:
            self._failures[kind] = self._failures.get(kind, 0) + 1
        except Exception:                                  # pragma: no cover - last resort
            pass

    def _add_record(self, record: Any) -> None:
        if not isinstance(record, RejectionRecord):
            self._fail("not_a_rejection_record")
            return
        if record.cycle_id != self._cycle_id:
            self._fail("cycle_mismatch")
            return
        if record.record_id in self._records:
            self._duplicates += 1
            return
        self._records[record.record_id] = record

    # ── observing calls: each returns exactly what it was given ──
    def observe_stage(self, stage: str, inputs: Any, outputs: Any, rejections: Sequence = (), *,
                      held: int = 0, expanded_from: int | None = None) -> Any:
        """Count one stage pass: ``len(inputs)`` in, ``len(outputs)`` passed, and its records.
        Returns ``outputs`` itself. Unsized inputs or outputs are not consumed: the call is
        counted as a failure instead."""
        if not self._enabled:
            return outputs
        try:
            if not isinstance(inputs, Sized) or not isinstance(outputs, Sized):
                self._fail("unsized_stage_io")
                return outputs
            self._counts.append(StageCount(stage, len(inputs), len(outputs), held, expanded_from))
            self.record_many(rejections)
        except Exception as exc:
            self._fail(type(exc).__name__)
        return outputs

    def observe_counts(self, stage: str, *, n_in: int, passed: int, held: int = 0,
                       expanded_from: int | None = None) -> None:
        """Count a stage from integers, for callers that hold no list (for example SQL counts)."""
        if not self._enabled:
            return None
        try:
            self._counts.append(StageCount(stage, n_in, passed, held, expanded_from))
        except Exception as exc:
            self._fail(type(exc).__name__)
        return None

    def record(self, record: Any) -> Any:
        """Append one RejectionRecord; returns it unchanged."""
        if not self._enabled:
            return record
        try:
            self._add_record(record)
        except Exception as exc:
            self._fail(type(exc).__name__)
        return record

    def record_many(self, records: Sequence) -> Sequence:
        if not self._enabled:
            return records
        try:
            if not isinstance(records, (list, tuple)):
                self._fail("records_not_list")
                return records
            for r in records:
                self._add_record(r)
        except Exception as exc:
            self._fail(type(exc).__name__)
        return records

    def capture_ranking(self, ranking_inputs: Sequence) -> Sequence:
        """Store what a ranker was given (frozen RankingInput values); returns the same object."""
        if not self._enabled:
            return ranking_inputs
        try:
            if not isinstance(ranking_inputs, (list, tuple)):
                self._fail("ranking_inputs_not_list")
                return ranking_inputs
            for item in ranking_inputs:
                if isinstance(item, RankingInput):
                    self._ranking.append(item)
                else:
                    self._fail("not_a_ranking_input")
        except Exception as exc:
            self._fail(type(exc).__name__)
        return ranking_inputs

    # ── report ──
    def report(self, *, chain: Sequence[str] = ()) -> FunnelCycleReport | None:
        """The cycle report (``None`` when disabled). Order is canonical, not call order."""
        if not self._enabled:
            return None
        conservation = None
        try:
            conservation = check_conservation(self._counts, self._records.values(), chain=tuple(chain))
        except Exception as exc:
            self._fail(type(exc).__name__)
        try:
            counts = tuple(c for _, c in sorted(merge_stage_counts(self._counts).items()))
        except Exception as exc:
            self._fail(type(exc).__name__)
            counts = ()
        records = tuple(sorted(self._records.values(), key=lambda r: (r.stage, r.record_id)))
        ranking = tuple(sorted(self._ranking, key=lambda x: (x.input_position, x.tie_break_key,
                                                             x.selection_version)))
        return FunnelCycleReport(self._cycle_id, counts, records, ranking, conservation,
                                 self.failure_count, tuple(sorted(self._failures.items())),
                                 self._duplicates)


def instrumented(recorder: FunnelRecorder | None, stage: str, inputs: Any, outputs: Any,
                 rejections: Iterable = ()) -> Any:
    """Convenience pass-through for call sites: ``return instrumented(rec, "F5", xs, ys, recs)``.
    With no recorder it is the identity on ``outputs``."""
    if recorder is None:
        return outputs
    return recorder.observe_stage(stage, inputs, outputs, rejections)
