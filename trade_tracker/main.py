"""
Trade Tracker - يراقب الإشارات المرسلة ويسجل نتائجها تلقائياً
يتحقق من السعر كل 5 دقائق ويسجل: WIN / LOSS / EXPIRED
يستخدم shared.triple_barrier كمصدر حقيقة واحد لمنطق الخروج.
"""
import asyncio
import math
import sys
import json
import dataclasses
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
sys.path.append('/app')

import aiohttp
from shared.config import config
from shared import evidence_v2
from shared.database import Database
from shared.logger import setup_logger
from shared.alerts import send_alert
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared.outbox import worker_id, claim, ack, fail, enqueue, defer
from shared.outbox_watch import DeadLetterWatch, previous_watermark
from shared.delivery_policy import bounded_delay
from shared import capacity_authority as capacity
from shared import cost_label_policy as cost_policy
from shared import ledger_legacy_adapter, position_state_shadow
from shared.accounting_flags import LEGACY_FLAGS, resolve_accounting_flags
from shared.admission_capacity import TrackerAdmissionFunnel, funnel_service, routed_risk_decision
from shared.candle import candle_interval_case_sql
from shared.execution import rebase_long_bracket
from shared.entry_execution import decide_long_entry, resolve_entry_fill, FILL_MODELS
from shared.partial_exits import aggregate_close, fills_between
from shared.signal_stop import candle_invalidated
from shared.risk_management import RiskSnapshot
from shared.economic_halt_policy import (
    OBSERVED_OUTBOX_AGGREGATE, OBSERVED_OUTBOX_EVENT, economic_halt_blocks, economic_halt_mode,
    evaluate_with_policy, observation_transition, observed_codes, persisted_halt_reasons,
)
from shared.risk_epoch import (
    acquire_risk_admission_lock, effective_risk_start, loss_streak_halt_active,
    tail_loss_streak,
)
from shared.trading_state import get_pause_state
from shared.signal_readiness import READY_SQL_PREDICATE
from shared.signal_identity import freshness_at, integrity_mode
from shared.triple_barrier import (
    create_config_from_trade,
    create_state_from_trade,
    step_barrier,
    barrier_status_summary,
    TripleBarrierConfig,
    TripleBarrierState,
    expiry_policy_for_timeframe,
)
try:
    from .binance_price_stream import BinancePriceStream
except ImportError:  # container executes /app/main.py as a top-level module
    from binance_price_stream import BinancePriceStream

logger = setup_logger('trade_tracker')

# مدة انتهاء الصفقة بالساعات — يُستخدم في TripleBarrierConfig تلقائياً
TRADE_EXPIRY_HOURS = 48

# نسبة الـ trailing stop — يُستخدم في TripleBarrierConfig تلقائياً
TRAIL_STOP_PCT = 2.5

_trade_locks: dict[int, asyncio.Lock] = {}
_closing: set[int] = set()
_min_notional_cache: dict[str, float] = {}
price_stream: BinancePriceStream | None = None
# WP2 accounting/capacity flags (shared/accounting_flags.py). The legacy values until main()
# resolves the environment; an unknown value refuses to start there.
WP2_FLAGS = LEGACY_FLAGS
_FUNNEL = None              # shared.funnel_hooks.FunnelService, only with FUNNEL_RECORDING=on
# WP-E06: PAPER_COUNTER_LABELS (shared/cost_label_policy.py), default off. On, each recorded close
# also logs its counter basis: the legacy gross increment and the stored net label beside it.
COUNTER_LABELS = False


def _costs():
    """legacy_tracker_v1 bound to the current config (read at the call site, as before)."""
    return cost_policy.bound_costs(config)


def configure_wp2(environ=None):
    """Resolve and validate the WP2 flags and the cost binding; raises on any invalid value."""
    global WP2_FLAGS, _FUNNEL, COUNTER_LABELS
    flags = resolve_accounting_flags(environ)
    cost_policy.validate_policies(_costs(), cost_label_policy=flags.cost_label_policy,
                                  break_even_policy=flags.break_even_policy)
    counter_labels = cost_policy.counter_labels_enabled(environ)
    WP2_FLAGS = flags
    COUNTER_LABELS = counter_labels
    _FUNNEL = (funnel_service('trade_tracker', max_records_per_day=flags.funnel_max_records_per_day)
               if flags.funnel_recording else None)
    return flags


async def main():
    logger.info("🚀 بدء تشغيل Trade Tracker...")
    flags = configure_wp2()                      # WP2: unknown flag or invalid cost config refuses
    if not flags.is_legacy:
        logger.warning(f"WP2 flags not at their legacy defaults: {flags.as_dict()}")
    if COUNTER_LABELS:
        logger.warning("WP2 PAPER_COUNTER_LABELS=on: counter-basis log lines enabled")
    await Database.connect()
    await require_schema('trade_tracker')
    integrity_mode(config)                       # A44: unknown SIGNAL_INTEGRITY_MODE refuses to start
    if config.PAPER_ENTRY_FILL_MODEL not in FILL_MODELS:           # A38: fail closed
        raise RuntimeError(f'unknown PAPER_ENTRY_FILL_MODEL {config.PAPER_ENTRY_FILL_MODEL!r}')
    await mark_started('trade_tracker')
    dead_watch = DeadLetterWatch(
        'trade_tracker', ('signal.delivered',), logger=logger,
        alert=lambda text: send_alert(text, level='critical', component='TradeTracker'),
        resume_from=lambda: previous_watermark('trade_tracker'))

    consecutive_errors = 0
    owner = worker_id('trade_tracker')
    global price_stream
    stream_task = None
    if config.PRICE_STREAM_ENABLED:
        price_stream = BinancePriceStream(
            symbol_provider=get_open_symbols,
            on_price=handle_stream_price,
            logger=logger,
            refresh_seconds=config.PRICE_STREAM_REFRESH_SECONDS,
            alert_after_seconds=config.PRICE_STREAM_ALERT_AFTER_SECONDS,
            on_status=publish_stream_status,
        )
        stream_task = asyncio.create_task(price_stream.run(), name='binance-price-stream')
    await publish_recovery_event()
    ev2_task = evidence_v2.start_flusher('trade_tracker')   # None unless EVIDENCE_V2_ENABLED

    try:
        while True:
            try:
                await close_blacklisted_trades()
                await enforce_max_open_trades()
                await track_open_trades()
                delivery_events = await claim('signal.delivered', owner, limit=50)
                await register_new_signals()
                delivery = await reconcile_delivery_events(delivery_events, owner)
                await _v2_expiry_sweep()
                await dead_watch.poll()
                consecutive_errors = 0
                await mark_success('trade_tracker', _with_ev2({
                    'delivery_events': len(delivery_events), 'delivery': delivery,
                    'dead_letters': dead_watch.snapshot(),
                    'entry_fill_model': config.PAPER_ENTRY_FILL_MODEL,
                    'price_stream': price_stream.snapshot() if price_stream else None,
                    **({'wp2': {'flags': WP2_FLAGS.as_dict(), 'shadow': dict(WP2_SHADOW_STATS)}}
                       if not WP2_FLAGS.is_legacy else {})}))
                # REST backup checker: catches missed WebSocket events and fills
                # waiting limit candidates without making REST the primary feed.
                await asyncio.sleep(config.PRICE_BACKUP_CHECK_SECONDS)

            except Exception as e:
                consecutive_errors += 1
                await mark_failure('trade_tracker', e)
                network = is_network_error(e)
                wait = compute_backoff(consecutive_errors, network)
                msg = f"❌ خطأ في Trade Tracker ({consecutive_errors}): {format_error(e)}"
                if network:
                    logger.warning(msg)
                else:
                    logger.error(msg)
                if consecutive_errors >= alert_threshold(network):
                    await send_alert(
                        f"Trade Tracker فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
                        level='critical', component='TradeTracker'
                    )
                await asyncio.sleep(wait)

    finally:
        await evidence_v2.stop('trade_tracker', ev2_task)
        if stream_task:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        await Database.disconnect()



# ── Evidence recorder v2 (P1-C) — admission, entry, lifecycle and risk events. Every helper
# reads its inputs, never mutates them, never raises and is a no-op unless EVIDENCE_V2_ENABLED.
_LAST_RISK_CONTEXT: dict = {}
# P1-R: last observed outcome code per signal (bounded; memory only, used to explain deferrals
# and to classify window expiry as NO_FILL). Filled only while instrumentation is ON.
_V2_LAST_OUTCOME: "OrderedDict[int, str]" = OrderedDict()
_V2_LAST_OUTCOME_MAX = 10000
_V2_PROCESS_STARTED = datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC like signal_time
# Must match the admission window of register_new_signals (asserted by tests).
V2_ADMISSION_WINDOW_SQL = "INTERVAL '2 hours'"
_V2_ADMISSION_WINDOW = timedelta(hours=2)   # same window, for the watermark
# Read-only twin of DELIVERY_TERMINAL_SQL that names WHY a delivered signal is terminal
# (same conditions, same order of precedence; asserted equivalent by tests). NULL = not terminal.
DELIVERY_OUTCOME_SQL = f"""
    SELECT CASE
        WHEN NOT s.telegram_sent THEN 'ENTRY_REJECTED'
        WHEN NOT {READY_SQL_PREDICATE} THEN 'NOT_READY'
        WHEN s.signal_time <= NOW()-{V2_ADMISSION_WINDOW_SQL} THEN 'STALE'
        WHEN EXISTS (SELECT 1 FROM symbol_blacklist b WHERE b.symbol=s.symbol) THEN 'BLACKLISTED'
        WHEN EXISTS (SELECT 1 FROM approval_requests ar
                     WHERE ar.signal_id=s.id AND ar.status='rejected') THEN 'REJECTED'
    END AS code
    FROM signals s WHERE s.id=$1
    """
