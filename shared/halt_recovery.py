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

Invariants (pinned by tests/test_halt_recovery.py):
- Only TECHNICAL halts can ever be assessed eligible. RISK_LIMIT, MANUAL and UNKNOWN never are; they
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

ALL_BLOCKERS = (B_NOT_TECHNICAL, B_CLOCK_INVALID, B_CHECK_MALFORMED, B_CHECK_STALE, B_CHECK_FUTURE,
                B_NON_FINITE, B_PRICE_COVERAGE, B_FRESH_INVALID, B_PAUSE_NOT_MASKED,
                B_INDEPENDENT_HALT, B_UNRECOGNISED_DECISION, B_LOSS_STREAK, B_CLEAN_CHECKS)

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
    prices_requested        number of open positions that needed a current price.
    prices_obtained         number of usable prices actually obtained for them.
    decision_reason         reason of a fresh evaluate_new_trade on the snapshot WITH THE ADMINISTRATIVE
                            PAUSE MASKED (manually_paused=False), so an independent halt stays visible.
    loss_streak_halt_active halt_active from the independent shared.risk_epoch.loss_streak_state().
    consecutive_clean_checks number of consecutive checks, ending with this one, that were clean.
    """
    evaluated_at: datetime
    inputs_finite: bool
    prices_requested: int
    prices_obtained: int
    decision_reason: str
    loss_streak_halt_active: bool
    consecutive_clean_checks: int


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


def assess_technical_resume(pause_reason, checks: FreshRiskCheck, now: datetime, *,
                            max_age_s: float = 120, min_clean_checks: int = 3) -> Assessment:
    """Decide whether a technical halt is eligible for an owner-approved resume.

    Never raises on bad data: every defect becomes a fixed blocker. Raises ValueError only for an
    invalid policy parameter (a programming error, not a runtime condition).
    """
    if not (isinstance(max_age_s, (int, float)) and not isinstance(max_age_s, bool)
            and 0 < max_age_s < float('inf')):
        raise ValueError('max_age_s must be a positive finite number')
    if not (_is_int(min_clean_checks) and min_clean_checks >= 1):
        raise ValueError('min_clean_checks must be an integer >= 1')

    halt_class = classify_halt(pause_reason)
    reason_out = pause_reason if halt_class != UNKNOWN else None
    blockers: list[str] = []
    if halt_class != TECHNICAL:
        blockers.append(B_NOT_TECHNICAL)

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
        req, got = checks.prices_requested, checks.prices_obtained
        if not (_is_int(req) and _is_int(got) and req >= 0 and got == req):
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
        clean = checks.consecutive_clean_checks
        if not (_is_int(clean) and clean >= min_clean_checks):
            blockers.append(B_CLEAN_CHECKS)

    ordered = tuple(b for b in ALL_BLOCKERS if b in blockers)
    return Assessment(eligible=not ordered, halt_class=halt_class, blockers=ordered,
                      pause_reason=reason_out, decision_reason=decision_reason)


def assessment_digest(assessment: Assessment) -> str:
    """Stable digest of what the owner is approving (class, reason, eligibility, blockers, decision).

    Deliberately excludes timestamps and check counters so a later fresh re-assessment of the SAME
    situation reproduces it, while any change in the halt or the risk posture does not.
    """
    payload = json.dumps({
        'v': 1,
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
    """CSPRNG hex string of nbytes random bytes (same source as the secrets module's helpers)."""
    return f'{secrets.randbits(nbytes * 8):0{nbytes * 2}x}'


def issue_resume_challenge(assessment: Assessment, pause_row_id, now: datetime, ttl_s: float = 300,
                           nonce_bytes: Callable[[int], str] = _random_hex) -> Challenge:
    """Step one: bind a single-use random nonce to this pause row and this exact assessment.

    Refuses (ChallengeRefused) unless the assessment is eligible. Issuing a challenge changes no state.
    """
    if not isinstance(assessment, Assessment) or assessment.eligible is not True \
            or assessment.halt_class != TECHNICAL or assessment.blockers:
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
    if current_assessment.eligible is not True or current_assessment.blockers \
            or current_assessment.halt_class != TECHNICAL:
        return False, R_INELIGIBLE
    if not hmac.compare_digest(assessment_digest(current_assessment), challenge.assessment_digest):
        return False, R_CHANGED
    used_nonces.add(challenge.nonce)
    return True, R_CONFIRMED


# ── operator alert ────────────────────────────────────────────────────────

_STEPS = {
    TECHNICAL: (
        'Steps: (a) confirm market data is reachable again; (b) run the fresh validity verification '
        '(finite inputs, full price coverage, consecutive clean checks within the age bound); '
        '(c) independent safeguards: fresh evaluation with the pause masked and loss-streak state; '
        '(d) explicit two-step owner approval; (e) only then the existing /resume write.',
        'الخطوات: تأكد من عودة بيانات السوق، ثم تحقق صلاحية جديد بفحوص نظيفة متتالية، ثم الضمانات '
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
