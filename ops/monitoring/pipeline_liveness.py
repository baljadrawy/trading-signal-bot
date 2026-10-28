#!/usr/bin/env python3
"""Independent liveness monitor for the Paper signal pipeline (stdlib only).

Why: ``shared/health.py`` only checks heartbeat age, and an idle loop records
success, so every container stays "healthy" even when the pipeline produces
nothing (e.g. the scanner returning 0 coins every cycle because the risk
control pause is active).  This module classifies end-to-end liveness from
per-stage observations instead:

    PRODUCTIVE            signals are being produced and the latest acked
                          candidate outcome is a delivery within the
                          productive horizon
    IDLE_BY_DESIGN        stages alive, no signal yet but within the normal
                          low-signal horizon (or the market filter yields 0
                          for less than the stall horizon), a fresh signal
                          not yet delivered, or the latest candidate awaiting
                          owner approval
    BLOCKED_RISK_CONTROL  the scanner reports the risk-control pause marker,
                          or the telegram gate refused the latest candidate
                          (pause / portfolio capacity)
    UPSTREAM_OUTAGE       network-type scanner errors or market-data fetch
                          errors in consecutive cycles, empty market data,
                          zero eligible coins beyond the stall horizon, or
                          the Collector is not explicitly healthy and fresh
    STALLED               scanner silent or failing with non-network errors,
                          a downstream stage silent while its upstream
                          produces, no signal / no delivery beyond the
                          abnormal horizon, the latest candidate outcome an
                          expiry without a later delivery, future-dated log
                          lines, or a log source that cannot be read

Privacy contract: the pause *reason* is PROTECTED.  The adapter detects only
the pause marker character and discards everything after it; observations,
verdicts and CLI output carry no free text taken from the logs (no reasons,
no symbols, no messages), only timestamps, counts and fixed reason codes.

Fail-safe contract: ambiguity resolves to the MORE alarming state, never to a
healthy one (unparseable Collector state, future-dated log lines, an
unreadable log source and non-network scanner errors all count against
health).  If a stage's log cannot be read the CLI still prints a fixed-code
verdict (STALLED / log_source_unavailable) and exits non-zero.

Scope: the stages covered are scanner, analyzer, signal_engine and the
telegram candidate gate.  The trade tracker (``trading_tracker``) is NOT
monitored: its log lines carry trade outcomes, which this module must never
read, so tracker liveness stays with its own heartbeat.  A telegram "skipped
as not deliverable" ack writes no log line; saved signals are always written
deliverable (decision_source=policy_ready) in the save transaction, so a skip
only concerns an already-delivered duplicate and does not affect the backlog.

Read-only: the CLI only runs ``docker logs`` (or reads files given with
``--log-file``) and optionally reads the Collector health JSON.  It never
writes to the database, never execs into containers and restarts nothing.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

PRODUCTIVE = "PRODUCTIVE"
IDLE_BY_DESIGN = "IDLE_BY_DESIGN"
BLOCKED_RISK_CONTROL = "BLOCKED_RISK_CONTROL"
UPSTREAM_OUTAGE = "UPSTREAM_OUTAGE"
STALLED = "STALLED"
STATES = (PRODUCTIVE, IDLE_BY_DESIGN, BLOCKED_RISK_CONTROL, UPSTREAM_OUTAGE, STALLED)
HEALTHY_STATES = (PRODUCTIVE, IDLE_BY_DESIGN)

# Scanner cycle outcomes
OK, PAUSED, FAILED, INCOMPLETE = "ok", "paused", "failed", "incomplete"

# Telegram candidate outcomes, ordered from least to most alarming
_DELIVERED, _APPROVAL, _REFUSED, _EXPIRED = 0, 1, 2, 3
_OUTCOME_NAMES = {_DELIVERED: "delivered", _APPROVAL: "approval_requested",
                  _REFUSED: "refused", _EXPIRED: "expired_undelivered"}

# Hysteresis confirmations (see step())
ENTER_CONFIRM, EXIT_CONFIRM = 2, 3


# ----------------------------------------------------------------------------
# Thresholds and their data basis
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Thresholds:
    """Defaults derived from the live pipeline history (2026-10-15..10-22).

    * scan_interval_s = 300: scanner cycle-start gaps, median 301 s, max 304 s
      over 576 cycles (48 h); SCAN_INTERVAL_SECONDS = 300.
    * silence_factor = 3: a stage is silent after 3 missed intervals (15 min).
    * productive_h = 6: in productive operation (10-20..10-21, 36 saved
      signals) the longest gap between saved signals was 5.53 h (p90 1.49 h);
      a signal within 6 h therefore means "producing".
    * stall_no_signal_h = 24: the slowest observed day had 5 signals
      (range 5-38/day, 10-17..10-21).  Under a Poisson model at 5/day the
      chance of a 24 h gap is exp(-5) = 0.7 %, of a 12 h gap 8 %, of a 6 h gap
      29 %.  So 6-24 h without a signal while all stages are alive is a normal
      low-signal night (IDLE_BY_DESIGN); beyond 24 h it is STALLED.
    * delivery_stall_min = 30: replaying 57 saves / 57 deliveries (72 h) with
      the 120 s save/delivery log-order skew tolerance, every backlog drained
      within 15 s (55 episodes).  Telegram retries defer 60, 120, 240, 480,
      then 600 s, so 30 min allows about five deferral rounds before STALLED.
    * outage_cycles = 2 of the last outage_lookback = 3 scanner cycles failed
      (or hit a market-data fetch error); a single transient TimeoutError
      (observed once in 48 h) does not flip the state.
    * collector_stale_s = 120: the Collector container health check itself
      treats a health file older than 30 s as unhealthy; 120 s tolerates the
      write cadence plus clock skew.  Only HEALTHY is healthy.  BANNED_418,
      FAILED and STOPPED_INCOMPLETE (critical in the P2 continuous monitor),
      stale / unreadable / unparseable health and any unknown state count as
      upstream outage.  DEGRADED can be raised by non-market reasons (e.g. an
      unacknowledged previous-run-crash flag) and the lifecycle states are
      not market faults, so they are reported as an advisory reason only.
    * zero eligible coins for longer than stall_no_signal_h, or an empty
      market-data universe (total = 0) in outage_cycles consecutive cycles,
      is an upstream outage: the 24 h ticker filter over ~500 USDT pairs
      leaving nothing for a whole stall horizon means the data is missing.
    * clock_skew_s = 120: a log line dated more than this after "now" makes
      the time base untrustworthy (STALLED / future_dated_log_lines).
    """
    scan_interval_s: float = 300.0
    silence_factor: float = 3.0
    productive_h: float = 6.0
    stall_no_signal_h: float = 24.0
    delivery_stall_min: float = 30.0
    delivery_skew_s: float = 120.0
    outage_cycles: int = 2
    outage_lookback: int = 3
    collector_stale_s: float = 120.0
    collector_healthy_states: Tuple[str, ...] = ("HEALTHY",)
    collector_outage_states: Tuple[str, ...] = ("BANNED_418", "FAILED", "STOPPED_INCOMPLETE")
    collector_advisory_states: Tuple[str, ...] = ("DEGRADED", "DEGRADED_DISK", "STARTING",
                                                  "STOPPING", "STOPPED", "DISABLED")
    clock_skew_s: float = 120.0

    @property
    def silence_s(self) -> float:
        return self.scan_interval_s * self.silence_factor


DEFAULT_THRESHOLDS = Thresholds()


def derive_thresholds(scan_starts: Sequence[float], signal_ts: Sequence[float],
                      days_observed: Optional[float] = None, alpha: float = 0.01,
                      base: Thresholds = DEFAULT_THRESHOLDS) -> Thresholds:
    """Re-derive interval and horizons from an observed history.

    scan interval = median cycle-start gap; productive horizon = ceil of the
    longest observed signal gap (at least 1 h); stall horizon = the gap a
    Poisson process at the observed rate exceeds with probability ``alpha``,
    never shorter than twice the productive horizon.
    """
    out = base
    s = sorted(scan_starts)
    gaps = [b - a for a, b in zip(s, s[1:]) if b > a]
    if gaps:
        out = replace(out, scan_interval_s=float(statistics.median(gaps)))
    sig = sorted(signal_ts)
    if len(sig) >= 3:
        sgaps = [b - a for a, b in zip(sig, sig[1:])]
        prod_h = max(1.0, math.ceil(max(sgaps) / 3600.0))
        span_d = days_observed or max((sig[-1] - sig[0]) / 86400.0, 1e-9)
        rate_h = len(sig) / (span_d * 24.0)
        stall_h = max(2 * prod_h, math.ceil(-math.log(alpha) / rate_h))
        out = replace(out, productive_h=float(prod_h), stall_no_signal_h=float(stall_h))
    return out


# ----------------------------------------------------------------------------
# Observations
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class ScanCycle:
    ts: float                       # cycle start (epoch seconds, UTC)
    outcome: str                    # ok | paused | failed | incomplete
    eligible: Optional[int] = None  # eligible-coin count (ok cycles)
    total: Optional[int] = None     # total-coin count
    upstream_error: bool = False    # market-data fetch error inside the cycle


@dataclass
class Observations:
    now: float
    window_start: float
    scanner_cycles: List[ScanCycle] = field(default_factory=list)
    analyzer_cycles: List[float] = field(default_factory=list)
    engine_ticks: List[float] = field(default_factory=list)       # any engine cycle evidence
    engine_no_fresh: List[float] = field(default_factory=list)    # "no fresh analysis"
    signals_saved: List[float] = field(default_factory=list)
    deliveries: List[float] = field(default_factory=list)
    delivery_failures: List[float] = field(default_factory=list)  # expired undelivered
    delivery_refusals: List[float] = field(default_factory=list)  # gate refused (pause/capacity)
    approval_requests: List[float] = field(default_factory=list)  # awaiting manual approval
    upstream_errors: List[float] = field(default_factory=list)
    collector: Optional[Dict[str, object]] = None  # {"state": str, "ts_ms": int} or {"error": code}
    future_events: int = 0          # lines dated beyond now + clock_skew_s (dropped, counted)

    def all_ts(self) -> List[float]:
        return ([c.ts for c in self.scanner_cycles] + self.analyzer_cycles + self.engine_ticks
                + self.engine_no_fresh + self.signals_saved + self.deliveries
                + self.delivery_failures + self.delivery_refusals + self.approval_requests
                + self.upstream_errors)

    def until(self, t: float, lookback_s: Optional[float] = None) -> "Observations":
        """Observations as they would have been seen at time ``t``.

        ``future_events`` counts lines dated beyond the *real* now; they are
        only future relative to a step that is itself at the real now, so an
        earlier replay step does not inherit them.
        """
        lo = self.window_start if lookback_s is None else max(self.window_start, t - lookback_s)
        f = lambda xs: [x for x in xs if lo <= x <= t]
        return Observations(
            now=t, window_start=lo,
            scanner_cycles=[c for c in self.scanner_cycles if lo <= c.ts <= t],
            analyzer_cycles=f(self.analyzer_cycles), engine_ticks=f(self.engine_ticks),
            engine_no_fresh=f(self.engine_no_fresh), signals_saved=f(self.signals_saved),
            deliveries=f(self.deliveries), delivery_failures=f(self.delivery_failures),
            delivery_refusals=f(self.delivery_refusals),
            approval_requests=f(self.approval_requests),
            upstream_errors=f(self.upstream_errors), collector=self.collector,
            future_events=self.future_events if t >= self.now else 0)


@dataclass
class Verdict:
    state: str
    reasons: List[str]
    evidence: Dict[str, object]

    def to_dict(self) -> Dict[str, object]:
        return {"state": self.state, "reasons": list(self.reasons), "evidence": dict(self.evidence)}


# ----------------------------------------------------------------------------
# Pure classifier
# ----------------------------------------------------------------------------
def backlog_since(saved: Sequence[float], delivered: Sequence[float],
                  skew_s: float = 120.0) -> Optional[float]:
    """Count-based delivery backlog (logs carry no shared id we keep).

    Replays saves (+1) and deliveries (-1) in time order and returns when the
    current non-empty backlog last rose from empty, or None if it is empty.
    The engine writes its "saved" line after publishing, so telegram can log
    the delivery a few seconds *before* the save line: a delivery seen with an
    empty backlog is kept as a credit for ``skew_s`` and consumed by the next
    save inside that horizon.  A backlog that has not drained for longer than
    the delivery threshold means the delivery stage is not keeping up.
    """
    events = sorted([(t, 1) for t in saved] + [(t, -1) for t in delivered],
                    key=lambda e: (e[0], e[1]))
    depth, since = 0, None
    credits: List[float] = []
    for t, d in events:
        credits = [c for c in credits if t - c <= skew_s]
        if d > 0:
            if credits:
                credits.pop(0)
                continue
            if depth == 0:
                since = t
            depth += 1
        elif depth > 0:
            depth -= 1
            if depth == 0:
                since = None
        else:
            credits.append(t)
    return since


def backlog_episodes(saved: Sequence[float], delivered: Sequence[float],
                     skew_s: float = 120.0) -> List[float]:
    """Durations (s) of every drained backlog episode; for threshold review."""
    out: List[float] = []
    evs = sorted(set(saved) | set(delivered))
    prev = None
    for t in evs:
        cur = backlog_since([x for x in saved if x <= t], [x for x in delivered if x <= t], skew_s)
        if prev is not None and cur is None:
            out.append(t - prev)
        prev = cur
    return out


def _age(now: float, ts: Optional[float]) -> Optional[float]:
    return None if ts is None else round(now - ts, 1)


def classify(obs: Observations, th: Thresholds = DEFAULT_THRESHOLDS) -> Verdict:
    now = obs.now
    cycles = sorted(obs.scanner_cycles, key=lambda c: c.ts)
    closed = [c for c in cycles if c.outcome != INCOMPLETE]
    last_cycle = cycles[-1] if cycles else None
    last_closed = closed[-1] if closed else None
    last_signal = max(obs.signals_saved) if obs.signals_saved else None
    last_delivery = max(obs.deliveries) if obs.deliveries else None
    last_analyzer = max(obs.analyzer_cycles) if obs.analyzer_cycles else None
    last_engine = max(obs.engine_ticks) if obs.engine_ticks else None
    window_s = now - obs.window_start
    ev: Dict[str, object] = {
        "window_h": round(window_s / 3600.0, 2),
        "scanner_cycles": len(cycles),
        "scanner_cycles_paused": sum(c.outcome == PAUSED for c in cycles),
        "scanner_cycles_failed": sum(c.outcome == FAILED for c in cycles),
        "scanner_cycles_eligible_gt0": sum(c.outcome == OK and (c.eligible or 0) > 0 for c in cycles),
        "last_scanner_cycle_age_s": _age(now, last_cycle.ts if last_cycle else None),
        "last_scanner_outcome": last_cycle.outcome if last_cycle else None,
        "last_eligible": last_cycle.eligible if last_cycle else None,
        "analyzer_cycles": len(obs.analyzer_cycles),
        "signals_saved": len(obs.signals_saved),
        "deliveries": len(obs.deliveries),
        "delivery_refusals": len(obs.delivery_refusals),
        "approval_requests": len(obs.approval_requests),
        "last_signal_age_s": _age(now, last_signal),
        "last_delivery_age_s": _age(now, last_delivery),
        "upstream_error_events": len(obs.upstream_errors),
    }
    advisory: List[str] = []

    # Collector (optional, secondary).  Only an explicitly healthy, fresh,
    # parseable report is healthy; anything else is advisory or outage.
    collector_outage: Optional[str] = None
    if obs.collector is not None:
        c = obs.collector
        cstate = c.get("state")
        ts_ms = c.get("ts_ms")
        ev["collector_state"] = cstate if isinstance(cstate, str) else None
        if c.get("error"):
            collector_outage = "collector_health_unreadable"
        elif not isinstance(cstate, str) or not isinstance(ts_ms, (int, float)):
            collector_outage = "collector_health_unparseable"
        elif ts_ms / 1000.0 > now + th.clock_skew_s:
            collector_outage = "collector_health_future_dated"
        elif now - ts_ms / 1000.0 > th.collector_stale_s:
            collector_outage = "collector_health_stale"
        elif cstate in th.collector_healthy_states:
            pass
        elif cstate in th.collector_advisory_states:
            advisory.append("collector_degraded_advisory")
        elif cstate in th.collector_outage_states:
            collector_outage = "collector_state_outage"
        else:
            collector_outage = "collector_state_unknown"

    # 0. Clock skew: a future-dated line never counts as "recent activity"
    future = obs.future_events + sum(t > now + th.clock_skew_s for t in obs.all_ts())
    if future:
        ev["future_dated_events"] = future
        return Verdict(STALLED, ["future_dated_log_lines"] + advisory, ev)

    # 1. Scanner silence (most severe: nothing upstream is running)
    if last_cycle is None:
        if window_s >= th.silence_s:
            return Verdict(STALLED, ["no_scanner_cycles_in_window"] + advisory, ev)
        return Verdict(IDLE_BY_DESIGN, ["insufficient_window"] + advisory, ev)
    if now - last_cycle.ts > th.silence_s:
        return Verdict(STALLED, ["scanner_silent"] + advisory, ev)

    # 2. Risk-control pause (marker only; the reason is never read).  An
    # in-progress cycle has no outcome yet, so look back to the last closed one.
    if last_closed is not None and last_closed.outcome == PAUSED:
        run = 0
        for c in reversed(closed):
            if c.outcome != PAUSED:
                break
            run += 1
        first = closed[len(closed) - run].ts
        ev["paused_cycles_consecutive"] = run
        ev["paused_since_s"] = round(now - first, 1)
        return Verdict(BLOCKED_RISK_CONTROL, ["risk_control_pause_marker"] + advisory, ev)

    # 3. Upstream outage.  Network-type scanner errors (and market-data fetch
    # errors) are upstream; any other failing cycle is a code fault (STALLED).
    recent = [c for c in closed if c.outcome != PAUSED][-th.outage_lookback:]
    degraded = sum(c.outcome == FAILED or c.upstream_error for c in recent)
    code_faults = sum(c.outcome == FAILED and not c.upstream_error for c in recent)
    ev["recent_cycles_degraded"] = degraded
    if degraded >= th.outage_cycles and code_faults:
        return Verdict(STALLED, ["scanner_cycles_failing_non_network_error"] + advisory, ev)
    reasons: List[str] = []
    if degraded >= th.outage_cycles:
        reasons.append("scanner_cycles_failing_or_fetch_errors")
    # Zero-eligible stretch: ok cycles with 0 eligible coins since the last
    # eligible>0 (or paused) cycle.  A FAILED cycle neither counts nor resets
    # the stretch, so sparse failures cannot keep it IDLE_BY_DESIGN forever.
    stall_s = th.stall_no_signal_h * 3600
    zero_run: List[ScanCycle] = []
    zero_since: Optional[float] = None
    zero_truncated = True                       # stretch reaches the window start
    for c in reversed(closed):
        if c.outcome == PAUSED or (c.outcome == OK and (c.eligible or 0) > 0):
            zero_truncated = False
            break
        if c.outcome == OK:
            zero_run.append(c)
        zero_since = c.ts
    ev["zero_eligible_cycles_consecutive"] = len(zero_run)
    if zero_run:
        ev["zero_eligible_for_s"] = round(now - zero_since, 1)
    if (len(zero_run) >= th.outage_cycles
            and all(c.total == 0 for c in zero_run[:th.outage_cycles])):
        reasons.append("scanner_market_data_empty")
    elif zero_run and now - zero_since > stall_s:
        reasons.append("zero_eligible_beyond_stall_horizon")
    elif zero_run and zero_truncated and window_s < stall_s:
        advisory.append("window_shorter_than_stall_horizon")
    if collector_outage:
        reasons.append(collector_outage)
    if reasons:
        return Verdict(UPSTREAM_OUTAGE, reasons + advisory, ev)
    if degraded:
        advisory.append("transient_upstream_error")

    # Current productive run: consecutive non-paused cycles ending now
    run_cycles: List[ScanCycle] = []
    for c in reversed(cycles):
        if c.outcome == PAUSED:
            break
        run_cycles.append(c)
    run_cycles.reverse()
    run_start = run_cycles[0].ts
    window_truncated = len(run_cycles) == len(cycles)  # run may extend before the window
    eligible_cycles = [c for c in run_cycles if c.outcome == OK and (c.eligible or 0) > 0]
    ev["run_age_s"] = round(now - run_start, 1)

    # 4. Downstream silence while upstream produces.  Measured from the most
    # recent eligible cycle old enough that the analyzer had to answer it.
    stalled: List[str] = []
    due = [c for c in eligible_cycles if now - c.ts > th.silence_s]
    if due:
        due_ts = due[-1].ts
        analyzer_answered = any(t >= due_ts - th.scan_interval_s for t in obs.analyzer_cycles)
        if not analyzer_answered:
            stalled.append("analyzer_silent_while_scanner_eligible")
        if last_analyzer is not None and (
                last_engine is None or now - last_engine > th.silence_s):
            stalled.append("signal_engine_silent_while_analyzer_active")
        nf = [t for t in obs.engine_no_fresh if t >= now - th.silence_s]
        if len(nf) >= 3 and not analyzer_answered:
            stalled.append("engine_reports_no_fresh_analysis")

    # No-signal clock starts at the later of last signal and start of the run
    clock_from = max(run_start, last_signal) if last_signal is not None else run_start
    quiet_s = now - clock_from
    ev["no_signal_for_s"] = round(quiet_s, 1)
    if eligible_cycles and last_analyzer is not None and quiet_s > th.stall_no_signal_h * 3600:
        stalled.append("no_signal_beyond_abnormal_horizon")

    # Only signals saved in the current (unpaused) run count: the pause gate
    # legitimately holds delivery, so pre-pause leftovers are not a stall.
    # Every acked outcome drains the backlog: delivered, refused by the risk
    # gate, sent for manual approval, or expired undelivered.  Draining is not
    # health: only a delivery can make the verdict PRODUCTIVE.
    run_from = run_start - th.delivery_skew_s
    terminal = sorted(obs.deliveries + obs.delivery_refusals + obs.approval_requests
                      + obs.delivery_failures)
    b_since = backlog_since([t for t in obs.signals_saved if t >= run_start],
                            [t for t in terminal if t >= run_from],
                            th.delivery_skew_s)
    ev["delivery_backlog_age_s"] = _age(now, b_since)
    if b_since is not None and now - b_since > th.delivery_stall_min * 60:
        stalled.append("signal_saved_not_delivered")
    # Latest acked candidate outcome; on a timestamp tie the more alarming
    # kind sorts last and wins.
    outcomes = sorted([(t, _DELIVERED) for t in obs.deliveries]
                      + [(t, _APPROVAL) for t in obs.approval_requests]
                      + [(t, _REFUSED) for t in obs.delivery_refusals]
                      + [(t, _EXPIRED) for t in obs.delivery_failures])
    last_out = outcomes[-1] if outcomes else None
    if last_out is not None:
        ev["last_candidate_outcome"] = _OUTCOME_NAMES[last_out[1]]
        ev["last_candidate_outcome_age_s"] = _age(now, last_out[0])
    recent_fail = [t for t in obs.delivery_failures
                   if t >= run_start and now - t <= th.delivery_stall_min * 60]
    # An expiry drains the backlog but is a delivery failure: it stays STALLED
    # until a later delivery (or other acked outcome) supersedes it.
    expired_last = (last_out is not None and last_out[1] == _EXPIRED
                    and last_out[0] >= run_from)
    if recent_fail or expired_last:
        stalled.append("delivery_expired_undelivered")
    if stalled:
        return Verdict(STALLED, stalled + advisory, ev)

    # 5. Delivery gate refusing (pause or capacity): the latest acked
    # candidate outcome was a refusal, so signals cannot become trades.
    if last_out is not None and last_out[1] == _REFUSED:
        ev["last_refusal_age_s"] = _age(now, last_out[0])
        return Verdict(BLOCKED_RISK_CONTROL, ["delivery_refused_by_risk_gate"] + advisory, ev)

    # 6. Healthy states.  An approval request is not a trade: never PRODUCTIVE.
    if last_out is not None and last_out[1] == _APPROVAL and last_out[0] >= run_from:
        return Verdict(IDLE_BY_DESIGN, ["awaiting_owner_approval"] + advisory, ev)
    productive_s = th.productive_h * 3600
    if last_signal is not None and now - last_signal <= productive_s:
        if (last_out is not None and last_out[1] == _DELIVERED
                and now - last_out[0] <= productive_s):
            return Verdict(PRODUCTIVE, ["signal_within_productive_horizon"] + advisory, ev)
        return Verdict(IDLE_BY_DESIGN, ["signal_not_yet_delivered"] + advisory, ev)
    if not eligible_cycles:
        return Verdict(IDLE_BY_DESIGN, ["no_eligible_coins"] + advisory, ev)
    idle = ["no_signal_within_normal_low_signal_horizon"]
    if (window_truncated and window_s < stall_s
            and "window_shorter_than_stall_horizon" not in advisory):
        idle.append("window_shorter_than_stall_horizon")
    return Verdict(IDLE_BY_DESIGN, idle + advisory, ev)


# ----------------------------------------------------------------------------
# Hysteresis
# ----------------------------------------------------------------------------
@dataclass
class TrackerState:
    state: Optional[str] = None
    since: Optional[float] = None
    candidate: Optional[str] = None
    candidate_count: int = 0


def _confirm_need(state: str, candidate: str, enter_confirm: int = ENTER_CONFIRM,
                  exit_confirm: int = EXIT_CONFIRM) -> int:
    if candidate not in HEALTHY_STATES and state in HEALTHY_STATES:
        return enter_confirm
    return exit_confirm


def step(prev: TrackerState, raw: Verdict, now: float,
         enter_confirm: int = ENTER_CONFIRM,
         exit_confirm: int = EXIT_CONFIRM) -> Tuple[TrackerState, Verdict]:
    """Debounce raw verdicts.  A switch into an unhealthy state needs
    ``enter_confirm`` consecutive raw evaluations; a switch back to a healthy
    state (or between unhealthy states) needs ``exit_confirm``.  Moves between
    the two healthy states are immediate (both mean "working").  The first
    evaluation adopts the raw state.
    """
    if prev.state is None:
        return TrackerState(raw.state, now, None, 0), raw
    if raw.state == prev.state:
        return TrackerState(prev.state, prev.since, None, 0), raw
    if raw.state in HEALTHY_STATES and prev.state in HEALTHY_STATES:
        return TrackerState(raw.state, now, None, 0), raw
    need = _confirm_need(prev.state, raw.state, enter_confirm, exit_confirm)
    count = prev.candidate_count + 1 if prev.candidate == raw.state else 1
    if count >= need:
        return TrackerState(raw.state, now, None, 0), raw
    held = Verdict(prev.state, ["hysteresis_hold"], dict(raw.evidence))
    held.evidence["pending_state"] = raw.state
    held.evidence["pending_count"] = count
    held.evidence["pending_reasons"] = list(raw.reasons)
    return TrackerState(prev.state, prev.since, raw.state, count), held


def timeline(obs: Observations, step_s: float, th: Thresholds = DEFAULT_THRESHOLDS,
             lookback_s: Optional[float] = None, start: Optional[float] = None,
             **kw) -> List[Dict[str, object]]:
    """Replay the window with hysteresis; return state segments."""
    t = start if start is not None else obs.window_start + th.silence_s
    times: List[float] = []
    while t <= obs.now + 1e-9:
        times.append(t)
        t += step_s
    if not times or times[-1] < obs.now:   # always end at the real now
        times.append(obs.now)
    tracker = TrackerState()
    segs: List[Dict[str, object]] = []
    for t in times:
        tracker, v = step(tracker, classify(obs.until(t, lookback_s), th), t, **kw)
        if not segs or segs[-1]["state"] != v.state:
            segs.append({"state": v.state, "from": _iso(t), "to": _iso(t), "reasons": v.reasons})
        else:
            segs[-1]["to"] = _iso(t)
    return segs


# ----------------------------------------------------------------------------
# Log adapter (reads only marker / count lines; never keeps message text)
# ----------------------------------------------------------------------------
PAUSE_MARKER = "⏸"  # the pause glyph; the variation selector may follow
_DOCKER_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z\s?")
_APP_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:,\d+)? \|")
_INT = re.compile(r"(\d+)")
_APP_LEVEL = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)? \|[^|]*\| *([A-Z]+) *\|")
_EXC_NAME = re.compile(r"\(\d+\): ([A-Za-z_][\w.]*)")
# Exception class names that shared/retry_utils.is_network_error() treats as
# network errors; used only when the log level is not present in the line.
NETWORK_EXC_NAMES = frozenset((
    "TimeoutError", "OSError", "ConnectionError", "ConnectionResetError",
    "ConnectionRefusedError", "ConnectionAbortedError", "BrokenPipeError", "gaierror",
    "ClientConnectionError", "ClientConnectorError", "ServerDisconnectedError",
    "ClientOSError", "ServerTimeoutError", "ClientConnectorDNSError",
    "PostgresConnectionError", "ConnectionDoesNotExistError"))

SCAN_START = "\U0001F50D بدء دورة المسح"            # magnifier + "scan cycle start"
SCAN_TOTAL = "\U0001F4CA إجمالي العملات:"            # chart + "total coins:"
SCAN_ELIGIBLE = "\U0001F3AF العملات المؤهلة للتحليل:"  # target + "eligible coins:"
SCAN_DONE = "✅ وجدنا"                           # check + "found N"
SCAN_FAIL = "❌ خطأ في دورة المسح"               # cross + "scan cycle error"
BTC_TREND_ERR = "خطأ في تحديث اتجاه BTC"             # BTC trend fetch error
ANALYZER_CYCLE = "\U0001F52C تحليل"                  # microscope + "analysing"
ENGINE_SAVED = "✅ تم حفظ الإشارة"               # "signal saved"
ENGINE_NO_FRESH = "\U0001F4A4 لا نتائج تحليل طازجة"  # "no fresh analysis"
ENGINE_NO_SIGNAL = "\U0001F4A4 لا إشارة"              # "no signal this cycle"
TG_DELIVERED = "\U0001F4E5 مرشح معتمد أُرسل"           # "approved candidate sent"
TG_REFUSED = "عدم إرسال المرشح"                       # "candidate not sent" (gate refused)
TG_APPROVAL = "\U0001F50D طلب موافقة"                  # "approval request" (awaiting)
# Candidate expiry only; lifecycle notifications log "notification ... expired undelivered".
TG_EXPIRED = re.compile(r"\bcandidate \S+ for signal \S+ expired undelivered\b")


def _ts(line: str) -> Tuple[Optional[float], str]:
    m = _DOCKER_TS.match(line)
    if m:
        rest = line[m.end():]
        t = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00").timestamp()
        return t, rest
    m = _APP_TS.match(line)
    if m:  # application timestamps are UTC in these containers
        t = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}+00:00").timestamp()
        return t, line
    return None, line


def strip_after_pause_marker(line: str) -> str:
    """Return the line cut at the pause marker (the reason is never kept)."""
    i = line.find(PAUSE_MARKER)
    return line if i < 0 else line[:i + 1]


def redact(line: str) -> str:
    """Cut at the pause marker and after the gate-refusal code: the refusal
    line carries the symbol and the (protected) block reason after it."""
    line = strip_after_pause_marker(line)
    i = line.find(TG_REFUSED)
    return line if i < 0 else line[:i + len(TG_REFUSED)]


def _is_network_failure(line: str) -> bool:
    """scanner/main.py logs a network-type cycle error at WARNING and any
    other exception at ERROR.  Without a level, fall back to the exception
    class name; anything undeterminable is treated as a code fault."""
    m = _APP_LEVEL.match(line)
    if m:
        return m.group(1) == "WARNING"
    m = _EXC_NAME.search(line, line.find(SCAN_FAIL))
    return bool(m) and m.group(1).rsplit(".", 1)[-1] in NETWORK_EXC_NAMES


def _int_after(text: str, key: str) -> Optional[int]:
    m = _INT.search(text, text.find(key) + len(key))
    return int(m.group(1)) if m else None


def parse_scanner(lines: Iterable[str]) -> Tuple[List[ScanCycle], List[float]]:
    cycles: List[ScanCycle] = []
    errors: List[float] = []
    cur: Optional[dict] = None

    def close(outcome_default: str = INCOMPLETE):
        if cur is not None:
            cycles.append(ScanCycle(cur["ts"], cur.get("outcome", outcome_default),
                                    cur.get("eligible"), cur.get("total"), cur.get("err", False)))

    for raw in lines:
        t, line = _ts(raw.rstrip("\n"))
        if t is None:
            continue
        line = strip_after_pause_marker(line)  # reason dropped before any matching
        if SCAN_START in line:
            close()
            cur = {"ts": t}
            continue
        if cur is None:  # tail of a cycle that started before the window
            if PAUSE_MARKER in line or SCAN_TOTAL in line:
                cur = {"ts": t}
            else:
                if BTC_TREND_ERR in line or (SCAN_FAIL in line and _is_network_failure(line)):
                    errors.append(t)
                continue
        if PAUSE_MARKER in line:
            cur["outcome"] = PAUSED
        elif SCAN_TOTAL in line:
            cur["total"] = _int_after(line, SCAN_TOTAL)
        elif SCAN_ELIGIBLE in line:
            cur["eligible"] = _int_after(line, SCAN_ELIGIBLE)
        elif BTC_TREND_ERR in line:
            cur["err"] = True
            errors.append(t)
        elif SCAN_FAIL in line:
            cur["outcome"] = FAILED
            if _is_network_failure(line):
                cur["err"] = True
                errors.append(t)
            close()
            cur = None
        elif SCAN_DONE in line:
            if cur.get("outcome") != PAUSED:
                cur["outcome"] = OK
                if cur.get("eligible") is None:
                    cur["eligible"] = _int_after(line, SCAN_DONE)
            close()
            cur = None
    close()
    return cycles, errors


def _times(lines: Iterable[str], *needles) -> Dict[object, List[float]]:
    """Timestamps of lines matching each needle (a substring or a compiled regex)."""
    out: Dict[object, List[float]] = {n: [] for n in needles}
    for raw in lines:
        t, line = _ts(raw.rstrip("\n"))
        if t is None:
            continue
        line = redact(line)
        for n in needles:
            if (n.search(line) if hasattr(n, "search") else n in line):
                out[n].append(t)
    return out


def build_observations(stage_lines: Dict[str, Iterable[str]], now: float, window_start: float,
                       collector: Optional[Dict[str, object]] = None,
                       th: Thresholds = DEFAULT_THRESHOLDS) -> Observations:
    """Events are clipped to [window_start, now].  A line dated within
    ``clock_skew_s`` after now is clamped to now; one dated later is dropped
    and counted in ``future_events`` (the classifier then fails safe)."""
    future = 0
    limit = now + th.clock_skew_s

    def clip(xs: Iterable[float]) -> List[float]:
        nonlocal future
        kept: List[float] = []
        for x in xs:
            if x > limit:
                future += 1
            elif x >= window_start:
                kept.append(min(x, now))
        return kept

    raw_cycles, errors = parse_scanner(stage_lines.get("scanner", []))
    cycles: List[ScanCycle] = []
    for c in raw_cycles:
        if c.ts > limit:
            future += 1
        elif c.ts >= window_start:
            cycles.append(replace(c, ts=min(c.ts, now)))
    a = _times(stage_lines.get("analyzer", []), ANALYZER_CYCLE)
    e = _times(stage_lines.get("signal_engine", []), ENGINE_SAVED, ENGINE_NO_FRESH, ENGINE_NO_SIGNAL)
    g = _times(stage_lines.get("telegram", []), TG_DELIVERED, TG_EXPIRED, TG_REFUSED, TG_APPROVAL)
    ticks = sorted(e[ENGINE_SAVED] + e[ENGINE_NO_FRESH] + e[ENGINE_NO_SIGNAL])
    return Observations(
        now=now, window_start=window_start, scanner_cycles=cycles,
        analyzer_cycles=clip(a[ANALYZER_CYCLE]), engine_ticks=clip(ticks),
        engine_no_fresh=clip(e[ENGINE_NO_FRESH]), signals_saved=clip(e[ENGINE_SAVED]),
        deliveries=clip(g[TG_DELIVERED]), delivery_failures=clip(g[TG_EXPIRED]),
        delivery_refusals=clip(g[TG_REFUSED]), approval_requests=clip(g[TG_APPROVAL]),
        upstream_errors=clip(errors), collector=collector, future_events=future)


def read_collector_health(path: str) -> Dict[str, object]:
    """Keep only state and ts_ms; any failure becomes an error code."""
    try:
        with open(path, encoding="utf-8") as fh:
            h = json.load(fh)
        state = h.get("state")
        ts_ms = h.get("ts_ms")
        return {"state": state if isinstance(state, str) else None,
                "ts_ms": ts_ms if isinstance(ts_ms, (int, float)) else None}
    except (OSError, ValueError, AttributeError):
        return {"error": "unreadable"}


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
CONTAINERS = {"scanner": "trading_scanner", "analyzer": "trading_analyzer",
              "signal_engine": "trading_signal_engine", "telegram": "trading_telegram"}
DOCKER_TIMEOUT_S = 60.0
EXIT_LOG_SOURCE_UNAVAILABLE = 2


class LogSourceError(Exception):
    """A stage log could not be read; ``code`` is a fixed reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _duration_s(s: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd])", s.strip())
    if not m:
        raise argparse.ArgumentTypeError("duration like 30m, 48h, 2d")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _docker_lines(container: str, since: str, timeout_s: float = DOCKER_TIMEOUT_S) -> List[str]:
    try:
        p = subprocess.run(["docker", "logs", "-t", "--since", since, container],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                           timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise LogSourceError("docker_logs_timeout") from None
    except (OSError, subprocess.SubprocessError):
        raise LogSourceError("docker_unavailable") from None
    if p.returncode != 0:  # e.g. missing / renamed container; output is discarded
        raise LogSourceError("docker_logs_failed")
    return p.stdout.decode("utf-8", "replace").splitlines()


def _file_lines(path: str) -> List[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        raise LogSourceError("log_file_unreadable") from None


def _load_tracker_state(path: str) -> TrackerState:
    """Persisted hysteresis state; anything invalid means "no prior state".

    An out-of-range ``candidate_count`` is clamped to [0, need - 1] for that
    transition, so a corrupt file can never skip the confirmation rounds.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        state, since, cand = d.get("state"), d.get("since"), d.get("candidate")
        count = d.get("candidate_count", 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return TrackerState()
    if state not in STATES or not isinstance(since, (int, float)) or isinstance(since, bool):
        return TrackerState()
    if count is None:
        count = 0
    if not isinstance(count, int) or isinstance(count, bool):
        return TrackerState()
    if cand not in STATES or cand == state:
        return TrackerState(state, float(since), None, 0)
    count = max(0, min(count, _confirm_need(state, cand) - 1))
    return TrackerState(state, float(since), cand, count)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Paper pipeline liveness classifier")
    ap.add_argument("--since", default="48h", help="log window, e.g. 48h")
    ap.add_argument("--log-file", action="append", default=[], metavar="STAGE=PATH",
                    help="read a stage's log from a file instead of docker logs")
    ap.add_argument("--collector-health", metavar="PATH", help="collector_health.json (optional)")
    ap.add_argument("--timeline", metavar="STEP", type=_duration_s,
                    help="also replay the window with hysteresis at this step")
    ap.add_argument("--state-file", metavar="PATH",
                    help="persist hysteresis state between runs (written only if given)")
    ap.add_argument("--docker-timeout", metavar="DURATION", type=_duration_s,
                    default=DOCKER_TIMEOUT_S, help="per-container docker logs timeout, e.g. 60s")
    ap.add_argument("--now", type=float, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    now = args.now if args.now is not None else time.time()
    window_start = now - _duration_s(args.since)
    files = dict(x.split("=", 1) for x in args.log_file)
    stage_lines: Dict[str, List[str]] = {}
    source_errors: Dict[str, str] = {}
    for stage, container in CONTAINERS.items():
        try:
            if stage in files:
                stage_lines[stage] = _file_lines(files[stage])
            else:
                stage_lines[stage] = _docker_lines(container, args.since, args.docker_timeout)
        except LogSourceError as exc:
            source_errors[stage] = exc.code
    if source_errors:  # fail safe: a fixed-code verdict, never a healthy one
        del stage_lines
        out = {"evaluated_at": _iso(now), "since": args.since, "state": STALLED,
               "reasons": ["log_source_unavailable"],
               "evidence": {"log_source_errors": source_errors}}
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return EXIT_LOG_SOURCE_UNAVAILABLE
    collector = read_collector_health(args.collector_health) if args.collector_health else None
    obs = build_observations(stage_lines, now, window_start, collector)
    del stage_lines  # raw text is never emitted
    raw = classify(obs)
    out: Dict[str, object] = {"evaluated_at": _iso(now), "since": args.since}
    if args.state_file:
        prev = _load_tracker_state(args.state_file)
        tracker, shown = step(prev, raw, now)
        with open(args.state_file, "w", encoding="utf-8") as fh:
            json.dump(asdict(tracker), fh)
        out.update(shown.to_dict())
        out["raw_state"] = raw.state
    else:
        out.update(raw.to_dict())
    out["thresholds"] = {k: v for k, v in asdict(DEFAULT_THRESHOLDS).items()}
    if args.timeline:
        out["timeline"] = timeline(obs, args.timeline)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
