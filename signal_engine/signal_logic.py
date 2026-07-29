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

logger = setup_logger('signal_logic')

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


def _record_evidence(signal, source):
    """Fail-safe evidence hook. Reads the signal, never mutates it, never raises —
    even if logging itself fails (the except-handler's own log is guarded)."""
    if not config.ENABLE_EVIDENCE_RECORDER or not signal:
        return
    try:
        from research.null_a.recorder import capture_signal
        capture_signal(get_evidence_recorder(), signal, source=source,
                       model_version=config.APP_VERSION)
    except Exception:
        try:
            logger.warning("evidence hook failed", exc_info=True)
        except Exception:
            pass


class SignalEngine:

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

    async def _get_symbol_cooldown_set(self) -> set:
        """
        Cooldown 2 ساعات لكل عملة:
        أي عملة صدرت لها إشارة في آخر 2 ساعة → لا إشارة جديدة لها.
        الهدف: منع تكرار نفس العملة المتعثرة مراراً (كحادثة PROMUSDT -$16).
        ملاحظة: نستخدم NOW() - INTERVAL في SQL مباشرة لتجنب مشكلة timezone مع PostgreSQL.
        """
        try:
            rows = await Database.fetch(
                """SELECT DISTINCT symbol FROM signals
                   WHERE signal_time > NOW() - INTERVAL '2 hours'"""
            )
            symbols = {r['symbol'] for r in rows}
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
        if await macro.should_block_now():
            logger.warning("⏸️ Macro block (BTC strong_bearish أو USDT.D rising_fast)")
            return None
        macro_state = macro.macro_state_key()
        # خلايا متعلَّمة مخنوقة
        throttled = set()
        for r in await Database.fetch(
                "SELECT trade_type, timeframe FROM learned_gates "
                "WHERE macro_state=$1 AND n>=$2 AND weight<=0", macro_state, config.MIN_CELL_N):
            throttled.add((r['trade_type'], r['timeframe']))

        open_symbols = set(x['symbol'] for x in await Database.fetch(
            "SELECT DISTINCT symbol FROM active_trades WHERE status='open'"))
        cooldown = await self._get_symbol_cooldown_set()
        blocked = open_symbols | cooldown

        best = None
        for row in results:
            data = row['analysis_data']
            if isinstance(data, str):
                data = json.loads(data)
            symbol = data.get('symbol') or row['symbol']
            tt = data.get('trade_type')
            if not tt or symbol in blocked:
                continue
            if (tt, data.get('timeframe')) in throttled:
                logger.debug(f"⏭️ {symbol} {tt}/{data.get('timeframe')} throttled (learned loser)")
                continue
            # أول مرشّح صالح غير مخنوق يكفي (paper، جمع عيّنة) — بلا تفضيل نوع.
            # حُيِّد تفضيل reversion (flip 4f84717) 2026-07-29: كلا النوعين بلا حافة صافية
            # بعد الرسوم (تدقيق 2026-07-29 + دحض canary-close OOS)، والخنق المُتعلَّم
            # (learned_gates.weight) هو من يقصي الخلايا الخاسرة لا انحياز مبرمَج.
            if best is None:
                best = {**data, 'macro_snapshot': {**macro.snapshot(), **macro.state()},
                        'macro_state': macro_state}
        if best:
            logger.info(f"🏆 live signal: {best['symbol']} | {best.get('trade_type')} | {best.get('timeframe')} | {macro_state}")
        _record_evidence(best, source="live")
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
            logger.warning(f"فشل جلب volume_usdt لـ {symbol}: {e}")
        return None

    async def save_signal(self, signal: Dict) -> int:
        """حفظ الإشارة في قاعدة البيانات"""
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
        features_snapshot = dict(signal.get('features') or {})
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
        })

        signal_id = await Database.fetchval("""
            INSERT INTO signals (
                symbol, timeframe, market_condition,
                entry_price, target_1, target_2, target_3,
                stop_loss, score, score_details, is_paper_trade,
                volume_usdt, features_snapshot, trade_type, macro_snapshot
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            RETURNING id
        """,
            signal['symbol'], signal.get('timeframe', config.TIMEFRAME),
            signal.get('market_condition', 'unknown'),
            signal['entry_price'], signal['target_1'], signal['target_2'], signal['target_3'],
            signal['stop_loss'], int(signal['total_score']), json.dumps(score_details),
            config.PAPER_TRADING, volume_usdt, json.dumps(features_snapshot),
            signal.get('trade_type'), json.dumps(signal.get('macro_snapshot') or {}))

        # تحديث عداد الإشارات اليومية
        await Database.execute("""
            INSERT INTO risk_management (date, signals_sent)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (date) DO UPDATE
            SET signals_sent = risk_management.signals_sent + 1
        """)

        return signal_id
