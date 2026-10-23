"""Technical-halt recovery (design and test only): shared/halt_recovery.py plus fault injection on the
REAL tracker admission path.

No production access: the database facade, the pause state and the HTTP client are fakes. The
fault-injection tests document the incident chain (price fetch timeout -> None -> NaN unrealized ->
invalid_risk_state) and pin the stickiness invariant the owner wants preserved.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared import halt_recovery as hr
from shared.halt_recovery import (
    FreshRiskCheck, assess_technical_resume, classify_halt, issue_resume_challenge,
    technical_halt_alert, verify_resume_confirmation)

try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service', allow_module_level=True)

UTC = timezone.utc
NOW = datetime(2026, 10, 21, 20, 30, tzinfo=UTC)
TECH = 'risk:invalid_risk_state'


def spaced(end, n=3, gap=30):
    return tuple(end - timedelta(seconds=gap * i) for i in reversed(range(n)))


def clean(**kw):
    base = dict(evaluated_at=NOW - timedelta(seconds=5), inputs_finite=True, open_count=2,
                prices_requested=2, prices_obtained=2, decision_reason='within_limits',
                loss_streak_halt_active=False)
    base.update(kw)
    base.setdefault('clean_check_times', spaced(base['evaluated_at']))
    return FreshRiskCheck(**base)


_DEFAULT = object()


def A(reason, checks, now, hist=_DEFAULT, complete=True, **kw):
    """assess_technical_resume with a complete history consisting of the current reason only."""
    if hist is _DEFAULT:
        hist = (reason,)
    return assess_technical_resume(reason, checks, now, reasons_since_last_resume=hist,
                                   history_complete=complete, **kw)


# ── classification ────────────────────────────────────────────────────────

@pytest.mark.parametrize('reason,expected', [
    ('risk:invalid_risk_state', hr.TECHNICAL),
    ('invalid_risk_state', hr.TECHNICAL),
    ('risk_state_missing', hr.TECHNICAL),
    ('risk_state_inconsistent', hr.TECHNICAL),
    ('risk:daily_loss_limit', hr.RISK_LIMIT),
    ('risk:weekly_loss_limit', hr.RISK_LIMIT),
    ('risk:max_drawdown_limit', hr.RISK_LIMIT),
    ('risk:loss_streak_halt', hr.RISK_LIMIT),
    ('daily_loss_limit', hr.RISK_LIMIT),
    ('loss_streak_halt', hr.RISK_LIMIT),
    ('manual_pause', hr.MANUAL),
    ('manual_resume', hr.UNKNOWN),
    ('trading_paused', hr.UNKNOWN),
    ('risk:', hr.UNKNOWN),
    ('risk:risk_state_missing', hr.UNKNOWN),
    ('risk:manual_pause', hr.UNKNOWN),
    ('RISK:invalid_risk_state', hr.UNKNOWN),
    (' risk:invalid_risk_state', hr.UNKNOWN),
    ('gross_exposure_limit', hr.UNKNOWN),
    ('', hr.UNKNOWN),
    (None, hr.UNKNOWN),
    (7, hr.UNKNOWN),
])
def test_classification_table(reason, expected):
    assert classify_halt(reason) == expected


def test_classification_uses_the_code_constants():
    from shared.trading_state import RISK_STATE_INCONSISTENT, RISK_STATE_MISSING
    assert classify_halt(RISK_STATE_MISSING) == hr.TECHNICAL
    assert classify_halt(RISK_STATE_INCONSISTENT) == hr.TECHNICAL


# ── assessment and blockers ───────────────────────────────────────────────

def test_clean_technical_halt_is_eligible():
    a = A(TECH, clean(), NOW)
    assert a.eligible and a.halt_class == hr.TECHNICAL and a.blockers == ()


def test_flat_book_needs_no_prices_only_when_asserted():
    a = A(TECH, clean(open_count=0, prices_requested=0, prices_obtained=0), NOW)
    assert a.eligible
    # Zero prices for a book that is not asserted flat is a coverage gap, not a pass.
    for kw in (dict(open_count=2, prices_requested=0, prices_obtained=0),
               dict(open_count=None, prices_requested=0, prices_obtained=0),
               dict(open_count=-1, prices_requested=-1, prices_obtained=-1),
               dict(open_count=3, prices_requested=2, prices_obtained=2)):
        assert A(TECH, clean(**kw), NOW).blockers == ('price_coverage_incomplete',), kw


@pytest.mark.parametrize('kw,blocker', [
    (dict(evaluated_at=NOW - timedelta(seconds=121)), 'check_stale'),
    (dict(evaluated_at=NOW + timedelta(seconds=1)), 'check_from_future'),
    (dict(evaluated_at=NOW.replace(tzinfo=None)), 'check_malformed'),
    (dict(inputs_finite=False), 'inputs_non_finite'),
    (dict(inputs_finite=1), 'inputs_non_finite'),
    (dict(prices_obtained=1), 'price_coverage_incomplete'),
    (dict(prices_obtained=3), 'price_coverage_incomplete'),
    (dict(open_count=-1, prices_requested=-1, prices_obtained=-1), 'price_coverage_incomplete'),
    (dict(open_count=True, prices_requested=1, prices_obtained=1), 'price_coverage_incomplete'),
    (dict(prices_obtained=True, prices_requested=1), 'price_coverage_incomplete'),
    (dict(decision_reason='daily_loss_limit'), 'independent_risk_halt_active'),
    (dict(decision_reason='weekly_loss_limit'), 'independent_risk_halt_active'),
    (dict(decision_reason='max_drawdown_limit'), 'independent_risk_halt_active'),
    (dict(decision_reason='loss_streak_halt'), 'independent_risk_halt_active'),
    (dict(decision_reason='invalid_risk_state'), 'fresh_evaluation_invalid'),
    (dict(decision_reason='risk:invalid_risk_state'), 'pause_not_masked'),
    (dict(decision_reason='manual_pause'), 'pause_not_masked'),
    (dict(decision_reason='trading_paused'), 'pause_not_masked'),
    (dict(decision_reason='something_new'), 'unrecognised_decision_reason'),
    (dict(decision_reason=None), 'unrecognised_decision_reason'),
    (dict(loss_streak_halt_active=True), 'loss_streak_halt_active'),
    (dict(loss_streak_halt_active=None), 'loss_streak_halt_active'),
    (dict(clean_check_times=spaced(NOW - timedelta(seconds=5), n=2)), 'insufficient_clean_checks'),
    (dict(clean_check_times=()), 'insufficient_clean_checks'),
    (dict(clean_check_times=3), 'clean_checks_invalid'),
    (dict(clean_check_times=None), 'clean_checks_invalid'),
])
def test_each_blocker(kw, blocker):
    a = A(TECH, clean(**kw), NOW)
    assert not a.eligible
    assert blocker in a.blockers
    assert set(a.blockers) <= set(hr.ALL_BLOCKERS)


def test_age_bound_is_inclusive_and_configurable():
    assert A(TECH, clean(evaluated_at=NOW - timedelta(seconds=120)), NOW).eligible
    a = A(TECH, clean(evaluated_at=NOW - timedelta(seconds=30)), NOW, max_age_s=20)
    assert a.blockers == ('check_stale',)
    a = A(TECH, clean(clean_check_times=spaced(NOW - timedelta(seconds=5), n=4)), NOW,
          min_clean_checks=5)
    assert a.blockers == ('insufficient_clean_checks',)


def test_clean_check_sequence_is_verified_not_trusted():
    e = NOW - timedelta(seconds=5)
    ok = A(TECH, clean(clean_check_times=spaced(e, n=5, gap=20)), NOW)
    assert ok.eligible, 'more checks than required is fine; spacing equal to the minimum is fine'
    cases = [
        ((e - timedelta(seconds=40), e - timedelta(seconds=20), e - timedelta(seconds=1)),
         'clean_checks_invalid'),                                    # last != evaluated_at
        ((e - timedelta(seconds=40), e - timedelta(seconds=41), e), 'clean_checks_invalid'),
        ((e - timedelta(seconds=40), e - timedelta(seconds=40), e), 'clean_checks_invalid'),
        ((e - timedelta(seconds=40), e - timedelta(seconds=30), e), 'clean_checks_invalid'),
        ((e - timedelta(seconds=40), (e - timedelta(seconds=20)).replace(tzinfo=None), e),
         'clean_checks_invalid'),
        (spaced(e, n=3, gap=600), 'clean_checks_outside_window'),     # oldest 1205 s ago
    ]
    for times, blocker in cases:
        a = A(TECH, clean(clean_check_times=times), NOW)
        assert a.blockers == (blocker,), (times, a.blockers)
    # Window is configurable; policy that cannot be met is a programming error.
    assert A(TECH, clean(clean_check_times=spaced(e, gap=600)), NOW,
             max_check_window_s=1300).eligible
    with pytest.raises(ValueError):
        A(TECH, clean(), NOW, min_check_spacing_s=0)
    with pytest.raises(ValueError):
        A(TECH, clean(), NOW, min_clean_checks=3, min_check_spacing_s=60, max_check_window_s=100)


def test_soft_reasons_do_not_block():
    for reason in ('drawdown_caution', 'weekly_reduce', 'loss_streak_reduce', 'max_open_trades',
                   'gross_exposure_limit', 'symbol_concentration_limit'):
        assert A(TECH, clean(decision_reason=reason), NOW).eligible


def test_malformed_inputs_never_raise_and_never_eligible():
    assert A(TECH, None, NOW).blockers == ('check_malformed',)
    a = A(TECH, clean(), NOW.replace(tzinfo=None))
    assert not a.eligible and 'clock_invalid' in a.blockers
    with pytest.raises(ValueError):
        A(TECH, clean(), NOW, max_age_s=0)
    with pytest.raises(ValueError):
        A(TECH, clean(), NOW, min_clean_checks=0)


@pytest.mark.parametrize('reason', ['risk:daily_loss_limit', 'risk:weekly_loss_limit',
                                    'risk:max_drawdown_limit', 'risk:loss_streak_halt',
                                    'manual_pause', 'manual_resume', 'trading_paused', None, 'x'])
def test_non_technical_never_eligible_even_with_perfect_checks(reason):
    a = A(reason, clean(clean_check_times=spaced(NOW - timedelta(seconds=5), n=20, gap=20)), NOW)
    assert not a.eligible and a.blockers[0] == 'not_technical_halt'
    assert set(a.blockers) <= {'not_technical_halt', 'halt_provenance_not_technical',
                               'halt_history_incomplete'}
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(a, 1, NOW)


# ── halt provenance (finding: the current reason can be a relabel) ─────────

@pytest.mark.parametrize('history,blocker', [
    (('manual_pause', TECH), 'halt_provenance_not_technical'),
    (('risk:daily_loss_limit', TECH), 'halt_provenance_not_technical'),
    (('risk:loss_streak_halt', TECH, TECH), 'halt_provenance_not_technical'),
    ((TECH, 'manual_pause', TECH), 'halt_provenance_not_technical'),
    (('غير محدد', TECH), 'halt_provenance_not_technical'),
    ((), 'halt_history_incomplete'),
    (None, 'halt_history_incomplete'),
    (TECH, 'halt_history_incomplete'),                  # a bare string is not a history
    ((TECH, None), 'halt_history_incomplete'),
    (('risk_state_missing',), 'halt_history_incomplete'),  # does not end at the current reason
])
def test_provenance_blocks_relabelled_or_unknown_history(history, blocker):
    a = A(TECH, clean(), NOW, hist=history)
    assert not a.eligible and blocker in a.blockers
    assert 'not_technical_halt' not in a.blockers, 'the CURRENT label alone looks technical'
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(a, 1, NOW)


@pytest.mark.parametrize('complete', [False, None, 1, 'yes'])
def test_incomplete_history_is_never_eligible(complete):
    a = A(TECH, clean(), NOW, hist=(TECH,) * 5, complete=complete)
    assert a.blockers == ('halt_history_incomplete',)


def test_only_technical_history_is_eligible():
    hist = ('risk:invalid_risk_state',) * 458
    a = A(TECH, clean(), NOW, hist=hist)
    assert a.eligible and a.history_complete
    b = A(TECH, clean(), NOW, hist=('risk_state_missing', TECH, TECH))
    assert b.eligible
    # Repeats collapse, so the growing scanner log between challenge and confirm keeps the digest;
    # a different transition sequence does not.
    assert hr.assessment_digest(a) == hr.assessment_digest(A(TECH, clean(), NOW, hist=(TECH,)))
    assert hr.assessment_digest(a) != hr.assessment_digest(b)


def test_history_is_bound_into_the_challenge():
    a = A(TECH, clean(), NOW, hist=(TECH,))
    ch = issue_resume_challenge(a, 41, NOW, nonce_bytes=nonces())
    other = A(TECH, clean(), NOW, hist=('risk_state_missing', TECH))
    assert other.eligible
    assert verify_resume_confirmation(ch, ch.nonce, 41, other, NOW, set()) == \
        (False, 'assessment_changed')
    forged = hr.Assessment(eligible=True, halt_class=hr.TECHNICAL, blockers=())
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(forged, 1, NOW)
    assert verify_resume_confirmation(ch, ch.nonce, 41, forged, NOW, set()) == \
        (False, 'no_longer_eligible')


def test_unknown_reason_is_not_echoed():
    a = A('weird; DROP', clean(), NOW)
    assert a.pause_reason is None and a.halt_class == hr.UNKNOWN


# ── two-step approval ─────────────────────────────────────────────────────

def nonces():
    seq = iter(f'{i:032x}' for i in range(1, 100))
    return lambda n: next(seq)


def issued(row=41, now=NOW, ttl=300):
    a = A(TECH, clean(evaluated_at=now - timedelta(seconds=5)), now)
    return a, issue_resume_challenge(a, row, now, ttl_s=ttl, nonce_bytes=nonces())


def test_default_nonce_is_random_and_long():
    a = A(TECH, clean(), NOW)
    c1, c2 = issue_resume_challenge(a, 1, NOW), issue_resume_challenge(a, 1, NOW)
    assert len(c1.nonce) == 32 and re.fullmatch('[0-9a-f]+', c1.nonce) and c1.nonce != c2.nonce
    assert c1.expires_at == NOW + timedelta(seconds=300)


def test_confirmation_happy_path_then_replay():
    a, ch = issued()
    later = NOW + timedelta(seconds=60)
    fresh = A(TECH, clean(evaluated_at=later - timedelta(seconds=2),
                          clean_check_times=spaced(later - timedelta(seconds=2), n=7, gap=20)),
              later, hist=(TECH,) * 4)
    used = set()
    assert verify_resume_confirmation(ch, ch.nonce, 41, fresh, later, used) == (True, 'confirmed')
    assert ch.nonce in used
    assert verify_resume_confirmation(ch, ch.nonce, 41, fresh, later, used) == (False, 'nonce_replayed')


def test_confirmation_refusals():
    a, ch = issued()
    t = NOW + timedelta(seconds=10)
    good = A(TECH, clean(evaluated_at=t), t)
    assert verify_resume_confirmation(ch, ch.nonce, 41, good, NOW + timedelta(seconds=300), set()) \
        == (False, 'challenge_expired')
    assert verify_resume_confirmation(ch, ch.nonce, 41, good, NOW - timedelta(seconds=1), set()) \
        == (False, 'challenge_from_future')
    assert verify_resume_confirmation(ch, 'f' * 32, 41, good, t, set()) == (False, 'nonce_mismatch')
    assert verify_resume_confirmation(ch, None, 41, good, t, set()) == (False, 'nonce_mismatch')
    assert verify_resume_confirmation(ch, 'تأكيد', 41, good, t, set()) == (False, 'nonce_mismatch')
    assert verify_resume_confirmation(ch, ch.nonce, 42, good, t, set()) == (False, 'pause_row_changed')
    assert verify_resume_confirmation(ch, ch.nonce, None, good, t, set()) == (False, 'pause_row_changed')
    stale = A(TECH, clean(evaluated_at=NOW - timedelta(seconds=500)), t)
    assert verify_resume_confirmation(ch, ch.nonce, 41, stale, t, set()) == (False, 'no_longer_eligible')
    risk = A('risk:daily_loss_limit', clean(evaluated_at=t), t)
    assert verify_resume_confirmation(ch, ch.nonce, 41, risk, t, set()) == (False, 'no_longer_eligible')
    soft = A(TECH, clean(evaluated_at=t, decision_reason='drawdown_caution'), t)
    assert soft.eligible
    assert verify_resume_confirmation(ch, ch.nonce, 41, soft, t, set()) == (False, 'assessment_changed')
    other = A('risk_state_missing', clean(evaluated_at=t), t)
    assert verify_resume_confirmation(ch, ch.nonce, 41, other, t, set()) == (False, 'assessment_changed')
    assert verify_resume_confirmation(ch, ch.nonce, 41, good, t, frozenset()) == (False, 'malformed_request')
    assert verify_resume_confirmation(ch, ch.nonce, 41, good, t.replace(tzinfo=None), set()) \
        == (False, 'malformed_request')
    used = set()
    for code_case in range(3):
        verify_resume_confirmation(ch, 'f' * 32, 41, good, t, used)
    assert used == set(), 'refusals never record a nonce'


def test_issue_refusals():
    bad = A(TECH, clean(inputs_finite=False), NOW)
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(bad, 1, NOW)
    good = A(TECH, clean(), NOW)
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(good, True, NOW)
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(good, 1, NOW.replace(tzinfo=None))
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(good, 1, NOW, nonce_bytes=lambda n: 'short')
    forged = hr.Assessment(eligible=True, halt_class=hr.RISK_LIMIT, blockers=())
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(forged, 1, NOW)
    with pytest.raises(hr.ChallengeRefused):
        issue_resume_challenge(good, 1, NOW.replace(tzinfo=None), nonce_bytes=nonces())


def test_malformed_challenge_never_raises():
    a, ch = issued()
    t = NOW + timedelta(seconds=10)
    good = A(TECH, clean(evaluated_at=t), t)
    naive_issue = dataclass_replace(ch, issued_at=ch.issued_at.replace(tzinfo=None))
    naive_expiry = dataclass_replace(ch, expires_at=ch.expires_at.replace(tzinfo=None))
    for bad in (naive_issue, naive_expiry,
                dataclass_replace(ch, issued_at=None),
                dataclass_replace(ch, nonce=None),
                dataclass_replace(ch, nonce=12345),
                dataclass_replace(ch, nonce=['x'] * 40),
                dataclass_replace(ch, nonce='short'),
                dataclass_replace(ch, assessment_digest=None),
                dataclass_replace(ch, pause_row_id='41'),
                dataclass_replace(ch, pause_row_id=True)):
        used = set()
        assert verify_resume_confirmation(bad, ch.nonce, 41, good, t, used) == \
            (False, 'malformed_request')
        assert used == set()
    broken = dataclass_replace(good, pause_reason=object())
    assert verify_resume_confirmation(ch, ch.nonce, 41, broken, t, set()) == \
        (False, 'malformed_request')


def test_missing_state_row_binds_none():
    a = A('risk_state_missing', clean(), NOW)
    ch = issue_resume_challenge(a, None, NOW, nonce_bytes=nonces())
    assert verify_resume_confirmation(ch, ch.nonce, None, a, NOW, set()) == (True, 'confirmed')
    assert verify_resume_confirmation(ch, ch.nonce, 5, a, NOW, set()) == (False, 'pause_row_changed')


def test_module_is_pure():
    import ast, inspect
    tree = ast.parse(inspect.getsource(hr))
    mods = {n.module if isinstance(n, ast.ImportFrom) else a.name
            for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert mods <= {'__future__', 'dataclasses', 'hashlib', 'hmac', 'json', 'secrets',
                    'datetime', 'typing'}


def test_nothing_imports_the_module_at_runtime():
    """Whole-repository scan: only tests/ and the module itself may mention an import of it."""
    import pathlib
    root = pathlib.Path(hr.__file__).resolve().parents[1]
    me = pathlib.Path(hr.__file__).resolve()
    pat = re.compile(r'^\s*(from\s+[\w.]*halt_recovery\b|from\s+[\w.]+\s+import\s+[^#\n]*'
                     r'\bhalt_recovery\b|import\s+[^#\n]*\bhalt_recovery\b)'
                     r'|import_module\([^)]*halt_recovery', re.M)
    skip = {'.git', 'tests', 'node_modules', '__pycache__'}
    scanned, hits = 0, []
    for p in root.rglob('*.py'):
        rel = p.relative_to(root).parts
        if p.resolve() == me or any(part in skip or part.startswith('.') or 'venv' in part
                                    or part == 'site-packages' for part in rel[:-1]):
            continue
        scanned += 1
        if pat.search(p.read_text(errors='ignore')):
            hits.append(str(p.relative_to(root)))
    assert scanned > 50, 'the scan must actually cover the repository'
    assert hits == []
    assert pat.search('from shared.halt_recovery import classify_halt')
    assert pat.search('from shared import halt_recovery as hr')
    assert pat.search("importlib.import_module('shared.halt_recovery')")


# ── alert ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('reason,cls', [(TECH, 'TECHNICAL'), ('risk:loss_streak_halt', 'RISK_LIMIT'),
                                        ('manual_pause', 'MANUAL'), ('reason 12345', 'UNKNOWN')])
def test_alert_fixed_text_no_values(reason, cls):
    since = datetime(2026, 10, 21, 20, 23, 41, tzinfo=UTC)
    text = technical_halt_alert(reason, since)
    assert f'class {cls}' in text and 'BLOCKED_RISK_CONTROL' in text
    stamp = '2026-10-21 20:23Z'
    assert stamp in text
    rest = text.replace(stamp, '')
    assert not re.search(r'[0-9٠-٩۰-۹]', rest), 'no digits beyond the timestamp'
    assert '12345' not in text
    assert re.search(r'[؀-ۿ]', text), 'short Arabic part present'
    if cls == 'TECHNICAL':
        assert '/resume' in text and 'two-step' in text
    if cls == 'RISK_LIMIT':
        assert '/recover_risk' in text


def test_alert_unknown_time():
    assert 'unknown time' in technical_halt_alert(TECH, None)
    assert 'unknown time' in technical_halt_alert(TECH, datetime(2026, 1, 1))


# ── fault injection on the REAL tracker admission path ───────────────────

class FakeDB:
    """Minimal stand-in for the Database facade: no closed trades, N open positions."""

    def __init__(self, open_symbols):
        self.open_symbols = list(open_symbols)

    async def fetchval(self, sql, *args):
        if 'active_trades' in sql:
            return len(self.open_symbols)
        return None                                   # no recovery epoch on record

    async def fetch(self, sql, *args):
        if 'trade_results' in sql:
            return []
        if 'active_trades' in sql:
            return [{'symbol': s, 'entry_price': 100.0, 'trade_type': 'scalp', 'regime': None}
                    for s in self.open_symbols]
        return []


class _Resp:
    status = 200

    async def json(self):
        return {'price': '100.0'}

    async def text(self):
        return ''


class _Get:
    def __init__(self, fail):
        self.fail = fail

    async def __aenter__(self):
        if self.fail:
            raise asyncio.TimeoutError()
        return _Resp()

    async def __aexit__(self, *exc):
        return False


def fake_session(failing: set, calls: list):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, **kw):
            symbol = url.rsplit('symbol=', 1)[-1]
            calls.append(symbol)
            return _Get(symbol in failing)
    return Session


class LogSpy:
    def __init__(self):
        self.errors = []

    def error(self, msg, *a, **k):
        self.errors.append(str(msg))

    def __getattr__(self, name):
        return lambda *a, **k: None


def wire(monkeypatch, db, failing, pause=(False, None)):
    calls, log = [], LogSpy()
    monkeypatch.setattr(tracker, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(tracker, 'get_pause_state', AsyncMock(return_value=pause))
    monkeypatch.setattr(tracker.aiohttp, 'ClientSession', fake_session(failing, calls))
    monkeypatch.setattr(tracker, 'logger', log)
    return calls, log


@pytest.mark.asyncio
async def test_fault_a_price_timeout_yields_invalid_risk_state(monkeypatch):
    db = FakeDB(['AAAUSDT', 'BBBUSDT'])
    calls, log = wire(monkeypatch, db, failing={'BBBUSDT'})
    assert await tracker.get_current_price('BBBUSDT') is None   # real function swallows -> None
    decision = await tracker.assess_new_trade_risk('CCCUSDT')
    assert (decision.allowed, decision.reason) == (False, 'invalid_risk_state')
    assert 'BBBUSDT' in calls
    assert any('خطأ في جلب سعر' in e for e in log.errors), 'the logged error type from the incident'
    # Even while an administrative pause is set, the finite-input check is reported first.
    wire(monkeypatch, db, failing={'BBBUSDT'}, pause=(True, TECH))
    assert (await tracker.assess_new_trade_risk('CCCUSDT')).reason == 'invalid_risk_state'


@pytest.mark.asyncio
async def test_fault_b_prices_recover_then_only_the_sticky_pause_remains(monkeypatch):
    db = FakeDB(['AAAUSDT', 'BBBUSDT'])
    # Pause masked (fresh check style): the real path no longer reports invalid_risk_state.
    calls, _ = wire(monkeypatch, db, failing=set())
    masked = await tracker.assess_new_trade_risk('CCCUSDT')
    assert masked.reason != 'invalid_risk_state'
    # With the default canary capacity the clean book may still refuse on capacity; that is a
    # per-trade constraint, never persisted as a pause, so it does not block a technical resume.
    assert masked.reason in hr._NON_HALT_DECISION_REASONS
    assert sorted(calls) == ['AAAUSDT', 'BBBUSDT']
    # Pause NOT masked: the sticky pause reason is what every admission now carries.
    wire(monkeypatch, db, failing=set(), pause=(True, TECH))
    paused = await tracker.assess_new_trade_risk('CCCUSDT')
    assert (paused.allowed, paused.reason) == (False, TECH)
    # The design: a fresh check built from the masked evaluation makes the halt eligible.
    t = datetime.now(UTC)
    check = FreshRiskCheck(evaluated_at=t, inputs_finite=True, open_count=2, prices_requested=2,
                           prices_obtained=2, decision_reason=masked.reason,
                           loss_streak_halt_active=False, clean_check_times=spaced(t))
    assert A(TECH, check, t).eligible
    # ...and the unmasked decision is caught, never mistaken for a clean pass.
    bad = dataclass_replace(check, decision_reason=paused.reason)
    assert 'pause_not_masked' in A(TECH, bad, t).blockers


def dataclass_replace(obj, **kw):
    import dataclasses
    return dataclasses.replace(obj, **kw)


def test_mask_administrative_pause_on_real_snapshot():
    from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade
    snap = RiskSnapshot(realized_total_usdt=0.0, daily_pnl_usdt=0.0, weekly_pnl_usdt=0.0,
                        unrealized_pnl_usdt=0.0, peak_equity_usdt=500.0, open_count=0,
                        symbol_open_count=0, consecutive_losses=0, manually_paused=True,
                        manual_pause_reason=TECH)
    limits = RiskLimits(capital_usdt=500.0, trade_amount_usdt=50.0, max_open_trades=5)
    assert evaluate_new_trade(snap, limits).reason == TECH
    masked = hr.mask_administrative_pause(snap)
    assert snap.manually_paused and not masked.manually_paused
    assert evaluate_new_trade(masked, limits).reason == 'within_limits'


class SQLConn:
    """Captures SQL from record_risk_decision; no database."""

    def __init__(self, prior_paused):
        self.prior_paused = prior_paused
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append(('fetchrow', sql, args))
        return {'is_trading_paused': self.prior_paused} if self.prior_paused is not None else None

    async def fetchval(self, sql, *args):
        self.calls.append(('fetchval', sql, args))
        return 1

    async def execute(self, sql, *args):
        self.calls.append(('execute', sql, args))

    def transaction(self):
        return _CM(self)


class _CM:
    def __init__(self, v):
        self.v = v

    async def __aenter__(self):
        return self.v

    async def __aexit__(self, *exc):
        return False


def decision(reason):
    return SimpleNamespace(reason=reason, allowed=False, daily_pnl_pct=0.0, weekly_pnl_pct=0.0,
                           drawdown_pct=0.0, consecutive_losses=0)


async def drive_record(monkeypatch, reason, prior_paused):
    conn = SQLConn(prior_paused)
    monkeypatch.setattr(tracker, 'Database', SimpleNamespace(acquire=lambda: _CM(conn)))
    enq = AsyncMock()
    monkeypatch.setattr(tracker, 'enqueue', enq)
    monkeypatch.setattr(tracker, '_v2_risk_state', lambda *a, **k: None)
    await tracker.record_risk_decision(decision(reason))
    upsert = [c for c in conn.calls if 'INSERT INTO risk_management' in c[1]]
    assert len(upsert) == 1
    return conn, upsert[0], enq


def _norm(sql):
    return re.sub(r'\s+', ' ', sql)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['invalid_risk_state', 'daily_loss_limit', 'weekly_loss_limit',
                                    'max_drawdown_limit', 'loss_streak_halt'])
async def test_fault_c_hard_halt_set_includes_invalid_risk_state(monkeypatch, reason):
    _, (_, sql, args), enq = await drive_record(monkeypatch, reason, prior_paused=False)
    assert args[2] is True and args[3] == f'risk:{reason}'
    assert enq.await_count == 1, 'a new halt raises one risk.halted notification'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['within_limits', TECH, 'drawdown_caution', 'max_open_trades'])
async def test_fault_c_upsert_keeps_or_merge_so_halt_is_sticky(monkeypatch, reason):
    """Owner invariant: a later non-halting decision never clears is_trading_paused; only /resume
    (manual_resume) does. A design change here must fail this test."""
    _, (_, sql, args), enq = await drive_record(monkeypatch, reason, prior_paused=True)
    s = _norm(sql)
    assert args[2] is False and args[3] is None
    assert ('is_trading_paused=(risk_management.is_trading_paused OR EXCLUDED.is_trading_paused)'
            in s)
    assert ('pause_reason=CASE WHEN EXCLUDED.is_trading_paused THEN EXCLUDED.pause_reason '
            'ELSE risk_management.pause_reason END' in s)
    assert 'manual_resume' not in s.split('ON CONFLICT')[1], 'tracker never writes a resume'
    assert enq.await_count == 0


def test_fault_c_or_merge_semantics_model():
    """Executable model of the upsert's ON CONFLICT clause (the SQL text is pinned above).

    Once paused, stays paused. But the REASON is overwritten by every later hard halt: a manual
    pause or a risk-limit halt followed by one price timeout reads 'risk:invalid_risk_state'. That
    relabel is why eligibility is decided on the history since the last resume, not the label.
    """
    def upsert(row, paused, reason):
        return (row[0] or paused, reason if paused else row[1])
    row = (False, None)
    row = upsert(row, True, TECH)
    for _ in range(5):
        row = upsert(row, False, None)
    assert row == (True, TECH)
    for origin in ('manual_pause', 'risk:daily_loss_limit', 'risk:loss_streak_halt'):
        row = upsert((True, origin), True, TECH)
        assert row == (True, TECH), 'the origin is overwritten'
        assert classify_halt(row[1]) == hr.TECHNICAL, 'so the current label alone looks technical'
        a = A(row[1], clean(), NOW, hist=(origin, row[1]))
        assert not a.eligible and a.blockers == ('halt_provenance_not_technical',)


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', ['manual_pause', 'risk:daily_loss_limit'])
async def test_fault_d_relabel_on_real_path_emits_no_outbox_event(monkeypatch, origin):
    """Real functions: with a non-technical halt active, one price timeout still yields
    invalid_risk_state (finite check first), record_risk_decision writes 'risk:invalid_risk_state'
    over the row, and NO risk.halted event is enqueued (already paused), so the outbox cannot see
    the relabel either."""
    db = FakeDB(['AAAUSDT', 'BBBUSDT'])
    wire(monkeypatch, db, failing={'BBBUSDT'}, pause=(True, origin))
    d = await tracker.assess_new_trade_risk('CCCUSDT')
    assert d.reason == 'invalid_risk_state'
    _, (_, sql, args), enq = await drive_record(monkeypatch, d.reason, prior_paused=True)
    assert args[2] is True and args[3] == TECH
    assert enq.await_count == 0
