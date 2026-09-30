> **HISTORICAL / DO NOT EXECUTE OPERATIONAL COMMANDS** — see docs/ops/COMPOSE_OPERATIONS.md

# Live-Learning Signal Collector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the live (paper) signal bot into an open-ended collector that emits simple-indicator long signals tagged by trade-type + full BTC/ETH/USDT.D macro context, and continuously learns (rolling window) which (type × macro × timeframe) cells win.

**Architecture:** Reuse scanner/trade_tracker/telegram/DB. Add `MacroContext` (macro fetch + light gate), `SimpleEntry` (momentum/reversion triggers) wired into `technical_analyzer.analyze`, a live-learning branch in `signal_engine`, and a `ContinuousLearner` cron job that writes a `learned_gates` table the engine consults. All gated behind `LIVE_LEARNING_MODE`.

**Tech Stack:** Python 3.12, asyncpg/PostgreSQL, pandas 3.0 + `ta`, python-binance (async), CoinGecko REST, Docker Compose. Unit tests via pytest in `research/skill_application/.venv`.

## Global Constraints

- `PAPER_TRADING=true` stays true — NO real execution, ever, in this work.
- DB role `trading_signal_bot`, db `trading_signals`; direct psql: `docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "..."`.
- Closed-candle only: indicators computed on closed candles (`_get_candles` already drops the in-progress bar). Do not reintroduce look-ahead.
- Timeframes for this mode: `15m,4h,1d` (`TIMEFRAMES_LL`).
- Long-only. Reuse `_calculate_levels` (ATR) + `trade_tracker` unchanged.
- Old score path must remain functional when `LIVE_LEARNING_MODE=false` (no deletion of existing logic; branch around it).
- Rebuild containers with `--no-cache` after code changes.

---

## File Structure

- Create `shared/macro_context.py` — macro fetch (Binance BTC/ETH + CoinGecko USDT.D/BTC.D), state classification, `should_block()`.
- Create `analyzer/simple_entry.py` — pure trigger functions returning `'momentum' | 'reversion' | None`.
- Create `database/migrate_live_learning_2026_06_25.sql` — new columns + tables.
- Create `research/continuous_learner.py` — rolling-window aggregation → `learned_gates`.
- Create `tests/test_simple_entry.py`, `tests/test_macro_context.py`, `tests/test_continuous_learner.py` — pytest unit tests.
- Modify `shared/config.py` — add `LIVE_LEARNING_MODE` + params.
- Modify `analyzer/technical_analyzer.py` — compute + attach `trade_type` in `analyze()` when live-learning on.
- Modify `signal_engine/signal_logic.py` — live-learning branch in `find_best_signal` + persist `trade_type`/`macro_snapshot` in `save_signal`.
- Modify `docker-compose.yml` — add `continuous_learner` service (or cron entry).

---

### Task 1: Database migration

**Files:**
- Create: `database/migrate_live_learning_2026_06_25.sql`

**Interfaces:**
- Produces: `signals.trade_type` (varchar), `signals.macro_snapshot` (jsonb); tables `macro_history`, `learned_gates`.

- [ ] **Step 1: Write migration SQL**

```sql
-- database/migrate_live_learning_2026_06_25.sql
ALTER TABLE signals ADD COLUMN IF NOT EXISTS trade_type VARCHAR;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS macro_snapshot JSONB;

CREATE TABLE IF NOT EXISTS macro_history (
    date DATE PRIMARY KEY,
    usdt_d NUMERIC,
    btc_d NUMERIC,
    btc_trend VARCHAR,
    eth_trend VARCHAR,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learned_gates (
    trade_type VARCHAR,
    macro_state VARCHAR,
    timeframe VARCHAR,
    n INT DEFAULT 0,
    wr NUMERIC,
    expectancy NUMERIC,
    weight NUMERIC DEFAULT 1.0,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (trade_type, macro_state, timeframe)
);
```

