#!/usr/bin/env python3
"""
مسح اكتشاف حافة شامل v2 — نسخة محسّنة بـ numpy vectorized
=============================================================
التاريخ: 2026-05-22
التحسين: بدلاً من حساب المؤشرات نقطة-نقطة (بطيء)، نحسبها على المصفوفة كاملاً
         ثم نأخذ القيم عند النقاط العشوائية المُختارة. سرعة 50-100x.

قواعد:
  - بحث فقط — التجميد ساري، لا تعديل على الكود الحيّ.
  - بلا تسرّب مستقبلي: كل مؤشر يستخدم نافذة rolling ← الماضي فقط.
  - cache klines على /tmp/edge_cache/ (ephemeral لكن كافٍ للجلسة).
  - بلا حزم جديدة.
"""

import os, sys, random, pickle, time, json, gc, math
import requests
import numpy as np
from datetime import datetime, timezone

# ================================================================
# مسارات
# ================================================================
CACHE_DIR   = "/tmp/edge_cache_1h"
CACHE_1D    = "/tmp/edge_cache_1d"
RESULTS_DIR = "/app/research/results"
SYMBOL_FILE = "/tmp/edge_symbols.pkl"

os.makedirs(CACHE_DIR,   exist_ok=True)
os.makedirs(CACHE_1D,    exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

DATE_STAMP  = "2026_05_22_v2"
OUTPUT_JSON = os.path.join(RESULTS_DIR, f"edge_discovery_{DATE_STAMP}.json")
OUTPUT_MD   = os.path.join(RESULTS_DIR, f"edge_discovery_{DATE_STAMP}.md")

# ================================================================
# ثوابت
# ================================================================
SEED             = 20260522
BINANCE_BASE     = "https://api.binance.com"
INTERVAL_1H      = "1h"
DAYS_BACK        = 180
FWD_BARS         = 48           # 48h في إطار 1h
FEE              = 0.003
TARGET_A_THRESH  = 0.03
TARGET_B_THRESH  = 0.05
MIN_CANDLES      = 250          # حد أدنى للمؤشرات
POINTS_PER_SYM   = 600          # 600×80 = 48,000 نقطة
REQUEST_SLEEP    = 0.22
PERM_N           = 500          # permutations
WF_SPLIT         = 0.5
MEM_LIMIT_BYTES  = 1_500_000_000

TARGET_LARGE = 30
TARGET_MID   = 30
TARGET_SMALL = 20

# ================================================================
# فحص الذاكرة
# ================================================================
def check_mem():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb * 1024 > MEM_LIMIT_BYTES
    except Exception:
        pass
    return False

# ================================================================
# Spearman IC و BH و Cohen d
# ================================================================

def rank_arr(arr):
    n   = len(arr)
    idx = np.argsort(arr, kind='mergesort')
    rnk = np.empty(n, dtype=float)
    i   = 0
    while i < n:
        j = i + 1
        while j < n and arr[idx[j]] == arr[idx[i]]:
            j += 1
        r = (i + j - 1) / 2.0
        for k in range(i, j):
            rnk[idx[k]] = r
        i = j
    return rnk

def spearman_ic(x, y):
    if len(x) < 10:
        return np.nan
    rx = rank_arr(np.asarray(x, float))
    ry = rank_arr(np.asarray(y, float))
    mx, my = rx.mean(), ry.mean()
    num = ((rx - mx) * (ry - my)).sum()
    den = np.sqrt(((rx - mx)**2).sum() * ((ry - my)**2).sum())
    return float(num / den) if den > 0 else 0.0

def perm_pvalue(ic_obs, x, y, n_perm=PERM_N, seed=42):
    rng = np.random.default_rng(seed)
    if len(x) < 10:
        return 1.0
    count = sum(1 for _ in range(n_perm) if abs(spearman_ic(x, rng.permutation(y))) >= abs(ic_obs))
    return (count + 1) / (n_perm + 1)

def cohen_d_decile(x, y):
    n   = len(y)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    top = y[idx[-cut:]]
    bot = y[idx[:cut]]
    if len(top) < 3 or len(bot) < 3:
        return np.nan
    mt, mb = np.mean(top), np.mean(bot)
    st = np.std(top, ddof=1)
    sb = np.std(bot, ddof=1)
    sp = np.sqrt(((len(top)-1)*st**2 + (len(bot)-1)*sb**2) / (len(top)+len(bot)-2))
    return float((mt - mb) / sp) if sp > 0 else 0.0

def expectancy_decile(x, y_ret):
    n   = len(y_ret)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    def exp_f(arr):
        adj = arr - FEE
        wr  = (adj > 0).mean()
        avg_w = adj[adj > 0].mean() if (adj > 0).any() else 0.0
        avg_l = adj[adj <= 0].mean() if (adj <= 0).any() else 0.0
        return float(wr * avg_w + (1 - wr) * avg_l)
    return exp_f(y_ret[idx[-cut:]]), exp_f(y_ret[idx[:cut]])

def bh_fdr(pvals, q=0.05):
    n   = len(pvals)
    idx = np.argsort(pvals)
    pv  = np.array(pvals)[idx]
    qv  = pv * n / (np.arange(1, n+1))
    # enforce monotonicity
    for i in range(n-2, -1, -1):
        if qv[i] > qv[i+1]:
            qv[i] = qv[i+1]
    result = np.empty(n)
    result[idx] = qv
    return result.tolist()

# ================================================================
# جلب klines
# ================================================================

def fetch_klines(symbol):
    cache_path = os.path.join(CACHE_DIR, f"{symbol}_1h.pkl")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - DAYS_BACK * 86_400_000
    limit    = 1000
    all_k    = []
    cur      = start_ms

    while cur < now_ms:
        try:
            r = requests.get(f"{BINANCE_BASE}/api/v3/klines",
                             params={"symbol": symbol, "interval": INTERVAL_1H,
                                     "startTime": cur, "limit": limit},
                             timeout=15)
            if r.status_code == 429:
                time.sleep(60); continue
            if r.status_code != 200:
                break
            data = r.json()
            if not data:
                break
            all_k.extend(data)
            cur = data[-1][0] + 3_600_000
            time.sleep(REQUEST_SLEEP)
        except Exception as e:
            print(f"  [WARN] {symbol}: {e}")
            time.sleep(5); break

    if all_k:
        with open(cache_path, "wb") as f:
            pickle.dump(all_k, f)
    return all_k

def parse_klines(raw):
    raw  = sorted(raw, key=lambda x: x[0])
    ts   = np.array([r[0] for r in raw], dtype=np.int64)
    H    = np.array([float(r[2]) for r in raw])
    L    = np.array([float(r[3]) for r in raw])
    C    = np.array([float(r[4]) for r in raw])
    V    = np.array([float(r[5]) for r in raw])
    return ts, H, L, C, V

# ================================================================
# حساب كل المؤشرات vectorized على المصفوفة الكاملة
# ================================================================

def compute_all_indicators(C, H, L, V):
    """
    يحسب جميع المؤشرات على المصفوفة الكاملة (rolling backward).
    يعيد dict: {feat_name: array of length N}
    القيم قبل الحد الأدنى تُضبَط بـ NaN.
    """
    N = len(C)
    out = {}

    # --- RSI 14 ---
    rsi14 = _rolling_rsi(C, 14)
    out["rsi14"] = rsi14

    # --- RSI 7 ---
    out["rsi7"] = _rolling_rsi(C, 7)

    # --- Bollinger position 20 ---
    out["bb_pos"] = _rolling_bb_pos(C, 20, 2.0)

    # --- Stochastic RSI (14,3) ---
    out["stoch_rsi"] = _rolling_stoch_rsi(rsi14, 14, 3)

    # --- MACD histogram (12,26,9) ---
    out["macd_hist"] = _rolling_macd_hist(C, 12, 26, 9)

    # --- ADX 14 (مبسّط) ---
    out["adx14"] = _rolling_adx(H, L, C, 14)

    # --- ATR% 14 ---
    atr14 = _rolling_atr(H, L, C, 14)
    out["atr_pct"] = np.where(C > 0, atr14 / C, np.nan)

    # --- Momentum 6,12,24 ---
    for k in [6, 12, 24]:
        mom = np.full(N, np.nan)
        mom[k:] = C[k:] / C[:-k] - 1.0
        out[f"mom{k}"] = mom

    # --- Volume ratio (vol/ma_vol_20) ---
    ma_v = _rolling_mean(V, 20)
    out["vol_ratio"] = np.where(ma_v > 0, V / ma_v, np.nan)

    # --- Volume z-score (20) ---
    out["vol_zscore"] = _rolling_zscore(V, 20)

    # --- ATR percentile (52) ---
    out["atr_pct52"] = _rolling_percentile_rank(atr14, 52)

    # --- Realized volatility 24 ---
    log_ret = np.full(N, np.nan)
    log_ret[1:] = np.log(C[1:] / C[:-1])
    out["rvol24"] = _rolling_std(log_ret, 24) * np.sqrt(24)

    # --- Consecutive down candles ---
    out["consec_down"] = _consec_down(C)

    # --- Distance from 30d high/low (720h) ---
    hi30 = _rolling_max(H, 720)
    lo30 = _rolling_min(L, 720)
    out["dist_hi30"] = np.where(hi30 > 0, (C - hi30) / hi30, np.nan)
    out["dist_lo30"] = np.where(lo30 > 0, (C - lo30) / lo30, np.nan)

    # --- Price percentile in 30d range ---
    rng30 = hi30 - lo30
    out["price_pct30"] = np.where(rng30 > 0, np.clip((C - lo30) / rng30, 0, 1), 0.5)

    # --- RSI z-score rolling 50 ---
    out["rsi_zscore"] = _rolling_zscore(rsi14, 50)

    # --- BB position z-score rolling 50 ---
    out["bb_zscore"] = _rolling_zscore(out["bb_pos"], 50)

    # --- MACD hist percentile rank rolling 50 ---
    out["macd_pct50"] = _rolling_percentile_rank(out["macd_hist"], 50)

    # --- Momentum 6 percentile rank rolling 50 ---
    out["mom6_pct50"] = _rolling_percentile_rank(out["mom6"], 50)

    return out


# ================================================================
# دوال مؤشرات vectorized
# ================================================================

def _rolling_rsi(C, period=14):
    N  = len(C)
    d  = np.diff(C)
    g  = np.maximum(d, 0)
    l  = np.maximum(-d, 0)
    rsi = np.full(N, np.nan)
    if N < period + 1:
        return rsi
    # قيمة ابتدائية
    avg_g = g[:period].mean()
    avg_l = l[:period].mean()
    for i in range(period, len(d)):
        avg_g = (avg_g * (period - 1) + g[i]) / period
        avg_l = (avg_l * (period - 1) + l[i]) / period
        if avg_l == 0:
            rsi[i + 1] = 100.0
        else:
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return rsi

def _rolling_ema_arr(arr, period):
    N = len(arr)
    out = np.full(N, np.nan)
    start = period - 1
    # أول قيمة = mean أول period عناصر غير NaN
    valid_idx = np.where(~np.isnan(arr))[0]
    if len(valid_idx) < period:
        return out
    first_valid = valid_idx[0]
    if first_valid + period > N:
        return out
    out[first_valid + period - 1] = np.mean(arr[first_valid:first_valid + period])
    k = 2.0 / (period + 1.0)
    for i in range(first_valid + period, N):
        if np.isnan(arr[i]):
            out[i] = out[i-1]
        else:
            out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out

def _rolling_bb_pos(C, period=20, std_mult=2.0):
    N   = len(C)
    out = np.full(N, np.nan)
    for i in range(period - 1, N):
        w   = C[i-period+1:i+1]
        mu  = w.mean()
        sig = w.std(ddof=1)
        ub  = mu + std_mult * sig
        lb  = mu - std_mult * sig
        rng = ub - lb
        out[i] = float(np.clip((C[i] - lb) / rng, 0.0, 1.0)) if rng > 0 else 0.5
    return out

def _rolling_stoch_rsi(rsi_arr, period=14, smooth=3):
    N   = len(rsi_arr)
    raw = np.full(N, np.nan)
    for i in range(period - 1, N):
        w  = rsi_arr[i-period+1:i+1]
        if np.any(np.isnan(w)):
            continue
        lo = w.min(); hi = w.max()
        raw[i] = (rsi_arr[i] - lo) / (hi - lo + 1e-10)
    # تنعيم بالمتوسط المتحرك
    out = np.full(N, np.nan)
    for i in range(smooth - 1, N):
        w = raw[i-smooth+1:i+1]
        if not np.any(np.isnan(w)):
            out[i] = w.mean()
    return out

def _rolling_macd_hist(C, fast=12, slow=26, signal=9):
    N       = len(C)
    ema_f   = _rolling_ema_arr(C, fast)
    ema_s   = _rolling_ema_arr(C, slow)
    macd_l  = ema_f - ema_s
    sig_l   = _rolling_ema_arr(macd_l, signal)
    hist    = macd_l - sig_l
    return hist

def _rolling_atr(H, L, C, period=14):
    N  = len(C)
    tr = np.zeros(N)
    tr[0] = H[0] - L[0]
    for i in range(1, N):
        tr[i] = max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1]))
    atr = np.full(N, np.nan)
    if N < period + 1:
        return atr
    atr[period] = tr[1:period+1].mean()
    for i in range(period + 1, N):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr

