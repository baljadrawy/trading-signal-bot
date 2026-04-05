"""
منطق المسح والفلترة الأولية للعملات
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict
from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('scanner_logic')

class BinanceScanner:
    def __init__(self, client: AsyncClient):
        self.client = client
        self.btc_trend = "neutral"

    async def scan(self) -> List[Dict]:
        """المسح الرئيسي - يفلتر العملات المؤهلة"""
        
        # 1. تحقق من حالة إدارة المخاطر
        if await self._is_trading_paused():
            logger.warning("⏸️ التداول موقوف - تجاوز حد الخسائر")
            return []

        # 2. تحديث اتجاه BTC أولاً
        await self._update_btc_trend()
        
        # 3. جلب كل USDT pairs
        all_symbols = await self._get_usdt_pairs()
        logger.info(f"📊 إجمالي العملات: {len(all_symbols)}")
        
        # 4. جلب بيانات 24 ساعة لكل العملات دفعة واحدة
        tickers = await self._get_24h_tickers()
        
        # 5. الفلتر الأولي السريع
        candidates = []
        for symbol in all_symbols:
            ticker = tickers.get(symbol)
            if ticker and await self._passes_initial_filter(symbol, ticker):
                candidates.append({
                    'symbol': symbol,
                    'price': float(ticker['lastPrice']),
                    'volume_usdt': float(ticker['quoteVolume']),
                    'price_change_pct': float(ticker['priceChangePercent']),
                    'high_24h': float(ticker['highPrice']),
                    'low_24h': float(ticker['lowPrice']),
                    'btc_trend': self.btc_trend,
                    'scan_time': datetime.now().isoformat()
                })
        
        # 6. حفظ المرشحين في قاعدة البيانات للـ Analyzer
        if candidates:
            await self._save_candidates(candidates)
        
        logger.info(f"🎯 العملات المؤهلة للتحليل: {len(candidates)}")
        return candidates

    async def _get_usdt_pairs(self) -> List[str]:
        """جلب كل أزواج USDT النشطة"""
        exchange_info = await self.client.get_exchange_info()
        return [
            s['symbol'] for s in exchange_info['symbols']
            if s['quoteAsset'] == 'USDT'
            and s['status'] == 'TRADING'
            and s['symbol'] not in ['USDCUSDT', 'BUSDUSDT', 'TUSDUSDT']
        ]

    async def _get_24h_tickers(self) -> Dict:
        """جلب بيانات 24 ساعة لكل العملات دفعة واحدة"""
        tickers = await self.client.get_ticker()
        return {t['symbol']: t for t in tickers}

    async def _passes_initial_filter(self, symbol: str, ticker: Dict) -> bool:
        """الفلتر الأولي السريع"""
        try:
            volume_usdt = float(ticker['quoteVolume'])
            price_change = abs(float(ticker['priceChangePercent']))
            last_price = float(ticker['lastPrice'])

            # شرط 1: حجم تداول كافٍ
            if volume_usdt < config.MIN_VOLUME_USDT:
                return False

            # شرط 2: حركة سعرية كافية (لا نريد عملات ساكنة)
            if price_change < config.MIN_PRICE_CHANGE_PERCENT:
                return False

            # شرط 3: سعر معقول (نتجنب العملات بأسعار صفرية)
            if last_price <= 0:
                return False

            # شرط 4: إذا BTC في هبوط قوي، نتجاهل معظم العملات
            if self.btc_trend == "strong_bearish" and price_change < 5:
                return False

            return True

        except (ValueError, KeyError):
            return False

    async def _update_btc_trend(self):
        """تحديث اتجاه BTC"""
        try:
            klines = await self.client.get_klines(
                symbol='BTCUSDT',
                interval='4h',
                limit=10
            )
            closes = [float(k[4]) for k in klines]
            
            # حساب التغير
            change = ((closes[-1] - closes[0]) / closes[0]) * 100
            
            if change > 3:
                self.btc_trend = "strong_bullish"
            elif change > 1:
                self.btc_trend = "bullish"
            elif change < -3:
                self.btc_trend = "strong_bearish"
            elif change < -1:
                self.btc_trend = "bearish"
            else:
                self.btc_trend = "neutral"
                
            logger.info(f"₿ اتجاه BTC: {self.btc_trend} ({change:.2f}%)")
            
        except Exception as e:
            logger.error(f"خطأ في تحديث اتجاه BTC: {e}")
            self.btc_trend = "neutral"

    async def _save_candidates(self, candidates: List[Dict]):
        """حفظ المرشحين في قاعدة البيانات"""
        # نحفظ في جدول مؤقت يقرأه الـ Analyzer
        await Database.execute("""
            CREATE TABLE IF NOT EXISTS scan_candidates (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                data JSONB NOT NULL,
                scan_time TIMESTAMP DEFAULT NOW(),
                analyzed BOOLEAN DEFAULT false
            )
        """)
        
        # حذف المرشحين القديمة
        await Database.execute(
            "DELETE FROM scan_candidates WHERE scan_time < NOW() - INTERVAL '1 hour'"
        )
        
        # إدراج المرشحين الجدد
        await Database.executemany(
            """
            INSERT INTO scan_candidates (symbol, data)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            [(c['symbol'], json.dumps(c)) for c in candidates]
        )

    async def _is_trading_paused(self) -> bool:
        """تحقق من حالة إيقاف التداول"""
        result = await Database.fetchrow(
            "SELECT is_trading_paused FROM risk_management WHERE date = CURRENT_DATE"
        )
        return result['is_trading_paused'] if result else False