# P1-FIX (MINOR-1): keyset pagination over expired signals by a monotonic (signal_time, id)
# watermark. Every signal has the same admission window, so signals expire in signal_time order:
# each expired row is read once, in order, at most V2_EXPIRY_BATCH per sweep, so already-recorded
# rows can never starve newer expiries (the old oldest-first LIMIT could). Read-only.
V2_EXPIRY_BATCH = 200
_V2_EXPIRY_STATE: dict = {}          # {'watermark': (signal_time, id)}; created only while ON
# Signals whose admission window closed after this process started, still without a trade.
V2_EXPIRED_SQL = f"""
    SELECT s.id, s.symbol, s.timeframe, s.trade_type, s.signal_time, s.features_snapshot,
           EXISTS (SELECT 1 FROM symbol_blacklist b WHERE b.symbol=s.symbol) AS blacklisted,
           EXISTS (SELECT 1 FROM approval_requests ar
                   WHERE ar.signal_id=s.id AND ar.status='rejected') AS rejected
    FROM signals s
    LEFT JOIN active_trades at ON at.signal_id = s.id
    WHERE s.telegram_sent = true
      AND {READY_SQL_PREDICATE}
      AND at.id IS NULL
      AND s.signal_time <= NOW() - {V2_ADMISSION_WINDOW_SQL}
      AND (s.signal_time, s.id) > ($1::timestamp, $2::int)
    ORDER BY s.signal_time, s.id
    LIMIT {V2_EXPIRY_BATCH}
    """


def _v2_note_outcome(signal_id, code: str) -> None:
    try:
        _V2_LAST_OUTCOME[int(signal_id)] = code
        _V2_LAST_OUTCOME.move_to_end(int(signal_id))
        while len(_V2_LAST_OUTCOME) > _V2_LAST_OUTCOME_MAX:
            _V2_LAST_OUTCOME.popitem(last=False)
    except Exception:
        pass


async def _v2_delivery_consumed(event, kind: str) -> None:
    """delivery.consumed — what happened to one claimed runtime `signal.delivered` event:
    opened, terminal (with the named DELIVERY_TERMINAL_SQL condition) or deferred (with the
    last observed admission/entry outcome and whether this was the final outbox attempt).
    Read-only; runs after the runtime ack/fail and never changes it."""
    if not evidence_v2.enabled():
        return
    try:
        sid = event['aggregate_id']
        last = _V2_LAST_OUTCOME.get(int(sid))
        attempts, max_attempts = event.get('attempts'), event.get('max_attempts')
        payload = {'outbox_event_id': event['id'], 'attempts': attempts,
                   'max_attempts': max_attempts, 'last_outcome_code': last}
        if kind == 'opened':
            code = 'OPENED'
        elif kind == 'terminal':
            code = await Database.fetchval(DELIVERY_OUTCOME_SQL, sid) or 'UNKNOWN'
            if code == 'STALE' and last == 'AWAITING_FILL':
                payload['resolved_code'] = 'NO_FILL'
        else:
            exists = await Database.fetchval("SELECT 1 FROM signals WHERE id=$1", sid)
            code = 'SIGNAL_MISSING' if not exists else (last or 'DEFERRED_UNOBSERVED')
            payload['final_attempt'] = bool(attempts is not None and max_attempts is not None
                                            and attempts >= max_attempts)
        payload['outcome_code'] = code
        evidence_v2.emit('trade_tracker', 'delivery.consumed',
                         {'signal_id': sid, 'outbox_event_id': event['id']}, payload,
                         state={'kind': kind, 'outcome_code': code, 'attempts': attempts},
                         dedup_key=f"consumed:{event['id']}")
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


async def _v2_expiry_sweep() -> None:
    """entry.expired — terminal record for a sent, ready signal that left the admission window
    without a trade: NO_FILL when the last observed entry action was a limit wait. Read-only;
    only signals whose window closed after this process started (no restated history)."""
    if not evidence_v2.enabled():
        return
    try:
        if 'watermark' not in _V2_EXPIRY_STATE:     # first sweep: windows closing after boot only
            _V2_EXPIRY_STATE['watermark'] = (_V2_PROCESS_STARTED - _V2_ADMISSION_WINDOW, 0)
        wm_time, wm_id = _V2_EXPIRY_STATE['watermark']
        rows = await Database.fetch(V2_EXPIRED_SQL, wm_time, wm_id)
        for row in rows:
            last = _V2_LAST_OUTCOME.get(int(row['id']))
            code = ('BLACKLISTED' if row['blacklisted'] else 'REJECTED' if row['rejected']
                    else evidence_v2.expiry_outcome_code(last))
            dropped_before = evidence_v2.dropped_count('trade_tracker')
            evidence_v2.emit('trade_tracker', 'entry.expired', _v2_signal_subject(row), {
                'outcome_code': code, 'last_outcome_code': last,
                'signal_time': row['signal_time'], 'admission_window': '2 hours',
                'trade_type': row['trade_type'],
            }, state={'outcome_code': code}, dedup_key=f"expiry:{row['id']}")
            if (not evidence_v2.is_recorded('trade_tracker', f"expiry:{row['id']}", {'outcome_code': code})
                    and evidence_v2.dropped_count('trade_tracker') > dropped_before):
                break       # dropped (queue full): keep the watermark here and retry on the next sweep
            # recorded, or a non-retryable failure (counted in recorder errors): advance, so one bad
            # row can never block later expiries
            _V2_EXPIRY_STATE['watermark'] = (row['signal_time'], int(row['id']))   # advance past it
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _with_ev2(metadata: dict) -> dict:
    """Heartbeat metadata plus recorder health when v2 is enabled (unchanged otherwise)."""
    health = evidence_v2.health('trade_tracker')
    return {**metadata, 'evidence_v2': health} if health is not None else metadata


def _v2_signal_subject(sig) -> dict:
    features = sig['features_snapshot'] if 'features_snapshot' in sig.keys() else None
    if isinstance(features, str):
        features = json.loads(features)
    identity = (features or {}).get('identity') or {}
    return {'signal_id': sig['id'], 'candidate_id': identity.get('candidate_id'),
            'symbol': sig['symbol'], 'timeframe': sig['timeframe']}


def _v2_risk_payload(decision) -> dict:
    ctx = dict(_LAST_RISK_CONTEXT)
    out = {'risk_epoch_start': ctx.get('risk_epoch_start'), 'risk_snapshot': ctx.get('snapshot'),
           'risk_limits': ctx.get('limits'), 'risk_policy_version': config.RISK_POLICY_VERSION}
    if decision is not None:
        out['risk_decision'] = (dataclasses.asdict(decision) if dataclasses.is_dataclass(decision)
                                else {'allowed': getattr(decision, 'allowed', None),
                                      'reason': getattr(decision, 'reason', None)})
    return out


def _v2_note_risk_context(risk_start, snapshot, limits) -> None:
    if not evidence_v2.enabled():
        return
    try:
        _LAST_RISK_CONTEXT.clear()
        _LAST_RISK_CONTEXT.update({
            'risk_epoch_start': evidence_v2.ms_to_iso(evidence_v2.to_ms(risk_start)),
            'snapshot': dataclasses.asdict(snapshot), 'limits': dataclasses.asdict(limits)})
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_admission(sig, outcome: str, reason=None, decision=None, **extra) -> None:
    """admission.decision — emitted when a signal's admission state changes."""
    if not evidence_v2.enabled():
        return
    try:
        subject = _v2_signal_subject(sig)
        # Every admission record names the economic-halt policy it was decided under, so
        # observe-mode collection is separable (prospective-window boundary). Payload only:
        # the dedup state (and so event identity) is unchanged.
        payload = {**extra, 'risk_policy_version': config.RISK_POLICY_VERSION}
        if isinstance(reason, BaseException):
            reason = f"{type(reason).__name__}: {reason}"[:200]
        if reason is None and outcome == 'risk_rejected':
            reason = getattr(decision, 'reason', None)
        if decision is not None or outcome == 'risk_rejected':
            payload.update(_v2_risk_payload(decision))
        code = evidence_v2.admission_outcome_code(outcome, reason)
        payload['outcome_code'] = code
        _v2_note_outcome(sig['id'], code)
        evidence_v2.emit('trade_tracker', 'admission.decision', subject, payload,
                         state={'outcome': outcome, 'reason': reason},
                         dedup_key=f"admission:{sig['id']}")
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_entry(sig, entry_decision, observed_price, features) -> None:
    """entry.attempt — fill / limit_wait / reject, as decided by the unchanged fill model."""
    if not evidence_v2.enabled():
        return
    try:
        code = evidence_v2.entry_outcome_code(getattr(entry_decision, 'action', None))
        _v2_note_outcome(sig['id'], code)
        evidence_v2.emit('trade_tracker', 'entry.attempt', _v2_signal_subject(sig), {
            'outcome_code': code,
            'planned_entry': float(sig['entry_price']), 'observed_price': observed_price,
            'stop_loss': float(sig['stop_loss']),
            'invalidation_price': (features or {}).get('stop_invalidation'),
            'order_price': getattr(entry_decision, 'order_price', None),
            'trade_type': sig['trade_type'],
        }, state={'action': getattr(entry_decision, 'action', None),
                  'reason': getattr(entry_decision, 'reason', None)},
            dedup_key=f"entry:{sig['id']}")
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_capacity(blocked: bool, open_count, limit) -> None:
    if not evidence_v2.enabled():
        return
    try:
        evidence_v2.emit('trade_tracker', 'admission.capacity', {'stream': 'trade_tracker.capacity'},
                         {'open_count': open_count, 'max_open_trades': limit},
                         state={'blocked': blocked}, dedup_key='admission.capacity', transition=True)
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_trade_opened(sig, trade_id, bracket, fill_entry, entry_decision, risk_decision,
                     min_notional, expiry) -> None:
    if not evidence_v2.enabled():
        return
    try:
        subject = {**_v2_signal_subject(sig), 'active_trade_id': trade_id}
        evidence_v2.emit('trade_tracker', 'trade.opened', subject, {
            'fill_price': fill_entry, 'planned_entry': float(sig['entry_price']),
            'drift_pct': (fill_entry / float(sig['entry_price']) - 1) * 100,
            'bracket': dict(bracket), 'entry_order_type': getattr(entry_decision, 'action', None),
            'min_order_notional_usdt': min_notional,
            'expiry_hours': {'max': expiry[0], 't1_stall': expiry[1], 'no_t1': expiry[2]},
            'trade_amount_usdt': config.TRADE_AMOUNT_USDT,
            **_v2_risk_payload(risk_decision)})
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_target_hits(trade, partial_fills, highest_target, current_price, source, effective_stop) -> None:
    if not evidence_v2.enabled():
        return
    try:
        for fill in partial_fills:
            evidence_v2.emit('trade_tracker', 'trade.target_hit', {
                'active_trade_id': trade['id'], 'signal_id': trade.get('signal_id'),
                'target': fill.target}, {
                'fill_price': fill.price, 'quantity_fraction': fill.fraction,
                'notional_usdt': config.TRADE_AMOUNT_USDT * fill.fraction,
                'gross_profit_percent_contribution': fill.gross_pct_contribution,
                'gross_profit_usdt': fill.gross_usdt, 'observed_price': current_price,
                'highest_target': highest_target, 'price_source': source,
                'effective_stop_after': effective_stop})
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_trade_closed(trade, trade_result_id, reason, exit_price, weighted_exit, profit_pct,
                     profit_usdt, hours_open, target_reached, stop_hit) -> None:
    if not evidence_v2.enabled():
        return
    try:
        costs = _costs()
        fee_usdt = costs.fee_usdt()
        evidence_v2.emit('trade_tracker', 'trade.closed', {
            'active_trade_id': int(trade['id']), 'signal_id': trade.get('signal_id'),
            'trade_result_id': trade_result_id}, {
            'symbol': trade.get('symbol'), 'timeframe': trade.get('timeframe'),
            'exit_reason': reason, 'trigger_price': exit_price, 'weighted_exit_price': weighted_exit,
            'gross_profit_pct': profit_pct, 'gross_profit_usdt': profit_usdt,
            'fee_roundtrip_usdt': fee_usdt, 'net_profit_usdt': costs.net_usdt(profit_usdt),
            'result_label': 'WIN' if profit_usdt > 0 else 'LOSS',
            'hours_open': hours_open, 'target_reached': target_reached, 'stop_hit': stop_hit,
            'result_row_inserted': trade_result_id is not None})
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


