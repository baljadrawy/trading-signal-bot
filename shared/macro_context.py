"""سياق السوق الكلّي: BTC/ETH (Binance) + USDT.D/BTC.D (CoinGecko) + بوابة خفيفة.
يُخزّن مؤقتاً، يكتب snapshot يومي في macro_history لحساب اتجاه USDT.D."""
import time, json, urllib.request
from datetime import datetime, timezone
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('macro_context')
FLAT_EPS = 0.05  # نقطة مئوية: أقل من هذا = flat


def classify_usdtd_trend(now: float, avg_3d: float, spike_pp: float) -> str:
    d = now - avg_3d
    if d >= spike_pp:
        return 'rising_fast'
    if d > FLAT_EPS:
        return 'rising'
    if d < -FLAT_EPS:
        return 'falling'
    return 'flat'


def should_block(btc_trend: str, usdtd_trend: str) -> bool:
    return btc_trend == 'strong_bearish' or usdtd_trend == 'rising_fast'


def _cg_global() -> dict:
    req = urllib.request.Request("https://api.coingecko.com/api/v3/global",
                                 headers={'User-Agent': 'Mozilla/5.0'})
    g = json.loads(urllib.request.urlopen(req, timeout=20).read())
    mc = g['data']['market_cap_percentage']
    return {'usdt_d': float(mc.get('usdt', 0)), 'btc_d': float(mc.get('btc', 0))}


def _trend_from_change(change_pct: float) -> str:
    if change_pct <= -5: return 'strong_bearish'
    if change_pct < -1:  return 'bearish'
    if change_pct > 5:   return 'strong_bullish'
    if change_pct > 1:   return 'bullish'
    return 'neutral'


class MacroContext:
    def __init__(self, client):
        self.client = client            # python-binance AsyncClient
        self._snap = {}
        self._state = {}
        self._ts = 0.0

    async def _btc_eth_change(self, symbol: str) -> float:
        kl = await self.client.get_klines(symbol=symbol, interval='4h', limit=20)
        kl = kl[:-1]                    # أسقط الشمعة الجارية
        first_close = float(kl[-18][4]); last_close = float(kl[-1][4])  # ~3 أيام (18×4h)
        return (last_close - first_close) / first_close * 100

    async def refresh(self):
        try:
            cg = _cg_global()
        except Exception as e:
            logger.warning(f"CoinGecko fail, using last snapshot: {e}")
            cg = {'usdt_d': self._snap.get('usdt_d', 0), 'btc_d': self._snap.get('btc_d', 0)}
        try:
            btc_chg = await self._btc_eth_change('BTCUSDT')
            eth_chg = await self._btc_eth_change('ETHUSDT')
        except Exception as e:
            logger.warning(f"Binance macro fail: {e}")
            btc_chg = eth_chg = 0.0
        today = datetime.now(timezone.utc).date()
        # متوسط 3 أيام لـ USDT.D من macro_history
        rows = await Database.fetch(
            "SELECT usdt_d FROM macro_history WHERE date >= CURRENT_DATE - 3 AND usdt_d IS NOT NULL")
        avg_3d = (sum(float(r['usdt_d']) for r in rows) / len(rows)) if rows else cg['usdt_d']
        usdtd_trend = classify_usdtd_trend(cg['usdt_d'], avg_3d, config.USDTD_SPIKE_PP)
        btc_trend = _trend_from_change(btc_chg)
        eth_trend = _trend_from_change(eth_chg)
        self._snap = {'btc_change_pct': round(btc_chg, 2), 'eth_change_pct': round(eth_chg, 2),
                      'usdt_d': cg['usdt_d'], 'btc_d': cg['btc_d'],
                      'usdtd_3d_delta': round(cg['usdt_d'] - avg_3d, 3)}
        self._state = {'btc_trend': btc_trend, 'eth_trend': eth_trend, 'usdtd_trend': usdtd_trend}
        self._ts = time.time()
        await Database.execute(
            """INSERT INTO macro_history (date, usdt_d, btc_d, btc_trend, eth_trend)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (date) DO UPDATE SET usdt_d=$2, btc_d=$3, btc_trend=$4, eth_trend=$5, updated_at=NOW()""",
            today, cg['usdt_d'], cg['btc_d'], btc_trend, eth_trend)

    async def _ensure_fresh(self):
        if time.time() - self._ts > config.MACRO_CACHE_HOURS * 3600 or not self._state:
            await self.refresh()

    async def should_block_now(self) -> bool:
        await self._ensure_fresh()
        return should_block(self._state.get('btc_trend', 'neutral'),
                            self._state.get('usdtd_trend', 'flat'))

    def snapshot(self) -> dict:
        return dict(self._snap)

    def state(self) -> dict:
        return dict(self._state)

    def macro_state_key(self) -> str:
        """تمثيل مُكثَّف لخلايا التعلّم = اتجاه USDT.D."""
        return f"usdtd_{self._state.get('usdtd_trend', 'flat')}"