- [ ] **Step 2: Apply and verify**

Run:
```bash
docker exec -i postgres psql -U trading_signal_bot -d trading_signals < database/migrate_live_learning_2026_06_25.sql
docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "\d signals" | grep -E "trade_type|macro_snapshot"
docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "\dt" | grep -E "macro_history|learned_gates"
```
Expected: both columns present; both tables listed.

- [ ] **Step 3: Commit**

```bash
git add database/migrate_live_learning_2026_06_25.sql
git commit -m "feat(db): live-learning columns + macro_history + learned_gates"
```

---

### Task 2: Config parameters

**Files:**
- Modify: `shared/config.py`

**Interfaces:**
- Produces: `config.LIVE_LEARNING_MODE: bool`, `config.TIMEFRAMES_LL: list`, plus tunables listed below.

- [ ] **Step 1: Add fields to the `Config` dataclass** (after the `MIN_TIMEFRAME_CONFIRMATIONS` line)

```python
    # ── Live-Learning mode ──────────────────────────────────────────────
    LIVE_LEARNING_MODE: bool = os.getenv('LIVE_LEARNING_MODE', 'false').lower() == 'true'
    TIMEFRAMES_LL: list = field(default_factory=lambda: os.getenv('TIMEFRAMES_LL', '15m,4h,1d').split(','))
    MOM_BREAKOUT_N: int = int(os.getenv('MOM_BREAKOUT_N', '20'))
    MOM_VOL_MULT: float = float(os.getenv('MOM_VOL_MULT', '1.2'))
    REV_RSI: float = float(os.getenv('REV_RSI', '35'))
    USDTD_SPIKE_PP: float = float(os.getenv('USDTD_SPIKE_PP', '0.5'))
    MACRO_CACHE_HOURS: int = int(os.getenv('MACRO_CACHE_HOURS', '1'))
    WARMUP_N: int = int(os.getenv('WARMUP_N', '100'))
    ROLL_N: int = int(os.getenv('ROLL_N', '150'))
    MIN_CELL_N: int = int(os.getenv('MIN_CELL_N', '10'))
    THROTTLE_EXPECTANCY: float = float(os.getenv('THROTTLE_EXPECTANCY', '0'))
    LEARN_CRON_HOURS: int = int(os.getenv('LEARN_CRON_HOURS', '12'))
```

- [ ] **Step 2: Verify import**

Run: `docker exec trading_signal_engine python -c "from shared.config import config; print(config.LIVE_LEARNING_MODE, config.TIMEFRAMES_LL, config.REV_RSI)"`
Expected: `False ['15m', '4h', '1d'] 35.0`

- [ ] **Step 3: Commit**

```bash
git add shared/config.py
git commit -m "feat(config): live-learning mode flags + tunables"
```

---

### Task 3: SimpleEntry triggers (pure logic, TDD)

**Files:**
- Create: `analyzer/simple_entry.py`
- Test: `tests/test_simple_entry.py`

**Interfaces:**
- Produces: `detect_trade_type(df: pd.DataFrame, *, breakout_n=20, vol_mult=1.2, rev_rsi=35.0) -> str | None`.
  `df` has columns `open,high,low,close,volume,rsi,ema20,ema50,bb_lower` indexed by time; last row = decision (closed) candle.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_simple_entry.py
import pandas as pd, numpy as np
import sys; sys.path.insert(0, '.')
from analyzer.simple_entry import detect_trade_type

def _df(close, high=None, low=None, vol=None, rsi=50, ema20=None, ema50=None, bb_lower=None):
    n = len(close)
    high = high if high is not None else [c*1.001 for c in close]
    low = low if low is not None else [c*0.999 for c in close]
    vol = vol if vol is not None else [100.0]*n
    return pd.DataFrame({
        'open': close, 'high': high, 'low': low, 'close': close, 'volume': vol,
        'rsi': [rsi]*n,
        'ema20': ema20 if ema20 is not None else [c*0.95 for c in close],
        'ema50': ema50 if ema50 is not None else [c*0.90 for c in close],
        'bb_lower': bb_lower if bb_lower is not None else [c*0.80 for c in close],
    })