def _v2_risk_state(decision, paused: bool, was_paused: bool) -> None:
    if not evidence_v2.enabled():
        return
    try:
        payload = _v2_risk_payload(decision)
        evidence_v2.emit('trade_tracker', 'risk.state', {'stream': 'trade_tracker.risk'}, payload,
                         state={'allowed': decision.allowed, 'reason': decision.reason, 'paused': paused},
                         dedup_key='risk.state', transition=True)
        if paused and not was_paused:
            evidence_v2.emit('trade_tracker', 'risk.transition', {'stream': 'trade_tracker.risk'},
                             payload, state={'halted': True, 'reason': decision.reason}, transition=True)
        if not economic_halt_blocks(economic_halt_mode()):
            # Paper observe mode only: the economic state is recorded once per change
            # (append-only evidence; no pause row). The operator notification is the
            # separate `risk.observed` outbox event (_enqueue_observation_alert).
            evidence_v2.emit('trade_tracker', 'risk.observed', {'stream': 'trade_tracker.risk'},
                             payload, state={
                                 'observed': getattr(decision, 'observed_economic_stop', None),
                                 'flags': list(getattr(decision, 'economic_flags', ()) or ())},
                             dedup_key='risk.observed', transition=True)
    except Exception as exc:
        evidence_v2.hook_error('trade_tracker', exc)


# ── WP2 shadows (default off): position-state validation and ledger reconciliation. Each runs
# after the tracker's own committed step, reads only what that step already holds, never raises,
# and never changes a decision or a database write. Results go to the log and, when the
# evidence-v2 store is on, to it (no new table: persistence is WP-E03/WP-E04).
WP2_SHADOW_STATS = {'position_state_checked': 0, 'position_state_refusals': 0,
                    'ledger_reconciled': 0, 'ledger_mismatches': 0, 'shadow_errors': 0}


def _shadow_emit(event_type: str, subject: dict, payload: dict) -> None:
    if evidence_v2.enabled():
        evidence_v2.emit('trade_tracker', event_type, subject, payload)


def _shadow_min_notional(trade) -> float:
    return float(trade.get('min_order_notional_usdt') or config.MIN_ORDER_NOTIONAL_USDT)


def _shadow_position_result(result) -> None:
    WP2_SHADOW_STATS['position_state_checked'] += 1
    if not result.ok:
        WP2_SHADOW_STATS['position_state_refusals'] += 1
        logger.warning(f"position_state shadow refusal (trade {result.trade_id}, {result.site}): "
                       f"{[r.as_dict() for r in result.refusals]}")
    _shadow_emit('position_state.shadow', {'active_trade_id': result.trade_id, 'site': result.site},
                 result.as_dict())


def _shadow_target_hits(trade, cfg, state, prev_highest, partial_fills) -> None:
    try:
        entry = float(trade['entry_price'])
        result = position_state_shadow.validate_target_hits(
            trade, cfg=cfg, peak_before=max(float(trade.get('peak_price') or entry), entry),
            peak=state.peak, prev_highest=prev_highest, new_highest=state.highest_target,
            fills=partial_fills, notional=config.TRADE_AMOUNT_USDT,
            min_notional=_shadow_min_notional(trade))
        _shadow_position_result(result)
    except Exception as exc:
        WP2_SHADOW_STATS['shadow_errors'] += 1
        logger.error(f"position_state shadow failed (no effect): {format_error(exc)}")


def _shadow_close(trade, reason, exit_price) -> None:
    try:
        result = position_state_shadow.validate_close(
            trade, reason=reason, exit_price=exit_price, notional=config.TRADE_AMOUNT_USDT,
            min_notional=_shadow_min_notional(trade))
        _shadow_position_result(result)
    except Exception as exc:
        WP2_SHADOW_STATS['shadow_errors'] += 1
        logger.error(f"position_state shadow failed (no effect): {format_error(exc)}")


def _shadow_reconcile(trade, trade_result_id, target_legs, exit_price, remaining_fraction,
                      profit_usdt, econ) -> None:
    """PR-I13 shadow: ledger realized net against the net this close just booked."""
    try:
        opened = trade['opened_at']
        opened = opened.replace(tzinfo=timezone.utc) if opened.tzinfo is None else opened
        closed = max(datetime.now(timezone.utc), opened)
        close = ledger_legacy_adapter.TrackerClose(
            trade_id=int(trade['id']), symbol=str(trade['symbol']), strategy_id='unassigned',
            opened_at=opened, closed_at=closed, entry_price=float(trade['entry_price']),
            notional=config.TRADE_AMOUNT_USDT, target_fills=tuple(target_legs),
            final_exit_price=float(exit_price), remaining_fraction=float(remaining_fraction),
            booked_profit_usdt=round(profit_usdt, 4), booked_cost_usdt=econ['cost_usdt'],
            booked_net_profit_usdt=econ['net_profit_usdt'], label_policy=econ['label_policy'])
        rec = ledger_legacy_adapter.reconcile(close, _costs())
        WP2_SHADOW_STATS['ledger_reconciled'] += 1
        if not rec.ok:
            WP2_SHADOW_STATS['ledger_mismatches'] += 1
            logger.error(f"ledger shadow {rec.reason_code} for trade {rec.trade_id} "
                         f"(shadow only, no halt): {rec.as_dict()}")
        _shadow_emit('ledger.reconciliation', {'active_trade_id': int(trade['id']),
                                               'trade_result_id': trade_result_id}, rec.as_dict())
    except Exception as exc:
        WP2_SHADOW_STATS['shadow_errors'] += 1
        logger.error(f"ledger shadow failed (no effect): {format_error(exc)}")


async def get_open_symbols() -> set[str]:
    rows = await Database.fetch(
        "SELECT DISTINCT symbol FROM active_trades WHERE status='open'")
    return {row['symbol'] for row in rows}


async def handle_stream_price(symbol: str, price: float):
    """Evaluate every open trade for one symbol from an ordered WebSocket tick."""
    rows = await Database.fetch(
        "SELECT * FROM active_trades WHERE status='open' AND symbol=$1", symbol)
    for row in rows:
        await evaluate_trade_safely(dict(row), price, source='websocket')


async def _publish_runtime_event(event_type: str, payload: dict):
    async with Database.acquire() as conn:
        async with conn.transaction():
            key = await conn.fetchval(
                "SELECT nextval(pg_get_serial_sequence('outbox_events','id'))")
            await enqueue(conn, event_type, 'runtime_transition', key, payload)


async def publish_stream_status(status: str, details: dict):
    await _publish_runtime_event(f'price_stream.{status}', details)


async def publish_recovery_event():
    rows = await Database.fetch(
        "SELECT id,symbol FROM active_trades WHERE status='open' ORDER BY id")
    if rows:
        await _publish_runtime_event('tracker.recovered', {
            'count': len(rows),
            'symbols': [row['symbol'] for row in rows],
            'websocket_enabled': config.PRICE_STREAM_ENABLED,
        })


