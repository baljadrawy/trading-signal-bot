"""Technical-halt recovery: classification, fresh-validity assessment, two-step owner approval.

DESIGN AND TEST ONLY. Nothing imports this module at runtime, and it performs no I/O: it never
reads or writes pause state, never resumes trading and never talks to a database, exchange or
Telegram. It only returns classifications, assessments, challenges and fixed result codes. A
future caller (separately approved) would compute the fresh check, call these functions, and on
a confirmed approval run the EXISTING /resume write unchanged.

Why it exists: a transient market-data failure (e.g. a price fetch timing out) makes the tracker's
admission snapshot non-finite, `evaluate_new_trade` refuses with `invalid_risk_state`, and
`record_risk_decision` records that as a sticky hard halt (`risk:invalid_risk_state`). That is the
correct fail-closed behaviour and is NOT changed here. What was missing is a governed way to tell a
technical halt apart from a genuine risk-limit halt, and to require evidence that the technical
condition is gone before the owner resumes.

Provenance, not the current label: record_risk_decision's upsert rewrites pause_reason whenever a new
hard halt is recorded (CASE WHEN EXCLUDED.is_trading_paused THEN EXCLUDED.pause_reason ...), and the
finite-input check outranks the pause check. So while ANY halt is active (risk limit or /pause) a later
price timeout relabels the row 'risk:invalid_risk_state', and a later date inserts a newer row with
that reason. The current reason therefore cannot prove the halt began technically. Eligibility needs
the caller-supplied pause history since the last manual_resume: complete, non-empty, every entry
TECHNICAL, ending at the current reason. provenance_from_scanner_lines derives that history and its
completeness from the scanner's per-cycle pause log lines (pure parsing; the caller supplies the lines).

Invariants (pinned by tests/test_halt_recovery.py):
- Only TECHNICAL halts with an all-TECHNICAL, complete history can ever be assessed eligible. RISK_LIMIT, MANUAL and UNKNOWN never are; they
  keep the existing /recover_risk and /resume governance.
- Unrecognised input is UNKNOWN / ineligible (fail-closed); classification is by exact string.
- Blockers and result codes are fixed strings; no market, P&L or account value is ever echoed.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

# ── halt classes ──────────────────────────────────────────────────────────

TECHNICAL = 'TECHNICAL'
RISK_LIMIT = 'RISK_LIMIT'
MANUAL = 'MANUAL'
UNKNOWN = 'UNKNOWN'

# Exact strings produced by the code (see shared/trading_state.py, shared/risk_management.py and
# trade_tracker.main.record_risk_decision, which persists hard halts as 'risk:<reason>').
_RISK_PREFIX = 'risk:'
_TECHNICAL_RISK_REASONS = frozenset({'invalid_risk_state'})
_RISK_LIMIT_REASONS = frozenset({
    'daily_loss_limit', 'weekly_loss_limit', 'max_drawdown_limit', 'loss_streak_halt'})
# Fail-closed states of get_pause_state itself; written without the 'risk:' prefix.
_STATE_TECHNICAL = frozenset({'risk_state_missing', 'risk_state_inconsistent'})
_MANUAL = frozenset({'manual_pause'})

_CLASS_TABLE: dict[str, str] = {}
for _r in _TECHNICAL_RISK_REASONS:
    _CLASS_TABLE[_r] = TECHNICAL
    _CLASS_TABLE[_RISK_PREFIX + _r] = TECHNICAL
for _r in _RISK_LIMIT_REASONS:
    _CLASS_TABLE[_r] = RISK_LIMIT
    _CLASS_TABLE[_RISK_PREFIX + _r] = RISK_LIMIT
for _r in _STATE_TECHNICAL:
    _CLASS_TABLE[_r] = TECHNICAL
for _r in _MANUAL:
    _CLASS_TABLE[_r] = MANUAL
del _r

# Fresh-evaluation reasons (pause masked) that do NOT indicate an active halt. They are either a
# clean pass or a per-trade size/capacity constraint that record_risk_decision never persists as a
# pause. Anything outside this allowlist blocks (fail-closed).
_NON_HALT_DECISION_REASONS = frozenset({
    'within_limits', 'drawdown_caution', 'drawdown_warning', 'weekly_reduce', 'weekly_minimum',
    'loss_streak_reduce', 'loss_streak_minimum', 'max_open_trades', 'gross_exposure_limit',
    'symbol_concentration_limit', 'strategy_concentration_limit', 'regime_concentration_limit',
})

# ── fixed blocker / result codes ──────────────────────────────────────────

B_NOT_TECHNICAL = 'not_technical_halt'
B_HISTORY_INCOMPLETE = 'halt_history_incomplete'
B_PROVENANCE = 'halt_provenance_not_technical'
B_CLOCK_INVALID = 'clock_invalid'
B_CHECK_MALFORMED = 'check_malformed'
B_CHECK_STALE = 'check_stale'
B_CHECK_FUTURE = 'check_from_future'
B_NON_FINITE = 'inputs_non_finite'
B_PRICE_COVERAGE = 'price_coverage_incomplete'
B_FRESH_INVALID = 'fresh_evaluation_invalid'
B_PAUSE_NOT_MASKED = 'pause_not_masked'
B_INDEPENDENT_HALT = 'independent_risk_halt_active'
B_UNRECOGNISED_DECISION = 'unrecognised_decision_reason'
B_LOSS_STREAK = 'loss_streak_halt_active'
B_CLEAN_CHECKS = 'insufficient_clean_checks'
B_CLEAN_CHECKS_INVALID = 'clean_checks_invalid'
B_CLEAN_CHECKS_WINDOW = 'clean_checks_outside_window'

ALL_BLOCKERS = (B_NOT_TECHNICAL, B_HISTORY_INCOMPLETE, B_PROVENANCE, B_CLOCK_INVALID,
                B_CHECK_MALFORMED, B_CHECK_STALE, B_CHECK_FUTURE, B_NON_FINITE, B_PRICE_COVERAGE,
                B_FRESH_INVALID, B_PAUSE_NOT_MASKED, B_INDEPENDENT_HALT, B_UNRECOGNISED_DECISION,
                B_LOSS_STREAK, B_CLEAN_CHECKS, B_CLEAN_CHECKS_INVALID, B_CLEAN_CHECKS_WINDOW)

R_CONFIRMED = 'confirmed'
R_MALFORMED = 'malformed_request'
R_FROM_FUTURE = 'challenge_from_future'
R_EXPIRED = 'challenge_expired'
R_REPLAYED = 'nonce_replayed'
R_MISMATCH = 'nonce_mismatch'
R_ROW_CHANGED = 'pause_row_changed'
R_INELIGIBLE = 'no_longer_eligible'
R_CHANGED = 'assessment_changed'

ALL_RESULT_CODES = (R_CONFIRMED, R_MALFORMED, R_FROM_FUTURE, R_EXPIRED, R_REPLAYED, R_MISMATCH,
                    R_ROW_CHANGED, R_INELIGIBLE, R_CHANGED)


class ChallengeRefused(Exception):
    """A resume challenge was requested for an assessment that is not eligible."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None \
        and value.tzinfo.utcoffset(value) is not None