def test_momentum_breakout_with_volume():
    close = [10]*20 + [12]                       # last closes above prior 20-bar high (=~10.01)
    df = _df(close, vol=[100]*20 + [200])        # volume spike
    assert detect_trade_type(df, breakout_n=20, vol_mult=1.2) == 'momentum'

def test_momentum_blocked_without_volume():
    close = [10]*20 + [12]
    df = _df(close, vol=[100]*21)                # no volume spike
    assert detect_trade_type(df, breakout_n=20, vol_mult=1.2) != 'momentum'

def test_reversion_oversold_bounce():
    close = [10,9.5,9.0,8.5,8.6]                 # turning up at the end
    df = _df(close, rsi=30, bb_lower=[8.7]*5,    # close(8.6) < bb_lower*1.01 (8.787)
             ema20=[7]*5, ema50=[6]*5)
    assert detect_trade_type(df, rev_rsi=35) == 'reversion'

def test_no_signal_neutral():
    close = [10.0]*21
    df = _df(close, rsi=50)
    assert detect_trade_type(df) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_simple_entry.py -q`
Expected: FAIL (`ModuleNotFoundError: analyzer.simple_entry`). If pytest missing: `research/skill_application/.venv/bin/pip install -q pytest` first.

- [ ] **Step 3: Implement `analyzer/simple_entry.py`**

```python
"""محرّك دخول بسيط شفّاف (long فقط) — momentum أو reversion على شمعة مغلقة."""
import pandas as pd


def detect_trade_type(df: pd.DataFrame, *, breakout_n: int = 20,
                      vol_mult: float = 1.2, rev_rsi: float = 35.0):
    """يُرجع 'momentum' | 'reversion' | None. momentum له الأولوية لو أطلق الاثنان."""
    if df is None or len(df) < breakout_n + 2:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(last['close'])

    # momentum: إغلاق فوق EMA20>EMA50 + اختراق قمة آخر breakout_n شمعة سابقة + حجم
    try:
        prior_high = float(df['high'].iloc[-(breakout_n + 1):-1].max())
        vol_ma = float(df['volume'].iloc[-(breakout_n + 1):-1].mean())
        if (close > float(last['ema20']) > float(last['ema50'])
                and close > prior_high
                and float(last['volume']) > vol_mult * vol_ma):
            return 'momentum'
    except Exception:
        pass

    # reversion: RSI متشبّع + ارتداد (إغلاق>سابقه) + قرب الباند السفلي
    try:
        if (float(last['rsi']) < rev_rsi
                and close > float(prev['close'])
                and close < float(last['bb_lower']) * 1.01):
            return 'reversion'
    except Exception:
        pass
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_simple_entry.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add analyzer/simple_entry.py tests/test_simple_entry.py
git commit -m "feat(entry): simple momentum/reversion triggers + tests"
```

---

### Task 4: MacroContext (state classification TDD + async fetch)

**Files:**
- Create: `shared/macro_context.py`
- Test: `tests/test_macro_context.py`

**Interfaces:**
- Produces:
  - `classify_usdtd_trend(now: float, avg_3d: float, spike_pp: float) -> str` → `'rising_fast'|'rising'|'falling'|'flat'`.
  - `should_block(btc_trend: str, usdtd_trend: str) -> bool`.
  - `class MacroContext`: `async refresh()`, `snapshot() -> dict`, `state() -> dict`, `async should_block_now() -> bool` (cached `MACRO_CACHE_HOURS`).
- Consumes: Binance async client (BTC/ETH klines), CoinGecko `/global`, `macro_history` table for USDT.D trend.

- [ ] **Step 1: Write failing tests (pure functions only)**

```python
# tests/test_macro_context.py
import sys; sys.path.insert(0, '.')
from shared.macro_context import classify_usdtd_trend, should_block

