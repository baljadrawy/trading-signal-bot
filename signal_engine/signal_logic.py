"""
منطق اختيار أفضل إشارة مع تأكيد متعدد الـ Timeframes
"""
import json
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('signal_logic')

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
        - bearish أو strong_bearish → السوق في انهيار → إيقاف الإشارات
        مرجع: استراتيجية mean-reverting لا تعمل في هبوط قوي للسوق ككل.
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
            return trend in ('bearish', 'strong_bearish')
        except Exception as e:
            logger.warning(f"BTC crash check failed: {e}")
            return False

    async def _is_global_loss_cooldown(self) -> bool:
        """
        Cooldown 6 ساعات — يُطلق فقط عند stop_hit=true (ضربة SL حقيقية):
        - stop_hit=true  → السوق أسقط الـ SL → خطر فعلي → freeze 6h
        - stop_hit=false → expire 48h أو forced close → ليست إشارة انعكاس سوقي حاد
        الهدف: منع الدخول في سلسلة SL خلال نفس الشروط السوقية السيئة،
               دون تجميد البوت بعد خسارة expire رمزية كـ -$0.91 (حادثة SPKUSDT 2026-05-14).
        ملاحظة: نستخدم NOW() - INTERVAL في SQL مباشرة لتجنب مشكلة timezone مع PostgreSQL.
        """
        try:
            row = await Database.fetchrow(
                """SELECT id FROM trade_results
                   WHERE result = 'LOSS'
                   AND stop_hit = true
                   AND exit_time > NOW() - INTERVAL '6 hours'
                   LIMIT 1"""
            )
            if row:
                logger.info("⏸️ Cooldown نشط: SL hit في آخر 6 ساعات — إيقاف الإشارات مؤقتاً")
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
            logger.warning("⏸️ BTC 4h bearish — إيقاف الإشارات حماية لرأس المال")
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

        # جلب العملات المحظورة (صفقة مفتوحة أو مرفوضة أو في cooldown)
        open_symbols = set(r['symbol'] for r in await Database.fetch(
            "SELECT DISTINCT symbol FROM active_trades WHERE status = 'open'"
        ))
        rejected_symbols = set(r['symbol'] for r in await Database.fetch(
            "SELECT DISTINCT symbol FROM approval_requests WHERE status = 'rejected'"
        ))
        blocked_symbols = open_symbols | rejected_symbols | cooldown_symbols

        if blocked_symbols:
            logger.info(
                f"🚫 عملات محظورة: {len(blocked_symbols)} "
                f"(مفتوحة: {len(open_symbols)}, مرفوضة: {len(rejected_symbols)}, "
                f"cooldown: {len(cooldown_symbols)})"
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
            if not any(d.get('trend_ok') for d in tf_results):
                logger.debug(f"⏭️ تخطي {symbol} - تحت ema200 في كل الإطارات (downtrend)")
                continue

            # احسب عدد الـ Timeframes المتفقة (تجاوزت الحد الأدنى)
            qualifying = []
            for data in tf_results:
                # تخطي إطار volatile أو downtrend (تحت ema200)
                if data.get('market_condition') == 'volatile':
                    continue
                if not data.get('trend_ok', True):
                    continue

                score = float(data.get('total_score', 0))
                ob_score = data.get('order_book', {}).get('score', 0) if data.get('order_book') else 0
                btc_bonus = self._get_btc_bonus(data.get('market_condition', 'sideways'))
                final = score + ob_score + btc_bonus

                if final >= min_score:
                    qualifying.append((final, data))

            confirmations = len(qualifying)

            if confirmations < min_tf:
                logger.debug(
                    f"رفض {symbol} - تأكيدات: {confirmations}/{len(tf_results)} "
                    f"(مطلوب {min_tf})"
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

        return best_signal

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

        signal_id = await Database.fetchval("""
            INSERT INTO signals (
                symbol, timeframe, market_condition,
                entry_price, target_1, target_2, target_3,
                stop_loss, score, score_details, is_paper_trade
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """,
            signal['symbol'],
            signal.get('timeframe', config.TIMEFRAME),
            signal.get('market_condition', 'unknown'),
            signal['entry_price'],
            signal['target_1'],
            signal['target_2'],
            signal['target_3'],
            signal['stop_loss'],
            int(signal['total_score']),
            json.dumps(score_details),
            config.PAPER_TRADING
        )

        # تحديث عداد الإشارات اليومية
        await Database.execute("""
            INSERT INTO risk_management (date, signals_sent)
            VALUES (CURRENT_DATE, 1)
            ON CONFLICT (date) DO UPDATE
            SET signals_sent = risk_management.signals_sent + 1
        """)

        return signal_id