async def close_blacklisted_trades():
    """إغلاق أي صفقة مفتوحة لعملة في القائمة السوداء (مرفوضة من المستخدم)"""
    blacklisted = await Database.fetch("""
        SELECT at.*
        FROM active_trades at
        JOIN symbol_blacklist bl ON at.symbol = bl.symbol
        WHERE at.status = 'open'
    """)
    for trade in blacklisted:
        current_price = await get_current_price(trade['symbol'])
        if not current_price:
            logger.warning(
                f"تعذر إغلاق {trade['symbol']} المدرجة في القائمة السوداء: لا يوجد سعر")
            continue
        trade = dict(trade)
        entry = float(trade['entry_price'])
        pnl_pct = ((current_price - entry) / entry) * 100
        result = 'WIN' if pnl_pct > 0 else 'LOSS'
        await close_trade(
            trade, result, pnl_pct, current_price,
            'إغلاق تلقائي - أُضيف الرمز إلى القائمة السوداء')


async def enforce_max_open_trades():
    """إذا الصفقات المفتوحة تجاوزت الحد الأقصى، أغلق الأكثر خسارة حتى نصل للحد.
    المنطق: نتخلص من الصفقات الخاسرة أولاً (يحرر رأس المال ويقطع النزيف)،
    بدلاً من إغلاق الأقدم التي قد تكون على وشك تحقيق هدف.
    """
    if config.MAX_OPEN_TRADES <= 0:
        return

    open_trades = await Database.fetch("""
        SELECT id, symbol, entry_price, opened_at
        FROM active_trades
        WHERE status = 'open'
    """)

    excess = len(open_trades) - config.MAX_OPEN_TRADES
    if excess <= 0:
        return

    logger.warning(f"⚠️ {len(open_trades)} صفقة مفتوحة تتجاوز الحد {config.MAX_OPEN_TRADES} — إغلاق {excess} الأكثر خسارة")

    # جلب الأسعار الحالية وترتيب الصفقات من الأكثر خسارة للأقل
    trades_with_pnl = []
    for trade in open_trades:
        current_price = await get_current_price(trade['symbol'])
        if current_price:
            entry = float(trade['entry_price'])
            pnl_pct = ((current_price - entry) / entry) * 100
            trades_with_pnl.append((pnl_pct, dict(trade), current_price))
        else:
            # إذا لم نجد السعر نضعه كأسوأ حالة (يُغلق أولاً)
            trades_with_pnl.append((float('-inf'), dict(trade), None))

    # ترتيب من الأكثر خسارة (أدنى pnl) للأقل
    trades_with_pnl.sort(key=lambda x: x[0])

    for pnl_pct, trade_info, current_price in trades_with_pnl[:excess]:
        if current_price:
            trade_dict = dict(await Database.fetchrow(
                "SELECT * FROM active_trades WHERE id = $1", trade_info['id']
            ))
            result = 'WIN' if pnl_pct > 0 else 'LOSS'
            await close_trade(trade_dict, result, pnl_pct, current_price,
                              f"إغلاق تلقائي - تجاوز حد MAX_OPEN_TRADES={config.MAX_OPEN_TRADES} (خسارة: {pnl_pct:.2f}%)")
        else:
            # لا نُحوّل المركز إلى مغلق دون سعر ونتيجة؛ وإلا يختفي من المتابعة
            # ولا يمكن إنشاء إشعار إغلاق محاسبي صحيح.
            logger.error(
                f"تعذر إغلاق {trade_info['symbol']} لتجاوز الحد: لا يوجد سعر؛ ستبقى تحت المتابعة")


# A delivered signal is terminal (ack, never registered) when it is not sent, NOT
# READY (CR-1: decision_source='policy_ready' OR legacy claude_approved=true —
# READY_SQL_PREDICATE is NULL-safe, so NOT never degrades to NULL/"retry"), stale,
# blacklisted or rejected by the owner. Readiness never bypasses the risk guard.
DELIVERY_TERMINAL_SQL = f"""
    SELECT 1 FROM signals s
    WHERE s.id=$1 AND (
        NOT s.telegram_sent OR NOT {READY_SQL_PREDICATE}
        OR s.signal_time <= NOW()-INTERVAL '2 hours'
        OR EXISTS (SELECT 1 FROM symbol_blacklist b WHERE b.symbol=s.symbol)
        OR EXISTS (SELECT 1 FROM approval_requests ar
                   WHERE ar.signal_id=s.id AND ar.status='rejected'))
    """


# ── A38: durable paper entry orders ────────────────────────────────────────────────────────────
async def _load_entry_order(signal_id: int):
    return await Database.fetchrow(
        "SELECT order_kind, status FROM paper_entry_orders WHERE signal_id=$1", signal_id)


async def _record_entry_order(sig, order, fill, observed_price: float) -> None:
    """Create the order on its first evaluation; afterwards record kind changes (marketable ->
    resting) and rejection. The legacy fill model does not depend on this record, so a write
    failure there is logged and tolerated (admission is unchanged). resting_limit_v1 prices fills
    from the record, so it fails closed (the loop retries)."""
    try:
        if order is None:
            await Database.execute(
                """INSERT INTO paper_entry_orders
                   (signal_id, order_kind, limit_price, first_observed_price, status,
                    terminal_reason, fill_model)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (signal_id) DO NOTHING""",
                sig['id'], fill.order_kind, float(sig['entry_price']), float(observed_price),
                'rejected' if fill.action == 'reject' else 'working',
                fill.basis if fill.action == 'reject' else None, config.PAPER_ENTRY_FILL_MODEL)
        elif order['status'] == 'working':
            await Database.execute(
                """UPDATE paper_entry_orders
                   SET order_kind=$2,
                       status=CASE WHEN $3 THEN 'rejected' ELSE status END,
                       terminal_reason=CASE WHEN $3 THEN $4 ELSE terminal_reason END,
                       updated_at=NOW()
                   WHERE signal_id=$1 AND status='working'
                     AND (order_kind<>$2 OR $3)""",
                sig['id'], fill.order_kind, fill.action == 'reject', fill.basis)
    except Exception as exc:
        if config.PAPER_ENTRY_FILL_MODEL != 'observed_price_v0':
            raise
        logger.error(f"paper_entry_orders write failed for signal {sig['id']} "
                     f"(legacy fill model, admission unaffected): {format_error(exc)}")


def _entry_order_type(entry_decision, fill) -> str:
    """active_trades.entry_order_type: unchanged under the legacy model (the policy action);
    under resting_limit_v1 'limit' for a resting fill and 'market' for a marketable one."""
    if config.PAPER_ENTRY_FILL_MODEL == 'observed_price_v0':
        return entry_decision.action
    return 'limit' if fill.basis == 'resting_trade_through' else 'market'


# ── A38: delivery-event reconciliation ─────────────────────────────────────────────────────────
# `signal.delivered` is a reconciliation event: admission itself is poll-based
# (register_new_signals), and the event is completed when the signal's admission outcome is
# known. Before A38, an open admission window was handled with fail(): every 5-minute re-check
# consumed one of 8 attempts, so the event dead-lettered after about 37 minutes while the signal
# could still be admitted for 2 hours. 312 dead letters were mostly correct business outcomes,
# 9 trades opened after their event had died, and a genuine failure looked like any of them.
# Now:
#   * trade exists                 -> ack 'opened';
#   * terminal (DELIVERY_TERMINAL_SQL, unchanged) -> ack 'terminal:<DELIVERY_OUTCOME_SQL code>';
#   * window still open            -> defer (not an attempt), re-check every 5 min, never past
#                                     the window end;
#   * signal missing, or still unresolved DELIVERY_RESOLUTION_GRACE after the window closed
#     -> fail(): counted, and a dead letter is now a genuine, alerted failure.
DELIVERY_RECHECK_SECONDS = 300
DELIVERY_RESOLUTION_GRACE = timedelta(minutes=30)
DELIVERY_WINDOW_SQL = f"""
    SELECT EXTRACT(EPOCH FROM (s.signal_time + {V2_ADMISSION_WINDOW_SQL}) - NOW()) AS remaining_s
    FROM signals s WHERE s.id=$1
    """


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def reconcile_delivery_events(delivery_events, owner: str) -> dict:
    counts = {'opened': 0, 'terminal': 0, 'deferred': 0, 'failed': 0}
    for event in delivery_events:
        sid = event['aggregate_id']
        if await Database.fetchval("SELECT 1 FROM active_trades WHERE signal_id=$1", sid):
            await ack(event['id'], owner, 'opened')
            counts['opened'] += 1
            await _v2_delivery_consumed(event, 'opened')
            continue
        if await Database.fetchval(DELIVERY_TERMINAL_SQL, sid):
            code = await Database.fetchval(DELIVERY_OUTCOME_SQL, sid)
            await ack(event['id'], owner, f"terminal:{code or 'UNKNOWN'}")
            counts['terminal'] += 1
            await _v2_delivery_consumed(event, 'terminal')
            continue
        window = await Database.fetchrow(DELIVERY_WINDOW_SQL, sid)
        created = event.get('created_at')
        overdue = (created is not None and _naive_utc_now() - created
                   > _V2_ADMISSION_WINDOW + DELIVERY_RESOLUTION_GRACE)
        if window is None:
            await fail(event['id'], owner, RuntimeError('signal_missing'), DELIVERY_RECHECK_SECONDS)
            counts['failed'] += 1
        elif window['remaining_s'] is None or overdue:
            await fail(event['id'], owner,
                       RuntimeError('admission_state_unresolved_after_window'),
                       DELIVERY_RECHECK_SECONDS)
            counts['failed'] += 1
        else:
            await defer(event['id'], owner,
                        bounded_delay(DELIVERY_RECHECK_SECONDS, float(window['remaining_s'])),
                        'admission window open; awaiting admission outcome')
            counts['deferred'] += 1
        await _v2_delivery_consumed(event, 'deferred')
    return counts