def test_usdtd_rising_fast():
    # +0.6 نقطة مئوية فوق متوسط 3 أيام، عتبة 0.5
    assert classify_usdtd_trend(9.3, 8.7, 0.5) == 'rising_fast'

def test_usdtd_rising_not_fast():
    assert classify_usdtd_trend(8.9, 8.7, 0.5) == 'rising'

def test_usdtd_falling():
    assert classify_usdtd_trend(8.4, 8.7, 0.5) == 'falling'

def test_usdtd_flat():
    assert classify_usdtd_trend(8.71, 8.70, 0.5) == 'flat'

def test_block_on_btc_crash():
    assert should_block('strong_bearish', 'falling') is True

def test_block_on_usdtd_spike():
    assert should_block('neutral', 'rising_fast') is True

def test_no_block_normal():
    assert should_block('bullish', 'falling') is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_macro_context.py -q`
Expected: FAIL (`ModuleNotFoundError: shared.macro_context`).

- [ ] **Step 3: Implement `shared/macro_context.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_macro_context.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add shared/macro_context.py tests/test_macro_context.py
git commit -m "feat(macro): BTC/ETH/USDT.D context + light gate + tests"
```

---

### Task 5: Wire SimpleEntry into the analyzer

**Files:**
- Modify: `analyzer/technical_analyzer.py` (in `analyze()`, after `levels = self._calculate_levels(df, tf)`)

**Interfaces:**
- Consumes: `detect_trade_type` (Task 3), `config.LIVE_LEARNING_MODE`, `config.MOM_BREAKOUT_N/MOM_VOL_MULT/REV_RSI`.
- Produces: `analysis_data['trade_type']` (str or None) consumed by Task 6.

- [ ] **Step 1: Add import at top of `analyzer/technical_analyzer.py`** (near other imports)

```python
from simple_entry import detect_trade_type
```

- [ ] **Step 2: Compute trade_type and add to the returned dict.** In `analyze()`, change the `return { ... }` to include `trade_type`:

```python
            trade_type = None
            if config.LIVE_LEARNING_MODE:
                trade_type = detect_trade_type(
                    df, breakout_n=config.MOM_BREAKOUT_N,
                    vol_mult=config.MOM_VOL_MULT, rev_rsi=config.REV_RSI)

            return {
                'symbol': symbol,
                'timeframe': tf,
                'market_condition': market_condition,
                'total_score': scores['total'],
                'score_details': scores['details'],
                'features': features,
                'entry_price': levels['entry'],
                'target_1': levels['t1'],
                'target_2': levels['t2'],
                'target_3': levels['t3'],
                'stop_loss': levels['stop'],
                'atr': float(df['atr'].iloc[-1]),
                'rsi': float(df['rsi'].iloc[-1]),
                'macd_signal': scores['details'].get('macd', 0),
                'volume_ratio': float(df['volume_ratio'].iloc[-1]),
                'trend_ok': trend_ok,
                'trade_type': trade_type,
            }
