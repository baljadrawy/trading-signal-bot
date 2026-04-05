"""
تحليل Order Book - السيولة وجدران الشراء والبيع
"""
import asyncio
from typing import Dict, Optional
from binance import AsyncClient
from shared.logger import setup_logger

logger = setup_logger('orderbook_analyzer')

class OrderBookAnalyzer:
    def __init__(self, client: AsyncClient):
        self.client = client

    async def analyze(self, symbol: str) -> Dict:
        """تحليل Order Book للعملة"""
        try:
            # جلب Order Book (أعلى 20 مستوى)
            ob = await self.client.get_order_book(symbol=symbol, limit=20)
            
            bids = [(float(p), float(q)) for p, q in ob['bids']]
            asks = [(float(p), float(q)) for p, q in ob['asks']]
            
            if not bids or not asks:
                return self._empty_result()
            
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            current_price = (best_bid + best_ask) / 2
            
            # حجم طلبات الشراء والبيع
            total_bid_volume = sum(q for _, q in bids)
            total_ask_volume = sum(q for _, q in asks)
            
            # نسبة الشراء/البيع
            bid_ask_ratio = total_bid_volume / total_ask_volume if total_ask_volume > 0 else 1
            
            # البحث عن جدران السيولة
            buy_wall = self._find_wall(bids, current_price, is_buy=True)
            sell_wall = self._find_wall(asks, current_price, is_buy=False)
            
            # الـ Spread
            spread_pct = ((best_ask - best_bid) / best_bid) * 100
            
            # حساب النقطة
            score = self._calculate_score(bid_ask_ratio, buy_wall, sell_wall, spread_pct)
            
            return {
                'score': score,
                'bid_ask_ratio': round(bid_ask_ratio, 3),
                'total_bid_volume': round(total_bid_volume, 2),
                'total_ask_volume': round(total_ask_volume, 2),
                'buy_wall_price': buy_wall['price'] if buy_wall else None,
                'buy_wall_size': buy_wall['size'] if buy_wall else None,
                'sell_wall_price': sell_wall['price'] if sell_wall else None,
                'sell_wall_size': sell_wall['size'] if sell_wall else None,
                'spread_pct': round(spread_pct, 4),
            }
            
        except Exception as e:
            logger.error(f"خطأ في تحليل Order Book لـ {symbol}: {e}")
            return self._empty_result()

    def _find_wall(self, orders, current_price: float, is_buy: bool) -> Optional[Dict]:
        """البحث عن جدران السيولة الكبيرة"""
        if not orders:
            return None
            
        avg_size = sum(q for _, q in orders) / len(orders)
        wall_threshold = avg_size * 5  # جدار = 5 أضعاف المتوسط
        
        for price, size in orders:
            if size >= wall_threshold:
                distance_pct = abs(price - current_price) / current_price * 100
                if distance_pct <= 3:  # ضمن 3% من السعر الحالي
                    return {
                        'price': price,
                        'size': size,
                        'distance_pct': round(distance_pct, 2)
                    }
        return None

    def _calculate_score(self, bid_ask_ratio: float, buy_wall: Optional[Dict],
                         sell_wall: Optional[Dict], spread_pct: float) -> float:
        """حساب نقطة Order Book"""
        score = 0.0
        
        # نسبة الشراء للبيع
        if bid_ask_ratio >= 1.5:
            score += 0.5  # ضغط شراء قوي
        elif bid_ask_ratio >= 1.2:
            score += 0.3
        
        # جدار شراء قريب = دعم قوي
        if buy_wall and buy_wall.get('distance_pct', 100) <= 2:
            score += 0.3
        
        # لا يوجد جدار بيع قريب
        if not sell_wall or sell_wall.get('distance_pct', 0) >= 2:
            score += 0.2
        
        # السبريد ضيق = سيولة جيدة
        if spread_pct <= 0.1:
            score += 0.0  # طبيعي في العملات الكبيرة
        elif spread_pct > 0.5:
            score -= 0.2  # عقوبة للسبريد الواسع
        
        return round(max(0, min(1, score)), 2)  # من 0 إلى 1

    def _empty_result(self) -> Dict:
        return {
            'score': 0,
            'bid_ask_ratio': 1.0,
            'total_bid_volume': 0,
            'total_ask_volume': 0,
            'buy_wall_price': None,
            'buy_wall_size': None,
            'sell_wall_price': None,
            'sell_wall_size': None,
            'spread_pct': 0,
        }
