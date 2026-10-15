"""
منطق اختيار أفضل إشارة مع تأكيد متعدد الـ Timeframes
"""
import json
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.macro_context import MacroContext
from shared.outbox import enqueue
from shared.signal_readiness import (
    READY_DECISION_SOURCE, SIGNAL_READY_EVENT, assert_signal_complete, ready_payload)
from shared.learning_governance import exploration_selected
from shared import evidence_v2
from shared.dependency_safety import cycle_gate, guarded_read
from shared.signal_identity import (IDENTITY_VERSION, IdentityError, bracket_hash,
                                    identity_from_candidate, integrity_check, integrity_mode)

logger = setup_logger('signal_logic')

# A44 (SIGNAL_INTEGRITY_MODE=enforce): reads whose failure must not turn into eligibility.
OPEN_SYMBOLS_SQL = "SELECT DISTINCT symbol FROM active_trades WHERE status='open'"
COOLDOWN_SQL = """SELECT DISTINCT symbol FROM signals
                   WHERE signal_time > NOW() - INTERVAL '2 hours'"""
LEARNED_GATES_SQL = ("SELECT trade_type, timeframe FROM learned_gates "
                     "WHERE macro_state=$1 AND n>=$2 AND weight<=0")
EMITTED_SETUPS_SQL = "SELECT setup_key FROM signals WHERE setup_key = ANY($1::text[])"

# ── Evidence flight-recorder (PR #3c) — shadow, default-off, fully isolated ──────────
# ALL imports are lazy and guarded: with the flag off, signal_logic loads and behaves
# byte-identically. With the flag on but the recorder unavailable, failures are buried —
# the signal path is NEVER affected.
_evidence_recorder = None
_evidence_unavailable = False


def get_evidence_recorder():
    global _evidence_recorder, _evidence_unavailable
    if not config.ENABLE_EVIDENCE_RECORDER or _evidence_unavailable:
        return None
    if _evidence_recorder is None:
        try:
            import os as _os
            from research.null_a.recorder import EvidenceRecorder, CaptureFilter
            from research.null_a.sinks import JsonlSink
            _tel_path = _os.path.join(_os.path.abspath(config.EVIDENCE_DIR), "_telemetry.json")
            cap_filter = CaptureFilter(
                symbols=config.EVIDENCE_FILTER_SYMBOLS or None,
                timeframes=config.EVIDENCE_FILTER_TIMEFRAMES or None,
                sources=config.EVIDENCE_FILTER_SOURCES or None,
                max_per_hour=config.EVIDENCE_FILTER_MAX_SIGNALS_PER_HOUR)
            _evidence_recorder = EvidenceRecorder(
                sink=JsonlSink(config.EVIDENCE_DIR), enabled=True, capture_filter=cap_filter,
                telemetry_path=_tel_path, telemetry_history_size=config.EVIDENCE_TELEMETRY_HISTORY,
                phase_id=config.EVIDENCE_PHASE_ID,
                max_queue=config.EVIDENCE_MAX_QUEUE, batch_size=config.EVIDENCE_BATCH_SIZE,
                flush_interval_s=config.EVIDENCE_FLUSH_INTERVAL_S,
                flush_retry_count=config.EVIDENCE_FLUSH_RETRY_COUNT,
                flush_backoff_ms=config.EVIDENCE_FLUSH_BACKOFF_MS,
                shutdown_flush_timeout_ms=config.EVIDENCE_SHUTDOWN_FLUSH_TIMEOUT_MS)
        except Exception:
            _evidence_unavailable = True
            try:
                logger.warning("evidence recorder unavailable; continuing without it", exc_info=True)
            except Exception:
                pass
            return None
    return _evidence_recorder


def _record_evidence(signal, source, decision="signal_generated"):
    """Fail-safe evidence hook. Reads the signal, never mutates it, never raises —
    even if logging itself fails (the except-handler's own log is guarded)."""
    if not config.ENABLE_EVIDENCE_RECORDER or not signal:
        return
    try:
        from research.null_a.recorder import capture_signal
        capture_signal(get_evidence_recorder(), signal, source=source,
                       model_version=config.APP_VERSION, decision=decision)
    except Exception:
        try:
            logger.warning("evidence hook failed", exc_info=True)
        except Exception:
            pass


# ── Evidence recorder v2 (P1) — point-in-time decision events. Every helper below reads its
# inputs, never mutates them, never raises and is a no-op unless EVIDENCE_V2_ENABLED. ─────────
_GEOMETRY_KEYS = ('entry_price', 'target_1', 'target_2', 'target_3', 'stop_loss',
                  'stop_invalidation', 'stop_risk_pct', 'stop_policy', 'stop_valid',
                  'stop_reject_reason')


def _v2_macro_context(macro, macro_state=None) -> dict | None:
    """Macro context and freshness as seen by this decision (pure reads)."""
    if not evidence_v2.enabled():
        return None
    try:
        snap = dict(macro.snapshot() or {})
        valid_ts = getattr(macro, '_last_valid_ts', None)
        age = snap.get('macro_age_seconds')
        now = evidence_v2.now_ms()
        return {
            'decision_at_ms': now,
            'macro_state': macro_state if macro_state is not None else macro.macro_state_key(),
            'macro_data_valid': snap.get('macro_data_valid'),
            'macro_age_seconds': age,
            'macro_valid_at_ms': (int(valid_ts * 1000) if valid_ts
                                  else (now - int(age * 1000) if age is not None else None)),
            'macro_snapshot': snap,
            'macro_trend_state': dict(macro.state() or {}),
        }
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)
        return None


def _v2_candidate(data, decision: str, reason: str | None, ctx: dict | None, **extra) -> None:
    """candidate.evaluated — emitted only when this candidate's decision state changes."""
    if not evidence_v2.enabled():
        return
    try:
        if isinstance(data, str):
            data = json.loads(data)
        pit = data.get('pit') or {}
        ob = data.get('order_book') or {}
        cid = pit.get('candidate_id')
        subject = {'candidate_id': cid, 'candle_id': pit.get('candle_id'),
                   'symbol': data.get('symbol'), 'timeframe': data.get('timeframe')}
        ctx = ctx or {}
        payload = {
            'geometry': {k: data.get(k) for k in _GEOMETRY_KEYS},
            'trade_type': data.get('trade_type'),
            'entry_reason': data.get('entry_reason'),
            'total_score': data.get('total_score'),
            'order_book': {k: ob.get(k) for k in ('valid', 'spread_pct', 'score')},
            'macro': {k: ctx.get(k) for k in ('macro_state', 'macro_data_valid',
                                              'macro_age_seconds', 'macro_valid_at_ms')},
            'pit': pit,
            'identity_status': 'ok' if cid else 'missing_pit',
            **extra,
        }
        evidence_v2.emit('signal_engine', 'candidate.evaluated', subject, payload,
                         state={'decision': decision, 'reason': reason},
                         dedup_key='eval:' + (cid or f"{subject['symbol']}|{subject['timeframe']}|nopit"),
                         event_time_ms=ctx.get('decision_at_ms'))
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)