```

Note: `df` already has `rsi`, `ema20`, `ema50`, `bb_lower` (computed in `_calculate_indicators`). No new indicators needed.

- [ ] **Step 3: Verify analyzer still imports/runs**

Run: `docker compose build --no-cache analyzer && docker compose up -d analyzer && sleep 20 && docker compose logs analyzer --tail=20`
Expected: no ImportError; analyzer processing candidates.

- [ ] **Step 4: Commit**

```bash
git add analyzer/technical_analyzer.py
git commit -m "feat(analyzer): attach trade_type in live-learning mode"
```

---

### Task 6: SignalEngine live-learning branch + recording

**Files:**
- Modify: `signal_engine/signal_logic.py` (`find_best_signal` and `save_signal`)

**Interfaces:**
- Consumes: `analysis_data['trade_type']` (Task 5), `MacroContext` (Task 4), `learned_gates` table (Task 1/7).
- Produces: rows in `signals` with `trade_type`, `macro_snapshot`.

- [ ] **Step 1: Add a live-learning selection method to `SignalEngine`.** Add imports at top:

```python
from shared.macro_context import MacroContext
```

Add this method to the class:

```python
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
            # أول مرشّح صالح يكفي (paper، جمع عيّنة)؛ تفضيل momentum
            if best is None or (tt == 'momentum' and best.get('trade_type') != 'momentum'):
                best = {**data, 'macro_snapshot': {**macro.snapshot(), **macro.state()},
                        'macro_state': macro_state}
        if best:
            logger.info(f"🏆 live signal: {best['symbol']} | {best.get('trade_type')} | {best.get('timeframe')} | {macro_state}")
        return best
```

- [ ] **Step 2: Persist new fields in `save_signal`.** In the `INSERT INTO signals (...)` add `trade_type, macro_snapshot`:

```python
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
```

- [ ] **Step 3: Branch the caller in `signal_engine/main.py`.** Where it currently calls `engine.find_best_signal(results)`, wrap:

```python
        if config.LIVE_LEARNING_MODE:
            best_signal = await engine.find_best_signal_live(results, macro_ctx)
        else:
            best_signal = await engine.find_best_signal(results)
```

And construct `macro_ctx = MacroContext(client)` once at startup in `main()` (the engine already has a Binance `client`; if not, create `AsyncClient` like the analyzer does). Add `from shared.macro_context import MacroContext` import.

- [ ] **Step 4: Verify end-to-end (paper) with mode ON**

Run:
```bash
# enable in .env then rebuild engine+analyzer
grep -q LIVE_LEARNING_MODE .env || echo "LIVE_LEARNING_MODE=true" >> .env
docker compose build --no-cache analyzer signal_engine && docker compose up -d analyzer signal_engine
sleep 90
docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "SELECT symbol, timeframe, trade_type, macro_snapshot->>'usdt_d' FROM signals WHERE trade_type IS NOT NULL ORDER BY signal_time DESC LIMIT 5;"
```
Expected: rows with `trade_type` in {momentum,reversion} and a `usdt_d` value (after a scan/analyze cycle produces a trigger).

- [ ] **Step 5: Commit**

```bash
git add signal_engine/signal_logic.py signal_engine/main.py
git commit -m "feat(signal): live-learning selection + macro recording + learned_gates throttle"
```

---

### Task 7: ContinuousLearner (rolling aggregation, TDD)

**Files:**
- Create: `research/continuous_learner.py`
- Test: `tests/test_continuous_learner.py`

**Interfaces:**
- Produces: `compute_cells(trades: list[dict], min_cell_n: int, throttle_expectancy: float) -> list[dict]`
  where each input trade = `{trade_type, macro_state, timeframe, profit_percent, is_win}` and each output cell =
  `{trade_type, macro_state, timeframe, n, wr, expectancy, weight}`.
  `weight = 1.0` if `expectancy > throttle_expectancy` and `n>=min_cell_n`; `0.0` if `expectancy<=throttle` and `n>=min_cell_n`; else `1.0` (neutral warm-up).
- Async `run()` reads last `ROLL_N` closed trades joined to signals, calls `compute_cells`, upserts `learned_gates`, sends a Telegram summary.

- [ ] **Step 1: Write failing tests (pure aggregation)**

```python
# tests/test_continuous_learner.py
import sys; sys.path.insert(0, '.')
from research.continuous_learner import compute_cells

def _t(tt, ms, tf, pct):
    return {'trade_type': tt, 'macro_state': ms, 'timeframe': tf,
            'profit_percent': pct, 'is_win': pct > 0}