def _rolling_adx(H, L, C, period=14):
    """ADX مبسّط vectorized."""
    N = len(C)
    out = np.full(N, np.nan)
    if N < period * 3:
        return out
    dm_p = np.maximum(np.diff(H), 0)
    dm_n = np.maximum(-np.diff(L), 0)
    for i in range(len(dm_p)):
        if dm_p[i] > dm_n[i]:
            dm_n[i] = 0
        elif dm_n[i] > dm_p[i]:
            dm_p[i] = 0
        else:
            dm_p[i] = dm_n[i] = 0
    tr = np.array([max(H[i]-L[i], abs(H[i]-C[i-1]), abs(L[i]-C[i-1])) for i in range(1, N)])
    atr_s = tr[:period].sum()
    dmp_s = dm_p[:period].sum()
    dmn_s = dm_n[:period].sum()
    dx_arr = []
    for i in range(period, len(tr)):
        atr_s = atr_s - atr_s/period + tr[i]
        dmp_s = dmp_s - dmp_s/period + dm_p[i]
        dmn_s = dmn_s - dmn_s/period + dm_n[i]
        dip = 100*dmp_s/atr_s if atr_s > 0 else 0
        din = 100*dmn_s/atr_s if atr_s > 0 else 0
        dx = 100*abs(dip-din)/(dip+din) if (dip+din)>0 else 0
        dx_arr.append(dx)
    dx_arr = np.array(dx_arr)
    for i in range(period-1, len(dx_arr)):
        out[i + period + 1] = np.mean(dx_arr[i-period+1:i+1])
    return out

