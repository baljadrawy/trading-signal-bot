"""Paper economic-loss observation (owner decision 2026-10-26).

enforce (default) must decide exactly as before; Paper observe must let economic hard
stops through as auditable observations while technical, administrative and portfolio
stops stay fail-closed. No database: the tracker's Database facade is faked.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from shared import economic_halt_policy as policy
from shared import evidence_v2 as ev2
from shared.config import Config, config
from shared.economic_halt_policy import (
    ECONOMIC_HARD_STOPS, ENFORCE, OBSERVE, classify_reason, evaluate_with_policy,
    legacy_fields, persisted_halt_reasons, resolve_economic_halt_mode,
)
from shared.risk_epoch import (
    LOSS_STREAK_HALTED, LOSS_STREAK_OBSERVED, LOSS_STREAK_RECOVERY_REQUIRED, TRADING_ACTIVE,
    TRADING_PAUSED, LossStreakState, operational_state,
)
from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade
from shared.telegram_messages import (
    OBSERVED_LABEL, OBSERVED_STATUS_LINE, observed_loss_streak_resume_note,
    observed_loss_streak_status_lines,
)
from evidence_v2_fakes import inject_recorder

try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service', allow_module_level=True)


def L(**changes):
    values = dict(capital_usdt=500, trade_amount_usdt=50, max_open_trades=10)
    values.update(changes)
    return RiskLimits(**values)


def S(**changes):
    values = dict(realized_total_usdt=0, daily_pnl_usdt=0, weekly_pnl_usdt=0,
                  unrealized_pnl_usdt=0, peak_equity_usdt=500, open_count=0,
                  symbol_open_count=0, consecutive_losses=0)
    values.update(changes)
    return RiskSnapshot(**values)


# name -> (snapshot, limits, allowed, reason, size_multiplier, max_positions), copied from
# the pre-change evaluate_new_trade output.
SCENARIOS = {
    'clean': (S(), L(), True, 'within_limits', 1.0, 8),
    'daily': (S(daily_pnl_usdt=-15, weekly_pnl_usdt=-15, realized_total_usdt=-15), L(),
              False, 'daily_loss_limit', 1.0, 8),
    'weekly': (S(weekly_pnl_usdt=-50, realized_total_usdt=-50), L(),
               False, 'weekly_loss_limit', 0.1, 1),
    'drawdown': (S(realized_total_usdt=-75), L(), False, 'max_drawdown_limit', 0.25, 2),
    'streak7': (S(consecutive_losses=7), L(), False, 'loss_streak_halt', 0.1, 1),
    'streak5': (S(consecutive_losses=5), L(), True, 'loss_streak_minimum', 0.1, 1),
    'streak3': (S(consecutive_losses=3), L(), True, 'loss_streak_reduce', 0.5, 4),
    'dd_caution': (S(realized_total_usdt=-30), L(), True, 'drawdown_caution', 0.5, 4),
    'daily_and_streak': (S(daily_pnl_usdt=-20, weekly_pnl_usdt=-20, realized_total_usdt=-20,
                           consecutive_losses=8), L(), False, 'daily_loss_limit', 0.1, 1),
    'all_four': (S(daily_pnl_usdt=-80, weekly_pnl_usdt=-80, realized_total_usdt=-80,
                   consecutive_losses=9), L(), False, 'daily_loss_limit', 0.1, 1),
    'unrealized_daily': (S(unrealized_pnl_usdt=-16, open_count=1), L(),
                         False, 'daily_loss_limit', 1.0, 8),
    'gross': (S(open_count=8), L(), False, 'gross_exposure_limit', 1.0, 8),
    'symbol': (S(symbol_open_count=1), L(), False, 'symbol_concentration_limit', 1.0, 8),
    'strategy': (S(strategy_open_count=4), L(), False, 'strategy_concentration_limit', 1.0, 8),
    'regime': (S(regime_open_count=5), L(), False, 'regime_concentration_limit', 1.0, 8),
    'maxopen': (S(open_count=1), L(max_open_trades=1), False, 'max_open_trades', 1.0, 1),
    'streak7_maxopen': (S(consecutive_losses=7, open_count=1), L(max_open_trades=1),
                        False, 'loss_streak_halt', 0.1, 1),
    'streak7_gross': (S(consecutive_losses=7, open_count=8), L(),
                      False, 'loss_streak_halt', 0.1, 1),
    'streak5_capacity': (S(consecutive_losses=5, open_count=1), L(),
                         False, 'loss_streak_minimum', 0.1, 1),
    'paused': (S(manually_paused=True, manual_pause_reason='manual_pause'), L(),
               False, 'manual_pause', 1.0, 8),
    'paused_streak': (S(manually_paused=True, manual_pause_reason='risk:loss_streak_halt',
                        consecutive_losses=7), L(), False, 'risk:loss_streak_halt', 0.1, 1),
    'nan': (S(unrealized_pnl_usdt=float('nan'), consecutive_losses=7), L(),
            False, 'invalid_risk_state', 0.0, 0),
}


# ---- enforce: byte-identical decisions ---------------------------------------------------

@pytest.mark.parametrize('name', sorted(SCENARIOS))
def test_enforce_is_identical_to_legacy(name):
    snap, lim, allowed, reason, mult, max_pos = SCENARIOS[name]
    legacy = evaluate_new_trade(snap, lim)
    for decision in (evaluate_with_policy(snap, lim), evaluate_with_policy(snap, lim, ENFORCE)):
        assert legacy_fields(decision) == legacy_fields(legacy)
        assert (decision.allowed, decision.reason) == (allowed, reason)
        assert (decision.size_multiplier, decision.max_positions) == (mult, max_pos)
        assert decision.observed_economic_stop is None
        assert decision.risk_policy_version == 'econ-enforce-v1'
        if reason in ECONOMIC_HARD_STOPS:
            assert decision.economic_flags[0] == reason      # same precedence as the chain


def test_enforce_persisted_halt_set_is_the_legacy_set():
    legacy = {'daily_loss_limit', 'weekly_loss_limit', 'max_drawdown_limit',
              'loss_streak_halt', 'invalid_risk_state'}
    assert persisted_halt_reasons(ENFORCE) == legacy
    assert persisted_halt_reasons(OBSERVE) == {'invalid_risk_state'}


# ---- observe: economic stops allowed + flagged -------------------------------------------

@pytest.mark.parametrize('name,stop,flags', [
    ('daily', 'daily_loss_limit', ('daily_loss_limit',)),
    ('weekly', 'weekly_loss_limit', ('weekly_loss_limit',)),
    ('drawdown', 'max_drawdown_limit', ('max_drawdown_limit',)),
    ('streak7', 'loss_streak_halt', ('loss_streak_halt',)),
    ('unrealized_daily', 'daily_loss_limit', ('daily_loss_limit',)),
    ('daily_and_streak', 'daily_loss_limit', ('daily_loss_limit', 'loss_streak_halt')),
    ('all_four', 'daily_loss_limit', ('daily_loss_limit', 'weekly_loss_limit',
                                      'max_drawdown_limit', 'loss_streak_halt')),
])
def test_observe_allows_and_flags_each_economic_stop(name, stop, flags):
    snap, lim, _allowed, _reason, mult, max_pos = SCENARIOS[name]
    d = evaluate_with_policy(snap, lim, OBSERVE)
    assert d.allowed
    assert d.reason == f'observed:{stop}'
    assert d.observed_economic_stop == stop
    assert d.economic_flags == flags
    assert d.risk_policy_version == 'econ-observe-v1'
    # Sizing is unchanged: same multiplier/capacity and computed values as enforce.
    legacy = evaluate_new_trade(snap, lim)
    assert (d.size_multiplier, d.max_positions) == (mult, max_pos)
    assert legacy_fields(d)[2:] == legacy_fields(legacy)[2:]


@pytest.mark.parametrize('name', ['clean', 'streak5', 'streak3', 'dd_caution'])
def test_observe_leaves_non_economic_allowed_decisions_alone(name):
    snap, lim, *_ = SCENARIOS[name]
    d = evaluate_with_policy(snap, lim, OBSERVE)
    assert legacy_fields(d) == legacy_fields(evaluate_new_trade(snap, lim))
    assert d.observed_economic_stop is None and d.economic_flags == ()


@pytest.mark.parametrize('name,reason', [
    ('gross', 'gross_exposure_limit'), ('symbol', 'symbol_concentration_limit'),
    ('strategy', 'strategy_concentration_limit'), ('regime', 'regime_concentration_limit'),
    ('maxopen', 'max_open_trades'), ('streak5_capacity', 'loss_streak_minimum'),
    ('paused', 'manual_pause'), ('paused_streak', 'risk:loss_streak_halt'),
    ('nan', 'invalid_risk_state'),
])
def test_observe_keeps_technical_admin_and_portfolio_stops_blocking(name, reason):
    snap, lim, *_ = SCENARIOS[name]
    d = evaluate_with_policy(snap, lim, OBSERVE)
    assert not d.allowed and d.reason == reason
    assert d.observed_economic_stop is None


@pytest.mark.parametrize('name,reason', [
    ('streak7_maxopen', 'loss_streak_minimum'),    # capacity (reduced by sizing) still binds
    ('streak7_gross', 'gross_exposure_limit'),
])
def test_observe_economic_stop_masking_a_portfolio_stop_is_still_blocked(name, reason):
    snap, lim, *_ = SCENARIOS[name]
    d = evaluate_with_policy(snap, lim, OBSERVE)
    assert not d.allowed and d.reason == reason
    assert d.observed_economic_stop == 'loss_streak_halt'
    assert d.economic_flags == ('loss_streak_halt',)


@pytest.mark.parametrize('reason', ['risk_state_missing', 'risk_state_inconsistent',
                                    'manual_pause', 'trading_paused'])
def test_observe_state_faults_and_pauses_block_even_with_economic_breach(reason):
    d = evaluate_with_policy(S(manually_paused=True, manual_pause_reason=reason,
                               consecutive_losses=9, daily_pnl_usdt=-40), L(), OBSERVE)
    assert not d.allowed and d.reason == reason
    assert d.economic_flags == ('daily_loss_limit', 'loss_streak_halt')


def test_classification_table():
    assert {classify_reason(r) for r in ECONOMIC_HARD_STOPS} == {'economic'}
    assert classify_reason('invalid_risk_state') == 'technical'
    for r in ('manual_pause', 'risk_state_missing', 'risk_state_inconsistent',
              'risk:loss_streak_halt', 'trading_paused'):
        assert classify_reason(r) == 'admin'
    for r in ('gross_exposure_limit', 'symbol_concentration_limit', 'max_open_trades',
              'strategy_concentration_limit', 'regime_concentration_limit'):
        assert classify_reason(r) == 'portfolio'
    assert classify_reason('loss_streak_minimum') == 'sizing'
    assert classify_reason('observed:loss_streak_halt') == 'observed'
    assert classify_reason('within_limits') == 'ok'


# ---- mode resolution ------------------------------------------------------------------

@pytest.mark.parametrize('raw,paper,mode,warns', [
    (None, True, ENFORCE, False), ('enforce', True, ENFORCE, False),
    ('observe', True, OBSERVE, False), (' OBSERVE ', True, OBSERVE, False),
    ('observe', False, ENFORCE, True), ('enforce', False, ENFORCE, False),
    ('off', True, ENFORCE, True), ('', True, ENFORCE, False),
])
def test_mode_resolution(raw, paper, mode, warns):
    got, warning = resolve_economic_halt_mode(raw, paper)
    assert got == mode and bool(warning) == warns


def test_default_config_is_enforce():
    import inspect
    import os
    import shared.config as cfgmod
    assert "os.getenv('PAPER_ECONOMIC_HALT_MODE', 'enforce')" in inspect.getsource(cfgmod)
    assert Config.__dataclass_fields__['PAPER_ECONOMIC_HALT_MODE'].type is str
    if 'PAPER_ECONOMIC_HALT_MODE' not in os.environ:
        assert config.PAPER_ECONOMIC_HALT_MODE == 'enforce'
        assert config.ECONOMIC_HALT_MODE == ENFORCE
        assert config.RISK_POLICY_VERSION == 'econ-enforce-v1'


def test_observe_ignored_without_paper_trading(monkeypatch, caplog):
    monkeypatch.setattr(config, 'PAPER_ECONOMIC_HALT_MODE', 'observe')
    monkeypatch.setattr(config, 'PAPER_TRADING', False)
    monkeypatch.setattr(policy, '_WARNED', set())
    with caplog.at_level('WARNING'):
        assert config.ECONOMIC_HALT_MODE == ENFORCE
    assert config.RISK_POLICY_VERSION == 'econ-enforce-v1'
    assert any('PAPER_TRADING' in r.message for r in caplog.records)
    monkeypatch.setattr(config, 'PAPER_TRADING', True)
    assert config.ECONOMIC_HALT_MODE == OBSERVE
    assert config.RISK_POLICY_VERSION == 'econ-observe-v1'


# ---- operator surfaces (shared helpers; telegram/main.py is not importable here) --------

def _streak(halt, open_positions=0):
    return LossStreakState(datetime(2026, 7, 20, tzinfo=timezone.utc), 9 if halt else 2, 7,
                           halt, halt and open_positions == 0, open_positions, None)


def test_operational_state_enforce_unchanged_and_observe_relabelled():
    assert operational_state(_streak(True), False) == LOSS_STREAK_RECOVERY_REQUIRED
    assert operational_state(_streak(True, 2), False) == LOSS_STREAK_HALTED
    assert operational_state(_streak(False), True) == TRADING_PAUSED
    assert operational_state(_streak(False), False) == TRADING_ACTIVE
    assert operational_state(_streak(True), False, ENFORCE) == LOSS_STREAK_RECOVERY_REQUIRED
    assert operational_state(_streak(True), False, OBSERVE) == LOSS_STREAK_OBSERVED
    assert operational_state(_streak(True), True, OBSERVE) == TRADING_PAUSED   # pause still blocks
    assert operational_state(_streak(False), False, OBSERVE) == TRADING_ACTIVE


def test_observed_texts():
    assert OBSERVED_LABEL == 'observed (Paper observe mode, not blocking)'
    assert OBSERVED_LABEL in OBSERVED_STATUS_LINE
    assert OBSERVED_LABEL in observed_loss_streak_status_lines(9, 7) and '9/7' in \
        observed_loss_streak_status_lines(9, 7)
    assert OBSERVED_LABEL in observed_loss_streak_resume_note(9, 7)
    assert policy.loss_streak_status_label(OBSERVE) == OBSERVED_LABEL
    assert policy.loss_streak_status_label(ENFORCE) == 'halt active'


# ---- real tracker path (Database faked) -------------------------------------------------

CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
LOSS_NET = -2.0


class FakeDB:
    """Database facade + connection stand-in recording every statement."""

    def __init__(self, profits):
        self.profits = list(profits)
        self.writes = []

    async def fetchval(self, sql, *args):
        if 'INSERT INTO risk_management' in sql:
            self.writes.append(('risk_management', sql, args))
            return 11
        if 'outbox_events' in sql:
            self.writes.append(('outbox', sql, args))
            return 22
        if 'MAX(epoch_started_at)' in sql:
            return None
        return 0

    async def fetch(self, sql, *args):
        if 'trade_results' in sql:
            return [dict(profit_usdt=pnl, result='LOSS', exit_time=CLEAN_START + timedelta(hours=i))
                    for i, pnl in enumerate(self.profits)]
        return []

    async def fetchrow(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        self.writes.append(('execute', sql, args))
        return 'OK'

    def acquire(self):
        return _Ctx(self)

    def transaction(self):
        return _Ctx(self)


class _Ctx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def wire(monkeypatch, mode, profits, pause=(False, None)):
    db = FakeDB(profits)
    monkeypatch.setattr(config, 'PAPER_ECONOMIC_HALT_MODE', mode)
    monkeypatch.setattr(config, 'PAPER_TRADING', True)
    monkeypatch.setattr(tracker, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(tracker, 'get_pause_state', AsyncMock(return_value=pause))
    monkeypatch.setattr(tracker, 'get_current_price', AsyncMock(return_value=100.0))
    return db


@pytest.mark.asyncio
async def test_tracker_enforce_still_halts_on_loss_streak(monkeypatch):
    db = wire(monkeypatch, 'enforce', [LOSS_NET] * 7)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not d.allowed and d.reason == 'loss_streak_halt'
    await tracker.record_risk_decision(d)
    rm = [w for w in db.writes if w[0] == 'risk_management']
    assert rm[0][2][2:] == (True, 'risk:loss_streak_halt')
    assert any(w[0] == 'outbox' and 'risk.halted' in w[2] for w in db.writes)


@pytest.mark.asyncio
async def test_tracker_observe_admits_and_never_pauses_for_economics(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS_NET] * 7)
    before = list(db.profits)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert d.allowed and d.reason == 'observed:loss_streak_halt'
    assert d.consecutive_losses == 7 and d.risk_policy_version == 'econ-observe-v1'
    await tracker.record_risk_decision(d)
    rm = [w for w in db.writes if w[0] == 'risk_management']
    assert len(rm) == 1
    _daily, streak, paused, reason = rm[0][2]
    assert streak == 7, 'the counter is still recorded exactly as before'
    assert paused is False and reason is None
    outbox = [w for w in db.writes if w[0] == 'outbox']
    assert not any('risk.halted' in w[2] for w in outbox), 'no risk.halted transition'
    # The only outbox row is the observation notice (tests/test_paper_economic_alerts.py).
    assert [w[2][:2] for w in outbox] == [('risk.observed', 'risk_observation')]
    assert db.profits == before, 'loss history untouched'
    # Only the pre-existing statement shape is written (no new columns/tables).
    enforce_db = wire(monkeypatch, 'enforce', [LOSS_NET] * 7)
    await tracker.record_risk_decision(await tracker.assess_new_trade_risk('BTCUSDT'))
    enforce_sql = [w[1] for w in enforce_db.writes if w[0] == 'risk_management']
    assert [w[1] for w in rm] == enforce_sql


@pytest.mark.asyncio
async def test_tracker_observe_still_pauses_for_invalid_risk_state(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS_NET] * 7)
    monkeypatch.setattr(tracker, 'get_current_price', AsyncMock(return_value=None))
    plain_fetch = db.fetch

    async def fetch_with_open_trade(sql, *args):
        if 'active_trades' in sql:        # an open trade whose price is missing -> NaN
            return [{'symbol': 'ETHUSDT', 'entry_price': 100.0,
                     'trade_type': 'momentum', 'regime': 'flat'}]
        return await plain_fetch(sql, *args)
    db.fetch = fetch_with_open_trade
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not d.allowed and d.reason == 'invalid_risk_state'
    await tracker.record_risk_decision(d)
    rm = [w for w in db.writes if w[0] == 'risk_management']
    assert rm[0][2][2:] == (True, 'risk:invalid_risk_state')
    assert any(w[0] == 'outbox' and 'risk.halted' in w[2] for w in db.writes)


@pytest.mark.asyncio
@pytest.mark.parametrize('pause', [(True, 'manual_pause'), (True, 'risk_state_missing'),
                                   (True, 'risk_state_inconsistent'),
                                   (True, 'risk:loss_streak_halt')])
async def test_tracker_observe_keeps_pauses_blocking(monkeypatch, pause):
    wire(monkeypatch, 'observe', [LOSS_NET] * 7, pause=pause)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not d.allowed and d.reason == pause[1]


@pytest.mark.asyncio
async def test_tracker_observe_without_paper_is_enforce(monkeypatch):
    wire(monkeypatch, 'observe', [LOSS_NET] * 7)
    monkeypatch.setattr(config, 'PAPER_TRADING', False)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not d.allowed and d.reason == 'loss_streak_halt'
    assert d.risk_policy_version == 'econ-enforce-v1'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,active,expected', [
    ('enforce', True, (True, None)), ('enforce', False, (False, None)),
    ('observe', True, (False, 'loss_streak_halt')), ('observe', False, (False, None)),
])
async def test_admission_lock_recheck(monkeypatch, mode, active, expected):
    wire(monkeypatch, mode, [])
    check = AsyncMock(return_value=active)
    monkeypatch.setattr(tracker, 'loss_streak_halt_active', check)
    conn = object()
    assert await tracker._loss_streak_under_lock(conn) == expected
    check.assert_awaited_once_with(conn)


# ---- evidence carries the policy version ------------------------------------------------

SIG = {'id': 5, 'symbol': 'BTCUSDT', 'timeframe': '4h', 'features_snapshot': None}


@pytest.mark.parametrize('mode,version', [('enforce', 'econ-enforce-v1'),
                                          ('observe', 'econ-observe-v1')])
def test_admission_evidence_carries_policy_version(monkeypatch, mode, version):
    monkeypatch.setattr(config, 'PAPER_ECONOMIC_HALT_MODE', mode)
    monkeypatch.setattr(config, 'PAPER_TRADING', True)
    rec, sink = inject_recorder(monkeypatch, 'trade_tracker')
    try:
        decision = evaluate_with_policy(*SCENARIOS['streak7'][:2], mode)
        tracker._v2_admission(dict(SIG, id=5), 'admitted', None, decision, active_trade_id=1)
        tracker._v2_admission(dict(SIG, id=6), 'no_price', 'no_current_fill_price')
        tracker._v2_admission(dict(SIG, id=7), 'risk_rejected', None, decision)
        tracker._v2_risk_state(decision, False, False)
        rec.flush_now()
        records = sink.records()
        admissions = [r for r in records if r['event_type'] == 'admission.decision']
        assert len(admissions) == 3
        assert all(r['payload']['risk_policy_version'] == version for r in admissions)
        risk = admissions[0]['payload']['risk_decision']
        assert risk['risk_policy_version'] == version
        assert risk['observed_economic_stop'] == (
            'loss_streak_halt' if mode == 'observe' else None)
        observed = [r for r in records if r['event_type'] == 'risk.observed']
        assert len(observed) == (1 if mode == 'observe' else 0)
        if observed:
            assert observed[0]['state'] == {'observed': 'loss_streak_halt',
                                            'flags': ['loss_streak_halt']}
    finally:
        ev2.reset_for_tests()