def _now_ms() -> int:
    """Admission time for the A44 freshness rule (injectable in tests)."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def integrity_admission_refusal(sig, now_ms: int | None = None) -> str | None:
    """A44: why a delivered signal must not open a trade, or None.

    The 2 h admission window is wall-clock; a setup is only actionable until a newer candle of
    its timeframe has closed (A43: ADA/NEAR/ORCA/POL were re-opened 4 h later on a superseded
    candle). A signal without a stored setup identity is refused (fail closed)."""
    features = sig['features_snapshot'] or {}
    if isinstance(features, str):
        features = json.loads(features)
    setup = features.get('setup_identity') or {}
    close_ms = setup.get('candle_close_time_ms')
    if not setup.get('key') or not isinstance(close_ms, int) or isinstance(close_ms, bool):
        return 'integrity:setup_identity_missing'
    now_ms = _now_ms() if now_ms is None else now_ms
    fresh = freshness_at(sig['timeframe'], close_ms, now_ms)
    return None if fresh.admissible else f'integrity:{fresh.reason}'


async def register_new_signals():
    """تسجيل الإشارات المرسلة حديثاً كصفقات نشطة — صفقة واحدة لكل (عملة، إطار) لكل شمعة"""
    # تحقق من حد الصفقات المفتوحة
    funnel = TrackerAdmissionFunnel.begin(_FUNNEL) if _FUNNEL is not None else None
    if config.MAX_OPEN_TRADES > 0:
        open_count = await Database.fetchval(
            "SELECT COUNT(*) FROM active_trades WHERE status = 'open'"
        ) or 0
        pre = capacity.tracker_precheck(open_count, config.MAX_OPEN_TRADES, site='loop_entry')
        if pre.blocked:
            _v2_capacity(True, open_count, config.MAX_OPEN_TRADES)
            logger.info(f"⏸️ وصلنا للحد الأقصى للصفقات المفتوحة: {open_count}/{config.MAX_OPEN_TRADES}")
            if funnel is not None:
                funnel.loop_entry_full(pre)
                funnel.finish()
            return
        _v2_capacity(False, open_count, config.MAX_OPEN_TRADES)

    candle_case = candle_interval_case_sql('s.timeframe')
    new_signals = await Database.fetch(f"""
        SELECT DISTINCT ON (s.symbol)
               s.id, s.symbol, s.entry_price, s.target_1, s.target_2, s.target_3,
               s.stop_loss, s.timeframe, s.is_paper_trade, s.trade_type,
               s.features_snapshot
        FROM signals s
        LEFT JOIN active_trades at ON s.id = at.signal_id
        WHERE s.telegram_sent = true
        AND {READY_SQL_PREDICATE}
        AND at.id IS NULL
        AND s.signal_time > NOW() - INTERVAL '2 hours'
        AND NOT EXISTS (
            SELECT 1 FROM active_trades at2
            WHERE at2.symbol = s.symbol AND at2.status = 'open'
        )
        AND NOT EXISTS (
            -- صفقة واحدة لكل (رمز، إطار) خلال فترة الشمعة — يمنع عدّ نفس الإعداد المُعاد إطلاقه مراراً
            SELECT 1 FROM active_trades at3
            WHERE at3.symbol = s.symbol
              AND at3.timeframe = s.timeframe
              AND at3.opened_at > NOW() - ({candle_case})
        )
        AND NOT EXISTS (
            SELECT 1 FROM approval_requests ar
            WHERE ar.signal_id = s.id AND ar.status = 'rejected'
        )
        AND s.symbol NOT IN (
            SELECT symbol FROM symbol_blacklist
        )
        ORDER BY s.symbol, s.signal_time DESC
    """)

    if funnel is not None:
        funnel.considered(len(new_signals))
    for index, sig in enumerate(new_signals):
        if config.MAX_OPEN_TRADES > 0:
            open_count = await Database.fetchval(
                "SELECT COUNT(*) FROM active_trades WHERE status = 'open'"
            ) or 0
            pre = capacity.tracker_precheck(open_count, config.MAX_OPEN_TRADES, site='per_signal')
            if pre.blocked:
                _v2_capacity(True, open_count, config.MAX_OPEN_TRADES)
                logger.info(f"⏸️ توقف تسجيل إشارات جديدة — وصلنا الحد: {open_count}/{config.MAX_OPEN_TRADES}")
                if funnel is not None:
                    funnel.capacity_full(new_signals[index:], pre)
                break

        if integrity_mode(config) == 'enforce':                    # A44: admit fresh setups only
            refusal = integrity_admission_refusal(sig)
            if refusal:
                _v2_admission(sig, 'integrity_rejected', refusal)
                logger.warning(f"⛔ {sig['symbol']} (signal {sig['id']}) not admitted: {refusal}")
                # Terminal exactly like an entry rejection (A38 reconciliation acks it).
                await Database.execute(
                    "UPDATE signals SET telegram_sent=false WHERE id=$1", sig['id'])
                if funnel is not None:
                    funnel.exclude('F4_integrity')
                continue

        fill_entry = await get_current_price(sig['symbol'])
        if not fill_entry:
            _v2_admission(sig, 'no_price', 'no_current_fill_price')
            logger.warning(f"تعذر تسجيل {sig['symbol']}: لا يوجد سعر تعبئة حالي")
            if funnel is not None:
                funnel.no_price(sig)
            continue

        features = sig['features_snapshot'] or {}
        if isinstance(features, str):
            features = json.loads(features)
        entry_decision = decide_long_entry(
            trade_type=sig['trade_type'],
            planned_entry=float(sig['entry_price']),
            current_price=fill_entry,
            stop_loss=float(sig['stop_loss']),
            invalidation_price=features.get('stop_invalidation'),
        )
        # A38: the fill model turns the (unchanged) entry policy decision into a simulated fill.
        # With the default legacy model, fill.action mirrors entry_decision.action exactly.
        order = await _load_entry_order(sig['id'])
        fill = resolve_entry_fill(
            model=config.PAPER_ENTRY_FILL_MODEL, decision=entry_decision,
            previous_kind=order['order_kind'] if order else None,
            planned_entry=float(sig['entry_price']), current_price=fill_entry,
            stop_loss=float(sig['stop_loss']),
            invalidation_price=features.get('stop_invalidation'))
        await _record_entry_order(sig, order, fill, fill_entry)
        _v2_entry(sig, entry_decision, fill_entry, features)
        if fill.action == 'reject':
            logger.warning(
                f"⛔ رفض تعبئة {sig['symbol']}: {entry_decision.reason} "
                f"(الآن={fill_entry}, stop={sig['stop_loss']})")
            # Make the rejection terminal without mislabelling it as a model decision.
            await Database.execute(
                "UPDATE signals SET telegram_sent=false WHERE id=$1", sig['id'])
            if funnel is not None:
                funnel.entry_rejected(sig, entry_decision.reason)
            continue
        if fill.action == 'wait':
            logger.info(
                f"⏳ Limit paper order {sig['symbol']} @ {sig['entry_price']}; "
                f"السعر الحالي {fill_entry} — لا نطارد السعر ({fill.basis})")
            if funnel is not None:
                funnel.held_wait()
            continue
        observed_price, fill_entry = fill_entry, float(fill.price)
        min_notional = await get_min_notional(sig['symbol'])

        macro_state = await Database.fetchval(
            "SELECT COALESCE(macro_snapshot->>'usdtd_trend', market_condition) FROM signals WHERE id=$1",
            sig['id'])
        trade_type = await Database.fetchval(
            "SELECT trade_type FROM signals WHERE id=$1", sig['id'])
        risk_decision = await assess_new_trade_risk(
            sig['symbol'], trade_type=trade_type, regime=macro_state)
        await record_risk_decision(risk_decision)
        if risk_decision.allowed and getattr(risk_decision, 'observed_economic_stop', None):
            logger.warning(
                f"{sig['symbol']}: economic stop {risk_decision.observed_economic_stop} "
                f"observed (Paper observe mode, not blocking; "
                f"flags={','.join(risk_decision.economic_flags)})")
        if not risk_decision.allowed:
            _v2_admission(sig, 'risk_rejected', None, risk_decision, observed_price=observed_price)
            logger.warning(
                f"⛔ رفض صفقة {sig['symbol']} بواسطة حارس المخاطر: "
                f"{risk_decision.reason} (daily={risk_decision.daily_pnl_pct:.2f}%, "
                f"weekly={risk_decision.weekly_pnl_pct:.2f}%, "
                f"drawdown={risk_decision.drawdown_pct:.2f}%)")
            if funnel is not None:
                funnel.risk_refused(sig, _last_capacity_decision(risk_decision))
            continue
        try:
            bracket = rebase_long_bracket(
                float(sig['entry_price']), fill_entry,
                float(sig['target_1']), float(sig['target_2']), float(sig['target_3']),
                float(sig['stop_loss']),
            )
        except ValueError as exc:
            _v2_admission(sig, 'bracket_invalid', exc)
            logger.error(f"رفض bracket غير صالح لـ {sig['symbol']}: {exc}")
            if funnel is not None:
                funnel.exclude('F5_bracket_invalid')
            continue

        expiry_h, t1_expiry_h, no_t1_expiry_h = expiry_policy_for_timeframe(sig['timeframe'])
        async with Database.acquire() as conn:
            async with conn.transaction():
                # Same advisory lock /recover_risk takes. Held only across the
                # halt re-check and the row that makes the position real, so a
                # recovery can never be acknowledged on a flat-book assumption
                # that this insert is about to invalidate.
                await acquire_risk_admission_lock(conn)
                streak_blocks, streak_observed = await _loss_streak_under_lock(conn)
                if streak_blocks:
                    # A recovery/halt transition landed between the risk check
                    # above and this lock; re-verify rather than trust the
                    # earlier read.
                    _v2_admission(sig, 'halt_under_admission_lock', 'loss_streak_halt')
                    logger.warning(
                        f"⛔ إلغاء فتح {sig['symbol']}: قاطع سلسلة الخسائر أصبح نشطاً "
                        f"قبل تثبيت الصفقة")
                    if funnel is not None:
                        funnel.halt_under_lock(sig)
                    continue
                trade_id = await conn.fetchval("""
                    INSERT INTO active_trades
                    (signal_id, symbol, entry_price, target_1, target_2, target_3,
                     stop_loss, timeframe, is_paper_trade, entry_order_type,
                     stop_policy, stop_invalidation, exit_policy_version,
                     min_order_notional_usdt, expiry_policy_version,
                     expiry_h, t1_expiry_h, no_t1_expiry_h, entry_fill_model)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                            $15, $16, $17, $18, $19)
                    ON CONFLICT (signal_id) WHERE signal_id IS NOT NULL DO NOTHING
                    RETURNING id
                """,
                    sig['id'], sig['symbol'],
                    bracket['entry_price'], bracket['target_1'], bracket['target_2'], bracket['target_3'],
                    bracket['stop_loss'], sig['timeframe'], sig['is_paper_trade'],
                    _entry_order_type(entry_decision, fill), features.get('stop_policy'),
                    (float(features['stop_invalidation'])
                     * fill_entry / float(sig['entry_price'])
                     if features.get('stop_invalidation') else bracket['stop_loss']),
                    'partial_25_50_25_v1', min_notional, 'timeframe_v1',
                    expiry_h, t1_expiry_h, no_t1_expiry_h, config.PAPER_ENTRY_FILL_MODEL)
                if trade_id:
                    await conn.execute(
                        "UPDATE paper_entry_orders SET status='filled', fill_price=$2, "
                        "fill_basis=$3, updated_at=NOW() WHERE signal_id=$1 AND status='working'",
                        sig['id'], fill_entry, fill.basis)
                    await enqueue(conn, 'trade.opened', 'active_trade', trade_id,
                                  {'active_trade_id': trade_id})
        if trade_id:
            _v2_admission(sig, 'admitted', None, risk_decision, active_trade_id=trade_id,
                          **({'observed_under_admission_lock': streak_observed}
                             if streak_observed else {}))
            _v2_trade_opened(sig, trade_id, bracket, fill_entry, entry_decision, risk_decision,
                             min_notional, (expiry_h, t1_expiry_h, no_t1_expiry_h))
            if funnel is not None:
                funnel.admitted()
        else:
            _v2_admission(sig, 'already_registered', 'active_trade_exists_for_signal')
            if funnel is not None:
                funnel.already_registered(sig)
        if trade_id:
            drift_pct = (fill_entry / float(sig['entry_price']) - 1) * 100
            logger.info(
                f"📋 صفقة جديدة مسجلة: {sig['symbol']} @ {fill_entry} "
                f"(سعر الإشارة {sig['entry_price']}، drift {drift_pct:+.3f}%)")
    if funnel is not None:
        funnel.finish()


async def _loss_streak_under_lock(conn) -> tuple[bool, str | None]:
    """Locked loss-streak re-check: (blocks, observed_reason).

    enforce: identical to the legacy check (an active halt blocks). Paper observe: an
    active halt does not block; it is returned as an observation for the admission
    evidence. Must be called while holding acquire_risk_admission_lock.
    """
    if not await loss_streak_halt_active(conn):
        return False, None
    if economic_halt_blocks(economic_halt_mode()):
        return True, None
    logger.warning("loss_streak_halt active under admission lock: observed (Paper observe mode, not blocking)")
    return False, 'loss_streak_halt'


async def assess_new_trade_risk(symbol: str, trade_type: str | None = None,
                                regime: str | None = None):
    """Build a UTC, net-of-cost portfolio snapshot and evaluate one admission."""
    # Same helper the status/telemetry surfaces read, so a displayed streak can
    # never disagree with the streak this admission actually uses. With no
    # acknowledged recovery on record this equals LEARNING_CLEAN_START exactly.
    risk_start = await effective_risk_start()
    results = await Database.fetch("""
        SELECT profit_usdt, result, exit_time
        FROM trade_results
        WHERE exit_time >= $1::timestamptz
        ORDER BY exit_time, id
    """, risk_start)
    open_trades = await Database.fetch("""
        SELECT at.symbol, at.entry_price, s.trade_type,
               COALESCE(s.macro_snapshot->>'usdtd_trend', s.market_condition) AS regime
        FROM active_trades at
        LEFT JOIN signals s ON s.id=at.signal_id
        WHERE at.status='open'
    """)
    is_paused, pause_reason = await get_pause_state()

    now = datetime.now(timezone.utc)
    week_start = now.date()
    week_start = week_start.fromordinal(week_start.toordinal() - week_start.weekday())
    costs = _costs()            # legacy_tracker_v1: the flat round trip, recomputed (PR-06)
    cumulative = 0.0
    peak = config.RISK_CAPITAL_USDT
    daily = weekly = 0.0
    net_results = []
    for row in results:
        net = costs.net_usdt(float(row['profit_usdt']))
        cumulative += net
        peak = max(peak, config.RISK_CAPITAL_USDT + cumulative)
        exit_time = row['exit_time']
        if exit_time.tzinfo is None:
            exit_time = exit_time.replace(tzinfo=timezone.utc)
        if exit_time.date() == now.date():
            daily += net
        if exit_time.date() >= week_start:
            weekly += net
        net_results.append(net)

    consecutive_losses = tail_loss_streak(net_results)

    unrealized = 0.0
    for trade in open_trades:
        price = await _risk_price(trade['symbol'])
        if not price:
            unrealized = float('nan')  # Missing market state must fail closed.
            break
        entry = float(trade['entry_price'])
        unrealized += costs.net_usdt(((price / entry) - 1.0) * config.TRADE_AMOUNT_USDT)

    # WP-E08: the limits the capacity authority reads, built exactly as before
    # (min(MAX_OPEN_TRADES, RISK_CANARY_MAX_OPEN_TRADES) slots plus the configured limits).
    limits = capacity.legacy_risk_limits(config)
    snapshot = RiskSnapshot(
        realized_total_usdt=cumulative,
        daily_pnl_usdt=daily,
        weekly_pnl_usdt=weekly,
        unrealized_pnl_usdt=unrealized,
        peak_equity_usdt=peak,
        open_count=len(open_trades),
        symbol_open_count=sum(1 for t in open_trades if t['symbol'] == symbol),
        consecutive_losses=consecutive_losses,
        strategy_open_count=sum(
            1 for t in open_trades if trade_type and t['trade_type'] == trade_type),
        regime_open_count=sum(
            1 for t in open_trades if regime and t['regime'] == regime),
        manually_paused=is_paused,
        manual_pause_reason=pause_reason,
    )
    _v2_note_risk_context(risk_start, snapshot, limits)
    # WP-E08: one F7 capacity decision; the returned object is the policy's own decision.
    decision, authority = routed_risk_decision(
        snapshot, limits, economic_halt_mode(), evaluate=evaluate_with_policy,
        on_attribution_error=_capacity_attribution_error)
    _LAST_CAPACITY[:] = [decision, authority]
    return decision


_LAST_CAPACITY: list = []       # [decision, CapacityDecision | None] of the last assessment


def _last_capacity_decision(decision):
    """The capacity authority's description of ``decision`` when it was the last assessed."""
    if len(_LAST_CAPACITY) == 2 and _LAST_CAPACITY[0] is decision:
        return _LAST_CAPACITY[1]
    return None


