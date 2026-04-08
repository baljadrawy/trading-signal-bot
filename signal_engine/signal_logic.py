"""
منطق اختيار أفضل إشارة وحفظها
"""
import json
from typing import Dict, List, Optional
from datetime import datetime
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('signal_logic')

class SignalEngine:
    
    async def find_best_signal(self, results: List) -> Optional[Dict]:
        """إيجاد أفضل إشارة من نتائج التحليل"""
        
        # التحقق من حدود الإشارات اليومية
        signals_today = await Database.fetchval(
            "SELECT signals_sent FROM risk_management WHERE date = CURRENT_DATE"
        ) or 0
        
        if signals_today >= config.MAX_SIGNALS_PER_DAY:
            logger.info(f"⏸️ وصلنا للحد الأقصى اليومي: {signals_today} إشارات")
            return None
        
        best = None
        best_score = 0
        
        for row in results:
            data = json.loads(row['analysis_data']) if isinstance(row['analysis_data'], str) else row['analysis_data']
            
            score = float(data.get('total_score', 0))
            ob_score = data.get('order_book', {}).get('score', 0) if data.get('order_book') else 0
            
            # إضافة نقطة Order Book وBTC Trend
            btc_bonus = self._get_btc_bonus(data.get('market_condition', 'sideways'))
            final_score = score + ob_score + btc_bonus
            
            # شرط الحد الأدنى للنقاط
            if final_score < config.MIN_SCORE_TO_SIGNAL:
                continue

            # تحذير Volume ضعيف لكن لا نرفض الإشارة
            if data.get('score_details', {}).get('volume', 0) == 0:
                logger.debug(f"⚠️ {row['symbol']} - Volume ضعيف (لكن نكمل التقييم)")
            
            # أفضل نقاط
            if final_score > best_score:
                best_score = final_score
                best = {**data, 'total_score': round(final_score, 2)}
        
        if best:
            logger.info(f"🏆 أفضل إشارة: {best['symbol']} بنقاط {best['total_score']}/10")
        
        return best

    def _get_btc_bonus(self, market_condition: str) -> float:
        """مكافأة بناءً على حالة BTC"""
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
        
        signal_id = await Database.fetchval("""
            INSERT INTO signals (
                symbol, timeframe, market_condition,
                entry_price, target_1, target_2, target_3,
                stop_loss, score, score_details, is_paper_trade
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """,
            signal['symbol'],
            config.TIMEFRAME,
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
