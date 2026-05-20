"""
بحث: هندسة عكسية لمنهجية اختيار سعر Entry في التوصيات الخارجية
================================================================
يحلل 12 توصية سكالب خارجية (قالب ثابت: T1=+4%, T2=+7%, T3=+9%, SL=-4%)
ويبحث عن المؤشرات التي تفسر اختيار سعر Entry.

التشغيل: داخل analyzer container
  docker compose exec analyzer python3 research/entry_reverse_engineer.py

المخرج: research/entry_methodology_report.md
"""

import sys, os, time, math, json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.append('/app')

import requests
import numpy as np
import pandas as pd

# ─── الثوابت ────────────────────────────────────────────────────────────────

OUTPUT_MD   = '/app/research/entry_methodology_report.md'
API_BASE    = 'https://api.binance.com'
API_DELAY   = 0.25   # ثانية بين الطلبات (rate-limit safety)
CANDLES     = 220    # عدد الشموع لكل timeframe (يكفي لـ EMA200 + فيبوناتشي)
WINDOW_48H  = 48     # ±48h للبحث عن لمسة Entry
NEAR_PCT    = 0.005  # ±0.5% للتطابق مع المستويات

# ─── بيانات التوصيات ────────────────────────────────────────────────────────

SIGNALS = [
    {"symbol": "STORJUSDT",  "entry": 0.1164,  "date_utc": "2026-05-17"},
    {"symbol": "ENJUSDT",    "entry": 0.0447,  "date_utc": "2026-05-18"},
    {"symbol": "HMSTRUSDT",  "entry": 0.000149,"date_utc": "2026-05-18"},
    {"symbol": "APTUSDT",    "entry": 0.9430,  "date_utc": "2026-05-18"},
    {"symbol": "ONDOUSDT",   "entry": 0.3811,  "date_utc": "2026-05-18"},
    {"symbol": "RONINUSDT",  "entry": 0.1076,  "date_utc": "2026-05-18"},
    {"symbol": "INJUSDT",    "entry": 5.022,   "date_utc": "2026-05-18"},
    {"symbol": "CFGUSDT",    "entry": 0.2802,  "date_utc": "2026-05-19"},
    {"symbol": "SEIUSDT",    "entry": 0.0605,  "date_utc": "2026-05-19"},
    {"symbol": "SUSDT",      "entry": 0.0441,  "date_utc": "2026-05-19"},
    {"symbol": "RADUSDT",    "entry": 0.3140,  "date_utc": "2026-05-19"},
    {"symbol": "PLUMEUSDT",  "entry": 0.0117,  "date_utc": "2026-05-19"},
]

# ─── جلب klines ─────────────────────────────────────────────────────────────

def fetch_klines(symbol: str, interval: str, end_time_ms: int, limit: int = CANDLES) -> Optional[pd.DataFrame]:
    """يجلب شموع OHLCV من Binance REST API."""
    url = f"{API_BASE}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "endTime": end_time_ms,
        "limit": limit,
    }
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 429:
                print(f"  [rate-limit] {symbol}/{interval} — sleep 10s")
                time.sleep(10)
                continue
            r.raise_for_status()
            raw = r.json()
            if not raw:
                return None
            df = pd.DataFrame(raw, columns=[
                'open_time','open','high','low','close','volume',
                'close_time','qav','trades','tbav','tqav','ignore'
            ])
            for c in ['open','high','low','close','volume']:
                df[c] = df[c].astype(float)
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
            return df
        except Exception as e:
            print(f"  [error] {symbol}/{interval} attempt={attempt+1}: {e}")
            time.sleep(2)
    return None

# ─── مساعدات حساب المؤشرات ──────────────────────────────────────────────────

def _ema(series: np.ndarray, period: int) -> np.ndarray:
    """EMA بسيطة بدون ta."""
    k = 2.0 / (period + 1)
    out = np.full(len(series), np.nan)
    # أول قيمة = SMA
    if len(series) < period:
        return out
    out[period - 1] = series[:period].mean()
    for i in range(period, len(series)):
        out[i] = series[i] * k + out[i-1] * (1 - k)
    return out