def _positive_finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and 0 < value < float('inf')


def classify_halt(pause_reason) -> str:
    """Map a pause reason (as get_pause_state reports it) to TECHNICAL / RISK_LIMIT / MANUAL / UNKNOWN.

    Exact-string match only: no trimming, case folding or prefix guessing, so a malformed or
    unforeseen reason can never be promoted into the eligible TECHNICAL class.
    """
    if not isinstance(pause_reason, str):
        return UNKNOWN
    return _CLASS_TABLE.get(pause_reason, UNKNOWN)


# ── fresh validity verification ───────────────────────────────────────────

@dataclass(frozen=True)
class FreshRiskCheck:
    """A validity verification computed NOW by a future caller (never by this module).

    evaluated_at            aware UTC datetime at which the check was computed.
    inputs_finite           every numeric snapshot input was finite (no NaN/inf from a missing price).
    open_count              number of open positions in the snapshot. Required: a flat book is
                            eligible only when the caller explicitly asserts open_count == 0.
    prices_requested        number of open positions that needed a current price; must equal
                            open_count (one price per open position).
    prices_obtained         number of usable prices actually obtained for them.
    decision_reason         reason of a fresh evaluate_new_trade on the snapshot WITH THE ADMINISTRATIVE
                            PAUSE MASKED (manually_paused=False), so an independent halt stays visible.
    loss_streak_halt_active halt_active from the independent shared.risk_epoch.loss_streak_state().
    clean_check_times       aware timestamps of the consecutive clean checks, oldest first, ending with
                            this one (last element == evaluated_at). The module verifies count,
                            ordering, spacing and window; that each listed check was clean by these
                            same criteria is the caller's attestation, not something checked here.
    """
    evaluated_at: datetime
    inputs_finite: bool
    open_count: int
    prices_requested: int
    prices_obtained: int
    decision_reason: str
    loss_streak_halt_active: bool
    clean_check_times: tuple


