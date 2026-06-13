#!/usr/bin/env python3
"""
مسح اكتشاف حافة شامل — بيانات نظيفة من السوق
=================================================
التاريخ: 2026-05-22
الهدف: اختبار 3 أهداف × ~40 ميزة على ≥100,000 نقطة عشوائية
       مستقل تماماً عن سجلّ صفقات البوت.

قواعد صارمة:
  - بحث فقط — التجميد ساري، لا تعديل على الكود الحيّ.
  - بلا تسرّب مستقبلي: كل ميزة تُحسب من klines[0..t] فقط.
  - بلا حزم جديدة (numpy/pandas/requests موجودة).
  - معالجة متدفّقة عملة-عملة.
  - cache klines على القرص.

الأهداف:
  TARGET_A_long: هل تحرّك السعر +3% قبل −3% خلال 48 شمعة (48h في إطار 1h)؟
  TARGET_B_vol : هل |العائد| > 5% خلال 48 شمعة؟ (تذبذب، اتجاه-محايد)
  TARGET_C_rel : هل عائد 48h للعملة > متوسط عيّنة السوق في نفس النافذة؟

الإطار: 1h أساسي، 1d للسياق (BTC trend).

الاختبار:
  - IC (Spearman) + permutation p-value
  - Walk-Forward: نصف أول (train) / نصف ثانٍ (OOS)
  - FDR Benjamini-Hochberg عبر (ميزة × هدف) معاً
  - حجم أثر Cohen d
  - expectancy بعد رسوم 0.3% لأعلى decile وأدنى decile

ميزة «ناجية» = q<0.05 AND (|d|>0.1 OR |IC_OOS|>0.05) AND WF_same_sign
"""

import os, sys, random, pickle, time, json, gc, math
import requests
import numpy as np
from datetime import datetime, timezone

# ================================================================
# مسارات
# ================================================================
BASE_DIR    = "/home/tradmin/trading-signal-bot/analyzer/research"
CACHE_DIR   = os.path.join(BASE_DIR, "cache", "edge_discovery_1h")
CACHE_1D    = os.path.join(BASE_DIR, "cache", "edge_discovery_1d")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
SYMBOL_CACHE = os.path.join(BASE_DIR, "cache", "edge_discovery_symbols.pkl")