def _rolling_mean(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        seg = arr[i-w+1:i+1]
        if not np.any(np.isnan(seg)):
            out[i] = seg.mean()
    return out

def _rolling_std(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        seg = arr[i-w+1:i+1]
        if not np.any(np.isnan(seg)):
            out[i] = seg.std(ddof=1)
    return out

def _rolling_zscore(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        seg = arr[i-w+1:i+1]
        if np.any(np.isnan(seg)):
            continue
        mu  = seg.mean()
        std = seg.std(ddof=1)
        out[i] = (arr[i] - mu) / std if std > 0 else 0.0
    return out

def _rolling_percentile_rank(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        seg = arr[i-w+1:i+1]
        if np.any(np.isnan(seg)):
            continue
        out[i] = float((seg <= arr[i]).sum()) / len(seg)
    return out

def _rolling_max(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        out[i] = arr[i-w+1:i+1].max()
    return out

def _rolling_min(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        out[i] = arr[i-w+1:i+1].min()
    return out

def _consec_down(C):
    N = len(C)
    out = np.zeros(N)
    for i in range(1, N):
        if C[i] < C[i-1]:
            out[i] = out[i-1] + 1
        else:
            out[i] = 0
    return out

# ================================================================
# حساب الأهداف vectorized
# ================================================================

def compute_targets_vec(C, H, L, valid_indices):
    """
    يحسب الأهداف الثلاثة لكل نقطة في valid_indices.
    يعيد arrays: target_a, target_b, ret_48h
    """
    n_pts   = len(valid_indices)
    ta      = np.zeros(n_pts, dtype=np.int8)
    tb      = np.zeros(n_pts, dtype=np.int8)
    ret48   = np.zeros(n_pts, dtype=float)

    for k, t in enumerate(valid_indices):
        if t + FWD_BARS >= len(C):
            ta[k] = tb[k] = -1
            continue
        entry = C[t]
        if entry <= 0:
            ta[k] = tb[k] = -1
            continue
        # TARGET_A: +3% قبل -3%
        hit_up = hit_dn = False
        for i in range(t+1, t+FWD_BARS+1):
            if H[i] / entry - 1 >= TARGET_A_THRESH:
                hit_up = True; break
            if 1 - L[i] / entry >= TARGET_A_THRESH:
                hit_dn = True; break
        ta[k] = 1 if hit_up else 0

        # TARGET_B
        r = C[t + FWD_BARS] / entry - 1.0
        tb[k] = 1 if abs(r) > TARGET_B_THRESH else 0
        ret48[k] = r

    return ta, tb, ret48

# ================================================================
# اختيار الرموز
# ================================================================

def get_symbols():
    if os.path.exists(SYMBOL_FILE):
        with open(SYMBOL_FILE, "rb") as f:
            s = pickle.load(f)
        print(f"[INFO] رموز من cache: {len(s)}")
        return s

    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    data = requests.get(url, timeout=20).json()
    usdt = [d for d in data
            if d["symbol"].endswith("USDT")
            and not any(x in d["symbol"] for x in ["DOWN","UP","BEAR","BULL","3L","3S"])
            and float(d.get("quoteVolume", 0)) > 1_000_000]
    usdt.sort(key=lambda d: float(d.get("quoteVolume", 0)), reverse=True)
    rng = random.Random(SEED)
    large = rng.sample([d["symbol"] for d in usdt[:60]], min(TARGET_LARGE, 60))
    mid_pool = [d["symbol"] for d in usdt[60:300] if d["symbol"] not in large]
    mid   = rng.sample(mid_pool, min(TARGET_MID, len(mid_pool)))
    small_pool = [d["symbol"] for d in usdt[300:800]
                  if d["symbol"] not in large and d["symbol"] not in mid]
    small = rng.sample(small_pool, min(TARGET_SMALL, len(small_pool)))
    syms  = list(dict.fromkeys(large + mid + small))
    with open(SYMBOL_FILE, "wb") as f:
        pickle.dump(syms, f)
    print(f"[INFO] اختار {len(syms)} رمزاً")
    return syms

# ================================================================
# معالجة رمز واحد
# ================================================================

def process_symbol(symbol, rng_obj):
    raw = fetch_klines(symbol)
    if len(raw) < MIN_CANDLES + FWD_BARS:
        print(f"  [SKIP] {symbol}: {len(raw)} شمعة")
        return [], None

    ts, H, L, C, V = parse_klines(raw)
    N = len(C)

    # حساب كل المؤشرات vectorized مرة واحدة
    indicators = compute_all_indicators(C, H, L, V)

    # نافذة صالحة
    valid_start = 230  # بعد أطول نافذة (720h للـ 30d محمية بـ rolling_max)
    # ملاحظة: rolling_max(720) يعطي nan لـ i<719 — لكننا نستخدم 230 لأننا نتسامح مع nan على بعض الميزات
    valid_end   = N - FWD_BARS - 1
    if valid_end <= valid_start:
        return [], None

    valid_indices = list(range(valid_start, valid_end))
    n_pts = min(POINTS_PER_SYM, len(valid_indices))
    sampled_t = sorted(rng_obj.sample(valid_indices, n_pts))

    # حساب الأهداف لهذه النقاط
    ta, tb, ret48 = compute_targets_vec(C, H, L, sampled_t)

    # جمع الصفوف
    rows = []
    feat_names = list(indicators.keys())
    for k, t in enumerate(sampled_t):
        if ta[k] == -1:
            continue
        row = {
            "symbol": symbol,
            "ts": int(ts[t]),
            "hour_utc": int((ts[t] / 1000 % 86400) // 3600),
            "target_a": int(ta[k]),
            "target_b": int(tb[k]),
            "ret_48h":  float(ret48[k]),
        }
        for fn in feat_names:
            v = indicators[fn][t]
            row[fn] = float(v) if not np.isnan(v) else None
        row["hour_utc"] = float(row["hour_utc"])
        rows.append(row)

    # إحصاء الحافة على هذا الرمز (للـ cross-sectional لاحقاً)
    sym_median_ret = float(np.median(ret48))

    del raw, ts, H, L, C, V, indicators
    gc.collect()

    print(f"  [OK] {symbol}: {len(rows)} نقطة — hit_A={ta[ta>=0].mean():.2f}, ret_median={sym_median_ret:.3f}")
    return rows, sym_median_ret

# ================================================================
# اختبار ميزة × هدف
# ================================================================

def test_one(fn, tn, x_arr, y_arr, ts_arr, wf_split_ts, ret_arr):
    """x_arr, y_arr بعد إزالة NaN."""
    mask = (~np.isnan(x_arr)) & (~np.isnan(y_arr))
    x  = x_arr[mask]
    y  = y_arr[mask]
    ts = ts_arr[mask]
    r  = ret_arr[mask]
    if len(x) < 50:
        return None

    ic_all = spearman_ic(x, y)
    pval   = perm_pvalue(ic_all, x, y)
    d      = cohen_d_decile(x, y)
    exp_t, exp_b = expectancy_decile(x, r)

    # Walk-Forward
    train = ts < wf_split_ts
    oos   = ts >= wf_split_ts
    ic_tr  = spearman_ic(x[train], y[train]) if train.sum() >= 20 else np.nan
    ic_oos = spearman_ic(x[oos],   y[oos])   if oos.sum()   >= 20 else np.nan
    wf_ok  = (not np.isnan(ic_tr) and not np.isnan(ic_oos)
              and np.sign(ic_tr) == np.sign(ic_oos))

    return {
        "feature":        fn,
        "target":         tn,
        "n":              int(len(x)),
        "n_train":        int(train.sum()),
        "n_oos":          int(oos.sum()),
        "ic_all":         float(ic_all),
        "ic_train":       float(ic_tr)  if not np.isnan(ic_tr)  else None,
        "ic_oos":         float(ic_oos) if not np.isnan(ic_oos) else None,
        "p_value":        float(pval),
        "cohen_d":        float(d)      if not np.isnan(d)      else None,
        "exp_top_ret":    float(exp_t),
        "exp_bot_ret":    float(exp_b),
        "wf_consistent":  bool(wf_ok),
    }

# ================================================================
# الميزات المقطعية (cross-sectional)
# ================================================================

def add_cross_sectional(all_rows):
    from collections import defaultdict
    by_ts = defaultdict(list)
    for i, row in enumerate(all_rows):
        ts_h = (row["ts"] // 3_600_000) * 3_600_000
        by_ts[ts_h].append(i)

    rsi_rank    = [None] * len(all_rows)
    mom12_rank  = [None] * len(all_rows)
    mkt_rel_str = [None] * len(all_rows)

    for ts_h, idxs in by_ts.items():
        if len(idxs) < 3:
            continue
        rsi_v  = np.array([all_rows[i].get("rsi14") or np.nan for i in idxs], float)
        mom_v  = np.array([all_rows[i].get("mom12") or np.nan for i in idxs], float)

        vr = ~np.isnan(rsi_v)
        vm = ~np.isnan(mom_v)
        if vr.sum() >= 3:
            ri = [i for i,f in zip(idxs,vr) if f]
            rv = rsi_v[vr]
            rnk = rank_arr(rv) / max(len(rv)-1, 1)
            for j, i in enumerate(ri):
                rsi_rank[i] = float(rnk[j])
        if vm.sum() >= 3:
            mi = [i for i,f in zip(idxs,vm) if f]
            mv = mom_v[vm]
            rnk = rank_arr(mv) / max(len(mv)-1, 1)
            med = float(np.median(mv))
            for j, i in enumerate(mi):
                mom12_rank[i] = float(rnk[j])
                mkt_rel_str[i] = float(all_rows[i].get("mom12") or 0) - med

    for i, row in enumerate(all_rows):
        row["rsi_rank_cs"]   = rsi_rank[i]
        row["mom12_rank_cs"] = mom12_rank[i]
        row["mkt_rel_str"]   = mkt_rel_str[i]

    return all_rows

# ================================================================
# الرئيسي
# ================================================================

def main():
    rng = random.Random(SEED)
    np.random.seed(SEED)

    print("=" * 60)
    print("مسح اكتشاف حافة v2 — 2026-05-22")
    print("=" * 60)

    symbols = get_symbols()
    print(f"[INFO] عدد الرموز: {len(symbols)}")

    # معالجة الرموز
    all_rows = []
    all_market_rets = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] {sym}")
        if check_mem():
            print("[WARN] ذاكرة عالية — GC")
            gc.collect()
        rows, med_ret = process_symbol(sym, rng)
        all_rows.extend(rows)
        if med_ret is not None:
            all_market_rets.append(med_ret)
        if (i+1) % 10 == 0:
            print(f"  → إجمالي: {len(all_rows)} نقطة")
            gc.collect()

    print(f"\n[INFO] إجمالي النقاط: {len(all_rows)}")
    if len(all_rows) < 5000:
        print("[ERROR] نقاط غير كافية!")
        sys.exit(1)

    # إضافة TARGET_C: هل ret_48h > median_ret_market للـ timestamp؟
    # نحسب median ret لكل timestamp من كل الرموز
    from collections import defaultdict
    ts_rets = defaultdict(list)
    for row in all_rows:
        ts_h = (row["ts"] // 3_600_000) * 3_600_000
        ts_rets[ts_h].append(row["ret_48h"])
    ts_median = {k: float(np.median(v)) for k, v in ts_rets.items() if len(v) >= 3}
    n_tc = 0
    for row in all_rows:
        ts_h = (row["ts"] // 3_600_000) * 3_600_000
        med = ts_median.get(ts_h)
        if med is not None:
            row["target_c"] = 1 if row["ret_48h"] > med else 0
            n_tc += 1
        else:
            row["target_c"] = None
    print(f"[INFO] target_c مُحسَب لـ {n_tc}/{len(all_rows)} نقطة")

    # الميزات المقطعية
    print("[INFO] إضافة ميزات cross-sectional...")
    all_rows = add_cross_sectional(all_rows)

    # جميع أسماء الميزات
    feat_names = [
        "rsi14", "rsi7", "bb_pos", "stoch_rsi", "macd_hist", "adx14",
        "atr_pct", "mom6", "mom12", "mom24", "vol_ratio", "vol_zscore",
        "atr_pct52", "rvol24", "hour_utc", "consec_down",
        "dist_hi30", "dist_lo30", "price_pct30",
        "rsi_zscore", "bb_zscore", "macd_pct50", "mom6_pct50",
        "rsi_rank_cs", "mom12_rank_cs", "mkt_rel_str",
    ]
    target_names = ["target_a", "target_b", "target_c"]

    # تحويل إلى arrays
    n = len(all_rows)
    feat_arrs = {}
    for fn in feat_names:
        feat_arrs[fn] = np.array([r.get(fn) if r.get(fn) is not None else np.nan
                                   for r in all_rows], dtype=float)
    tgt_arrs = {}
    for tn in target_names:
        tgt_arrs[tn] = np.array([r.get(tn) if r.get(tn) is not None else np.nan
                                  for r in all_rows], dtype=float)

    ts_vals  = np.array([r["ts"] for r in all_rows], dtype=np.int64)
    ret_arr  = np.array([r["ret_48h"] for r in all_rows], dtype=float)

    # Walk-Forward split (50% زمنياً)
    ts_sorted = np.sort(ts_vals)
    wf_split_ts = int(ts_sorted[len(ts_sorted) // 2])

    # إحصاءات الأهداف
    target_stats = {}
    for tn in target_names:
        ta = tgt_arrs[tn]
        valid = ta[~np.isnan(ta)]
        if len(valid) > 0:
            target_stats[tn] = {"n": int(len(valid)), "hit_rate": float(np.mean(valid))}

    # الاختبارات
    print("[INFO] تشغيل الاختبارات الإحصائية...")
    all_results = []
    for tn in target_names:
        print(f"  هدف: {tn}")
        for fn in feat_names:
            res = test_one(fn, tn,
                           feat_arrs[fn], tgt_arrs[tn],
                           ts_vals, wf_split_ts, ret_arr)
            if res is not None:
                all_results.append(res)

    # FDR
    print("[INFO] تطبيق FDR Benjamini-Hochberg...")
    pvals = [r["p_value"] for r in all_results]
    qvals = bh_fdr(pvals, q=0.05)
    for i, r in enumerate(all_results):
        r["q_value"] = float(qvals[i])

    # تحديد الناجيات (صارم)
    survivors = []
    borderline = []
    for r in all_results:
        ic_oos = r.get("ic_oos") or 0.0
        d_val  = r.get("cohen_d") or 0.0
        q      = r.get("q_value", 1.0)
        wf_ok  = r.get("wf_consistent", False)
        if q < 0.05 and (abs(d_val) > 0.1 or abs(ic_oos) > 0.05) and wf_ok:
            survivors.append(r)
        elif q < 0.1 and (abs(d_val) > 0.08 or abs(ic_oos) > 0.04):
            borderline.append(r)

    survivors.sort(key=lambda r: abs(r.get("ic_oos") or 0.0), reverse=True)
    borderline.sort(key=lambda r: abs(r.get("ic_oos") or 0.0), reverse=True)

    # حفظ النتائج
    output = {
        "date":          "2026-05-22",
        "seed":          SEED,
        "n_symbols":     len(symbols),
        "n_rows":        len(all_rows),
        "n_features":    len(feat_names),
        "n_tests":       len(all_results),
        "wf_split_ts":   wf_split_ts,
        "target_stats":  target_stats,
        "survivors":     survivors,
        "borderline":    borderline,
        "all_results":   all_results,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"[INFO] حُفظ في {OUTPUT_JSON}")

    # طباعة الملخص
    print("\n" + "=" * 60)
    print(f"الملخص:")
    print(f"  الرموز: {len(symbols)}")
    print(f"  النقاط: {len(all_rows)}")
    print(f"  الاختبارات: {len(all_results)}")
    print(f"  الناجيات الصارمة: {len(survivors)}")
    print(f"  الحدّية: {len(borderline)}")
    print()
    for tn in target_names:
        ts_surv = [s for s in survivors if s["target"] == tn]
        ts_bord = [s for s in borderline if s["target"] == tn]
        print(f"  [{tn}] stat={target_stats.get(tn,{}).get('hit_rate','?'):.2f}")
        print(f"    ناجيات: {len(ts_surv)}")
        for s in ts_surv[:8]:
            print(f"      {s['feature']:20} IC_OOS={s.get('ic_oos','?'):+.3f}  q={s.get('q_value','?'):.3f}"
                  f"  d={s.get('cohen_d','?'):+.3f}  WF={'✓' if s['wf_consistent'] else '✗'}"
                  f"  E_top={s.get('exp_top_ret','?'):+.3f}")
        if ts_bord:
            print(f"    حدّية: {len(ts_bord)} (q<0.1)")
    print("=" * 60)

    # تقرير MD
    lines = [f"# نتائج مسح الحافة — {DATE_STAMP}\n",
             f"- **العيّنة:** {len(all_rows)} نقطة، {len(symbols)} رمزاً، 180 يوماً\n",
             f"- **الاختبارات:** {len(all_results)} (ميزة × هدف)\n",
             f"- **الناجيات الصارمة (q<0.05, |d|>0.1 أو |IC_OOS|>0.05, WF ثابت):** {len(survivors)}\n\n"]
    for tn in target_names:
        ts_surv = [s for s in survivors if s["target"] == tn]
        ts_bord = [s for s in borderline if s["target"] == tn]
        stat = target_stats.get(tn, {})
        lines.append(f"## {tn} (hit_rate={stat.get('hit_rate','?'):.2f}, n={stat.get('n','?')})\n")
        if ts_surv:
            lines.append("| ميزة | IC_OOS | q | d | WF | E_top | E_bot |\n")
            lines.append("|------|--------|---|---|----|-------|-------|\n")
            for s in ts_surv:
                ic  = f"{s.get('ic_oos', 0):+.3f}"
                qv  = f"{s.get('q_value', 1):.3f}"
                dv  = f"{s.get('cohen_d', 0):+.3f}"
                wf  = "ثابت" if s.get("wf_consistent") else "متقلّب"
                et  = f"{s.get('exp_top_ret', 0):+.3f}"
                eb  = f"{s.get('exp_bot_ret', 0):+.3f}"
                lines.append(f"| {s['feature']} | {ic} | {qv} | {dv} | {wf} | {et} | {eb} |\n")
        else:
            lines.append("لا ناجيات صارمة.\n")
        if ts_bord:
            lines.append(f"\nحدّية (q<0.1): {', '.join(s['feature'] for s in ts_bord[:5])}\n")
        lines.append("\n")

    with open(OUTPUT_MD, "w") as f:
        f.writelines(lines)
    print(f"[INFO] التقرير: {OUTPUT_MD}")

    return output


if __name__ == "__main__":
    main()
