"""Candidate-query selection policy of the signal engine (WP-B05; R1.b, R1.d, R1.f; OF F6).

``SELECTION_POLICY`` (environment) decides which fresh ``analysis_results`` rows
``signal_engine/main.py`` hands to the selector each cycle:

* ``legacy`` (default): the existing query, unchanged byte for byte. It sorts by symbol, then by
  ``total_score``, and keeps the first ``SELECTION_LIMIT`` rows, so the cut falls on the
  alphabetical tail (R1, OF-03). Nothing in this module runs on that path; the query literal
  stays in ``signal_engine/main.py``.
* ``rank_then_limit_v1``: read every fresh row with the same WHERE clause, rank all of them by a
  declared score, break ties by a hash of the declared selection version and the candidate
  identity, and keep the first ``limit`` rows. The limit is the caller's ``SELECTION_LIMIT``,
  unchanged. Every row beyond it is reported with its rank, so no row leaves silently.

The ranking score is an owner decision (OF-OD-14, OQ-09; ``total_score`` is data-mined). So
``rank_then_limit_v1`` refuses to start unless both of these are declared, and nothing here
defaults or chooses either:

* ``SELECTION_VERSION``: the selection version label. It enters every tie-break key and record;
* ``SELECTION_SCORE_KEY``: ``<analysis_data field>:<higher_first|lower_first>``.

A row whose score is missing or not finite is ranked after every scored row, in tie-break order,
and is flagged. With at most ``limit`` fresh rows, both policies therefore hand the selector
the same set of rows.

Activating a non-legacy policy on Paper is a declared selection boundary (R1.c, WP-G01). It also
needs the selection version inside the strategy identity (R5.d). Today it is not there: these
settings are read from the environment, because a new ``Config`` field would move
``config_hash`` for every legacy process too.

Reuse (R1.d): the tie-break basis is the A43 rule of ``shared/candidate_selection.py``
(``_tie_hash``: the pit ``candidate_id``, else ``symbol|timeframe|trade_type``), with the
declared version in place of the A43 constant. Tests hold the two equal. The A43 and S3
selection modules themselves are not imported, because the isolation-contract tests forbid any
production importer of them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SELECTION_POLICY_ENV = "SELECTION_POLICY"
SELECTION_VERSION_ENV = "SELECTION_VERSION"
SELECTION_SCORE_KEY_ENV = "SELECTION_SCORE_KEY"

LEGACY = "legacy"
RANK_THEN_LIMIT_V1 = "rank_then_limit_v1"
SELECTION_POLICIES = (LEGACY, RANK_THEN_LIMIT_V1)
SCORE_DIRECTIONS = ("higher_first", "lower_first")          # = shared.funnel_records.SCORE_DIRECTIONS

_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class SelectionPolicy:
    name: str
    selection_version: str | None = None
    score_field: str | None = None
    score_direction: str | None = None

    @property
    def is_legacy(self) -> bool:
        return self.name == LEGACY

    @property
    def score_key(self) -> str | None:
        return None if self.is_legacy else f"{self.score_field}:{self.score_direction}"

    def as_dict(self) -> dict:
        return {"policy": self.name, "selection_version": self.selection_version,
                "score_key": self.score_key}


def selection_policy_from_env(environ: Mapping[str, str] | None = None) -> SelectionPolicy:
    """Parse the selection settings; an unknown, incomplete or malformed setting refuses to start."""
    env = os.environ if environ is None else environ
    raw = env.get(SELECTION_POLICY_ENV, LEGACY)
    name = str(raw).strip().lower()
    if name not in SELECTION_POLICIES:
        raise RuntimeError(f"unknown {SELECTION_POLICY_ENV} {raw!r}; expected one of {SELECTION_POLICIES}")
    if name == LEGACY:
        return SelectionPolicy(LEGACY)
    version = str(env.get(SELECTION_VERSION_ENV, "")).strip()
    key = str(env.get(SELECTION_SCORE_KEY_ENV, "")).strip()
    if not version or not key:
        raise RuntimeError(f"{SELECTION_POLICY_ENV}={name} needs an owner-declared {SELECTION_VERSION_ENV} "
                           f"and {SELECTION_SCORE_KEY_ENV} (OF-OD-14, OQ-09); none is chosen by default")
    if not _VERSION_RE.match(version):
        raise RuntimeError(f"malformed {SELECTION_VERSION_ENV} {version!r}")
    field, sep, direction = key.partition(":")
    if not sep or not _FIELD_RE.match(field) or direction not in SCORE_DIRECTIONS:
        raise RuntimeError(f"malformed {SELECTION_SCORE_KEY_ENV} {key!r}; expected "
                           f"<field>:<{'|'.join(SCORE_DIRECTIONS)}>")
    return SelectionPolicy(name, version, field, direction)


# ── ranking (pure) ─────────────────────────────────────────────────────────────────────────

def row_data(row: Mapping) -> Mapping:
    """The ``analysis_data`` of a candidate row as a mapping ({} when unreadable). Never mutates."""
    data = row.get("analysis_data") if isinstance(row, Mapping) else None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    return data if isinstance(data, Mapping) else {}


def score_of(data: Mapping, field: str) -> float | None:
    value = data.get(field)
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def tie_break_key(selection_version: str, data: Mapping, symbol: str, timeframe: str) -> str:
    """sha256(version | basis), basis = pit candidate_id, else symbol|timeframe|trade_type (A43)."""
    pit = data.get("pit")
    ident = pit.get("candidate_id") if isinstance(pit, Mapping) else None
    basis = ident or f"{symbol}|{timeframe}|{data.get('trade_type') or None}"
    return hashlib.sha256(f"{selection_version}|{basis}".encode()).hexdigest()


def _content_digest(data: Mapping) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class RankedRow:
    row: Any
    rank: int                      # 1-based over the complete ranked list
    symbol: str
    timeframe: str
    score: float | None
    tie_break_key: str
    data: Mapping

    @property
    def score_missing(self) -> bool:
        return self.score is None


@dataclass(frozen=True)
class RankedSelection:
    policy: SelectionPolicy
    limit: int
    ranked: tuple                  # every input row, in rank order

    @property
    def rows(self) -> list:
        """The rows handed to the selector: ranks 1..limit, in rank order (the input objects)."""
        return [r.row for r in self.ranked[:self.limit]]

    @property
    def cut(self) -> tuple:
        return self.ranked[self.limit:]

    def truncation_info(self) -> dict:
        total = len(self.ranked)
        return {"truncated": total > self.limit, "returned": min(total, self.limit),
                "eligible_total": total, "truncated_count": max(0, total - self.limit),
                "score_missing": sum(1 for r in self.ranked if r.score_missing),
                **self.policy.as_dict()}


def rank_then_limit(rows: Sequence[Mapping], policy: SelectionPolicy, limit: int) -> RankedSelection:
    """Rank every row by the declared score, then cut to ``limit``. Independent of input order,
    of symbol names (except through the hashed tie-break) and of database collation."""
    if policy.is_legacy:
        raise ValueError("legacy selection is the SQL query itself; it never ranks here")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive int")
    keyed = []
    for row in rows:
        data = row_data(row)
        symbol = str(data.get("symbol") or row.get("symbol") or "")
        timeframe = str(data.get("timeframe") or row.get("timeframe") or "")
        score = score_of(data, policy.score_field)
        tie = tie_break_key(policy.selection_version, data, symbol, timeframe)
        signed = 0.0 if score is None else (-score if policy.score_direction == "higher_first" else score)
        keyed.append(((score is None, signed, tie, _content_digest(data)), row, symbol, timeframe, score, tie, data))
    keyed.sort(key=lambda item: item[0])
    ranked = tuple(RankedRow(row, i + 1, symbol, timeframe, score, tie, data)
                   for i, (_, row, symbol, timeframe, score, tie, data) in enumerate(keyed))
    return RankedSelection(policy, limit, ranked)