def test_winning_cell_weight_1():
    trades = [_t('momentum','usdtd_falling','4h', p) for p in [2,3,-1,2,1,2,3,-1,2,2,3,1]]  # n=12 pos exp
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='momentum'][0]
    assert c['n'] == 12 and c['expectancy'] > 0 and c['weight'] == 1.0

def test_losing_cell_throttled():
    trades = [_t('reversion','usdtd_rising','1d', p) for p in [-2,-3,1,-2,-1,-2,-3,1,-2,-2,-1]]  # n=11 neg exp
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='reversion'][0]
    assert c['expectancy'] < 0 and c['weight'] == 0.0

def test_small_cell_neutral():
    trades = [_t('momentum','usdtd_flat','15m', p) for p in [-5,-5,-5]]  # n=3 < min
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='momentum'][0]
    assert c['n'] == 3 and c['weight'] == 1.0   # محايد رغم الخسارة (عيّنة صغيرة)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_continuous_learner.py -q`
Expected: FAIL (`ModuleNotFoundError: research.continuous_learner`).

- [ ] **Step 3: Implement `research/continuous_learner.py`**

```python
"""التعلّم الحي المستمرّ: نافذة متحرّكة → أوزان learned_gates لكل (نوع × ماكرو × إطار)."""
import asyncio
from collections import defaultdict
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
try:
    from shared.alerts import send_alert
except Exception:
    send_alert = None

logger = setup_logger('continuous_learner')


def compute_cells(trades, min_cell_n: int, throttle_expectancy: float):
    groups = defaultdict(list)
    for t in trades:
        groups[(t['trade_type'], t['macro_state'], t['timeframe'])].append(t)
    out = []
    for (tt, ms, tf), items in groups.items():
        n = len(items)
        wins = sum(1 for x in items if x['is_win'])
        exp = sum(float(x['profit_percent']) for x in items) / n
        if n >= min_cell_n:
            weight = 1.0 if exp > throttle_expectancy else 0.0
        else:
            weight = 1.0
        out.append({'trade_type': tt, 'macro_state': ms, 'timeframe': tf,
                    'n': n, 'wr': round(wins / n * 100, 1), 'expectancy': round(exp, 4),
                    'weight': weight})
    return out


async def run():
    closed = await Database.fetchval("SELECT COUNT(*) FROM trade_results")
    if (closed or 0) < config.WARMUP_N:
        logger.info(f"warm-up: {closed}/{config.WARMUP_N} closed trades; skipping learning")
        return
    rows = await Database.fetch(
        """SELECT s.trade_type, s.macro_snapshot, s.timeframe, tr.profit_percent,
                  (tr.result='WIN') AS is_win
           FROM trade_results tr JOIN signals s ON tr.signal_id = s.id
           WHERE s.trade_type IS NOT NULL
           ORDER BY tr.exit_time DESC LIMIT $1""", config.ROLL_N)
    trades = []
    for r in rows:
        ms = r['macro_snapshot'] or {}
        if isinstance(ms, str):
            import json; ms = json.loads(ms)
        trades.append({'trade_type': r['trade_type'],
                       'macro_state': f"usdtd_{ms.get('usdtd_trend', 'flat')}",
                       'timeframe': r['timeframe'], 'profit_percent': r['profit_percent'],
                       'is_win': r['is_win']})
    cells = compute_cells(trades, config.MIN_CELL_N, config.THROTTLE_EXPECTANCY)
    for c in cells:
        await Database.execute(
            """INSERT INTO learned_gates (trade_type, macro_state, timeframe, n, wr, expectancy, weight, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
               ON CONFLICT (trade_type, macro_state, timeframe)
               DO UPDATE SET n=$4, wr=$5, expectancy=$6, weight=$7, updated_at=NOW()""",
            c['trade_type'], c['macro_state'], c['timeframe'], c['n'], c['wr'], c['expectancy'], c['weight'])
    winners = sorted([c for c in cells if c['weight'] > 0 and c['n'] >= config.MIN_CELL_N],
                     key=lambda x: x['expectancy'], reverse=True)[:5]
    losers = [c for c in cells if c['weight'] == 0]
    msg = ("📚 Learner: " + f"{len(cells)} cells, {len(losers)} throttled.\n" +
           "Top: " + ", ".join(f"{c['trade_type']}/{c['macro_state']}/{c['timeframe']}(E={c['expectancy']},n={c['n']})" for c in winners))
    logger.info(msg)
    if send_alert:
        try:
            await send_alert(msg, level='info', component='Learner')
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_continuous_learner.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add research/continuous_learner.py tests/test_continuous_learner.py
git commit -m "feat(learner): rolling-window continuous learning into learned_gates + tests"
```