os.makedirs(CACHE_DIR,   exist_ok=True)
os.makedirs(CACHE_1D,    exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

DATE_STAMP  = "2026_05_22_edge_discovery"
OUTPUT_JSON = os.path.join(RESULTS_DIR, f"{DATE_STAMP}.json")
OUTPUT_MD   = os.path.join(RESULTS_DIR, f"{DATE_STAMP}.md")

# ================================================================
# ثوابت
# ================================================================
SEED             = 20260522
BINANCE_BASE     = "https://api.binance.com"
INTERVAL_1H      = "1h"
INTERVAL_1D      = "1d"
INTERVAL_MS_1H   = 3_600_000
INTERVAL_MS_1D   = 86_400_000
DAYS_BACK        = 180
FWD_BARS         = 48           # 48h باستخدام شموع 1h
FEE              = 0.003        # 0.3% round-trip
TARGET_A_THRESH  = 0.03         # +3% / -3%
TARGET_B_THRESH  = 0.05         # |ret| > 5%
MIN_CANDLES      = FWD_BARS + 200  # هامش كافٍ للمؤشرات
POINTS_PER_SYM   = 1250         # نقاط عشوائية/رمز → ~100k مع 80 رمزاً
REQUEST_SLEEP    = 0.25
MEM_LIMIT_BYTES  = 1_600_000_000
BOOTSTRAP_N      = 500          # عدد permutations
WF_SPLIT         = 0.5          # 50/50

TARGET_LARGE = 30
TARGET_MID   = 30
TARGET_SMALL = 20

# ================================================================
# أدوات مساعدة (بلا scipy)
# ================================================================

def check_mem():
    """يتحقق من الذاكرة ويعيد True إن اقتربنا من الحد."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb * 1024 > MEM_LIMIT_BYTES
    except Exception:
        pass
    return False


def spearman_ic(x, y):
    """Spearman Information Coefficient بلا scipy."""
    if len(x) < 10:
        return np.nan
    rx = _rank_arr(x)
    ry = _rank_arr(y)
    n  = len(rx)
    # حساب بيرسون على الرتب
    mx, my = np.mean(rx), np.mean(ry)
    num    = np.sum((rx - mx) * (ry - my))
    den    = np.sqrt(np.sum((rx - mx)**2) * np.sum((ry - my)**2))
    if den == 0:
        return 0.0
    return num / den


def _rank_arr(arr):
    """رتّب المصفوفة (average rank)."""
    arr  = np.asarray(arr, dtype=float)
    n    = len(arr)
    idx  = np.argsort(arr, kind='mergesort')
    rnk  = np.empty(n, dtype=float)
    i    = 0
    while i < n:
        j = i + 1
        while j < n and arr[idx[j]] == arr[idx[i]]:
            j += 1
        r = (i + j - 1) / 2.0  # average rank
        for k in range(i, j):
            rnk[idx[k]] = r
        i = j
    return rnk


def permutation_pvalue(ic_obs, x, y, n_perm=BOOTSTRAP_N, seed=42):
    """p-value بـ permutation test."""
    rng = np.random.default_rng(seed)
    if len(x) < 10:
        return 1.0
    count = 0
    for _ in range(n_perm):
        y_shuf = rng.permutation(y)
        ic_s   = spearman_ic(x, y_shuf)
        if abs(ic_s) >= abs(ic_obs):
            count += 1
    return (count + 1) / (n_perm + 1)


def cohen_d(x, y_label):
    """Cohen d بين top_decile و bottom_decile من x حسب y_label."""
    n   = len(y_label)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    top = y_label[idx[-cut:]]
    bot = y_label[idx[:cut]]
    if len(top) < 3 or len(bot) < 3:
        return np.nan
    mt, mb = np.mean(top), np.mean(bot)
    st, sb = np.std(top, ddof=1), np.std(bot, ddof=1)
    sp     = np.sqrt(((len(top)-1)*st**2 + (len(bot)-1)*sb**2)
                     / (len(top)+len(bot)-2))
    if sp == 0:
        return 0.0
    return (mt - mb) / sp


def expectancy_decile(x, y_ret, fee=FEE):
    """Expectancy بعد رسوم لأعلى decile وأدنى decile."""
    n   = len(y_ret)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    top_ret = y_ret[idx[-cut:]]
    bot_ret = y_ret[idx[:cut]]
    def exp_with_fee(ret_arr):
        adj = ret_arr - fee
        wr  = np.mean(adj > 0)
        avg_w = np.mean(adj[adj > 0]) if np.any(adj > 0) else 0.0
        avg_l = np.mean(adj[adj <= 0]) if np.any(adj <= 0) else 0.0
        return wr * avg_w + (1 - wr) * avg_l
    return float(exp_with_fee(top_ret)), float(exp_with_fee(bot_ret))


def benjamini_hochberg(pvalues, q=0.05):
    """BH FDR correction. يعيد قائمة q-values."""
    n   = len(pvalues)
    idx = np.argsort(pvalues)
    pv  = np.array(pvalues)[idx]
    qv  = np.empty(n)
    for i in range(n):
        qv[i] = pv[i] * n / (i + 1)
    # enforce monotonicity من الآخر
    for i in range(n - 2, -1, -1):
        if qv[i] > qv[i + 1]:
            qv[i] = qv[i + 1]
    # إعادة الترتيب الأصلي
    result = np.empty(n)
    result[idx] = qv
    return result.tolist()

# ================================================================
# جلب klines من Binance
# ================================================================

def fetch_klines(symbol, interval, days_back=DAYS_BACK):
    """يجلب كل الشموع مع cache على القرص (pickle)."""
    cache_dir = CACHE_DIR if interval == INTERVAL_1H else CACHE_1D
    cache_path = os.path.join(cache_dir, f"{symbol}_{interval}.pkl")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    now_ms    = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms  = now_ms - days_back * 86_400_000
    interval_ms = INTERVAL_MS_1H if interval == INTERVAL_1H else INTERVAL_MS_1D
    limit     = 1000
    all_klines = []
    cur        = start_ms

    while cur < now_ms:
        url    = f"{BINANCE_BASE}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval,
                  "startTime": cur, "limit": limit}
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            all_klines.extend(data)
            cur = data[-1][0] + interval_ms
            time.sleep(REQUEST_SLEEP)
        except Exception as e:
            print(f"  [WARN] {symbol} {interval}: {e}")
            time.sleep(5)
            break

    if all_klines:
        with open(cache_path, "wb") as f:
            pickle.dump(all_klines, f)
    return all_klines


def klines_to_arrays(raw):
    """يحوّل raw klines إلى arrays numpy."""
    raw = sorted(raw, key=lambda x: x[0])
    ts    = np.array([r[0] for r in raw], dtype=np.int64)
    opens  = np.array([float(r[1]) for r in raw])
    highs  = np.array([float(r[2]) for r in raw])
    lows   = np.array([float(r[3]) for r in raw])
    closes = np.array([float(r[4]) for r in raw])
    vols   = np.array([float(r[5]) for r in raw])
    return ts, opens, highs, lows, closes, vols

# ================================================================
# اختيار الرموز
# ================================================================

def get_symbols():
    """يختار 80 رمزاً USDT spot (large+mid+small)."""
    if os.path.exists(SYMBOL_CACHE):
        with open(SYMBOL_CACHE, "rb") as f:
            syms = pickle.load(f)
        print(f"[INFO] رموز من cache: {len(syms)}")
        return syms

    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=20)
        data = resp.json()
    except Exception as e:
        print(f"[ERROR] فشل جلب الرموز: {e}")
        sys.exit(1)

    usdt = [d for d in data
            if d["symbol"].endswith("USDT")
            and not any(x in d["symbol"] for x in ["DOWN", "UP", "BEAR", "BULL", "3L", "3S"])
            and float(d.get("quoteVolume", 0)) > 0]

    usdt.sort(key=lambda d: float(d.get("quoteVolume", 0)), reverse=True)

    rng = random.Random(SEED)
    large = [d["symbol"] for d in usdt[:60]][:TARGET_LARGE]
    large = rng.sample(large, TARGET_LARGE) if len(large) >= TARGET_LARGE else large

    mid_pool = [d["symbol"] for d in usdt[60:300]]
    mid = rng.sample(mid_pool, min(TARGET_MID, len(mid_pool)))

    small_pool = [d["symbol"] for d in usdt[300:800]]
    small = rng.sample(small_pool, min(TARGET_SMALL, len(small_pool)))

    syms = list(dict.fromkeys(large + mid + small))
    with open(SYMBOL_CACHE, "wb") as f:
        pickle.dump(syms, f)
    print(f"[INFO] اختار {len(syms)} رمزاً")
    return syms

# ================================================================
# حساب المؤشرات (بلا تسرّب مستقبلي)
# ================================================================

def compute_features_at(closes, highs, lows, vols, t):
    """
    يحسب كل الميزات عند نقطة t باستخدام closes[0..t] فقط.
    يعيد dict أو None إذا البيانات غير كافية.
    يُمرّر t كعدد صحيح (index في المصفوفة).
    """
    if t < 200:
        return None

    c  = closes[:t+1]
    h  = highs[:t+1]
    l  = lows[:t+1]
    v  = vols[:t+1]
    n  = len(c)

    feats = {}

    # --- RSI (14) ---
    try:
        rsi = _rsi(c, 14)
        feats["rsi14"] = float(rsi)
    except Exception:
        feats["rsi14"] = np.nan

    # --- RSI (7) ---
    try:
        rsi7 = _rsi(c, 7)
        feats["rsi7"] = float(rsi7)
    except Exception:
        feats["rsi7"] = np.nan

    # --- Bollinger position ---
    try:
        bb_pos = _bb_position(c, 20, 2.0)
        feats["bb_pos"] = float(bb_pos)  # 0=أسفل BB, 1=أعلى BB
    except Exception:
        feats["bb_pos"] = np.nan

    # --- Stochastic RSI ---
    try:
        stoch_rsi = _stoch_rsi(c, 14, 3)
        feats["stoch_rsi"] = float(stoch_rsi)
    except Exception:
        feats["stoch_rsi"] = np.nan

    # --- MACD histogram ---
    try:
        macd_h = _macd_histogram(c, 12, 26, 9)
        feats["macd_hist"] = float(macd_h)
    except Exception:
        feats["macd_hist"] = np.nan

    # --- ADX (14) ---
    try:
        adx = _adx(h, l, c, 14)
        feats["adx14"] = float(adx)
    except Exception:
        feats["adx14"] = np.nan

    # --- ATR% (14) ---
    try:
        atr_pct = _atr_pct(h, l, c, 14)
        feats["atr_pct"] = float(atr_pct)
    except Exception:
        feats["atr_pct"] = np.nan

    # --- Momentum (return last N candles) ---
    for N in [6, 12, 24]:
        if n > N:
            feats[f"mom{N}"] = float((c[-1] / c[-1-N] - 1.0))
        else:
            feats[f"mom{N}"] = np.nan

    # --- Volume ratio (vol / ma_vol_20) ---
    try:
        if n >= 20:
            ma_vol = np.mean(v[-20:])
            feats["vol_ratio"] = float(v[-1] / ma_vol) if ma_vol > 0 else np.nan
        else:
            feats["vol_ratio"] = np.nan
    except Exception:
        feats["vol_ratio"] = np.nan

    # --- Volume z-score (20-bar) ---
    try:
        if n >= 20:
            mu_v  = np.mean(v[-20:])
            std_v = np.std(v[-20:], ddof=1)
            feats["vol_zscore"] = float((v[-1] - mu_v) / std_v) if std_v > 0 else 0.0
        else:
            feats["vol_zscore"] = np.nan
    except Exception:
        feats["vol_zscore"] = np.nan

    # --- ATR percentile (52-bar rolling) ---
    try:
        atr_arr = _atr_array(h, l, c, 14)
        if len(atr_arr) >= 52:
            window = atr_arr[-52:]
            cur_atr = atr_arr[-1]
            feats["atr_pct52"] = float(np.sum(window <= cur_atr) / len(window))
        else:
            feats["atr_pct52"] = np.nan
    except Exception:
        feats["atr_pct52"] = np.nan

    # --- Realized volatility 24h ---
    try:
        if n >= 24:
            rets = np.log(c[-24:] / c[-25:-1]) if n >= 25 else np.diff(np.log(c[-25:]))
            feats["rvol24"] = float(np.std(rets, ddof=1) * np.sqrt(24))
        else:
            feats["rvol24"] = np.nan
    except Exception:
        feats["rvol24"] = np.nan

    # --- Hour of day (UTC) ---
    # لا نملك timestamp هنا — نستبدله بـ feature dummy 0..23 سنضيفه خارجاً

    # --- Consecutive down candles ---
    try:
        cnt = 0
        for i in range(n-1, max(n-20, 0), -1):
            if c[i] < c[i-1]:
                cnt += 1
            else:
                break
        feats["consec_down"] = float(cnt)
    except Exception:
        feats["consec_down"] = np.nan

    # --- Distance from 30d high/low ---
    try:
        w30 = min(n, 720)  # 720h = 30d
        hi30 = np.max(h[-w30:])
        lo30 = np.min(l[-w30:])
        feats["dist_hi30"] = float((c[-1] - hi30) / hi30) if hi30 > 0 else np.nan
        feats["dist_lo30"] = float((c[-1] - lo30) / lo30) if lo30 > 0 else np.nan
    except Exception:
        feats["dist_hi30"] = np.nan
        feats["dist_lo30"] = np.nan

    # --- Price percentile in 30d range ---
    try:
        w30 = min(n, 720)
        hi30 = np.max(h[-w30:])
        lo30 = np.min(l[-w30:])
        rng30 = hi30 - lo30
        feats["price_pct30"] = float((c[-1] - lo30) / rng30) if rng30 > 0 else 0.5
    except Exception:
        feats["price_pct30"] = np.nan

    # --- RSI z-score (rolling 50) ---
    try:
        rsi_arr = _rsi_array(c, 14)
        if len(rsi_arr) >= 50:
            window = rsi_arr[-50:]
            mu_r   = np.mean(window)
            std_r  = np.std(window, ddof=1)
            feats["rsi_zscore"] = float((rsi_arr[-1] - mu_r) / std_r) if std_r > 0 else 0.0
        else:
            feats["rsi_zscore"] = np.nan
    except Exception:
        feats["rsi_zscore"] = np.nan

    # --- BB position z-score (rolling 50) ---
    try:
        bb_arr = _bb_position_array(c, 20, 2.0)
        if len(bb_arr) >= 50:
            window = bb_arr[-50:]
            mu_bb  = np.mean(window)
            std_bb = np.std(window, ddof=1)
            feats["bb_zscore"] = float((bb_arr[-1] - mu_bb) / std_bb) if std_bb > 0 else 0.0
        else:
            feats["bb_zscore"] = np.nan
    except Exception:
        feats["bb_zscore"] = np.nan

    # --- MACD histogram percentile (rolling 50) ---
    try:
        macd_arr = _macd_hist_array(c, 12, 26, 9)
        if len(macd_arr) >= 50:
            window = macd_arr[-50:]
            cur_m  = macd_arr[-1]
            feats["macd_pct50"] = float(np.sum(window <= cur_m) / len(window))
        else:
            feats["macd_pct50"] = np.nan
    except Exception:
        feats["macd_pct50"] = np.nan

    # --- Momentum percentile (mom6) rolling 50 ---
    try:
        if n >= 57:  # 50 + 6 + margin
            mom_arr = np.array([(c[i] / c[i-6] - 1.0) for i in range(6, n)])
            if len(mom_arr) >= 50:
                window = mom_arr[-50:]
                cur_m  = mom_arr[-1]
                feats["mom6_pct50"] = float(np.sum(window <= cur_m) / len(window))
            else:
                feats["mom6_pct50"] = np.nan
        else:
            feats["mom6_pct50"] = np.nan
    except Exception:
        feats["mom6_pct50"] = np.nan

    return feats


# ================================================================
# دوال المؤشرات الداخلية
# ================================================================

def _rsi_array(c, period=14):
    """RSI كامل للسلسلة."""
    n = len(c)
    if n < period + 1:
        return np.array([])
    gains = np.maximum(np.diff(c), 0)
    losses = np.maximum(-np.diff(c), 0)
    rsi_vals = []
    avg_g = np.mean(gains[:period])
    avg_l = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_g / avg_l
            rsi_vals.append(100.0 - 100.0 / (1.0 + rs))
    return np.array(rsi_vals)

def _rsi(c, period=14):
    arr = _rsi_array(c, period)
    return arr[-1] if len(arr) > 0 else np.nan

def _ema(arr, period):
    """EMA."""
    if len(arr) < period:
        return np.nan
    k    = 2.0 / (period + 1.0)
    ema  = np.mean(arr[:period])
    for v in arr[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def _ema_array(arr, period):
    """EMA كاملة."""
    if len(arr) < period:
        return np.array([])
    k   = 2.0 / (period + 1.0)
    out = [np.mean(arr[:period])]
    for v in arr[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return np.array(out)

def _bb_position_array(c, period=20, std_mult=2.0):
    """Bollinger position (0..1) كاملة."""
    n = len(c)
    if n < period:
        return np.array([])
    out = []
    for i in range(period - 1, n):
        window = c[i-period+1:i+1]
        mu     = np.mean(window)
        sigma  = np.std(window, ddof=1)
        ub     = mu + std_mult * sigma
        lb     = mu - std_mult * sigma
        rng    = ub - lb
        if rng == 0:
            out.append(0.5)
        else:
            out.append(float(np.clip((c[i] - lb) / rng, 0.0, 1.0)))
    return np.array(out)

def _bb_position(c, period=20, std_mult=2.0):
    arr = _bb_position_array(c, period, std_mult)
    return arr[-1] if len(arr) > 0 else np.nan

def _stoch_rsi(c, period=14, smooth=3):
    """Stochastic RSI."""
    rsi_arr = _rsi_array(c, period)
    if len(rsi_arr) < period:
        return np.nan
    window = rsi_arr[-period:]
    lo     = np.min(window)
    hi     = np.max(window)
    if hi == lo:
        return 0.5
    raw    = (rsi_arr[-1] - lo) / (hi - lo)
    # تنعيم بسيط
    if len(rsi_arr) >= period + smooth - 1:
        sr_arr = []
        for i in range(period - 1, len(rsi_arr)):
            w = rsi_arr[i-period+1:i+1]
            lo2 = np.min(w); hi2 = np.max(w)
            sr_arr.append((rsi_arr[i] - lo2) / (hi2 - lo2 + 1e-10))
        if len(sr_arr) >= smooth:
            return float(np.mean(sr_arr[-smooth:]))
    return float(raw)

def _macd_hist_array(c, fast=12, slow=26, signal=9):
    """MACD histogram كاملة."""
    n = len(c)
    if n < slow + signal:
        return np.array([])
    ema_f = _ema_array(c, fast)
    ema_s = _ema_array(c, slow)
    # اجعلهما بنفس الطول
    diff_len = min(len(ema_f), len(ema_s))
    macd_line = ema_f[-diff_len:] - ema_s[-diff_len:]
    if len(macd_line) < signal:
        return np.array([])
    sig_line = _ema_array(macd_line, signal)
    hist     = macd_line[len(macd_line) - len(sig_line):] - sig_line
    return hist

def _macd_histogram(c, fast=12, slow=26, signal=9):
    arr = _macd_hist_array(c, fast, slow, signal)
    return arr[-1] if len(arr) > 0 else np.nan

def _atr_array(h, l, c, period=14):
    """ATR كاملة."""
    n = len(c)
    if n < period + 1:
        return np.array([])
    tr_arr = []
    for i in range(1, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        tr_arr.append(tr)
    tr_arr = np.array(tr_arr)
    if len(tr_arr) < period:
        return np.array([])
    atr = [np.mean(tr_arr[:period])]
    for tr in tr_arr[period:]:
        atr.append((atr[-1] * (period - 1) + tr) / period)
    return np.array(atr)

def _atr_pct(h, l, c, period=14):
    arr = _atr_array(h, l, c, period)
    if len(arr) == 0:
        return np.nan
    return float(arr[-1] / c[-1]) if c[-1] > 0 else np.nan

def _adx(h, l, c, period=14):
    """ADX مبسّط."""
    n = len(c)
    if n < period * 2 + 1:
        return np.nan
    try:
        dm_pos = np.maximum(np.diff(h), 0)
        dm_neg = np.maximum(-np.diff(l), 0)
        # fix: أيهما أكبر
        for i in range(len(dm_pos)):
            if dm_pos[i] > dm_neg[i]:
                dm_neg[i] = 0
            elif dm_neg[i] > dm_pos[i]:
                dm_pos[i] = 0
            else:
                dm_pos[i] = dm_neg[i] = 0

        tr_arr = np.array([
            max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
            for i in range(1, n)
        ])
        atr_sum = np.sum(tr_arr[:period])
        dmp_sum = np.sum(dm_pos[:period])
        dmn_sum = np.sum(dm_neg[:period])
        dx_arr  = []
        for i in range(period, len(tr_arr)):
            atr_sum = atr_sum - atr_sum / period + tr_arr[i]
            dmp_sum = dmp_sum - dmp_sum / period + dm_pos[i]
            dmn_sum = dmn_sum - dmn_sum / period + dm_neg[i]
            dip = 100 * dmp_sum / atr_sum if atr_sum > 0 else 0
            din = 100 * dmn_sum / atr_sum if atr_sum > 0 else 0
            dx  = 100 * abs(dip - din) / (dip + din) if (dip + din) > 0 else 0
            dx_arr.append(dx)
        if len(dx_arr) < period:
            return np.nan
        return float(np.mean(dx_arr[-period:]))
    except Exception:
        return np.nan

# ================================================================
# حساب الأهداف
# ================================================================

def compute_targets(closes, highs, lows, t, market_48h_ret=None):
    """
    يحسب الأهداف الثلاثة عند نقطة t.
    t: index في المصفوفة (الشمعة الحالية)
    market_48h_ret: متوسط عائد السوق خلال 48h من t (للهدف C)
    يعيد None إن لم تكتمل النافذة.
    """
    if t + FWD_BARS >= len(closes):
        return None

    entry = closes[t]
    if entry <= 0:
        return None

    # --- TARGET_A: +3% قبل -3% ---
    hit_up   = False
    hit_down = False
    for i in range(t+1, t+FWD_BARS+1):
        # نتحقق من High للصعود و Low للهبوط (داخل الشمعة)
        if highs[i] / entry - 1 >= TARGET_A_THRESH:
            hit_up = True
            break
        if 1 - lows[i] / entry >= TARGET_A_THRESH:
            hit_down = True
            break
    target_a = 1 if hit_up else 0  # لم يضرب -3% قبل +3%

    # --- TARGET_B: |عائد 48h| > 5% ---
    ret_48h  = closes[t + FWD_BARS] / entry - 1.0
    target_b = 1 if abs(ret_48h) > TARGET_B_THRESH else 0

    # --- TARGET_C: عائد أعلى من السوق ---
    if market_48h_ret is not None:
        target_c = 1 if ret_48h > market_48h_ret else 0
    else:
        target_c = None

    return {"target_a": target_a, "target_b": target_b, "target_c": target_c,
            "ret_48h": ret_48h}

# ================================================================
# معالجة رمز واحد
# ================================================================

def process_symbol(symbol, rng_obj, market_ret_by_ts=None):
    """
    يعالج رمزاً واحداً:
    - يجلب klines
    - يختار نقاط عشوائية
    - يحسب الميزات والأهداف لكل نقطة
    - يعيد list من dicts
    """
    raw_1h = fetch_klines(symbol, INTERVAL_1H)
    if len(raw_1h) < MIN_CANDLES + FWD_BARS:
        print(f"  [SKIP] {symbol}: {len(raw_1h)} شمعة < {MIN_CANDLES + FWD_BARS}")
        return []

    ts, opens, highs, lows, closes, vols = klines_to_arrays(raw_1h)

    # النافذة الصالحة: [200, len - FWD_BARS - 1]
    valid_start = 200
    valid_end   = len(closes) - FWD_BARS - 1
    if valid_end <= valid_start:
        return []

    valid_indices = list(range(valid_start, valid_end))
    n_pts = min(POINTS_PER_SYM, len(valid_indices))
    sampled_idx = rng_obj.sample(valid_indices, n_pts)

    rows = []
    for t in sampled_idx:
        feats = compute_features_at(closes, highs, lows, vols, t)
        if feats is None:
            continue
        if any(np.isnan(v) for v in feats.values()):
            # لا نتجاهل كلياً — بعض الميزات قد تكون NaN
            pass

        # ساعة اليوم UTC من timestamp
        ts_sec = ts[t] / 1000.0
        hour_utc = int((ts_sec % 86400) // 3600)
        feats["hour_utc"] = float(hour_utc)

        # السوق 48h
        mkt_ret = None
        if market_ret_by_ts is not None:
            ts_key = ts[t]
            mkt_ret = market_ret_by_ts.get(ts_key)

        tgts = compute_targets(closes, highs, lows, t, mkt_ret)
        if tgts is None:
            continue

        row = {"symbol": symbol, "t": t, "ts": int(ts[t]), **feats, **tgts}
        rows.append(row)

    print(f"  [OK] {symbol}: {len(rows)} نقطة")
    del ts, opens, highs, lows, closes, vols, raw_1h
    gc.collect()
    return rows

# ================================================================
# حساب متوسط عائد السوق (للهدف C)
# ================================================================

def build_market_returns(symbols, sample_frac=0.3):
    """
    يحسب متوسط عائد السوق لكل timestamp.
    يستخدم عيّنة من الرموز (30%) لتوفير الذاكرة.
    يستبعد كل عملة من حسابها الخاص.
    يعيد dict: {ts_open -> median_48h_ret}
    """
    rng = random.Random(SEED + 1)
    sub = rng.sample(symbols, max(1, int(len(symbols) * sample_frac)))
    # ts → list of 48h returns
    ts_rets = {}
    for sym in sub:
        raw = fetch_klines(sym, INTERVAL_1H)
        if len(raw) < MIN_CANDLES + FWD_BARS:
            continue
        ts_arr, _, _, _, c_arr, _ = klines_to_arrays(raw)
        valid_end = len(c_arr) - FWD_BARS - 1
        for t in range(200, valid_end):
            entry = c_arr[t]
            if entry <= 0:
                continue
            ret = c_arr[t + FWD_BARS] / entry - 1.0
            key = int(ts_arr[t])
            if key not in ts_rets:
                ts_rets[key] = []
            ts_rets[key].append(ret)
        del raw, ts_arr, c_arr
        gc.collect()

    # نأخذ الوسيط
    market_ret = {k: float(np.median(v)) for k, v in ts_rets.items() if len(v) >= 3}
    print(f"[INFO] market_ret built: {len(market_ret)} timestamps")
    return market_ret

# ================================================================
# حساب الميزات المقطعية (cross-sectional) — بعد جمع كل النقاط
# ================================================================

def add_cross_sectional_features(all_rows):
    """
    يضيف ميزات مقطعية:
    - rsi_rank_cross: ترتيب RSI مقارنة بالنقاط في نفس timestamp (±1h)
    - mom12_rank_cross: ترتيب momentum 12h مقطعياً
    ملاحظة: نجمع النقاط حسب timestamp ونرتّبها.
    """
    from collections import defaultdict
    by_ts = defaultdict(list)
    for i, row in enumerate(all_rows):
        # نقرّب لأقرب ساعة
        ts_h = (row["ts"] // 3_600_000) * 3_600_000
        by_ts[ts_h].append(i)

    rsi_rank    = np.full(len(all_rows), np.nan)
    mom12_rank  = np.full(len(all_rows), np.nan)
    btc_rel_str = np.full(len(all_rows), np.nan)  # mom12 / median(mom12)

    for ts_h, idxs in by_ts.items():
        if len(idxs) < 3:
            continue
        rsi_vals  = np.array([all_rows[i].get("rsi14", np.nan) for i in idxs])
        mom12_vals = np.array([all_rows[i].get("mom12", np.nan) for i in idxs])
        # تجاهل NaN
        valid_r = ~np.isnan(rsi_vals)
        valid_m = ~np.isnan(mom12_vals)
        if np.sum(valid_r) >= 3:
            ranks_r = _rank_arr(rsi_vals[valid_r]) / max(np.sum(valid_r) - 1, 1)
            for j, i in enumerate([k for k,f in zip(idxs, valid_r) if f]):
                rsi_rank[i] = ranks_r[j]
        if np.sum(valid_m) >= 3:
            ranks_m = _rank_arr(mom12_vals[valid_m]) / max(np.sum(valid_m) - 1, 1)
            med_m   = float(np.median(mom12_vals[valid_m]))
            for j, i in enumerate([k for k,f in zip(idxs, valid_m) if f]):
                mom12_rank[i] = ranks_m[j]
                btc_rel_str[i] = all_rows[i].get("mom12", 0) - med_m

    for i, row in enumerate(all_rows):
        row["rsi_rank_cross"]   = float(rsi_rank[i]) if not np.isnan(rsi_rank[i]) else np.nan
        row["mom12_rank_cross"] = float(mom12_rank[i]) if not np.isnan(mom12_rank[i]) else np.nan
        row["btc_rel_str"]      = float(btc_rel_str[i]) if not np.isnan(btc_rel_str[i]) else np.nan

    return all_rows

# ================================================================
# اختبار إحصائي
# ================================================================

def test_feature_target(feat_vals, target_vals, feat_name, target_name,
                        ts_vals, wf_split_ts):
    """
    يختبر ميزة × هدف:
    - IC كلي
    - IC في النصف الأول (WF_train) والنصف الثاني (WF_OOS)
    - p-value بـ permutation (على الكلي)
    - Cohen d
    - expectancy top/bot decile
    يعيد dict.
    """
    mask = (~np.isnan(feat_vals)) & (~np.isnan(target_vals))
    x    = feat_vals[mask]
    y    = target_vals[mask]
    ts   = ts_vals[mask]

    if len(x) < 30:
        return None

    ic_all  = spearman_ic(x, y)
    pval    = permutation_pvalue(ic_all, x, y)
    d       = cohen_d(x, y)
    exp_top, exp_bot = expectancy_decile(x, y)

    # Walk-Forward
    train_mask = ts < wf_split_ts
    oos_mask   = ts >= wf_split_ts

    ic_train = spearman_ic(x[train_mask], y[train_mask]) if np.sum(train_mask) >= 20 else np.nan
    ic_oos   = spearman_ic(x[oos_mask], y[oos_mask]) if np.sum(oos_mask) >= 20 else np.nan
    wf_consistent = (
        not np.isnan(ic_train) and not np.isnan(ic_oos)
        and np.sign(ic_train) == np.sign(ic_oos)
    )

    return {
        "feature":      feat_name,
        "target":       target_name,
        "n":            int(len(x)),
        "n_train":      int(np.sum(train_mask)),
        "n_oos":        int(np.sum(oos_mask)),
        "ic_all":       float(ic_all),
        "ic_train":     float(ic_train) if not np.isnan(ic_train) else None,
        "ic_oos":       float(ic_oos) if not np.isnan(ic_oos) else None,
        "p_value":      float(pval),
        "cohen_d":      float(d) if not np.isnan(d) else None,
        "exp_top_decile": float(exp_top),
        "exp_bot_decile": float(exp_bot),
        "wf_consistent":  bool(wf_consistent),
    }

# ================================================================
# البرنامج الرئيسي
# ================================================================

def main():
    rng_obj = random.Random(SEED)
    np.random.seed(SEED)

    print("=" * 60)
    print("مسح اكتشاف حافة شامل — 2026-05-22")
    print("=" * 60)

    # الخطوة 1: اختيار الرموز
    symbols = get_symbols()
    print(f"[INFO] الرموز: {len(symbols)}")

    # الخطوة 2: بناء مرجع السوق (للهدف C)
    print("[INFO] بناء متوسط عائد السوق...")
    market_ret = build_market_returns(symbols, sample_frac=0.3)

    # الخطوة 3: معالجة كل رمز
    all_rows = []
    total_syms = len(symbols)
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/{total_syms}] {sym}")
        if check_mem():
            print(f"[WARN] ذاكرة عالية — توقف مؤقت 10 ثانية")
            gc.collect()
            time.sleep(10)
        rows = process_symbol(sym, rng_obj, market_ret)
        all_rows.extend(rows)
        # Checkpoint كل 10 رموز
        if (i + 1) % 10 == 0:
            print(f"  → إجمالي النقاط حتى الآن: {len(all_rows)}")
            gc.collect()

    print(f"\n[INFO] إجمالي النقاط: {len(all_rows)}")

    # الخطوة 4: الميزات المقطعية
    print("[INFO] إضافة ميزات مقطعية...")
    all_rows = add_cross_sectional_features(all_rows)

    # الخطوة 5: تجهيز arrays للتحليل
    feat_names = [
        "rsi14", "rsi7", "bb_pos", "stoch_rsi", "macd_hist", "adx14",
        "atr_pct", "mom6", "mom12", "mom24", "vol_ratio", "vol_zscore",
        "atr_pct52", "rvol24", "hour_utc", "consec_down",
        "dist_hi30", "dist_lo30", "price_pct30",
        "rsi_zscore", "bb_zscore", "macd_pct50", "mom6_pct50",
        "rsi_rank_cross", "mom12_rank_cross", "btc_rel_str",
    ]
    target_names = ["target_a", "target_b", "target_c"]

    feat_arrays = {}
    for fn in feat_names:
        feat_arrays[fn] = np.array([r.get(fn, np.nan) for r in all_rows], dtype=float)

    target_arrays = {}
    for tn in target_names:
        vals = []
        for r in all_rows:
            v = r.get(tn)
            vals.append(float(v) if v is not None else np.nan)
        target_arrays[tn] = np.array(vals, dtype=float)

    ts_vals = np.array([r["ts"] for r in all_rows], dtype=np.int64)

    # Walk-Forward split: نقطة منتصف الزمن
    ts_sorted = np.sort(ts_vals)
    wf_split_ts = int(ts_sorted[len(ts_sorted) // 2])

    # عائد 48h للـ expectancy الفعلي
    ret_48h_arr = np.array([r.get("ret_48h", np.nan) for r in all_rows], dtype=float)

    # الخطوة 6: اختبار كل (ميزة × هدف)
    print("[INFO] تشغيل الاختبارات الإحصائية...")
    all_results = []
    for tn in target_names:
        print(f"  → هدف: {tn}")
        for fn in feat_names:
            # استخدم ret_48h للـ expectancy الفعلي بدل binary label
            res = test_feature_target(
                feat_arrays[fn],
                target_arrays[tn],
                fn, tn,
                ts_vals, wf_split_ts
            )
            if res is not None:
                # إضافة expectancy على العائد الفعلي (ret_48h)
                mask_fn = ~np.isnan(feat_arrays[fn])
                x_e  = feat_arrays[fn][mask_fn]
                y_e  = ret_48h_arr[mask_fn]
                exp_t, exp_b = expectancy_decile(x_e, y_e)
                res["exp_top_ret"] = exp_t
                res["exp_bot_ret"] = exp_b
                all_results.append(res)

    # الخطوة 7: FDR Benjamini-Hochberg — عبر كل (ميزة × هدف) معاً
    print("[INFO] تطبيق FDR Benjamini-Hochberg...")
    pvals_all = [r["p_value"] for r in all_results]
    q_vals    = benjamini_hochberg(pvals_all, q=0.05)
    for i, res in enumerate(all_results):
        res["q_value"] = float(q_vals[i])

    # الخطوة 8: تحديد الناجيات
    survivors = []
    for res in all_results:
        ic_oos = res.get("ic_oos") or 0.0
        d_val  = res.get("cohen_d") or 0.0
        q      = res.get("q_value", 1.0)
        wf_ok  = res.get("wf_consistent", False)
        # معيار الناجية الصارم
        if (q < 0.05
                and (abs(d_val) > 0.1 or abs(ic_oos) > 0.05)
                and wf_ok):
            survivors.append(res)

    # ترتيب الناجيات
    survivors.sort(key=lambda r: abs(r.get("ic_oos") or 0.0), reverse=True)

    # الخطوة 9: إحصائيات عامة
    n_total_rows = len(all_rows)
    n_symbols    = len(symbols)

    # توزيع الأهداف
    target_stats = {}
    for tn in target_names:
        ta = target_arrays[tn]
        valid = ta[~np.isnan(ta)]
        if len(valid) > 0:
            target_stats[tn] = {"n": int(len(valid)), "hit_rate": float(np.mean(valid))}

    # تحقق sanity: BTC +5% يجب أن يُطلق TARGET_A
    # سنسجّل فقط إحصائيات الأهداف كـ sanity

    # الخطوة 10: حفظ النتائج
    output = {
        "date":         "2026-05-22",
        "seed":         SEED,
        "n_symbols":    n_symbols,
        "n_rows":       n_total_rows,
        "n_features":   len(feat_names),
        "n_tests":      len(all_results),
        "wf_split_ts":  wf_split_ts,
        "target_stats": target_stats,
        "survivors":    survivors,
        "all_results":  all_results,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"[INFO] النتائج حُفظت في {OUTPUT_JSON}")

    # طباعة الملخص
    print("\n" + "=" * 60)
    print(f"الملخص:")
    print(f"  عدد الرموز: {n_symbols}")
    print(f"  إجمالي النقاط: {n_total_rows}")
    print(f"  عدد الاختبارات: {len(all_results)}")
    print(f"  الناجيات (q<0.05 + |d|>0.1 أو |IC_OOS|>0.05 + WF_ثابت): {len(survivors)}")
    for tn in target_names:
        ts_surv = [s for s in survivors if s["target"] == tn]
        print(f"  {tn}: {len(ts_surv)} ناجية")
        for s in ts_surv[:5]:
            print(f"    {s['feature']:20} IC_OOS={s.get('ic_oos','?'):+.3f}  q={s.get('q_value','?'):.3f}  d={s.get('cohen_d','?'):+.3f}  WF={'ثابت' if s['wf_consistent'] else 'متقلّب'}")
    print("=" * 60)

    # كتابة تقرير موجز
    with open(OUTPUT_MD, "w") as f:
        f.write(f"# نتائج مسح الحافة — {DATE_STAMP}\n\n")
        f.write(f"- **العيّنة:** {n_total_rows} نقطة، {n_symbols} رمزاً، 180 يوماً\n")
        f.write(f"- **الاختبارات:** {len(all_results)} (ميزة × هدف)\n")
        f.write(f"- **الناجيات الصارمة:** {len(survivors)}\n\n")
        for tn in target_names:
            ts_surv = [s for s in survivors if s["target"] == tn]
            f.write(f"## {tn}\n")
            if ts_surv:
                f.write("| ميزة | IC_OOS | q | d | WF |\n|------|--------|---|---|----|\n")
                for s in ts_surv:
                    ic  = f"{s.get('ic_oos', 0):+.3f}" if s.get('ic_oos') is not None else "N/A"
                    qv  = f"{s.get('q_value', 1):.3f}"
                    dv  = f"{s.get('cohen_d', 0):+.3f}" if s.get('cohen_d') is not None else "N/A"
                    wf  = "ثابت" if s.get("wf_consistent") else "متقلّب"
                    f.write(f"| {s['feature']} | {ic} | {qv} | {dv} | {wf} |\n")
            else:
                f.write("لا ناجيات.\n")
            f.write("\n")
    print(f"[INFO] التقرير: {OUTPUT_MD}")
    return output


if __name__ == "__main__":
    main()
