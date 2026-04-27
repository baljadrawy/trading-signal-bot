"""
منطق اختيار أفضل إشارة مع تأكيد متعدد الـ Timeframes
"""
import json
from typing import Dict, List, Optional
from datetime import datetime
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
        - إذا market_condition='bearish' → نعتبر السوق في انهيار → إيقاف الإشارات
        مرجع: استراتيجية mean-reverting لا تعمل في هبوط قوي للسوق ككل.
        """
        try:
            row = await Database.fetchrow(
                """SELECT analysis_data FROM analysis_results
                   WHERE symbol='BTCUSDT' AND timeframe='4h'
                   ORDER BY analyzed_at DESC LIMIT 1"""
            )
            if not row:
                return False
            data = row['analysis_data']
            if isinstance(data, str):
                data = json.loads(data)
            return data.get('market_condition') == 'bearish'
        except Exception as e:
            logger.warning(f"BTC crash check failed: {e}")
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

        # التحقق من حدود الإشارات اليومية
        signals_today = await Database.fetchval(
            "SELECT signals_sent FROM risk_management WHERE date = CURRENT_DATE"
        ) or 0

        if config.MAX_SIGNALS_PER_DAY > 0 and signals_today >= config.MAX_SIGNALS_PER_DAY:
            logger.info(f"⏸️ وصلنا للحد الأقصى اليومي: {signals_today} إشارات")
            return None

        # جلب العملات المحظورة (صفقة مفتوحة أو مرفوضة)
        open_symbols = set(r['symbol'] for r in await Database.fetch(
            "SELECT DISTINCT symbol FROM active_trades WHERE status = 'open'"
        ))
        rejected_symbols = set(r['symbol'] for r in await Database.fetch(
            "SELECT DISTINCT symbol FROM approval_requests WHERE status = 'rejected'"
        ))
        blocked_symbols = open_symbols | rejected_symbols

        if blocked_symbols:
            logger.info(f"🚫 عملات محظورة: {len(blocked_symbols)} (مفتوحة: {len(open_symbols)}, مرفوضة: {len(rejected_symbols)})")

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