def _capacity_attribution_error(exc) -> None:
    logger.error(f"capacity attribution did not reproduce the risk decision "
                 f"(decision unchanged): {format_error(exc)}")


RISK_PRICE_FETCH_MAX_RETRIES = 3


def _risk_price_retries() -> int:
    try:
        retries = int(config.RISK_PRICE_FETCH_RETRIES)
    except (TypeError, ValueError):
        return 0
    return min(max(retries, 0), RISK_PRICE_FETCH_MAX_RETRIES)


async def _risk_price(symbol: str):
    """Price for the admission risk snapshot only (technical-halt prevention option).

    RISK_PRICE_FETCH_RETRIES=0 (default): exactly one get_current_price call, the legacy
    behaviour. N>0: up to N more fresh fetches after a failed one, sleeping
    backoff * attempt between them. Still None when every attempt fails, so the caller's
    NaN -> invalid_risk_state fail-closed path is unchanged; nothing is cached or reused.
    """
    retries = _risk_price_retries()
    price = await get_current_price(symbol)
    for attempt in range(1, retries + 1):
        if price:
            break
        backoff = min(max(0.0, float(config.RISK_PRICE_FETCH_BACKOFF_SECONDS)), 5.0)
        await asyncio.sleep(backoff * attempt)
        price = await get_current_price(symbol)
        if price:
            logger.warning(f"risk price for {symbol} recovered on retry {attempt}/{retries}")
    return price