def _rsi(series: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(series, prepend=series[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    # Wilder smoothing
    avg_gain = np.full(len(series), np.nan)
    avg_loss = np.full(len(series), np.nan)
    if len(series) <= period:
        return avg_gain
    avg_gain[period] = gain[1:period+1].mean()
    avg_loss[period] = loss[1:period+1].mean()
    for i in range(period + 1, len(series)):
        avg_gain[i] = (avg_gain[i-1] * (period-1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i-1] * (period-1) + loss[i]) / period
    rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _bollinger(close: np.ndarray, period: int = 20, std_mult: float = 2.0):
    """يعيد (upper, mid, lower) arrays."""
    upper = np.full(len(close), np.nan)
    lower = np.full(len(close), np.nan)
    mid   = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        window = close[i - period + 1: i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        mid[i]   = m
        upper[i] = m + std_mult * s
        lower[i] = m - std_mult * s
    return upper, mid, lower

def _stoch_rsi(rsi_arr: np.ndarray, period: int = 14) -> np.ndarray:
    """Stochastic RSI (0-1)."""
    out = np.full(len(rsi_arr), np.nan)
    for i in range(period - 1, len(rsi_arr)):
        window = rsi_arr[i - period + 1: i + 1]
        lo = np.nanmin(window)
        hi = np.nanmax(window)
        if hi == lo:
            out[i] = 0.5
        else:
            out[i] = (rsi_arr[i] - lo) / (hi - lo)
    return out

def _find_swing_lows(low: np.ndarray, lookback: int = 3) -> List[int]:
    """يجد مؤشرات swing lows (قاع محلي)."""
    result = []
    for i in range(lookback, len(low) - lookback):
        if all(low[i] <= low[i-j] for j in range(1, lookback+1)) and \
           all(low[i] <= low[i+j] for j in range(1, lookback+1)):
            result.append(i)
    return result

def _find_swing_highs(high: np.ndarray, lookback: int = 3) -> List[int]:
    """يجد مؤشرات swing highs (قمة محلية)."""
    result = []
    for i in range(lookback, len(high) - lookback):
        if all(high[i] >= high[i-j] for j in range(1, lookback+1)) and \
           all(high[i] >= high[i+j] for j in range(1, lookback+1)):
            result.append(i)
    return result

def _fib_levels(swing_low: float, swing_high: float) -> Dict[str, float]:
    """مستويات فيبوناتشي التصحيحية من swing high → low (ارتداد هابط)."""
    diff = swing_high - swing_low
    return {
        "fib_0.236": swing_high - 0.236 * diff,
        "fib_0.382": swing_high - 0.382 * diff,
        "fib_0.500": swing_high - 0.500 * diff,
        "fib_0.618": swing_high - 0.618 * diff,
        "fib_0.786": swing_high - 0.786 * diff,
    }

def _pivot_daily(prev_high: float, prev_low: float, prev_close: float) -> Dict[str, float]:
    """Pivot Points كلاسيكي يومي."""
    pp = (prev_high + prev_low + prev_close) / 3
    s1 = 2 * pp - prev_high
    s2 = pp - (prev_high - prev_low)
    r1 = 2 * pp - prev_low
    r2 = pp + (prev_high - prev_low)
    return {"PP": pp, "S1": s1, "S2": s2, "R1": r1, "R2": r2}

def _near(price: float, level: float, pct: float = NEAR_PCT) -> bool:
    if level == 0:
        return False
    return abs(price - level) / level <= pct

def _range_position(price: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.5
    return (price - lo) / (hi - lo)

def _round_number_dist(price: float) -> float:
    """
    المسافة النسبية لأقرب رقم مستدير ذي معنى.
    نستخدم قوى 10 ومضاعفاتها (0.5×، 0.25×).
    """
    if price == 0:
        return 0.0
    magnitude = 10 ** math.floor(math.log10(price))
    candidates = []
    for m in [0.25, 0.5, 1.0, 2.0, 5.0, 10.0]:
        level = round(price / (magnitude * m)) * (magnitude * m)
        if level > 0:
            candidates.append(level)
    min_dist = min(abs(price - c) / price for c in candidates if c > 0)
    return min_dist

# ─── محرك التحليل لكل رمز ────────────────────────────────────────────────────

def analyze_signal(sig: dict) -> dict:
    symbol  = sig["symbol"]
    entry   = sig["entry"]
    date_str = sig["date_utc"]

    rec_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    # نافذة: rec_dt - 48h إلى rec_dt + 48h للبحث عن لمسة entry
    window_start = rec_dt - timedelta(hours=WINDOW_48H)
    window_end   = rec_dt + timedelta(hours=WINDOW_48H)
    # end_time لجلب klines = نهاية النافذة (لنأخذ بيانات حتى نقطة التقييم)
    fetch_end_ms = int(window_end.timestamp() * 1000)

    print(f"\n[{symbol}] entry={entry} date={date_str}")

    result = {
        "symbol": symbol,
        "entry": entry,
        "date_utc": date_str,
        "entry_touched": False,
        "entry_touch_time": None,
        "features": {}
    }

    # ─── 1. جلب klines ─────────────────────────────────────────────

    df_1h = fetch_klines(symbol, "1h", fetch_end_ms, limit=CANDLES)
    time.sleep(API_DELAY)
    df_4h = fetch_klines(symbol, "4h", fetch_end_ms, limit=CANDLES)
    time.sleep(API_DELAY)
    df_1d = fetch_klines(symbol, "1d", fetch_end_ms, limit=CANDLES)
    time.sleep(API_DELAY)

    if df_1h is None or len(df_1h) < 50:
        print(f"  [skip] بيانات 1h غير كافية")
        result["error"] = "insufficient_1h_data"
        return result

    # ─── 2. إيجاد لحظة Entry ────────────────────────────────────────

    # البحث في نافذة ±48h
    mask_1h = (df_1h['open_time'] >= window_start) & \
               (df_1h['open_time'] <= window_end + timedelta(hours=1))
    window_df = df_1h[mask_1h]

    touch_idx = None
    for idx in window_df.index:
        row = df_1h.loc[idx]
        if row['low'] <= entry <= row['high']:
            touch_idx = idx
            result["entry_touched"] = True
            result["entry_touch_time"] = str(row['open_time'])
            print(f"  [touch] entry لُمس عند {row['open_time']} (low={row['low']}, high={row['high']})")
            break

    # إن لم تُلمس → آخر شمعة قبل تاريخ التوصية
    if touch_idx is None:
        print(f"  [no-touch] entry لم يُلمس في ±48h — نستخدم آخر شمعة قبل التوصية")
        rec_ms = int(rec_dt.timestamp() * 1000)
        before_df = df_1h[df_1h['open_time'] <= rec_dt]
        if len(before_df) == 0:
            result["error"] = "no_candle_before_rec_date"
            return result
        touch_idx = before_df.index[-1]

    # ─── 3. اقتطاع df حتى لحظة Entry ────────────────────────────────

    # نأخذ الشموع حتى touch_idx (شاملاً)
    df_snap_1h = df_1h.loc[:touch_idx].copy()

    # نحدد end_time لاقتطاع 4h و 1d
    touch_time = df_1h.loc[touch_idx, 'open_time']

    def snap_df(df, t):
        if df is None or len(df) == 0:
            return None
        return df[df['open_time'] <= t].copy()

    df_snap_4h = snap_df(df_4h, touch_time)
    df_snap_1d = snap_df(df_1d, touch_time)

    feats = {}

    # ─── 4. حساب الميزات ─────────────────────────────────────────────

    for tf_name, df_tf in [("1h", df_snap_1h), ("4h", df_snap_4h), ("1d", df_snap_1d)]:
        if df_tf is None or len(df_tf) < 20:
            continue

        close = df_tf['close'].values
        high  = df_tf['high'].values
        low   = df_tf['low'].values

        # ── 4a. RSI(14) ────────────────────────────────────────────
        rsi_arr = _rsi(close, 14)
        rsi_val = rsi_arr[-1] if not np.isnan(rsi_arr[-1]) else np.nan
        feats[f"rsi_{tf_name}"] = round(float(rsi_val), 2) if not np.isnan(rsi_val) else None
        feats[f"rsi_oversold_{tf_name}"] = bool(rsi_val < 30) if not np.isnan(rsi_val) else False

        # ── 4b. Stoch RSI ─────────────────────────────────────────
        stoch_rsi_arr = _stoch_rsi(rsi_arr, 14)
        stoch_val = stoch_rsi_arr[-1] if not np.isnan(stoch_rsi_arr[-1]) else np.nan
        feats[f"stoch_rsi_{tf_name}"] = round(float(stoch_val), 4) if not np.isnan(stoch_val) else None
        feats[f"stoch_oversold_{tf_name}"] = bool(stoch_val < 0.2) if not np.isnan(stoch_val) else False

        # ── 4c. Bollinger Lower Band ───────────────────────────────
        bb_upper, bb_mid, bb_lower = _bollinger(close, 20, 2.0)
        bb_lo = bb_lower[-1]
        if not np.isnan(bb_lo):
            feats[f"bb_lower_{tf_name}"] = round(float(bb_lo), 8)
            feats[f"near_bb_lower_{tf_name}"] = _near(entry, bb_lo)
        else:
            feats[f"bb_lower_{tf_name}"] = None
            feats[f"near_bb_lower_{tf_name}"] = False

        # ── 4d. EMA 20/50/100/200 ─────────────────────────────────
        for period in [20, 50, 100, 200]:
            if len(close) >= period:
                ema_arr = _ema(close, period)
                ema_val = ema_arr[-1]
                if not np.isnan(ema_val):
                    feats[f"ema{period}_{tf_name}"] = round(float(ema_val), 8)
                    feats[f"near_ema{period}_{tf_name}"] = _near(entry, ema_val, 0.01)
                else:
                    feats[f"ema{period}_{tf_name}"] = None
                    feats[f"near_ema{period}_{tf_name}"] = False
            else:
                feats[f"ema{period}_{tf_name}"] = None
                feats[f"near_ema{period}_{tf_name}"] = False

        # ── 4e. Swing-Low Distance ─────────────────────────────────
        for lb in [20, 50, 100]:
            if len(low) >= lb:
                window_low = low[-lb:]
                sw_lows_idx = _find_swing_lows(window_low, lookback=3)
                if sw_lows_idx:
                    nearest_sl = min(window_low[i] for i in sw_lows_idx)
                    dist_pct = (entry - nearest_sl) / nearest_sl if nearest_sl > 0 else np.nan
                    feats[f"swing_low_{lb}_dist_pct"] = round(float(dist_pct)*100, 2) if not np.isnan(dist_pct) else None
                    feats[f"near_swing_low_{lb}"] = _near(entry, nearest_sl, 0.005)
                else:
                    feats[f"swing_low_{lb}_dist_pct"] = None
                    feats[f"near_swing_low_{lb}"] = False

        # ── 4f. Fibonacci ──────────────────────────────────────────
        sw_lows_idx_all = _find_swing_lows(low, lookback=3)
        sw_highs_idx_all = _find_swing_highs(high, lookback=3)
        if sw_lows_idx_all and sw_highs_idx_all:
            # آخر impulse صاعد: آخر swing_low ثم swing_high بعده
            last_sl_idx = sw_lows_idx_all[-1]
            # ابحث عن swing high بعد last_sl_idx
            sw_highs_after = [i for i in sw_highs_idx_all if i > last_sl_idx]
            if sw_highs_after:
                last_sh_idx = sw_highs_after[-1]
                sw_low_price  = low[last_sl_idx]
                sw_high_price = high[last_sh_idx]
                fib = _fib_levels(sw_low_price, sw_high_price)
                feats[f"fib_swing_low_{tf_name}"]  = round(float(sw_low_price), 8)
                feats[f"fib_swing_high_{tf_name}"] = round(float(sw_high_price), 8)
                nearest_fib = None
                nearest_fib_dist = float('inf')
                for fib_name, fib_val in fib.items():
                    dist = abs(entry - fib_val) / fib_val if fib_val > 0 else float('inf')
                    if dist < nearest_fib_dist:
                        nearest_fib_dist = dist
                        nearest_fib = fib_name
                feats[f"nearest_fib_{tf_name}"] = nearest_fib
                feats[f"nearest_fib_dist_{tf_name}"] = round(nearest_fib_dist * 100, 3)
                feats[f"near_fib_{tf_name}"] = (nearest_fib_dist <= NEAR_PCT)
            else:
                feats[f"nearest_fib_{tf_name}"] = None
                feats[f"near_fib_{tf_name}"] = False
                feats[f"nearest_fib_dist_{tf_name}"] = None
        else:
            feats[f"nearest_fib_{tf_name}"] = None
            feats[f"near_fib_{tf_name}"] = False
            feats[f"nearest_fib_dist_{tf_name}"] = None

        # ── 4g. Support Touches (100 شمعة 1h) ─────────────────────
        if tf_name == "1h":
            lows  = df_tf['low'].values
            highs = df_tf['high'].values
            touches = sum(
                1 for i in range(len(df_tf))
                if _near(lows[i], entry, 0.005) or _near(highs[i], entry, 0.005)
            )
            feats["support_touches_100"] = int(touches)

        # ── 4h. N-day Range Position (30d) ────────────────────────
        if tf_name == "1d" and len(df_tf) >= 20:
            last30 = df_tf['close'].values[-30:]
            lo30   = last30.min()
            hi30   = last30.max()
            feats["range_pos_30d"] = round(float(_range_position(entry, lo30, hi30)), 4)

    # ── 4i. Psychological Round Number ────────────────────────────
    feats["round_number_dist_pct"] = round(_round_number_dist(entry) * 100, 3)
    feats["near_round_number"] = feats["round_number_dist_pct"] < 2.0  # ±2%

    # ── 4j. Pivot Points (daily, من شمعة يومية سابقة) ─────────────
    if df_snap_1d is not None and len(df_snap_1d) >= 2:
        prev = df_snap_1d.iloc[-2]
        pivots = _pivot_daily(float(prev['high']), float(prev['low']), float(prev['close']))
        feats["pivot_PP"] = round(pivots["PP"], 8)
        feats["pivot_S1"] = round(pivots["S1"], 8)
        feats["pivot_S2"] = round(pivots["S2"], 8)
        feats["near_pivot_PP"] = _near(entry, pivots["PP"])
        feats["near_pivot_S1"] = _near(entry, pivots["S1"])
        feats["near_pivot_S2"] = _near(entry, pivots["S2"])
        feats["near_any_pivot"] = any([feats["near_pivot_PP"], feats["near_pivot_S1"], feats["near_pivot_S2"]])
    else:
        feats["near_any_pivot"] = False

    result["features"] = feats
    return result

# ─── تجميع النتائج وحساب نسب التطابق ────────────────────────────────────────

BOOL_FEATURES = [
    # BB Lower
    "near_bb_lower_1h", "near_bb_lower_4h", "near_bb_lower_1d",
    # EMA near (±1%)
    "near_ema20_1h",  "near_ema50_1h",  "near_ema100_1h",  "near_ema200_1h",
    "near_ema20_4h",  "near_ema50_4h",  "near_ema100_4h",  "near_ema200_4h",
    "near_ema20_1d",  "near_ema50_1d",  "near_ema100_1d",  "near_ema200_1d",
    # RSI oversold
    "rsi_oversold_1h", "rsi_oversold_4h", "rsi_oversold_1d",
    # Stoch oversold
    "stoch_oversold_1h", "stoch_oversold_4h", "stoch_oversold_1d",
    # Fibonacci
    "near_fib_1h", "near_fib_4h", "near_fib_1d",
    # Swing Low
    "near_swing_low_20", "near_swing_low_50", "near_swing_low_100",
    # Pivot
    "near_any_pivot", "near_pivot_S1", "near_pivot_S2",
    # Round number
    "near_round_number",
]

def summarize_results(results: List[dict]) -> pd.DataFrame:
    n = len(results)
    rows = []
    for feat in BOOL_FEATURES:
        hits = 0
        valid = 0
        for r in results:
            if "error" in r:
                continue
            val = r["features"].get(feat)
            if val is not None:
                valid += 1
                if val:
                    hits += 1
        rate = hits / valid if valid > 0 else 0.0
        rows.append({
            "feature": feat,
            "hits": hits,
            "valid": valid,
            "rate_pct": round(rate * 100, 1)
        })
    df = pd.DataFrame(rows).sort_values("rate_pct", ascending=False).reset_index(drop=True)
    return df

def find_top_combos(results: List[dict], summary_df: pd.DataFrame, top_n: int = 5) -> List[dict]:
    """يجد أعلى تركيبتين من الميزات بنسبة تطابق مشترك."""
    valid_results = [r for r in results if "error" not in r]
    n = len(valid_results)
    top_feats = summary_df[summary_df["rate_pct"] >= 40]["feature"].tolist()[:15]

    combos = []
    for i in range(len(top_feats)):
        for j in range(i+1, len(top_feats)):
            f1, f2 = top_feats[i], top_feats[j]
            both = sum(
                1 for r in valid_results
                if r["features"].get(f1) and r["features"].get(f2)
            )
            both_rate = both / n * 100 if n > 0 else 0
            combos.append({"f1": f1, "f2": f2, "both": both, "n": n, "rate_pct": round(both_rate, 1)})

    combos.sort(key=lambda x: -x["rate_pct"])
    return combos[:top_n]

# ─── كتابة التقرير ──────────────────────────────────────────────────────────

def write_report(results: List[dict], summary_df: pd.DataFrame, combos: List[dict]):
    n_total  = len(results)
    n_valid  = sum(1 for r in results if "error" not in r)
    n_touch  = sum(1 for r in results if r.get("entry_touched"))

    lines = []
    lines.append("# تقرير هندسة عكسية — منهجية اختيار Entry")
    lines.append(f"\n**تاريخ التحليل:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**العينة:** {n_total} توصية | {n_valid} مكتملة | {n_touch} لمست Entry في ±48h\n")
    lines.append("---\n")

    # ── جدول الميزات ──
    lines.append("## 1. جدول الميزات مرتباً بنسبة التطابق\n")
    lines.append("| الميزة | التطابق | من | نسبة% | تقدير |")
    lines.append("|--------|---------|-----|-------|-------|")
    for _, row in summary_df.iterrows():
        rate = row["rate_pct"]
        if rate >= 70:
            grade = "قوية"
        elif rate >= 50:
            grade = "متوسطة"
        else:
            grade = "ضعيفة"
        lines.append(f"| {row['feature']} | {row['hits']} | {row['valid']} | {rate}% | {grade} |")

    lines.append("")

    # ── أعلى 3 بصمات منفردة ──
    lines.append("## 2. أعلى 3 بصمات منفردة\n")
    top3 = summary_df.head(3)
    for rank, (_, row) in enumerate(top3.iterrows(), 1):
        lines.append(f"### #{rank}: {row['feature']}")
        lines.append(f"- التطابق: {row['hits']}/{row['valid']} = **{row['rate_pct']}%**")
        rate = row["rate_pct"]
        if rate >= 70:
            lines.append(f"- الحكم: **بصمة قوية** (≥70%)")
        elif rate >= 50:
            lines.append(f"- الحكم: بصمة متوسطة (50-70%)")
        else:
            lines.append(f"- الحكم: لا بصمة (<50%)")
        lines.append("")

    # ── أعلى 3 تركيبات ──
    lines.append("## 3. أعلى 3 تركيبات (ميزتان معاً)\n")
    lines.append("| الترتيب | الميزة 1 | الميزة 2 | التطابق المشترك | النسبة% |")
    lines.append("|---------|---------|---------|-----------------|---------|")
    for rank, combo in enumerate(combos[:3], 1):
        lines.append(f"| #{rank} | {combo['f1']} | {combo['f2']} | {combo['both']}/{combo['n']} | {combo['rate_pct']}% |")
    lines.append("")

    # ── تفاصيل كل توصية ──
    lines.append("## 4. تفاصيل الـ12 توصية\n")
    detail_feats = [
        "rsi_1h", "rsi_4h", "rsi_1d",
        "stoch_rsi_1h", "stoch_rsi_4h",
        "near_bb_lower_1h", "near_bb_lower_4h", "near_bb_lower_1d",
        "near_fib_1h", "near_fib_4h", "near_fib_1d",
        "near_ema50_1h", "near_ema100_1h", "near_ema200_1h",
        "near_swing_low_20", "near_swing_low_50",
        "near_any_pivot", "near_round_number",
        "support_touches_100", "range_pos_30d",
    ]

    header = "| Symbol | Entry | Touch |" + " | ".join(detail_feats) + " |"
    sep    = "|--------|-------|-------|" + "|".join(["---"]*len(detail_feats)) + "|"
    lines.append(header)
    lines.append(sep)

    for r in results:
        if "error" in r:
            lines.append(f"| {r['symbol']} | {r['entry']} | ERROR: {r['error']} |" + " | ".join(["-"]*len(detail_feats)) + " |")
            continue
        touch_str = "Y" if r.get("entry_touched") else "N"
        vals = []
        for f in detail_feats:
            v = r["features"].get(f)
            if isinstance(v, bool):
                vals.append("Y" if v else "N")
            elif v is None:
                vals.append("-")
            elif isinstance(v, float):
                vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        lines.append(f"| {r['symbol']} | {r['entry']} | {touch_str} | " + " | ".join(vals) + " |")

    lines.append("")

    # ── الاستنتاج النهائي ──
    lines.append("## 5. الاستنتاج النهائي\n")

    # حدد أقوى الأنماط
    strong = summary_df[summary_df["rate_pct"] >= 70]
    medium = summary_df[(summary_df["rate_pct"] >= 50) & (summary_df["rate_pct"] < 70)]
    top_combo_rate = combos[0]["rate_pct"] if combos else 0

    if len(strong) > 0:
        top_feat = strong.iloc[0]["feature"]
        top_rate = strong.iloc[0]["rate_pct"]
        lines.append(f"**البصمة الأقوى:** `{top_feat}` ({top_rate}% تطابق).")
        lines.append(f"وُجد {len(strong)} مؤشر(ات) قوية (≥70%) و{len(medium)} متوسطة.")

        lines.append("\n**المنهجية الأرجح:**")
        strong_names = list(strong["feature"])
        if any("bb_lower" in s for s in strong_names):
            lines.append("- **Bollinger Lower Band**: دخول عند الحد الأسفل للـ BB — مستوى oversold كلاسيكي")
        if any("rsi_oversold" in s for s in strong_names):
            lines.append("- **RSI Oversold (<30)**: المصدر ينتظر RSI تحت 30 كشرط دخول")
        if any("ema" in s for s in strong_names):
            ema_feats = [s for s in strong_names if "ema" in s]
            lines.append(f"- **EMA Support**: الدخول عند دعم EMA — {', '.join(ema_feats)}")
        if any("fib" in s for s in strong_names):
            lines.append("- **Fibonacci Retracement**: الدخول عند مستوى تصحيح فيبوناتشي")
        if any("pivot" in s for s in strong_names):
            lines.append("- **Pivot Points**: الدخول قرب مستويات pivot (S1/S2)")
        if any("swing_low" in s for s in strong_names):
            lines.append("- **Swing Low**: الدخول عند أقرب قاع تأرجح")

        lines.append("\n**درجة الثقة:** متوسطة-عالية (بصمات قوية ≥70% على n=12)")
    elif len(medium) > 0:
        lines.append(f"**لا بصمة قوية (≥70%).** أقوى مؤشر: {medium.iloc[0]['feature']} ({medium.iloc[0]['rate_pct']}%).")
        lines.append(f"أقوى تركيبة: {combos[0]['f1']} + {combos[0]['f2']} ({top_combo_rate}%).")
        if top_combo_rate >= 80:
            lines.append("\n**المنهجية الأرجح:** تركيبة مؤشرين متوسطَي الفردية لكن قويان معاً.")
            lines.append("\n**درجة الثقة:** متوسطة (تركيبة ≥80%، n=12)")
        else:
            lines.append("\n**لا نمط آلي واضح، الأرجح قرار بشري/مؤشر مركّب غير قياسي.**")
            lines.append("\n**درجة الثقة:** منخفضة")
    else:
        lines.append("**لا نمط آلي واضح، الأرجح قرار بشري/مؤشر مركّب غير قياسي.**")
        if combos:
            lines.append(f"\nأقوى تركيبة: {combos[0]['f1']} + {combos[0]['f2']} = {top_combo_rate}% (دون العتبة 80%).")
        lines.append("\n**درجة الثقة:** منخفضة")

    # قابلية المحاكاة
    lines.append("\n**هل المنهجية قابلة للمحاكاة برمجياً؟**")
    if len(strong) >= 2 or top_combo_rate >= 80:
        lines.append("نعم — يمكن إضافة فلتر `near_bb_lower` أو `near_ema_key` لماسح الإشارات بعد رفع التجميد.")
    elif len(strong) == 1:
        lines.append("جزئياً — البصمة الواحدة القوية قابلة للمحاكاة لكنها غير كافية وحدها (تحتاج مؤشراً مرافقاً).")
    else:
        lines.append("لا — المنهجية على الأرجح بشرية أو تعتمد مؤشرات مركّبة خاصة غير قياسية.")

    lines.append("\n---\n*تم توليد هذا التقرير تلقائياً بواسطة `research/entry_reverse_engineer.py`*")

    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"\n[done] التقرير محفوظ: {OUTPUT_MD}")

# ─── نقطة الدخول ────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("بحث: هندسة عكسية لمنهجية Entry الخارجية")
    print(f"العينة: {len(SIGNALS)} توصية")
    print("=" * 60)

    results = []
    for sig in SIGNALS:
        r = analyze_signal(sig)
        results.append(r)
        # حفظ تدريجي (تعافٍ من انقطاع)
        with open('/app/research/entry_re_partial.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')

    print("\n=== ملخص جلب البيانات ===")
    for r in results:
        status = "OK" if "error" not in r else f"ERROR: {r.get('error')}"
        touched = "لُمست" if r.get("entry_touched") else "لم تُلمس"
        print(f"  {r['symbol']}: {status} | entry {touched}")

    print("\n=== حساب النسب ===")
    summary_df = summarize_results(results)
    print(summary_df.head(15).to_string(index=False))

    print("\n=== أعلى التركيبات ===")
    combos = find_top_combos(results, summary_df)
    for c in combos[:5]:
        print(f"  {c['f1']} + {c['f2']}: {c['both']}/{c['n']} = {c['rate_pct']}%")

    write_report(results, summary_df, combos)

    # حفظ النتائج الخام
    with open('/app/research/entry_re_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"[done] النتائج الخام: /app/research/entry_re_results.json")

if __name__ == "__main__":
    main()