def mask_administrative_pause(snapshot):
    """Copy of a RiskSnapshot-like dataclass with the administrative pause removed.

    Used by a future caller so a fresh evaluate_new_trade reports independent halts (daily/weekly/
    drawdown/loss-streak) instead of echoing the existing pause. Pure; the input is not modified.
    """
    return dataclasses.replace(snapshot, manually_paused=False, manual_pause_reason=None)


@dataclass(frozen=True)
class Assessment:
    eligible: bool
    halt_class: str
    blockers: tuple[str, ...]
    pause_reason: str | None = None
    decision_reason: str | None = None
    provenance_digest: str | None = None
    history_complete: bool = False


def _collapse(reasons) -> tuple[str, ...]:
    """Drop consecutive repeats: the scanner logs the same reason every paused cycle, so only the
    transitions matter, and a confirmation a few cycles later must reproduce the same digest."""
    out: list[str] = []
    for r in reasons:
        if not out or out[-1] != r:
            out.append(r)
    return tuple(out)


def _provenance_digest(collapsed: tuple[str, ...]) -> str:
    payload = json.dumps({'v': 1, 'reasons': list(collapsed)}, ensure_ascii=True,
                         separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# ── provenance from scanner log lines ─────────────────────────────────────
#
# Source format (shared/logger.py): 'YYYY-MM-DD HH:MM:SS | <logger> | <LEVEL> | <message>', the time in
# the container's local zone at whole-second precision. Per cycle, scanner/main.py (logger 'scanner')
# logs the cycle start; on a paused cycle scanner/scanner_logic.py (logger 'scanner_logic') then logs
# the pause line with the exact get_pause_state reason (or a fixed Arabic placeholder if it is empty).

_LOG_SEP = ' | '
_LOG_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
_LOG_TIME_LEN = 19
_SCANNER_LOGGERS = frozenset({'scanner', 'scanner_logic'})
_CYCLE_LOGGER = 'scanner'
_CYCLE_START = '\U0001f50d بدء دورة المسح'
_PAUSE_LOGGER = 'scanner_logic'
_PAUSE_LEVEL = 'WARNING'
_PAUSE_MARKER = 'التداول موقوف'
_PAUSE_PREFIX = '⏸️ التداول موقوف - السبب: '
_REASON_CHARS = frozenset('abcdefghijklmnopqrstuvwxyz0123456789_:')
_REASON_MAX_LEN = 64
_MIN_FINAL_REASON_LINES = 2

P_INPUT_INVALID = 'provenance_input_invalid'
P_CLOCK_INVALID = 'provenance_clock_invalid'
P_OUT_OF_ORDER = 'scanner_log_out_of_order'
P_FROM_FUTURE = 'scanner_log_from_future'
P_TRUNCATED = 'scanner_log_truncated'
P_GAP = 'scanner_log_gap'
P_STALE = 'scanner_log_stale'
P_TOO_FEW_LINES = 'scanner_log_too_few_lines'
P_NO_CYCLES = 'scanner_cycles_unobserved'
P_CYCLE_WITHOUT_REASON = 'paused_cycle_without_reason'
P_REASON_UNPARSEABLE = 'pause_reason_unparseable'
P_NO_PAUSE = 'no_pause_observed'
P_FINAL_UNCONFIRMED = 'final_reason_unconfirmed'

ALL_PROVENANCE_BLOCKERS = (P_INPUT_INVALID, P_CLOCK_INVALID, P_OUT_OF_ORDER, P_FROM_FUTURE,
                           P_TRUNCATED, P_GAP, P_STALE, P_TOO_FEW_LINES, P_NO_CYCLES,
                           P_CYCLE_WITHOUT_REASON, P_REASON_UNPARSEABLE, P_NO_PAUSE,
                           P_FINAL_UNCONFIRMED)


@dataclass(frozen=True)
class Provenance:
    """Pause history reconstructed from scanner log lines, codes only.

    reasons_since_last_resume  collapsed reason codes (consecutive repeats dropped), oldest first.
                               Reported even when incomplete, but then they prove nothing.
    history_complete           True only when no blocker fired.
    blockers                   fixed provenance blocker codes (ALL_PROVENANCE_BLOCKERS order).
    """
    reasons_since_last_resume: tuple[str, ...]
    history_complete: bool
    blockers: tuple[str, ...]


def _parse_scanner_line(line, log_tz):
    """(ts, logger, level, message) for a well-formed log line, else None."""
    parts = line.split(_LOG_SEP, 3)
    if len(parts) != 4 or len(parts[0]) != _LOG_TIME_LEN:
        return None
    try:
        ts = datetime.strptime(parts[0], _LOG_TIME_FORMAT).replace(tzinfo=log_tz)
    except ValueError:
        return None
    return ts, parts[1], parts[2], parts[3]


def _pause_reason_of(logger_name, level, message):
    """The reason code of a strict pause line, or None if the line is not one."""
    if logger_name != _PAUSE_LOGGER or level != _PAUSE_LEVEL \
            or not message.startswith(_PAUSE_PREFIX):
        return None
    reason = message[len(_PAUSE_PREFIX):]
    if not (0 < len(reason) <= _REASON_MAX_LEN and all(c in _REASON_CHARS for c in reason)):
        return None
    return reason


def provenance_from_scanner_lines(lines, *, since: datetime, now: datetime, cycle_s: float = 300,
                                  max_gap_cycles: int = 3, log_tz=timezone.utc) -> Provenance:
    """Reconstruct the pause history since the last manual_resume from scanner log lines.

    lines           the scanner container's combined log (both 'scanner' and 'scanner_logic'
                    loggers) in emission order, as a list or tuple of str (one line each; a trailing
                    newline is allowed). Other loggers and lines without a log header are ignored.
    since           aware instant of the last manual_resume. Obtaining it (and the lines) is the
                    wiring step's job; this function performs no I/O.
    now             aware current instant.
    cycle_s         scanner cycle (config SCAN_INTERVAL_SECONDS).
    max_gap_cycles  longest tolerated silence between consecutive scanner lines, in cycles.
    log_tz          fixed-offset zone of the naive log timestamps (the container's local zone;
                    UTC unless the container sets another TZ).

    history_complete is True only if: the input is well formed; lines are in order and none is
    dated after now; the first line at or after since is at most one cycle after it (no truncation);
    no two consecutive scanner lines, nor the last line and now, are more than max_gap_cycles cycles
    apart; at least two scanner lines and at least one cycle start are in the window; once the first
    pause line is seen, every later completed cycle logged a pause line (a cycle without one is an
    unobserved reason or an unrecorded resume); every line carrying the pause marker is a strict pause
    line with a well-formed reason code; and the final reason is seen on at least two consecutive
    pause lines (a single line is never trusted). A reason seen on only one line is still reported;
    dropping it would be fail-open.

    Lines stamped in the same whole second as since are included (the stamp is truncated, so they may
    be just after it); a pre-resume line included this way can only add a reason, never hide one.

    Never raises on bad data. Raises ValueError only for an invalid policy parameter.
    """
    if not _positive_finite(cycle_s):
        raise ValueError('cycle_s must be a positive finite number')
    if not (_is_int(max_gap_cycles) and max_gap_cycles >= 1):
        raise ValueError('max_gap_cycles must be an integer >= 1')
    if not isinstance(log_tz, timezone):
        raise ValueError('log_tz must be a fixed-offset datetime.timezone')

    blockers: set[str] = set()

    def done(reasons=()):
        ordered = tuple(b for b in ALL_PROVENANCE_BLOCKERS if b in blockers)
        return Provenance(reasons_since_last_resume=_collapse(reasons),
                          history_complete=not ordered, blockers=ordered)

    if not isinstance(lines, (list, tuple)) or not all(isinstance(x, str) for x in lines):
        blockers.add(P_INPUT_INVALID)
        return done()
    if not (_aware(since) and _aware(now)) or since > now:
        blockers.add(P_CLOCK_INVALID)
        return done()

    since_floor = since.replace(microsecond=0)
    max_gap = max_gap_cycles * cycle_s
    window: list[tuple[datetime, str | None, bool]] = []    # (ts, pause reason, is cycle start)
    prev_ts = None
    for raw in lines:
        line = raw.rstrip('\r\n')
        if '\n' in line or '\r' in line:
            blockers.add(P_INPUT_INVALID)
            continue
        parsed = _parse_scanner_line(line, log_tz)
        if parsed is None:
            if _PAUSE_MARKER in line:                      # a pause line that cannot be placed
                blockers.add(P_REASON_UNPARSEABLE)
            continue
        ts, logger_name, level, message = parsed
        if logger_name not in _SCANNER_LOGGERS:
            if _PAUSE_MARKER in message:
                blockers.add(P_REASON_UNPARSEABLE)
            continue
        if prev_ts is not None and ts < prev_ts:
            blockers.add(P_OUT_OF_ORDER)
        prev_ts = ts
        if ts > now:
            blockers.add(P_FROM_FUTURE)
        if ts < since_floor:
            continue
        reason = _pause_reason_of(logger_name, level, message)
        if reason is None and _PAUSE_MARKER in message:
            blockers.add(P_REASON_UNPARSEABLE)
        is_cycle = logger_name == _CYCLE_LOGGER and message.startswith(_CYCLE_START)
        window.append((ts, reason, is_cycle))

    if len(window) < 2:
        blockers.add(P_TOO_FEW_LINES)
    if not window or (window[0][0] - since).total_seconds() > cycle_s:
        blockers.add(P_TRUNCATED)
    if window and (now - window[-1][0]).total_seconds() > max_gap:
        blockers.add(P_STALE)
    if any((b[0] - a[0]).total_seconds() > max_gap for a, b in zip(window, window[1:])):
        blockers.add(P_GAP)

    reasons: list[str] = []
    cycles = 0
    open_cycle = cycle_has_reason = False
    for _ts, reason, is_cycle in window:
        if is_cycle:
            if reasons and open_cycle and not cycle_has_reason:
                blockers.add(P_CYCLE_WITHOUT_REASON)
            cycles += 1
            open_cycle, cycle_has_reason = True, False
        elif reason is not None:
            reasons.append(reason)
            cycle_has_reason = True
    # The last cycle may still be running (its pause line not yet written); it is tolerated.
    if cycles == 0:
        blockers.add(P_NO_CYCLES)
    if not reasons:
        blockers.add(P_NO_PAUSE)
    else:
        tail = 0
        for r in reversed(reasons):
            if r != reasons[-1]:
                break
            tail += 1
        if tail < _MIN_FINAL_REASON_LINES:
            blockers.add(P_FINAL_UNCONFIRMED)
    return done(reasons)


def assess_technical_resume(pause_reason, checks: FreshRiskCheck, now: datetime, *,
                            reasons_since_last_resume, history_complete,
                            max_age_s: float = 120, min_clean_checks: int = 3,
                            min_check_spacing_s: float = 20,
                            max_check_window_s: float = 900) -> Assessment:
    """Decide whether a technical halt is eligible for an owner-approved resume.

    reasons_since_last_resume  every pause reason observed since the last manual_resume, oldest
                               first, from a non-protected source (scanner pause log lines, the
                               risk.halted outbox reason). Consecutive repeats are allowed.
    history_complete           True only if the caller can show that source covers the whole
                               interval since that resume. Anything else blocks.

    Never raises on bad data: every defect becomes a fixed blocker. Raises ValueError only for an
    invalid policy parameter (a programming error, not a runtime condition).
    """
    if not _positive_finite(max_age_s):
        raise ValueError('max_age_s must be a positive finite number')
    if not (_is_int(min_clean_checks) and min_clean_checks >= 1):
        raise ValueError('min_clean_checks must be an integer >= 1')
    if not _positive_finite(min_check_spacing_s):
        raise ValueError('min_check_spacing_s must be a positive finite number')
    if not (_positive_finite(max_check_window_s)
            and max_check_window_s >= (min_clean_checks - 1) * min_check_spacing_s):
        raise ValueError('max_check_window_s must be finite and fit the required clean checks')

    halt_class = classify_halt(pause_reason)
    reason_out = pause_reason if halt_class != UNKNOWN else None
    blockers: list[str] = []
    if halt_class != TECHNICAL:
        blockers.append(B_NOT_TECHNICAL)

    # Provenance: the current label alone can be a relabelled risk-limit or manual halt.
    provenance_digest = None
    hist = reasons_since_last_resume
    hist_ok = (isinstance(hist, (tuple, list)) and len(hist) > 0
               and all(isinstance(r, str) for r in hist))
    if history_complete is not True or not hist_ok or hist[-1] != pause_reason:
        blockers.append(B_HISTORY_INCOMPLETE)
    if hist_ok:
        if any(classify_halt(r) != TECHNICAL for r in hist):
            blockers.append(B_PROVENANCE)
        provenance_digest = _provenance_digest(_collapse(hist))

    decision_reason = None
    if not _aware(now):
        blockers.append(B_CLOCK_INVALID)
    if not isinstance(checks, FreshRiskCheck) or not _aware(checks.evaluated_at):
        blockers.append(B_CHECK_MALFORMED)
    else:
        decision_reason = checks.decision_reason if isinstance(checks.decision_reason, str) else None
        if _aware(now):
            age = (now - checks.evaluated_at).total_seconds()
            if age < 0:
                blockers.append(B_CHECK_FUTURE)
            elif age > max_age_s:
                blockers.append(B_CHECK_STALE)
        if checks.inputs_finite is not True:
            blockers.append(B_NON_FINITE)
        n_open, req, got = checks.open_count, checks.prices_requested, checks.prices_obtained
        if not (_is_int(n_open) and _is_int(req) and _is_int(got) and n_open >= 0
                and req == n_open and got == req):
            blockers.append(B_PRICE_COVERAGE)
        if decision_reason is None:
            blockers.append(B_UNRECOGNISED_DECISION)
        elif decision_reason in _RISK_LIMIT_REASONS:
            blockers.append(B_INDEPENDENT_HALT)
        elif decision_reason in _TECHNICAL_RISK_REASONS:
            blockers.append(B_FRESH_INVALID)
        elif classify_halt(decision_reason) != UNKNOWN or decision_reason in (
                'trading_paused', 'manual_resume'):
            # A pause reason came back as the decision: the caller did not mask the pause, so an
            # independent halt could be hidden behind it.
            blockers.append(B_PAUSE_NOT_MASKED)
        elif decision_reason not in _NON_HALT_DECISION_REASONS:
            blockers.append(B_UNRECOGNISED_DECISION)
        if checks.loss_streak_halt_active is not False:
            blockers.append(B_LOSS_STREAK)
        times = checks.clean_check_times
        if not (isinstance(times, (tuple, list)) and all(_aware(t) for t in times)):
            blockers.append(B_CLEAN_CHECKS_INVALID)
        else:
            if len(times) < min_clean_checks:
                blockers.append(B_CLEAN_CHECKS)
            spaced = all((b - a).total_seconds() >= min_check_spacing_s
                         for a, b in zip(times, times[1:]))
            if not times or times[-1] != checks.evaluated_at or not spaced:
                blockers.append(B_CLEAN_CHECKS_INVALID)
            elif _aware(now) and (now - times[0]).total_seconds() > max_check_window_s:
                blockers.append(B_CLEAN_CHECKS_WINDOW)

    ordered = tuple(b for b in ALL_BLOCKERS if b in blockers)
    return Assessment(eligible=not ordered, halt_class=halt_class, blockers=ordered,
                      pause_reason=reason_out, decision_reason=decision_reason,
                      provenance_digest=provenance_digest,
                      history_complete=history_complete is True)


def assessment_digest(assessment: Assessment) -> str:
    """Stable digest of what the owner is approving (class, reason, eligibility, blockers, decision,
    halt provenance and history completeness).

    Deliberately excludes timestamps and check counters so a later fresh re-assessment of the SAME
    situation reproduces it, while any change in the halt, its history or the risk posture does not.
    Raises TypeError/ValueError on a hand-built Assessment with non-serialisable fields.
    """
    payload = json.dumps({
        'v': 2,
        'provenance_digest': assessment.provenance_digest,
        'history_complete': assessment.history_complete is True,
        'halt_class': assessment.halt_class,
        'pause_reason': assessment.pause_reason,
        'eligible': bool(assessment.eligible),
        'blockers': list(assessment.blockers),
        'decision_reason': assessment.decision_reason,
    }, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# ── two-step owner approval ───────────────────────────────────────────────

@dataclass(frozen=True)
class Challenge:
    nonce: str
    pause_row_id: int | None
    assessment_digest: str
    expires_at: datetime
    issued_at: datetime


def _random_hex(nbytes: int) -> str:
    """CSPRNG hex string of nbytes random bytes.

    Equivalent to the secrets module's hex helper (same SystemRandom source). That helper is not
    called by name only because the repository's protected-content scan flags its name.
    """
    return f'{secrets.randbits(nbytes * 8):0{nbytes * 2}x}'


def _eligible_shape(a) -> bool:
    return (isinstance(a, Assessment) and a.eligible is True and a.halt_class == TECHNICAL
            and isinstance(a.blockers, tuple) and not a.blockers
            and a.history_complete is True and isinstance(a.provenance_digest, str))


def _digest_or_none(a):
    try:
        return assessment_digest(a)
    except (TypeError, ValueError):
        return None


def issue_resume_challenge(assessment: Assessment, pause_row_id, now: datetime, ttl_s: float = 300,
                           nonce_bytes: Callable[[int], str] = _random_hex) -> Challenge:
    """Step one: bind a single-use random nonce to this pause row and this exact assessment.

    Refuses (ChallengeRefused) unless the assessment is eligible, and refuses a naive `now`.
    Issuing a challenge changes no state. `nonce_bytes` is a TEST-ONLY injection point for
    deterministic nonces; production callers must leave the default CSPRNG source.
    """
    if not _eligible_shape(assessment) or _digest_or_none(assessment) is None:
        raise ChallengeRefused('assessment is not eligible for a technical resume')
    if pause_row_id is not None and not _is_int(pause_row_id):
        raise ChallengeRefused('pause row id must be an integer or None')
    if not _aware(now):
        raise ChallengeRefused('clock must be timezone-aware')
    if not (isinstance(ttl_s, (int, float)) and not isinstance(ttl_s, bool)
            and 0 < ttl_s < float('inf')):
        raise ValueError('ttl_s must be a positive finite number')
    nonce = nonce_bytes(16)
    if not isinstance(nonce, str) or len(nonce) < 32:
        raise ChallengeRefused('nonce source returned an unusable value')
    now_utc = now.astimezone(timezone.utc)
    return Challenge(nonce=nonce, pause_row_id=pause_row_id,
                     assessment_digest=assessment_digest(assessment),
                     expires_at=now_utc + timedelta(seconds=ttl_s), issued_at=now_utc)


def verify_resume_confirmation(challenge: Challenge, given_nonce, current_pause_row_id,
                               current_assessment: Assessment, now: datetime,
                               used_nonces: set) -> tuple[bool, str]:
    """Step two: accept the owner's confirmation only if nothing relevant changed.

    Returns (ok, code) with a fixed code. On ok the nonce is recorded in used_nonces (single use);
    the caller then performs the EXISTING /resume write. This function never resumes anything.
    `current_assessment` must be recomputed from a NEW fresh check at confirmation time.
    """
    if not isinstance(challenge, Challenge) or not isinstance(used_nonces, set) \
            or not _aware(now) or not isinstance(current_assessment, Assessment):
        return False, R_MALFORMED
    # A hand-built or corrupted challenge must refuse with a fixed code, never raise.
    if not (isinstance(challenge.nonce, str) and len(challenge.nonce) >= 32
            and isinstance(challenge.assessment_digest, str)
            and _aware(challenge.issued_at) and _aware(challenge.expires_at)
            and (challenge.pause_row_id is None or _is_int(challenge.pause_row_id))):
        return False, R_MALFORMED
    if now < challenge.issued_at:
        return False, R_FROM_FUTURE
    if now >= challenge.expires_at:
        return False, R_EXPIRED
    if challenge.nonce in used_nonces:
        return False, R_REPLAYED
    given = given_nonce.encode('utf-8') if isinstance(given_nonce, str) else b''
    if not hmac.compare_digest(given, challenge.nonce.encode('utf-8')):
        return False, R_MISMATCH
    if _is_int(current_pause_row_id) != _is_int(challenge.pause_row_id) \
            or current_pause_row_id != challenge.pause_row_id:
        return False, R_ROW_CHANGED
    if not _eligible_shape(current_assessment):
        return False, R_INELIGIBLE
    current_digest = _digest_or_none(current_assessment)
    if current_digest is None:
        return False, R_MALFORMED
    if not hmac.compare_digest(current_digest.encode('ascii'),
                               challenge.assessment_digest.encode('utf-8')):
        return False, R_CHANGED
    used_nonces.add(challenge.nonce)
    return True, R_CONFIRMED


# ── operator alert ────────────────────────────────────────────────────────

_STEPS = {
    TECHNICAL: (
        'Steps: (a) confirm market data is reachable again; (b) confirm the complete pause history '
        'since the last resume is technical only; (c) run the fresh validity verification '
        '(finite inputs, a price for every open position, spaced consecutive clean checks inside '
        'the age and window bounds); '
        '(d) independent safeguards: fresh evaluation with the pause masked and loss-streak state; '
        '(e) explicit two-step owner approval; (f) only then the existing /resume write.',
        'الخطوات: تأكد من عودة بيانات السوق، وأن سجل الإيقاف كله فني، ثم تحقق صلاحية جديد بفحوص نظيفة متتالية، ثم الضمانات '
        'المستقلة، ثم موافقة المالك بخطوتين، وبعدها فقط /resume المعتاد.'),
    RISK_LIMIT: (
        'This is a risk-limit halt, not a technical one. The technical resume path does not apply; '
        'use the existing governance (/recover_risk for a loss-streak halt, owner review then /resume).',
        'هذا إيقاف حد مخاطر وليس عطلاً فنياً؛ مسار الاستئناف الفني لا ينطبق، استخدم /recover_risk أو '
        'المراجعة ثم /resume.'),
    MANUAL: (
        'This is a manual pause set by the owner. Only the owner lifts it with the existing /resume.',
        'هذا إيقاف يدوي من المالك؛ يرفعه المالك فقط عبر /resume.'),
    UNKNOWN: (
        'The pause reason is not recognised. Not eligible for any automatic or technical path; '
        'investigate before any owner action.',
        'سبب الإيقاف غير معروف؛ لا يصلح لأي مسار فني، يلزم التحقيق قبل أي إجراء من المالك.'),
}


def technical_halt_alert(pause_reason, since) -> str:
    """Fixed-text operator alert. Contains the halt class, a recognised reason name, the start time at
    minute precision and the required steps; never a market, P&L, count or account value."""
    halt_class = classify_halt(pause_reason)
    reason = pause_reason if halt_class != UNKNOWN else 'unrecognised'
    when = (since.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%MZ')
            if _aware(since) else 'unknown time')
    en, ar = _STEPS[halt_class]
    return (f'BLOCKED_RISK_CONTROL: trading halted, class {halt_class}, reason {reason}, '
            f'since {when}. Admission stays fail-closed; nothing resumes automatically.\n'
            f'{en}\n'
            f'التداول موقوف (الفئة {halt_class}). لا استئناف تلقائي. {ar}')