async def record_risk_decision(decision):
    """Expose the evaluated state to existing scanner/Telegram controls."""
    # enforce: the legacy set (economic hard stops + invalid_risk_state). Paper observe:
    # only technical halts persist a pause; daily_pnl_percent/consecutive_losses are
    # still recorded exactly as before.
    mode = economic_halt_mode()
    hard_halts = persisted_halt_reasons(mode)
    paused = decision.reason in hard_halts
    async with Database.acquire() as conn:
        async with conn.transaction():
            prior = await conn.fetchrow("""
                SELECT is_trading_paused
                FROM risk_management
                WHERE is_trading_paused=true OR pause_reason='manual_resume'
                ORDER BY date DESC,id DESC LIMIT 1
                FOR UPDATE
            """)
            was_paused = bool(prior and prior['is_trading_paused'])
            risk_id = await conn.fetchval("""
                INSERT INTO risk_management
                    (date, daily_pnl_percent, consecutive_losses,
                     is_trading_paused, pause_reason)
                VALUES (CURRENT_DATE, $1, $2, $3, $4)
                ON CONFLICT (date) DO UPDATE SET
                    daily_pnl_percent=EXCLUDED.daily_pnl_percent,
                    consecutive_losses=EXCLUDED.consecutive_losses,
                    is_trading_paused=(risk_management.is_trading_paused
                                       OR EXCLUDED.is_trading_paused),
                    pause_reason=CASE WHEN EXCLUDED.is_trading_paused
                                      THEN EXCLUDED.pause_reason
                                      ELSE risk_management.pause_reason END
                RETURNING id
            """, decision.daily_pnl_pct, decision.consecutive_losses, paused,
                 f"risk:{decision.reason}" if paused else None)
            if paused and not was_paused:
                # Reserve a unique notification key so a later resume/re-halt on
                # the same day can produce a new, still-idempotent event.
                notification_key = await conn.fetchval(
                    "SELECT nextval(pg_get_serial_sequence('outbox_events','id'))")
                await enqueue(conn, 'risk.halted', 'risk_transition',
                              notification_key, {
                                  'risk_management_id': risk_id,
                                  'reason': decision.reason,
                                  'daily_pnl_pct': decision.daily_pnl_pct,
                                  'weekly_pnl_pct': decision.weekly_pnl_pct,
                                  'drawdown_pct': decision.drawdown_pct,
                                  'consecutive_losses': decision.consecutive_losses,
                                  'loss_halt_limit': config.STOP_ON_CONSECUTIVE_LOSSES,
                              })
            if not economic_halt_blocks(mode):
                # Paper observe mode only (enforce issues no extra statement at all).
                await _enqueue_observation_alert(conn, decision, risk_id)
    _v2_risk_state(decision, paused, was_paused)


async def _enqueue_observation_alert(conn, decision, risk_id):
    """Queue ONE `risk.observed` notification when the observed economic state changes.

    Owner contract section 3: economic observations are recorded, alerted on and analysed.
    The baseline is the last persisted `risk.observed` outbox row (restart-safe), and the
    dedup key is that row's id (shared.economic_halt_policy): repeated identical decisions,
    per-admission and per-cycle calls add nothing. Codes only -- no P&L, counts or drawdown.
    Runs inside record_risk_decision's transaction.
    """
    codes = observed_codes(decision)
    if codes is None:                 # technical halt: economic state unknown, not cleared
        return None
    last = await conn.fetchrow("""
        SELECT id, payload FROM outbox_events
        WHERE event_type=$1 AND aggregate_type=$2
        ORDER BY aggregate_id DESC LIMIT 1
    """, OBSERVED_OUTBOX_EVENT, OBSERVED_OUTBOX_AGGREGATE)
    previous = ()
    if last:
        payload = last['payload']
        if isinstance(payload, str):
            payload = json.loads(payload)
        previous = tuple((payload or {}).get('codes') or ())
    transition = observation_transition(previous, codes)
    if transition is None:
        return None
    return await enqueue(conn, OBSERVED_OUTBOX_EVENT, OBSERVED_OUTBOX_AGGREGATE,
                         int(last['id']) if last else 0, {
                             'codes': list(codes), 'previous_codes': list(previous),
                             'transition': transition, 'risk_management_id': risk_id,
                             'risk_policy_version': config.RISK_POLICY_VERSION,
                         })


async def track_open_trades():
    """متابعة الصفقات المفتوحة وتسجيل نتائجها"""
    open_trades = await Database.fetch("""
        SELECT * FROM active_trades
        WHERE status = 'open'
    """)

    if not open_trades:
        return

    logger.info(f"🔍 متابعة {len(open_trades)} صفقة مفتوحة...")

    for trade in open_trades:
        trade = dict(trade)
        current_price = await get_current_price(trade['symbol'])
        if not current_price:
            continue
        if (int(trade.get('highest_target_hit') or 0) == 0
                and trade.get('stop_invalidation')):
            candle = await get_last_closed_candle(
                trade['symbol'], trade.get('timeframe') or config.TIMEFRAME)
            opened_at = trade['opened_at']
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            opened_ms = int(opened_at.timestamp() * 1000)
            if candle and candle_invalidated(
                    opened_ms=opened_ms, candle_close_ms=candle['close_time'],
                    candle_close=candle['close'],
                    invalidation_price=float(trade['stop_invalidation']),
                    highest_target=int(trade.get('highest_target_hit') or 0)):
                logger.warning(
                    f"🕯️ إبطال إشارة {trade['symbol']}: إغلاق "
                    f"{trade.get('timeframe')}={candle['close']} <= "
                    f"{trade['stop_invalidation']}")
                entry = float(trade['entry_price'])
                pnl_pct = (current_price / entry - 1) * 100
                await close_trade(
                    trade, 'WIN' if pnl_pct > 0 else 'LOSS', pnl_pct,
                    current_price, 'signal_candle_invalidation')
                continue
        await evaluate_trade_safely(trade, current_price, source='rest_backup')


async def evaluate_trade_safely(trade: dict, current_price: float,
                                source: str):
    """Serialize lifecycle changes per trade across WebSocket and REST paths."""
    trade_id = int(trade['id'])
    if usable_price(current_price) is None:
        logger.error(f"تجاهل سعر غير صالح لـ {trade.get('symbol')} عبر {source}: {current_price!r}")
        return
    lock = _trade_locks.setdefault(trade_id, asyncio.Lock())
    async with lock:
        fresh = await Database.fetchrow(
            "SELECT * FROM active_trades WHERE id=$1 AND status='open'", trade_id)
        if not fresh:
            return
        await evaluate_trade(dict(fresh), current_price, source=source)


async def evaluate_trade(trade: dict, current_price: float,
                         source: str = 'rest_backup'):
    """تقييم صفقة واحدة وتسجيل نتيجتها — يستخدم shared.triple_barrier (مصدر حقيقة واحد)

    الجزء الخامس من الباكتيستر (2026-05-16): تم نقل منطق الخروج كاملاً إلى
    shared/triple_barrier.py — trade_tracker والباكتيستر يستوردان نفس الكود.
    """
    symbol = trade['symbol']
    entry  = float(trade['entry_price'])

    # حساب مدة الصفقة
    now    = datetime.now(timezone.utc)
    opened = trade['opened_at']
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    hours_open = (now - opened).total_seconds() / 3600

    # بناء Config و State من صف DB
    # Cost arguments from legacy_tracker_v1; PAPER_BREAK_EVEN_POLICY (R4.b, default legacy)
    # changes only the roundtrip_cost that the pinned break-even formula reads.
    cfg   = create_config_from_trade(
        trade, trade_amount=config.TRADE_AMOUNT_USDT,
        **cost_policy.barrier_cost_kwargs(_costs(), WP2_FLAGS.break_even_policy),
    )
    state = create_state_from_trade(trade)
    # ضبط ساعات الفتح الحالية (تُحسب من DB)
    state.hours_open = hours_open

    prev_highest = state.highest_target
    result = step_barrier(
        cfg, state, current_price, current_price, current_price, 0.0,
        stop_observation_price=current_price)

    # تسجيل الأهداف الجديدة في DB
    if state.highest_target > prev_highest:
        partial_fills = fills_between(
            previous_target=prev_highest,
            reached_target=state.highest_target,
            entry=entry,
            targets={1: float(trade['target_1']), 2: float(trade['target_2']),
                     3: float(trade['target_3'])},
            trade_amount=config.TRADE_AMOUNT_USDT,
            min_notional=float(
                trade.get('min_order_notional_usdt')
                or config.MIN_ORDER_NOTIONAL_USDT),
        ) if trade.get('exit_policy_version') == 'partial_25_50_25_v1' else []
        async with Database.acquire() as conn:
            async with conn.transaction():
                realized_pct = sum(fill.gross_pct_contribution for fill in partial_fills)
                realized_usdt = sum(fill.gross_usdt for fill in partial_fills)
                sold_fraction = sum(fill.fraction for fill in partial_fills)
                for fill in partial_fills:
                    await conn.execute("""
                        INSERT INTO trade_target_fills
                            (active_trade_id,signal_id,symbol,target_number,
                             fill_price,quantity_fraction,notional_usdt,
                             gross_profit_percent_contribution,gross_profit_usdt)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT (active_trade_id,target_number) DO NOTHING
                    """, trade['id'], trade['signal_id'], symbol, fill.target,
                         fill.price, fill.fraction,
                         config.TRADE_AMOUNT_USDT * fill.fraction,
                         fill.gross_pct_contribution, fill.gross_usdt)
                await conn.execute("""
                    UPDATE active_trades SET
                        highest_target_hit=$1,
                        remaining_fraction=GREATEST(0,remaining_fraction-$2),
                        realized_profit_percent=realized_profit_percent+$3,
                        realized_profit_usdt=realized_profit_usdt+$4
                    WHERE id=$5
                """, state.highest_target, sold_fraction, realized_pct,
                     realized_usdt, trade['id'])
                # T3 يغلق فوراً؛ رسالة الإغلاق تكفي وتمنع إشعارين متتاليين لنفس الحدث.
                if state.highest_target < 3:
                    event_aggregate_id = int(trade['id']) * 10 + state.highest_target
                    effective_stop, _ = state.effective_stop(cfg)
                    previous_remaining = float(
                        trade.get('remaining_fraction')
                        if trade.get('remaining_fraction') is not None else 1.0)
                    await enqueue(conn, 'trade.target_hit', 'active_trade_target',
                                  event_aggregate_id, {
                                      'active_trade_id': trade['id'],
                                      'target': state.highest_target,
                                      'current_price': current_price,
                                      'effective_stop': effective_stop,
                                      'sold_fraction': sold_fraction,
                                      'remaining_fraction': max(
                                          0, previous_remaining - sold_fraction),
                                  })
        try:
            _v2_stop, _ = state.effective_stop(cfg) if evidence_v2.enabled() else (None, None)
        except Exception:
            _v2_stop = None
        _v2_target_hits(trade, partial_fills, state.highest_target, current_price, source, _v2_stop)
        if WP2_FLAGS.position_state_shadow:
            _shadow_target_hits(trade, cfg, state, prev_highest, partial_fills)
        logger.info(
            f"🎯 {symbol} وصل T{state.highest_target} عبر {source}; "
            f"السعر={current_price:.6f}, شرائح={len(partial_fills)}")

    # تحديث peak_price في DB
    stored_peak = float(trade.get('peak_price') or entry)
    if state.peak > stored_peak:
        await Database.execute(
            "UPDATE active_trades SET peak_price = $1 WHERE id = $2",
            state.peak, trade['id']
        )

    if result is not None:
        # Reload partial accounting committed above (especially when the same
        # tick crosses T3) before producing the terminal aggregate result.
        refreshed = await Database.fetchrow(
            "SELECT * FROM active_trades WHERE id=$1", trade['id'])
        trade = dict(refreshed or trade)
        await close_trade_barrier(
            trade, result.result, result.profit_pct, result.profit_usdt,
            result.exit_price, result.exit_reason, result.target_reached, result.stop_hit,
        )
        return