---

### Task 8: Schedule the learner + rollout

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `research/continuous_learner.py` (Task 7), `config.LEARN_CRON_HOURS`.

- [ ] **Step 1: Add a lightweight scheduler service to `docker-compose.yml`** (reuses an existing image with shared/ + research/):

```yaml
  continuous_learner:
    build:
      context: .
      dockerfile: signal_engine/Dockerfile
    environment:
      - LIVE_LEARNING_MODE=${LIVE_LEARNING_MODE}
    command: >
      sh -c "while true; do python research/continuous_learner.py || true;
             sleep $$(( ${LEARN_CRON_HOURS:-12} * 3600 )); done"
    depends_on: [postgres]
    networks: [shared_db_net]
    restart: unless-stopped
```

(If `signal_engine/Dockerfile` does not COPY `research/`, add `COPY research/ ./research/` to it; verify `shared/` is copied.)

- [ ] **Step 2: Run all unit tests once more**

Run: `research/skill_application/.venv/bin/python -m pytest tests/ -q`
Expected: `14 passed` (4 + 7 + 3).

- [ ] **Step 3: Roll out (paper)**

Run:
```bash
docker exec -i postgres psql -U trading_signal_bot -d trading_signals < database/migrate_live_learning_2026_06_25.sql
grep -q LIVE_LEARNING_MODE .env || echo "LIVE_LEARNING_MODE=true" >> .env
docker compose build --no-cache analyzer signal_engine continuous_learner
docker compose up -d
sleep 10 && docker compose ps
```
Expected: all containers healthy; `continuous_learner` running.

- [ ] **Step 4: Verify collection after one cycle**

Run: `docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "SELECT trade_type, timeframe, COUNT(*) FROM signals WHERE trade_type IS NOT NULL GROUP BY 1,2;"`
Expected: counts accumulating as live trades trigger.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml signal_engine/Dockerfile
git commit -m "feat(ops): continuous_learner service + live-learning rollout"
```

---

## Self-Review

**Spec coverage:**
- §3.1 MacroContext → Task 4 ✓ | §3.2 SimpleEntry → Task 3, wired Task 5 ✓ | §3.3 DB → Task 1 ✓
- §3.4 SignalEngine gate+record → Task 6 ✓ | §3.5 tracker unchanged → (no task, intentional) ✓
- §3.6 ContinuousLearner → Task 7, scheduled Task 8 ✓ | §7 rollout/flag → Task 2 + Task 8 ✓
- §8 params → Task 2 ✓ | §5 error handling → MacroContext fallbacks (Task 4 Step 3) ✓

**Placeholder scan:** none — all steps contain real code/commands.

**Type consistency:** `detect_trade_type` signature identical in Tasks 3 & 5; `compute_cells` cell dict keys (`trade_type,macro_state,timeframe,n,wr,expectancy,weight`) identical in Task 7 test, impl, and `learned_gates` schema (Task 1); `macro_state` format `usdtd_<trend>` consistent across MacroContext.macro_state_key (Task 4), find_best_signal_live (Task 6), continuous_learner (Task 7).

**Note on tests:** project had no pytest suite; this plan introduces `tests/` run via the research venv (`research/skill_application/.venv`). Install pytest there if absent (`pip install pytest`).
