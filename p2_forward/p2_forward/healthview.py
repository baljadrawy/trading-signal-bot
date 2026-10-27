"""Optional views of the LIVE health file (development candidate after collector 1.6.1). Everything here is OFF by
default; with both flags off the collector never calls into this module and its health output is byte-identical.

Why: `state` turns DEGRADED as soon as any one of ~271 streams is stale or has a short gap. Almost all such samples
are a single quiet Tier-1/Tier-2 depth/book stream (gap cause `stale_stream`), not a collector defect, but every
consumer of `state` (Docker healthcheck, research-runner admission, monitor) treats them like one.

Two independent, opt-in views. Neither touches raw records, gap records, gap accounting, sealing or the verifiers:
the `health` raw records always keep the unfiltered `health_eval()` result.

* `health_state_split`: adds `integrity_state` and `coverage_state` next to the unchanged `state`.
  - integrity = writer / certifier / disk / write errors / quarantine / emit / sequence resets / queue drops /
    incidents of severity DEGRADED or CRITICAL (DEGRADED); duplicate obs_ids dropped by the writer (WARNING).
  - coverage = stream freshness, gaps, acknowledgements, connection data-liveness.
  - Anything else (tasks, clock, ban, handler exceptions, universe refresh) is operational: it keeps `state` DEGRADED
    but is neither integrity nor coverage. A reason this module does not know counts as integrity (fail closed).
* `health_coverage_tiering`: in the live file only, `state` may be HEALTHY with the WARNING `coverage:streams_stale:<n>`
  when the ONLY hard reasons are `stale:` / `gap_short:` / `gap_open:` (cause `stale_stream`) on fewer than K Tier-1/2
  book or depth streams, each affected for less than T seconds. Everything else stays DEGRADED at once: Tier-0, the
  market stream, any other gap cause, any gap or staleness at T or longer, a connection not data-live, a stream not
  ready / failed / awaiting post-reconnect data, and every integrity or operational reason. A stream leaves the
  episode only after CLEAR_EVALS consecutive clean evaluations (until then it keeps counting toward K and keeps its
  age); a stream that was not tolerable in its episode stays DEGRADED (`coverage_clearing:<stream>`) until then.
  The unfiltered state is kept in the file as `coverage_policy.raw_state`.
"""
from __future__ import annotations

CLEAR_EVALS = 2
TOLERATED_CAUSES = frozenset({"stale_stream"})
TOLERATED_TIERS = (1, 2)
TOLERATED_KINDS = ("book", "depth")
EVALUATED = ("HEALTHY", "DEGRADED", "STARTING")          # other states (stop, disk, ban, not started) pass through

INTEGRITY_EXACT = frozenset({
    "writer_dead", "writer_stale", "writer_not_durable", "certifier_dead", "certifier_not_ready", "certifier_stale",
    "certifier_scan_error", "certifier_backlog", "certification_failed", "certifier_restarted_10min", "write_errors",
    "writer_rejected_records", "disk_hard_stop", "seq_reset", "segments_quarantined", "emit_failed", "queue_drops"})
INTEGRITY_PREFIX = ("incident:",)                         # only DEGRADED / CRITICAL incidents are hard reasons
COVERAGE_EXACT = frozenset({"expected_ne_observing"})
COVERAGE_PREFIX = ("stale:", "gap_open:", "gap_short:", "conn_not_data_live:", "awaiting_post_reconnect:",
                   "not_ready:", "stream_failed:", "not_acked:", "coverage_clearing:")
OPERATIONAL_EXACT = frozenset({"banned_418", "clock_unknown", "clock_stale", "handler_exceptions_10min",
                               "task_failed_10min", "wall_clock_step_10min", "universe_refresh_failed", "not_started"})
OPERATIONAL_PREFIX = ("task_no_beat:", "task_stale:", "clock_")


def evaluated(state: str, startup: list) -> bool:
    """health_eval() ran its checks (not a stop / failure state, not the pre-WebSocket STARTING placeholder)."""
    return state in EVALUATED and "not_started" not in startup


def classify(reason: str) -> str:
    """'integrity' | 'coverage' | 'operational'. Unknown reasons are 'integrity' (never tolerated, never hidden)."""
    if reason in INTEGRITY_EXACT or reason.startswith(INTEGRITY_PREFIX):
        return "integrity"
    if reason in COVERAGE_EXACT or reason.startswith(COVERAGE_PREFIX):
        return "coverage"
    if reason in OPERATIONAL_EXACT or reason.startswith(OPERATIONAL_PREFIX):
        return "operational"
    return "integrity"


def split_states(hard: list, startup: list, duplicates_dropped: int = 0) -> tuple:
    """(integrity_state, coverage_state) for an evaluated health result. Values: OK, WARNING, STARTING, DEGRADED."""
    def level(cls):
        if any(classify(r) == cls for r in hard):
            return "DEGRADED"
        if any(classify(r) == cls for r in startup):
            return "STARTING"
        return "OK"
    integ = level("integrity")
    if integ == "OK" and duplicates_dropped:
        integ = "WARNING"
    return integ, level("coverage")