async def close_trade_barrier(
    trade: dict, result: str, profit_pct: float, profit_usdt: float,
    exit_price: float, reason: str, target_reached: int, stop_hit: bool
):
    """إغلاق الصفقة وتسجيل النتيجة — مع stop_hit الصحيح من TripleBarrier"""
    trade_id = int(trade['id'])
    if trade_id in _closing:
        return
    _closing.add(trade_id)
    symbol = trade['symbol']
    entry  = float(trade['entry_price'])

    hours_open = ((datetime.now(timezone.utc) - trade['opened_at'].replace(tzinfo=timezone.utc)
                   if trade['opened_at'].tzinfo is None
                   else datetime.now(timezone.utc) - trade['opened_at'])
                  .total_seconds() / 3600)

    try:
        remaining_fraction = float(trade.get('remaining_fraction') or 0)
        realized_pct = float(trade.get('realized_profit_percent') or 0)
        realized_usdt = float(trade.get('realized_profit_usdt') or 0)
        profit_pct, profit_usdt = aggregate_close(
            entry=entry, final_exit=exit_price,
            trade_amount=config.TRADE_AMOUNT_USDT,
            realized_pct=realized_pct, realized_usdt=realized_usdt,
            remaining_fraction=remaining_fraction)
        # Weighted average exit keeps the legacy result row interpretable.
        sold_fraction = max(0.0, 1.0 - remaining_fraction)
        realized_exit_value = 0.0
        fills = []
        if sold_fraction > 0:
            fills = await Database.fetch(
                "SELECT fill_price,quantity_fraction FROM trade_target_fills "
                "WHERE active_trade_id=$1", trade_id)
            realized_exit_value = sum(
                float(f['fill_price']) * float(f['quantity_fraction']) for f in fills)
        target_legs = tuple((float(f['quantity_fraction']), float(f['fill_price'])) for f in fills)
        weighted_exit = realized_exit_value + exit_price * remaining_fraction
        if sold_fraction + remaining_fraction <= 0:
            weighted_exit = exit_price

        async with Database.acquire() as conn:
            async with conn.transaction():
                # `result` keeps its legacy gross meaning; the economic (net) label is stored
                # beside it with its cost and policy (A38, shared.fees.economic_close).
                # Booked through legacy_tracker_v1 (shared.cost_models): under the default
                # PAPER_COST_LABEL_POLICY this is the bound model's economic_close, i.e.
                # shared.fees.economic_close on the configured values (R4.a/R4.e: flagged).
                economic_close = cost_policy.close_booking(
                    _costs(), WP2_FLAGS.cost_label_policy, entry_price=entry,
                    target_fills=target_legs, final_exit_price=exit_price,
                    remaining_fraction=remaining_fraction)
                econ = economic_close(profit_usdt)
                inserted = await conn.fetchval("""
                INSERT INTO trade_results
                (signal_id, symbol, entry_price, exit_price, profit_percent,
                 profit_usdt, result, exit_time, notes, duration_hours,
                 target_reached, stop_hit,
                 cost_usdt, net_profit_usdt, economic_result, label_policy)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9, $10, $11,
                        $12, $13, $14, $15)
                ON CONFLICT (signal_id) WHERE signal_id IS NOT NULL DO NOTHING
                RETURNING id
                """,
                    trade['signal_id'], symbol, entry, weighted_exit,
                    round(profit_pct, 4), round(profit_usdt, 4),
                    'WIN' if profit_usdt > 0 else 'LOSS', reason,
                    round(hours_open, 2), target_reached, stop_hit,
                    econ['cost_usdt'], econ['net_profit_usdt'], econ['economic_result'],
                    econ['label_policy'])
                await conn.execute(
                    "UPDATE active_trades SET status='closed',remaining_fraction=0 WHERE id=$1",
                    trade_id)
                if inserted:
                    final_result = 'WIN' if profit_usdt > 0 else 'LOSS'
                    column = 'wins' if final_result == 'WIN' else 'losses'
                    await conn.execute(f"""
                    INSERT INTO risk_management (date, {column})
                    VALUES (CURRENT_DATE, 1)
                    ON CONFLICT (date) DO UPDATE
                    SET {column}=risk_management.{column}+1
                    """)
                    await enqueue(conn, 'trade.closed', 'trade_result', inserted, {
                        'trade_result_id': inserted,
                        'active_trade_id': trade_id,
                    })

        _v2_trade_closed(trade, inserted, reason, exit_price, weighted_exit, profit_pct,
                         profit_usdt, hours_open, target_reached, stop_hit)
        if WP2_FLAGS.position_state_shadow:
            _shadow_close(trade, reason, exit_price)
        if WP2_FLAGS.ledger_shadow and inserted:
            _shadow_reconcile(trade, inserted, target_legs, exit_price, remaining_fraction,
                              profit_usdt, econ)
        result = 'WIN' if profit_usdt > 0 else 'LOSS'
        if COUNTER_LABELS and inserted:
            _log_counter_basis(profit_usdt, econ)
    finally:
        _closing.discard(trade_id)

    icon = "✅" if result == 'WIN' else "❌"
    logger.info(
        f"{icon} {symbol} | {result} | "
        f"ربح: {profit_pct:.2f}% ({profit_usdt:.2f} USDT) | {reason}"
    )
    # لا تنتظر محاولة دخول لاحقة لتحديث لوحة المخاطر وسلسلة الخسائر.
    try:
        decision = await assess_new_trade_risk('__POST_CLOSE_RISK_REFRESH__')
        await record_risk_decision(decision)
    except Exception as exc:
        logger.error(f"تعذر تحديث حالة المخاطر بعد الإغلاق: {format_error(exc)}")


def _log_counter_basis(profit_usdt, econ) -> None:
    """WP-E06 (PAPER_COUNTER_LABELS=on): log only; never changes the close."""
    try:
        logger.info(cost_policy.close_counter_log(profit_usdt, econ))
    except Exception as exc:
        logger.error(f"counter-basis log failed: {format_error(exc)}")


async def close_trade(trade: dict, result: str, profit_pct: float,
                      exit_price: float, reason: str):
    """إغلاق الصفقة — wrapper لـ enforce_max_open_trades و close_blacklisted_trades"""
    symbol      = trade['symbol']
    entry       = float(trade['entry_price'])
    profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
    stop_hit    = result == 'LOSS' and exit_price <= float(trade['stop_loss'])
    target_hit  = int(trade.get('highest_target_hit') or 0)

    await close_trade_barrier(
        trade, result, profit_pct, profit_usdt,
        exit_price, reason, target_hit, stop_hit
    )


def usable_price(value) -> float | None:
    """A price observation the tracker may act on: finite and > 0. Anything else (NaN, +/-inf,
    zero, negative, unparsable) is treated exactly like a failed fetch, so no decision, fill or
    economic label is ever computed from it (A49)."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


async def get_current_price(symbol: str) -> float:
    """جلب السعر الحالي من Binance"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    raise RuntimeError(f"Binance HTTP {resp.status}: {body}")
                data = await resp.json()
                if 'price' not in data:
                    raise ValueError(f"Binance response missing price: {str(data)[:200]}")
                price = usable_price(data['price'])
                if price is None:
                    raise ValueError(f"Binance price is not a usable price: {str(data['price'])[:40]}")
                return price
    except Exception as e:
        logger.error(f"خطأ في جلب سعر {symbol}: {format_error(e)}")
        return None


async def get_min_notional(symbol: str) -> float:
    """Read Binance's current order-notional floor, cached for this process."""
    if symbol in _min_notional_cache:
        return _min_notional_cache[symbol]
    fallback = config.MIN_ORDER_NOTIONAL_USDT
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.binance.com/api/v3/exchangeInfo',
                params={'symbol': symbol}, timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'Binance exchangeInfo HTTP {resp.status}')
                data = await resp.json()
                filters = data['symbols'][0]['filters']
                values = [float(f['minNotional']) for f in filters
                          if f.get('filterType') in ('NOTIONAL', 'MIN_NOTIONAL')
                          and f.get('minNotional')]
                value = max(values) if values else fallback
                _min_notional_cache[symbol] = value
                return value
    except Exception as exc:
        logger.warning(
            f"تعذر جلب MIN_NOTIONAL لـ {symbol}; استخدام {fallback}: {format_error(exc)}")
        return fallback


async def get_last_closed_candle(symbol: str, timeframe: str) -> dict | None:
    """Return Binance's latest fully closed candle for signal invalidation."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                'https://api.binance.com/api/v3/klines',
                params={'symbol': symbol, 'interval': timeframe, 'limit': 2},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'Binance klines HTTP {resp.status}')
                rows = await resp.json()
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                closed = [row for row in rows if int(row[6]) < now_ms]
                if not closed:
                    return None
                row = closed[-1]
                return {'open_time': int(row[0]), 'close_time': int(row[6]),
                        'close': float(row[4])}
    except Exception as exc:
        logger.warning(
            f"تعذر فحص شمعة الإبطال لـ {symbol}/{timeframe}: {format_error(exc)}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