def _v2_macro_block(results, ctx: dict | None) -> None:
    """All candidates of a macro-blocked cycle (rows read inside the guard)."""
    if ctx is None:
        return
    try:
        ctx['macro_blocked'] = True
        for r in results:
            _v2_candidate(r['analysis_data'], 'rejected', 'macro_block', ctx)
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)


def _v2_selection(eligible: list, best, key, ctx: dict | None) -> None:
    """Rank every eligible candidate by the SAME fixed key the selection uses (read-only)."""
    if not evidence_v2.enabled() or not eligible:
        return
    try:
        ranked = sorted(eligible, key=key)
        for rank, cand in enumerate(ranked, start=1):
            selected = cand is best
            _v2_candidate(cand, 'selected' if selected else 'rejected',
                          None if selected else 'not_selected_capacity', ctx,
                          selection={'rank': rank, 'eligible_count': len(ranked),
                                     'rank_key': list(key(cand)),
                                     'selection_volume_usdt': cand.get('_selection_volume_usdt')})
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)


def _v2_signal_refused(signal, exc: BaseException) -> None:
    """signal.refused (INCOMPLETE_SIGNAL) — save_signal rejected the signal before any write."""
    if not evidence_v2.enabled():
        return
    try:
        pit = (signal.get('pit') if isinstance(signal, dict) else None) or {}
        subject = {'candidate_id': pit.get('candidate_id'), 'candle_id': pit.get('candle_id'),
                   'symbol': signal.get('symbol') if isinstance(signal, dict) else None,
                   'timeframe': signal.get('timeframe') if isinstance(signal, dict) else None}
        evidence_v2.emit('signal_engine', 'signal.refused', subject,
                         {'outcome_code': 'INCOMPLETE_SIGNAL',
                          'error': f"{type(exc).__name__}: {exc}"[:300],
                          'geometry': {k: (signal.get(k) if isinstance(signal, dict) else None)
                                       for k in _GEOMETRY_KEYS + ('total_score',)},
                          'pit': pit},
                         state={'outcome': 'refused', 'reason': 'incomplete_signal'},
                         dedup_key='refused:' + (pit.get('candidate_id') or
                                                 f"{subject['symbol']}|{subject['timeframe']}"))
    except Exception as hook_exc:
        evidence_v2.hook_error('signal_engine', hook_exc)


def signal_identity(signal: dict) -> dict | None:
    """P1-A identity persisted with the signal (features_snapshot['identity']); None on error."""
    try:
        pit = signal.get('pit') or {}
        own = evidence_v2.process_identity(config)
        return {
            'candle_open_time_ms': pit.get('candle_open_time_ms'),
            'candle_close_time_ms': pit.get('candle_close_time_ms'),
            'candle_id': pit.get('candle_id'),
            'candidate_id': pit.get('candidate_id'),
            'strategy_version': config.APP_VERSION,
            'code_sha': own['code_sha'],
            'config_hash': own['config_hash'],
            'analyzer_code_sha': pit.get('code_sha'),
            'analyzer_config_hash': pit.get('config_hash'),
            'weights_hash': pit.get('weights_hash'),
            'identity_version': 1,
        }
    except Exception:
        return None


def _v2_signal_ready(signal_id, signal: dict, context=None) -> None:
    """P1-R evidence event `signal.ready`: the signal row (decision_source=policy_ready) and the
    runtime outbox event `signal.ready` were committed in one transaction. Lineage link
    candidate_id -> signal_id (entity event, idempotent by signal_id). Emitted after the commit."""
    if not evidence_v2.enabled():
        return
    try:
        pit = signal.get('pit') or {}
        subject = {'signal_id': signal_id, 'candidate_id': pit.get('candidate_id'),
                   'candle_id': pit.get('candle_id')}
        payload = {
            'outcome_code': 'POLICY_READY',
            'decision_source': READY_DECISION_SOURCE,
            'runtime_outbox_event': SIGNAL_READY_EVENT,
            'symbol': signal.get('symbol'), 'timeframe': signal.get('timeframe'),
            'trade_type': signal.get('trade_type'), 'selection_policy': signal.get('selection_policy'),
            'geometry': {k: signal.get(k) for k in ('entry_price', 'target_1', 'target_2', 'target_3',
                                                    'stop_loss', 'stop_invalidation', 'stop_risk_pct',
                                                    'stop_policy')},
            'macro_state': signal.get('macro_state'),
            'identity': signal_identity(signal),
            'pit': pit,
        }
        evidence_v2.emit('signal_engine', 'signal.ready', subject, payload,
                         event_time_ms=(context or {}).get('decision_at_ms'))
    except Exception as exc:
        evidence_v2.hook_error('signal_engine', exc)


_INSERT_ONCE_SQL = """
    INSERT INTO signals (
        symbol, timeframe, market_condition,
        entry_price, target_1, target_2, target_3,
        stop_loss, score, score_details, is_paper_trade,
        volume_usdt, features_snapshot, trade_type, macro_snapshot,
        decision_source, strategy_version, setup_key
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
    ON CONFLICT (setup_key) WHERE setup_key IS NOT NULL DO NOTHING
    RETURNING id
"""
_EXISTING_SETUP_SQL = """
    SELECT id, features_snapshot->'setup_identity'->>'bracket_hash' AS bracket_hash
    FROM signals WHERE setup_key = $1
"""