def _stream_reason(reason: str):
    """(stream, cause) for a tolerable-shaped reason (`stale:<s>`, `gap_short:<s>:<cause>`, `gap_open:<s>:<cause>`),
    else None. `stale:` carries no cause; it is accompanied by its stale_stream gap once a boundary passes."""
    if reason.startswith("stale:"):
        return reason[len("stale:"):], None
    for p in ("gap_short:", "gap_open:"):
        if reason.startswith(p):
            name, sep, cause = reason[len(p):].rpartition(":")
            return (name, cause) if sep and name else None
    return None


class CoveragePolicy:
    """Tiered coverage severity with clearing hysteresis. State is per stream: since_ms (episode start, kept until
    CLEAR_EVALS consecutive clean evaluations), clean (consecutive clean evaluations) and level (DEGRADED once the
    stream was not tolerable during the episode)."""

    def __init__(self, max_streams: int, max_age_s: int):
        if not (isinstance(max_streams, int) and max_streams >= 2 and isinstance(max_age_s, int) and max_age_s > 0):
            raise ValueError("max_streams must be >= 2 and max_age_s > 0")
        self.k, self.t_ms = max_streams, 1000 * max_age_s
        self.streams = {}

    def _age_ms(self, ent: dict, info, m: int) -> int:
        """Longest of: time in this episode, open-gap extent, time since the value went stale (conservative)."""
        age = m - ent["since_ms"]
        if info is not None:
            if info.get("gap_first_ms") is not None:
                age = max(age, m - info["gap_first_ms"])
            last, stale = info.get("last_ms"), info.get("stale_ms")
            if last is not None and stale is not None and m - last > stale:
                age = max(age, m - last - stale)
        return age

    def apply(self, state: str, hard: list, startup: list, warn: list, m: int, stream_info) -> dict:
        """stream_info(name) -> {tier, kind, gap_first_ms, last_ms, stale_ms} or None (unknown stream: not tolerable).
        Returns {state, reasons, warnings, coverage_state, detail}; the inputs are never mutated."""
        if not evaluated(state, startup):
            return {"state": state, "reasons": list(hard), "warnings": list(warn), "coverage_state": None,
                    "detail": {"raw_state": state, "tolerated": False, "evaluated": False}}
        per, blocking = {}, False
        for r in hard:
            if classify(r) != "coverage":
                blocking = True                                  # integrity / operational: DEGRADED immediately
                continue
            sr = _stream_reason(r)
            if sr is None:
                blocking = True                                  # conn not data-live, not ready, failed, unacked, ...
                continue
            per.setdefault(sr[0], []).append(sr[1])
        for name in per:                                         # episode bookkeeping (hysteresis)
            ent = self.streams.setdefault(name, {"since_ms": m, "clean": 0, "level": "WARNING"})
            ent["clean"] = 0
        for name in [n for n in self.streams if n not in per]:
            ent = self.streams[name]
            ent["clean"] += 1
            if ent["clean"] >= CLEAR_EVALS:
                del self.streams[name]
        for name, causes in per.items():
            info = stream_info(name)
            ok = (info is not None and info.get("tier") in TOLERATED_TIERS and info.get("kind") in TOLERATED_KINDS
                  and all(c is None or c in TOLERATED_CAUSES for c in causes)
                  and self._age_ms(self.streams[name], info, m) < self.t_ms)
            if not ok:
                self.streams[name]["level"] = "DEGRADED"
        n = len(self.streams)                                    # active + clearing streams of the episode
        clearing_bad = sorted(x for x, e in self.streams.items() if e["clean"] and e["level"] == "DEGRADED")
        tolerated = (state == "DEGRADED" and bool(per) and not blocking and not clearing_bad and n < self.k
                     and all(self.streams[x]["level"] == "WARNING" for x in per))
        cov_hard = [r for r in hard if classify(r) == "coverage"]
        reasons = [] if tolerated else list(hard)                # tolerated => every hard reason was coverage
        warnings = list(warn)
        reasons.extend(f"coverage_clearing:{x}" for x in clearing_bad)
        warn_streams = n if (tolerated or (not per and self.streams and not clearing_bad)) else 0
        if warn_streams:
            warnings.append(f"coverage:streams_stale:{warn_streams}")
            warnings.extend(f"coverage_tolerated:{r}" for r in (cov_hard if tolerated else []))
        if (state == "DEGRADED" and not tolerated) or reasons:
            out_state = "DEGRADED"
        elif startup:
            out_state = "STARTING"
        else:
            out_state = "HEALTHY"
        if any(classify(r) == "coverage" for r in reasons):
            cov = "DEGRADED"
        elif warn_streams:
            cov = "WARNING"
        elif any(classify(r) == "coverage" for r in startup):
            cov = "STARTING"
        else:
            cov = "OK"
        detail = {"raw_state": state, "tolerated": tolerated, "evaluated": True, "max_streams": self.k,
                  "max_age_s": self.t_ms // 1000, "clear_evals": CLEAR_EVALS,
                  "streams": {x: dict(e) for x, e in sorted(self.streams.items())[:20]}}
        return {"state": out_state, "reasons": reasons, "warnings": warnings, "coverage_state": cov, "detail": detail}