class SignalEngine:

    @staticmethod
    def _fixed_candidate_key(signal: dict) -> tuple:
        """Fixed execution-quality ordering; contains no learned performance inputs."""
        order_book = signal.get('order_book') or {}
        spread = order_book.get('spread_pct')
        spread = float(spread) if spread is not None else float('inf')
        liquidity = float(signal.get('_selection_volume_usdt') or 0.0)
        return (spread, -liquidity, signal.get('symbol', ''), signal.get('timeframe', ''))

    async def _get_live_thresholds(self) -> tuple:
        """يقرأ إعدادات MIN_SCORE و MIN_TF من optimizer_settings (تحديث حي)،
        ويعود إلى config.* إذا لم تكن موجودة."""
        try:
            rows = await Database.fetch(
                "SELECT key, value FROM optimizer_settings WHERE key IN ('min_score_to_signal', 'min_timeframe_confirmations')"
            )
            settings = {row['key']: row['value'] for row in rows}
            min_score = float(settings.get('min_score_to_signal', config.MIN_SCORE_TO_SIGNAL))
            min_tf = int(settings.get('min_timeframe_confirmations', config.MIN_TIMEFRAME_CONFIRMATIONS))
            return min_score, min_tf
        except Exception:
            return config.MIN_SCORE_TO_SIGNAL, config.MIN_TIMEFRAME_CONFIRMATIONS

    async def _is_btc_crashing(self) -> bool:
        """
        تحقق من حالة BTC على إطار 4h:
        - يقرأ btc_trend من آخر scan_candidate (Scanner يحدّثه كل 5min)
        - strong_bearish فقط (هبوط > 3% في 40 ساعة) → السوق في انهيار → إيقاف الإشارات
        - bearish (-1% إلى -3%) → تصحيح عادي → لا نوقف الإشارات (mean-reverting يعمل هنا)
        مرجع: البيانات تُظهر أن bearish ≠ انهيار؛ صمّت البوت 3+ أيام دون مبرر (2026-05-13→16).
        """
        try:
            row = await Database.fetchrow(
                """SELECT data FROM scan_candidates
                   ORDER BY scan_time DESC LIMIT 1"""
            )
            if not row:
                return False
            data = row['data']
            if isinstance(data, str):
                data = json.loads(data)
            trend = (data.get('btc_trend') or '').lower()
            return trend in ('strong_bearish',)
        except Exception as e:
            logger.warning(f"BTC crash check failed: {e}")
            return False

    async def _is_global_loss_cooldown(self) -> bool:
        """
        Cooldown بعد ضربة SL حقيقية (المدّة = config.GLOBAL_LOSS_COOLDOWN_HOURS ساعة):
        - stop_hit=true  → السوق أسقط الـ SL → خطر فعلي → freeze
        - stop_hit=false → expire 48h أو forced close → ليست إشارة انعكاس سوقي حاد
        الهدف: منع الدخول في سلسلة SL خلال نفس الشروط السوقية السيئة،
               دون تجميد البوت بعد خسارة expire رمزية كـ -$0.91 (حادثة SPKUSDT 2026-05-14).
        تعطيل: GLOBAL_LOSS_COOLDOWN_HOURS=0 (عُطّل 2026-06-20 في paper لزيادة الإشارات
               وإزالة تحيّز انتقاء البيانات — الكول داون كان يحجب ~25% من الوقت).
        ملاحظة: make_interval لتمرير المدّة بأمان وتجنب مشكلة timezone مع PostgreSQL.
        """
        hours = config.GLOBAL_LOSS_COOLDOWN_HOURS
        if hours <= 0:
            return False
        try:
            row = await Database.fetchrow(
                """SELECT id FROM trade_results
                   WHERE result = 'LOSS'
                   AND stop_hit = true
                   AND exit_time > NOW() - make_interval(hours => $1)
                   LIMIT 1""",
                hours
            )
            if row:
                logger.info(f"⏸️ Cooldown نشط: SL hit في آخر {hours} ساعات — إيقاف الإشارات مؤقتاً")
                return True
            return False
        except Exception as e:
            logger.warning(f"فشل فحص global loss cooldown: {e}")
            return False

    async def _cooldown_symbols(self) -> set:
        """Symbols that emitted a signal in the last 2 h. Raises on a DB error (A44)."""
        return {r['symbol'] for r in await Database.fetch(COOLDOWN_SQL)}

    async def _integrity_state(self, results, macro_state):
        """A44 enforce mode: the selector's safety-critical state, read with bounded retries.

        Returns (throttled, open_symbols, cooldown, emitted_setup_keys), or None when any of
        them could not be verified — then nothing is emitted this cycle (no new exposure on
        unverified state). Never raises for a dependency failure."""
        keys = set()
        for row in results:
            data = row['analysis_data']
            if isinstance(data, str):
                data = json.loads(data)
            try:
                keys.add(identity_from_candidate(data, strategy_version=config.APP_VERSION).key)
            except IdentityError:
                pass                                   # rejected per candidate later

        async def gates():
            if not config.LEARNING_GATES_ENABLED:
                return set()
            return {(r['trade_type'], r['timeframe']) for r in await Database.fetch(
                LEARNED_GATES_SQL, macro_state, config.MIN_CELL_N)}

        async def open_symbols():
            return {r['symbol'] for r in await Database.fetch(OPEN_SYMBOLS_SQL)}

        async def emitted():
            if not keys:
                return set()
            return {r['setup_key'] for r in await Database.fetch(EMITTED_SETUPS_SQL, sorted(keys))}

        outcomes = {'learned_gates': await guarded_read('learned_gates', gates),
                    'open_positions': await guarded_read('open_positions', open_symbols),
                    'symbol_cooldown': await guarded_read('symbol_cooldown', self._cooldown_symbols),
                    'emitted_setups': await guarded_read('emitted_setups', emitted)}
        gate = cycle_gate(outcomes)
        self.last_safety_gate = gate
        if not gate.allow_new_exposure:
            self.last_decisions.update({r['symbol']: gate.reason for r in results})
            logger.warning(f"⛔ no signal this cycle: {gate.reason} {list(gate.events)}")
            return None
        return tuple(outcomes[k].value for k in
                     ('learned_gates', 'open_positions', 'symbol_cooldown', 'emitted_setups'))

    async def _get_symbol_cooldown_set(self) -> set:
        """
        Cooldown 2 ساعات لكل عملة:
        أي عملة صدرت لها إشارة في آخر 2 ساعة → لا إشارة جديدة لها.
        الهدف: منع تكرار نفس العملة المتعثرة مراراً (كحادثة PROMUSDT -$16).
        ملاحظة: نستخدم NOW() - INTERVAL في SQL مباشرة لتجنب مشكلة timezone مع PostgreSQL.
        """
        try:
            symbols = await self._cooldown_symbols()
            if symbols:
                logger.info(f"⏳ عملات في cooldown (2h): {len(symbols)} — {', '.join(sorted(symbols))}")
            return symbols
        except Exception as e:
            logger.warning(f"فشل جلب symbol cooldown: {e}")
            return set()

    async def _is_inter_signal_cooldown(self) -> bool:
        """
        Cooldown 30 دقيقة بين أي إشارتين (بغض النظر عن العملة):
        الهدف: منع burst فتح 10 صفقات في 33 دقيقة (حادثة 2026-05-12 21:27-22:00 UTC).
        تركيز المخاطر في نافذة زمنية ضيقة يعني نفس ظروف السوق = correlation عالي.
        """
        try:
            row = await Database.fetchrow(
                """SELECT signal_time FROM signals
                   WHERE telegram_sent = true
                   AND signal_time > NOW() - INTERVAL '30 minutes'
                   ORDER BY signal_time DESC
                   LIMIT 1"""
            )
            if row:
                logger.info("⏳ Inter-signal cooldown نشط: إشارة صدرت منذ أقل من 30 دقيقة")
                return True
            return False
        except Exception as e:
            logger.warning(f"فشل فحص inter-signal cooldown: {e}")
            return False

    async def find_best_signal(self, results: List) -> Optional[Dict]:
        """
        يجمع نتائج كل الـ Timeframes لكل عملة،
        ويختار الإشارة التي تجاوزت الحد الأدنى للتأكيد.
        """

        # إعدادات حيّة (يحدّثها Optimizer في DB)
        min_score, min_tf = await self._get_live_thresholds()

        # ─── BTC Crash Pause ───────────────────────────────────────
        # لو BTC 4h في bearish → إيقاف توليد الإشارات
        # (mean-reverting لا يعمل في انهيار السوق ككل)
        if await self._is_btc_crashing():
            logger.warning("⏸️ BTC 4h strong_bearish — إيقاف الإشارات حماية رأس المال")
            return None

        # ─── Global Loss Cooldown (6h) ─────────────────────────────
        # بعد أي خسارة → توقف 6 ساعات قبل إشارة جديدة
        if await self._is_global_loss_cooldown():
            return None

        # ─── Inter-Signal Cooldown (30min) ─────────────────────────
        # إشارة صدرت في آخر 30 دقيقة (لأي عملة) → توقف
        # يمنع burst: فتح 10 صفقات في 33 دقيقة = تركيز مخاطر عالي
        if await self._is_inter_signal_cooldown():
            return None

        # ─── Per-Symbol Cooldown (2h) ──────────────────────────────
        # عملات صدرت لها إشارة في آخر 2 ساعة → محظورة
        cooldown_symbols = await self._get_symbol_cooldown_set()

        # التحقق من حدود الإشارات اليومية
        signals_today = await Database.fetchval(
            "SELECT signals_sent FROM risk_management WHERE date = CURRENT_DATE"
        ) or 0

        if config.MAX_SIGNALS_PER_DAY > 0 and signals_today >= config.MAX_SIGNALS_PER_DAY:
            logger.info(f"⏸️ وصلنا للحد الأقصى اليومي: {signals_today} إشارات")
            return None

        # جلب العملات المحظورة (صفقة مفتوحة أو في cooldown)
        # ملاحظة: approval_requests المرفوضة محذوفة من هنا — كل العملات المرفوضة
        # مُضافة الآن لـ symbol_blacklist ويحجبها Scanner من المصدر، فلا داعي لإعادة القراءة.
        open_symbols = set(r['symbol'] for r in await Database.fetch(
            "SELECT DISTINCT symbol FROM active_trades WHERE status = 'open'"
        ))
        blocked_symbols = open_symbols | cooldown_symbols

        if blocked_symbols:
            logger.info(
                f"🚫 عملات محظورة: {len(blocked_symbols)} "
                f"(مفتوحة: {len(open_symbols)}, cooldown: {len(cooldown_symbols)})"
            )

        # تجميع النتائج حسب العملة
        by_symbol: Dict[str, List[Dict]] = {}
        for row in results:
            data = row['analysis_data']
            if isinstance(data, str):
                data = json.loads(data)
            symbol = data.get('symbol') or row['symbol']
            by_symbol.setdefault(symbol, []).append(data)

        best_signal = None
        best_score = 0

        for symbol, tf_results in by_symbol.items():

            # تخطي العملات المحظورة (طبقة حماية ثانية)
            if symbol in blocked_symbols:
                logger.debug(f"⏭️ تخطي {symbol} - صفقة مفتوحة أو مرفوضة")
                continue

            # فلتر حالة السوق: رفض volatile (تاريخياً 34.4% win rate، -1.79% avg)
            volatile_count = sum(1 for d in tf_results if d.get('market_condition') == 'volatile')
            if volatile_count >= len(tf_results) / 2:
                logger.debug(f"⏭️ تخطي {symbol} - أغلب الإطارات volatile")
                continue

            # فلتر bullish regime — البيانات (2026-04-22+): 18 صفقة، 100% فشل، -$4
            # mean-reverting لا يعمل في صعود قوي (لا dips للشراء)
            bullish_count = sum(1 for d in tf_results if d.get('market_condition') == 'bullish')
            if bullish_count >= len(tf_results) / 2:
                logger.debug(f"⏭️ تخطي {symbol} - أغلب الإطارات bullish (mean-reverting يفشل)")
                continue

            # فلتر الاتجاه: رفض إذا لا يوجد إطار واحد على الأقل فوق ema200
            # استثناء: إذا وُجد إطار 1d في bearish/sideways (بيانات: WR=58%+$31 n=36)
            # الأساس: mean-reversion من oversold على 1d يعمل حتى في downtrend ممتد
            has_trend_ok = any(d.get('trend_ok') for d in tf_results)
            has_1d_bearish_edge = any(
                d.get('timeframe') == '1d'
                and d.get('market_condition') in ('bearish', 'sideways')
                and float(d.get('total_score', 0)) >= 2.5
                for d in tf_results
            )
            if not has_trend_ok and not has_1d_bearish_edge:
                logger.debug(f"⏭️ تخطي {symbol} - تحت ema200 في كل الإطارات (downtrend)")
                continue

            # احسب عدد الـ Timeframes المتفقة (تجاوزت الحد الأدنى)
            qualifying = []
            for data in tf_results:
                # تخطي إطار volatile
                if data.get('market_condition') == 'volatile':
                    continue
                # تخطي downtrend إلا إذا كان 1d في bearish/sideways (حافة مُثبَتة: WR=58%)
                is_1d_edge = (
                    data.get('timeframe') == '1d'
                    and data.get('market_condition') in ('bearish', 'sideways')
                )
                if not data.get('trend_ok', True) and not is_1d_edge:
                    continue

                score = float(data.get('total_score', 0))
                ob_score = data.get('order_book', {}).get('score', 0) if data.get('order_book') else 0
                btc_bonus = self._get_btc_bonus(data.get('market_condition', 'sideways'))
                # timeframe_bonus: 1d يُفضَّل على 1h (بيانات 2433 صفقة: 1d WR=39% vs 1h WR=37%،
                # وعند score=3: 1d/bearish WR=58%+$30، 1d/sideways WR=50%+$16 — حافة واضحة)
                tf_bonus = self._get_tf_bonus(data.get('timeframe', ''))
                final = score + ob_score + btc_bonus + tf_bonus

                if final >= min_score:
                    qualifying.append((final, data))

            confirmations = len(qualifying)

            # في سوق bearish عام، 1d وحده يكفي إذا كانت نقاطه >= 3.0 (حافة مُثبَتة n=66)
            # المنطق: الإطارات الأقصر (1h/4h) تحت EMA200 جميعها في هذه البيئة،
            #         لكن 1d+bearish/sideways+score>=3 يُثبت WR=57-58% تاريخياً
            top_1d_entry = next(
                (d for _, d in qualifying if d.get('timeframe') == '1d'
                 and d.get('market_condition') in ('bearish', 'sideways')
                 and float(d.get('total_score', 0)) >= 3.0),
                None
            )
            effective_min_tf = 1 if top_1d_entry else min_tf

            if confirmations < effective_min_tf:
                logger.debug(
                    f"رفض {symbol} - تأكيدات: {confirmations}/{len(tf_results)} "
                    f"(مطلوب {effective_min_tf})"
                )
                continue

            # اختر نتيجة الـ Timeframe الأعلى نقاطاً كمرجع للإشارة
            qualifying.sort(key=lambda x: x[0], reverse=True)
            top_score, top_data = qualifying[0]

            # فلتر: رفض إذا كان الإطار الرئيسي للإشارة نفسه bullish أو volatile
            # البيانات (2026-04-22→2026-05-14، 2433 صفقة):
            #   4h+bullish:  255 → WR 35%، -$107.64
            #   1d+volatile:  81 → WR 30%، -$102.60
            #   4h+volatile: 103 → WR 40% لكن avg_loss > avg_win، -$72.46
            # السبب: mean-reverting لا يعمل في bullish (لا dips كافية)
            #         و volatile يعني SL واسع + تحركات حادة تضرب الـ stop قبل الـ target
            top_mc = top_data.get('market_condition', '')
            top_tf = top_data.get('timeframe', '?')
            if top_mc in ('bullish', 'strong_bullish'):
                logger.debug(
                    f"⏭️ رفض {symbol} - الإطار الرئيسي ({top_tf}) "
                    f"في {top_mc} (mean-reverting لا يعمل)"
                )
                continue
            if top_mc == 'volatile':
                logger.debug(
                    f"⏭️ رفض {symbol} - الإطار الرئيسي ({top_tf}) volatile "
                    f"(بيانات: 1d+vol=-102$، 4h+vol=-72$، SL واسع + تحركات حادة)"
                )
                continue

            # فلتر: رفض الإشارة إذا إطارها الرئيسي 4h
            # البيانات (post-rebuild 2026-04-22→2026-05-16، 275 صفقة):
            #   4h: 66 صفقة، WR 34.8%، -$27.38 ← 73% من إجمالي الخسارة
            #   1h: 205 صفقة، WR 36.6%، -$5.45 ← الإطار المقبول
            # SL على 4h واسع جداً ويُضرب قبل بلوغ الـ target.
            if top_tf == '4h':
                logger.debug(
                    f"⏭️ رفض {symbol} - الإطار الرئيسي 4h "
                    f"(محظور: مسؤول عن 73% من خسائر post-rebuild)"
                )
                continue

            # ══ تجميد مرفوع 2026-06-06 ══
            # البيانات أثبتت أن الحافة المزعومة (1d+bearish/sideways+score=3 → WR=54%)
            # غير صحيحة: walk-forward على 1924 إشارة يُظهر WR=6.3% فقط (أبريل: 1887 → WR=6%)
            # استئناف البحث المنهجي عن حافة حقيقية عبر مساري SMC+Wide R:R
            # التجميد الصارم (1d + bearish/sideways فقط) مُرفوع — جميع timeframes/conditions مقبولة
            # المرشحات الأخرى (volatility، bullish، 4h) محفوظة كحماية أساسية معتمدة

            # فلتر: رفض 1d+bearish/sideways إذا total_score >= 4.0 (overbought filter)
            # البيانات (2433 صفقة، n=251 للـ 1d+bearish/sideways):
            #   1d+bearish+score=3: WR=58.3%، PnL=+$30.84 (n=36)
            #   1d+sideways+score=3: WR=50.0%، PnL=+$15.89 (n=34)
            #   1d+bearish+score=4: WR=42.9%، PnL=-$8.87 (n=56) ← خاسر
            #   1d+sideways+score=4: WR=36.8%، PnL=-$13.00 (n=125) ← خاسر
            #   1d+*+score=5: WR=20-22%، PnL<-$12 ← أسوأ
            # العلاقة عكسية: كلما ارتفع score في 1d كلما انخفض WR
            # التفسير: نقاط عالية في 1d = مؤشرات متراكمة تشير لـ overbought
            # الحل: سقف عند raw_score < 4.0 للحافة الإيجابية
            if top_tf == '1d' and top_mc in ('bearish', 'sideways'):
                raw_score_1d = float(top_data.get('total_score', 0))
                if raw_score_1d >= 4.0:
                    logger.debug(
                        f"⏭️ رفض {symbol} - 1d+{top_mc} بـ raw_score={raw_score_1d:.2f} >= 4.0 "
                        f"(overbought: بيانات n=251 تُظهر WR عكسي في 1d عند score>=4)"
                    )
                    continue

            # ══ بوابة stoch>0 — رُفع التجميد جزئياً لهذا التغيير (2026-06-20، بطلب المستخدم) ══
            # ⚠️ تصحيح تدقيق 2026-06-23 (على كامل DB الحيّ، n=2518 — حلّ محل أرقام n=80 المضلِّلة):
            #   stoch>0: n=1115 WR=38.3% gross -0.162$/صفقة  |  stoch=0: n=1403 WR=36.7% gross -0.256$
            #   (الادعاء القديم «stoch=0 → WR=21%» كان أثر نافذة n=52 فقط — خاطئ على البيانات الكاملة)
            #   البوابة مُخفِّف-خسارة حقيقي ومتكرر (يصمد في أبريل وحده) لكنه لا يخلق ربحاً:
            #   stoch>0 يبقى سالباً بعد الرسوم (net ≈ -0.32$/صفقة) → النظام «أقل خسارة» لا رابح.
            #   COMBO (stoch>0 & div>0): n=7 WR=71% لكن 5/7 في مايو وحده، يتعادل OOS في يونيو → لا يُعتمد كبوابة.
            stoch_contrib = float(top_data.get('score_details', {}).get('stoch_rsi', 0) or 0)
            if stoch_contrib <= 0:
                logger.debug(f"⏭️ رفض {symbol} - بوابة stoch>0 (stoch=0 gross -0.26$ vs stoch>0 -0.16$؛ مُخفِّف خسارة لا حافة)")
                continue

            # ══ بوابة السبريد — واقعية التنفيذ (تدقيق 2026-06-23) ══
            # الانزلاق يلتهم أي حافة في التنفيذ الحقيقي؛ والسبريد محسوب أصلاً في order_book.spread_pct
            # (نسبة مئوية، توزيع حيّ 0.0002–0.36%). نرفض المرشحين عاليي السبريد (غير قابلين للتنفيذ واقعياً).
            # ليست فلتر «حافة» (لا يدّعي تحسين WR) بل فلتر جدوى تنفيذ. الحدّ قابل للضبط بـ MAX_SPREAD_PCT.
            _ob = top_data.get('order_book') or {}
            _spread = _ob.get('spread_pct')
            if _spread is not None and float(_spread) > config.MAX_SPREAD_PCT:
                logger.debug(f"⏭️ رفض {symbol} - سبريد {float(_spread):.3f}% > {config.MAX_SPREAD_PCT}% (انزلاق يلتهم الحافة)")
                continue

            # ملاحظة RSI filter (محذوف — 2026-05-17):
            # بيانات: rsi>=1.2 → WR=60% (n=35)، لكن Walk-Forward أثبت أن كل الـ 35 صفقة
            # من أسبوع واحد فقط (Apr-20-27). في الأسابيع اللاحقة: rsi>=1.2 = 0 إشارة.
            # الفلتر سيوقف البوت عملياً في السوق الحالي (overfitting على حقبة معينة).
            # القرار: لا نُطبَّق حتى تتراكم 100+ صفقة rsi>=1.2 من فترات مختلفة.

            # جمع الـ Timeframes المؤكِّدة للعرض في الرسالة
            confirmed_tfs = [d.get('timeframe', '?') for _, d in qualifying]

            # نتأكد Volume ضعيف لكن لا نرفض
            if top_data.get('score_details', {}).get('volume', 0) == 0:
                logger.debug(f"⚠️ {symbol} - Volume ضعيف (لكن نكمل التقييم)")

            if top_score > best_score:
                best_score = top_score
                best_signal = {
                    **top_data,
                    'total_score': round(top_score, 2),
                    'confirmed_timeframes': confirmed_tfs,
                    'timeframe_confirmations': confirmations,
                }

        if best_signal:
            tfs = ', '.join(best_signal.get('confirmed_timeframes', []))
            logger.info(
                f"🏆 أفضل إشارة: {best_signal['symbol']} | "
                f"نقاط: {best_signal['total_score']}/10 | "
                f"تأكيد: {best_signal['timeframe_confirmations']} Timeframes ({tfs})"
            )

        _record_evidence(best_signal, source="paper")
        return best_signal

    async def find_best_signal_live(self, results, macro: 'MacroContext'):
        """وضع التعلّم الحي: مرشّحون من المؤشرات البسيطة + بوابة ماكرو خفيفة + learned_gates."""
        self.last_decisions = {}
        if await macro.should_block_now():
            self.last_decisions.update({r['symbol']: 'macro_block' for r in results})
            self.last_v2_context = _v2_macro_context(macro)
            _v2_macro_block(results, self.last_v2_context)
            logger.warning("⏸️ Macro block (BTC strong_bearish أو USDT.D rising_fast)")
            return None
        macro_state = macro.macro_state_key()
        self.last_v2_context = _v2_ctx = _v2_macro_context(macro, macro_state)
        enforce = integrity_mode(config) == 'enforce'
        emitted = frozenset()
        if enforce:                                    # A44: fail-closed safety reads
            state = await self._integrity_state(results, macro_state)
            if state is None:
                return None
            throttled, open_symbols, cooldown, emitted = state
            decision_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        else:
            # خلايا متعلَّمة مخنوقة
            throttled = set()
            if config.LEARNING_GATES_ENABLED:
                for r in await Database.fetch(LEARNED_GATES_SQL, macro_state, config.MIN_CELL_N):
                    throttled.add((r['trade_type'], r['timeframe']))

            open_symbols = set(x['symbol'] for x in await Database.fetch(OPEN_SYMBOLS_SQL))
            cooldown = await self._get_symbol_cooldown_set()
        blocked = open_symbols | cooldown

        eligible = []
        for row in results:
            data = row['analysis_data']
            if isinstance(data, str):
                data = json.loads(data)
            symbol = data.get('symbol') or row['symbol']
            tt = data.get('trade_type')
            if not tt:
                self.last_decisions.setdefault(symbol, 'no_trade_setup')
                _v2_candidate(data, 'rejected', 'no_trade_setup', _v2_ctx)
                continue
            order_book = data.get('order_book') or {}
            spread = order_book.get('spread_pct')
            if order_book.get('valid') is not True or spread is None:
                self.last_decisions[symbol] = 'order_book_unavailable'
                _record_evidence(data, source='live', decision='rejected_order_book_unavailable')
                _v2_candidate(data, 'rejected', 'order_book_unavailable', _v2_ctx)
                continue
            if float(spread) > config.MAX_SPREAD_PCT:
                self.last_decisions[symbol] = 'spread_exceeds_limit'
                _record_evidence(data, source='live', decision='rejected_spread_exceeds_limit')
                _v2_candidate(data, 'rejected', 'spread_exceeds_limit', _v2_ctx,
                              limit={'max_spread_pct': config.MAX_SPREAD_PCT})
                continue
            # Legacy rows/test fixtures predate signal-aware stop metadata.
            # Only an explicit False is rejected; new analyzer output always
            # supplies this field.
            if data.get('stop_valid') is False:
                reason = data.get('stop_reject_reason') or 'invalid_signal_stop'
                self.last_decisions[symbol] = f'stop_rejected:{reason}'
                _record_evidence(data, source='live', decision=f'rejected_{reason}')
                _v2_candidate(data, 'rejected', f'stop_rejected:{reason}', _v2_ctx)
                logger.info(
                    f"⛔ {symbol} {tt}/{data.get('timeframe')} وقف الإبطال مرفوض: {reason}")
                continue
            if symbol in open_symbols:
                self.last_decisions[symbol] = 'open_trade_exists'
                _record_evidence(data, source='live', decision='rejected_open_trade_exists')
                _v2_candidate(data, 'rejected', 'open_trade_exists', _v2_ctx)
                continue
            if symbol in cooldown:
                self.last_decisions[symbol] = 'symbol_cooldown'
                _record_evidence(data, source='live', decision='rejected_symbol_cooldown')
                _v2_candidate(data, 'rejected', 'symbol_cooldown', _v2_ctx)
                continue
            setup_identity = None
            if enforce:                                # A44: identity, freshness, duplicate
                verdict = integrity_check(data, decision_ms=decision_ms,
                                          strategy_version=config.APP_VERSION, emitted_keys=emitted)
                if not verdict.eligible:
                    reason = verdict.reasons[0]
                    self.last_decisions[symbol] = reason
                    _record_evidence(data, source='live', decision=f'rejected_{reason}')
                    _v2_candidate(data, 'rejected', reason, _v2_ctx)
                    continue
                ident = identity_from_candidate(data, strategy_version=config.APP_VERSION)
                setup_identity = {'version': IDENTITY_VERSION, 'key': ident.key,
                                  'bracket_hash': bracket_hash(data),
                                  'candle_open_time_ms': ident.candle_open_ms,
                                  'candle_close_time_ms': ident.candle_close_ms}
            if (tt, data.get('timeframe')) in throttled:
                bucket = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
                explore_key = f"{symbol}|{tt}|{macro_state}|{data.get('timeframe')}"
                if exploration_selected(explore_key, bucket, config.LEARNING_EXPLORATION_RATE):
                    self.last_decisions[symbol] = 'learned_gate_exploration'
                    logger.info(f"🧪 exploration: {symbol} {tt}/{data.get('timeframe')} ({macro_state})")
                else:
                    self.last_decisions.setdefault(symbol, 'learned_gate_throttled')
                    logger.debug(f"⏭️ {symbol} {tt}/{data.get('timeframe')} throttled (statistically negative)")
                    _record_evidence(data, source='live', decision='rejected_learned_gate')
                    _v2_candidate(data, 'rejected',
                                  self.last_decisions.get(symbol, 'learned_gate'), _v2_ctx)
                    continue
            selection_volume = await self._get_volume_usdt(symbol)
            selection_spread = float(spread)
            candidate = {
                **data,
                'execution_features': {
                    **(data.get('execution_features') or {}),
                    'selection_spread_pct': selection_spread,
                    'selection_volume_usdt': selection_volume,
                },
                'macro_snapshot': {**macro.snapshot(), **macro.state()},
                'macro_state': macro_state,
                '_selection_volume_usdt': selection_volume,
                **({'setup_identity': setup_identity} if setup_identity else {}),
            }
            eligible.append(candidate)

        best = min(eligible, key=self._fixed_candidate_key) if eligible else None
        _v2_selection(eligible, best, self._fixed_candidate_key, _v2_ctx)
        for candidate in eligible:
            selected = candidate is best
            decision = 'selected_fixed_execution_policy' if selected else 'rejected_fixed_policy_rank'
            self.last_decisions[candidate['symbol']] = 'selected' if selected else 'not_selected_capacity'
            _record_evidence(candidate, source='live', decision=decision)
        if best:
            logger.info(
                f"🏆 fixed-policy signal: {best['symbol']} | {best.get('trade_type')} | "
                f"{best.get('timeframe')} | {macro_state} | "
                f"rank={self._fixed_candidate_key(best)}")
            best.pop('_selection_volume_usdt', None)
        return best

    def _get_btc_bonus(self, market_condition: str) -> float:
        bonuses = {
            'strong_bullish': 1.0,
            'bullish': 0.7,
            'neutral': 0.3,
            'sideways': 0.3,
            'bearish': 0.0,
            'strong_bearish': -0.5,
        }
        return bonuses.get(market_condition, 0.3)

    def _get_tf_bonus(self, timeframe: str) -> float:
        """
        bonus يُفضّل الإطارات ذات الحافة الإيجابية (بيانات 2433 صفقة post-rebuild):
        - 1d: WR=39.1%، وعند score=3: bearish WR=58.3%+$31، sideways WR=50%+$16
              إجمالي score=3+1d → +$36.11 على 76 صفقة (الوحيد ذو PnL موجب واضح)
        - 1h: WR=36.7%، score=3+1h → -$19.75 (أسوأ من 1d)
        - 4h: محظور كإطار رئيسي (يُرفض لاحقاً بفلتر منفصل)
        القيمة +0.5 تُقدّم 1d على 1h عند التعادل دون اشتراط نقاط مرتفعة.
        """
        bonuses = {
            '1d': 0.5,
            '1h': 0.0,
            '4h': 0.0,   # محظور كإطار رئيسي، لكن قد يكون مؤكِّداً
            '15m': -0.5, # بيانات قليلة جداً (3 صفقات فقط)
        }
        return bonuses.get(timeframe, 0.0)

    async def _get_volume_usdt(self, symbol: str) -> float:
        """يجلب volume_usdt من آخر مسح في scan_candidates للعملة المحددة."""
        try:
            row = await Database.fetchrow(
                """SELECT data->>'volume_usdt' AS volume_usdt
                   FROM scan_candidates
                   WHERE symbol = $1
                   ORDER BY scan_time DESC
                   LIMIT 1""",
                symbol
            )
            if row and row['volume_usdt']:
                return float(row['volume_usdt'])
        except Exception as e:
            try:
                logger.warning(f"فشل جلب volume_usdt لـ {symbol}: {e}")
            except Exception:
                pass
        return None

    async def save_signal(self, signal: Dict) -> int:
        """حفظ الإشارة في قاعدة البيانات ونشر signal.ready في نفس المعاملة.

        CR-1: الإشارة تُحفظ جاهزة مباشرة (decision_source=policy_ready) دون المرور
        بـ claude_review؛ claude_approved يبقى NULL (لا موافقة Claude مزيّفة).
        الجاهزية لا تعني فتح صفقة: بوابة الإيقاف/B3 في telegram وحارس المخاطر
        في trade_tracker يبقيان صاحبَي القرار. لا يُنشر signal.created بعد الآن
        (لا مستهلك له)؛ التراجع = إعادة هذا الملف لنشر signal.created.
        """
        # fail-closed: إشارة ناقصة/تالفة لا تُحفظ ولا تصبح قابلة للتداول.
        try:
            assert_signal_complete(signal)
        except Exception as exc:
            _v2_signal_refused(signal, exc)   # P1-R: INCOMPLETE_SIGNAL evidence only
            raise                             # the refusal itself is unchanged
        score_details = signal.get('score_details', {})
        if signal.get('order_book'):
            score_details['order_book'] = signal['order_book'].get('score', 0)

        # نحفظ الـ Timeframes المؤكِّدة كـ string منفصل (لا نضعها في score_details لأنها list)
        confirmed_tfs = signal.get('confirmed_timeframes', [])
        score_details['timeframe_confirmations'] = signal.get('timeframe_confirmations', 1)
        # confirmed_timeframes تُحفظ كـ string مفصول بفاصلة لتجنب مشاكل float() في التدريب
        score_details['confirmed_timeframes_str'] = ','.join(confirmed_tfs)

        # جلب volume_usdt من آخر مسح في scan_candidates
        volume_usdt = await self._get_volume_usdt(signal['symbol'])

        # لقطة الميزات الخام (feature store — تدقيق 2026-06-23): قيم المؤشرات الفعلية + سياق دفتر الأوامر
        # وقت الإشارة، مرتبطة لاحقاً بالنتيجة عبر trade_results.signal_id → بحث ML نزيه على ميزات خام.
        _ob = signal.get('order_book') or {}
        research_features = dict(
            signal.get('research_features') or signal.get('features') or {})
        execution_features = dict(signal.get('execution_features') or {})
        features_snapshot = dict(research_features)  # compatibility for existing research readers
        features_snapshot.update({
            'spread_pct': _ob.get('spread_pct'),
            'bid_ask_ratio': _ob.get('bid_ask_ratio'),
            'ob_score': _ob.get('score'),
            'market_condition': signal.get('market_condition'),
            'timeframe': signal.get('timeframe'),
            'total_score': signal.get('total_score'),
            'trend_ok': signal.get('trend_ok'),
            'volume_usdt': volume_usdt,
            'trade_type': signal.get('trade_type'),
            'stop_policy': signal.get('stop_policy'),
            'stop_invalidation': signal.get('stop_invalidation'),
            'stop_risk_pct': signal.get('stop_risk_pct'),
            'entry_reason': signal.get('entry_reason'),
            'selection_policy': signal.get('selection_policy'),
            'research_features': research_features,
            'execution_features': execution_features,
        })
        # P1-A lineage anchor in the DB row — persisted only while forward instrumentation is ON
        _identity = signal_identity(signal) if evidence_v2.enabled() else None
        if _identity is not None:
            features_snapshot['identity'] = _identity
        # A44: in enforce mode the setup identity is mandatory and the insert is idempotent.
        setup = signal.get('setup_identity') if integrity_mode(config) == 'enforce' else None
        if integrity_mode(config) == 'enforce' and not (setup and setup.get('key')):
            raise ValueError('setup_identity_required')     # fail closed: never an unkeyed signal
        if setup:
            features_snapshot['setup_identity'] = dict(setup)
        self.last_emission = None

        async with Database.acquire() as conn:
            async with conn.transaction():
                if setup:
                    signal_id = await conn.fetchval(
                        _INSERT_ONCE_SQL,
                        signal['symbol'], signal.get('timeframe', config.TIMEFRAME),
                        signal.get('market_condition', 'unknown'),
                        signal['entry_price'], signal['target_1'], signal['target_2'],
                        signal['target_3'], signal['stop_loss'], int(signal['total_score']),
                        json.dumps(score_details), config.PAPER_TRADING, volume_usdt,
                        json.dumps(features_snapshot), signal.get('trade_type'),
                        json.dumps(signal.get('macro_snapshot') or {}),
                        READY_DECISION_SOURCE, config.APP_VERSION, setup['key'])
                    if signal_id is None:              # this setup was already emitted
                        row = await conn.fetchrow(_EXISTING_SETUP_SQL, setup['key'])
                        same = row is not None and row['bracket_hash'] == setup.get('bracket_hash')
                        self.last_emission = {'status': 'duplicate' if same else 'conflict',
                                              'existing_signal_id': row['id'] if row else None,
                                              'setup_key': setup['key']}
                        logger.warning(f"🔁 setup already emitted, not re-published: {self.last_emission}")
                        return None
                else:
                    signal_id = await conn.fetchval("""
                        INSERT INTO signals (
                            symbol, timeframe, market_condition,
                            entry_price, target_1, target_2, target_3,
                            stop_loss, score, score_details, is_paper_trade,
                            volume_usdt, features_snapshot, trade_type, macro_snapshot,
                            decision_source, strategy_version
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                        RETURNING id
                    """,
                        signal['symbol'], signal.get('timeframe', config.TIMEFRAME),
                        signal.get('market_condition', 'unknown'),
                        signal['entry_price'], signal['target_1'], signal['target_2'], signal['target_3'],
                        signal['stop_loss'], int(signal['total_score']), json.dumps(score_details),
                        config.PAPER_TRADING, volume_usdt, json.dumps(features_snapshot),
                        signal.get('trade_type'), json.dumps(signal.get('macro_snapshot') or {}),
                        READY_DECISION_SOURCE, config.APP_VERSION)
                await conn.execute("""
                    INSERT INTO risk_management (date, signals_sent)
                    VALUES (CURRENT_DATE, 1)
                    ON CONFLICT (date) DO UPDATE
                    SET signals_sent = risk_management.signals_sent + 1
                """)
                # إن فشل الإدراج أو النشر تتراجع المعاملة كاملة: لا إشارة ولا حدث.
                await enqueue(conn, SIGNAL_READY_EVENT, 'signal', signal_id,
                              ready_payload(signal_id, config.APP_VERSION))

        _v2_signal_ready(signal_id, signal, getattr(self, 'last_v2_context', None))   # after commit
        return signal_id
