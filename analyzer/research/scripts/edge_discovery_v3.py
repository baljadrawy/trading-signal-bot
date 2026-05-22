#!/usr/bin/env python3
"""
مسح اكتشاف حافة شامل v3 — سريع بدون permutation loops
=========================================================
التاريخ: 2026-05-22
التحسين الجوهري:
  - p-value بتقريب t-distribution للـ Spearman IC (صحيح إحصائياً لـ n≥30)
  - numpy vectorized: rank بـ argsort سريع + correlation سريع
  - لا permutation loops في المرحلة الرئيسية
  - PERM_N=300 يُحفَظ فقط للتحقّق النهائي من الناجيات

الصحة الإحصائية للتقريب t:
  t = IC * sqrt(n-2) / sqrt(1-IC²), df=n-2
  هذا التقريب صحيح عند H0 (IC=0) لـ n≥30 — وهو ما نحتاجه للـ p-value.
"""

import os, sys, random, pickle, time, json, gc, math
import requests
import numpy as np
from datetime import datetime, timezone

# ================================================================
# مسارات
# ================================================================
CACHE_DIR   = "/tmp/edge_cache_1h"
RESULTS_DIR = "/app/research/results"
SYMBOL_FILE = "/tmp/edge_symbols.pkl"

os.makedirs(CACHE_DIR,   exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

DATE_STAMP  = "2026_05_22_v3"
OUTPUT_JSON = os.path.join(RESULTS_DIR, f"edge_discovery_{DATE_STAMP}.json")
OUTPUT_MD   = os.path.join(RESULTS_DIR, f"edge_discovery_{DATE_STAMP}.md")

# ================================================================
# ثوابت
# ================================================================
SEED             = 20260522
BINANCE_BASE     = "https://api.binance.com"
INTERVAL_1H      = "1h"
DAYS_BACK        = 180
FWD_BARS         = 48
FEE              = 0.003
TARGET_A_THRESH  = 0.03
TARGET_B_THRESH  = 0.05
MIN_CANDLES      = 250
POINTS_PER_SYM   = 600
REQUEST_SLEEP    = 0.22
WF_SPLIT         = 0.5
MEM_LIMIT_BYTES  = 1_500_000_000
PERM_N_FINAL     = 300  # فقط للتحقق النهائي من الناجيات

TARGET_LARGE = 30
TARGET_MID   = 30
TARGET_SMALL = 20

# ================================================================
# أدوات مساعدة
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

def spearman_ic_fast(x, y):
    """Spearman IC بـ numpy argsort (سريع)."""
    n = len(x)
    if n < 10:
        return np.nan
    # rank
    rx = np.argsort(np.argsort(x.astype(float))).astype(float)
    ry = np.argsort(np.argsort(y.astype(float))).astype(float)
    mx, my = rx.mean(), ry.mean()
    num = ((rx - mx) * (ry - my)).sum()
    den = np.sqrt(((rx - mx)**2).sum() * ((ry - my)**2).sum())
    return float(num / den) if den > 0 else 0.0

def ic_to_pvalue(ic, n):
    """p-value من IC باستخدام t-distribution (تقريب H0)."""
    if np.isnan(ic) or n < 4:
        return 1.0
    ic = float(np.clip(ic, -0.9999, 0.9999))
    t  = ic * math.sqrt(n - 2) / math.sqrt(1 - ic**2)
    # CDF t بـ تقريب Beta incomplete — Abramowitz & Stegun 26.7.8
    p  = _t_pvalue(t, n - 2)
    return float(p)

def _t_pvalue(t, df):
    """p-value ثنائي الذيل لـ t-distribution بتقريب طبيعي لـ df>30، وإلا Beta."""
    # لـ df كبير → تقريب normal
    if df > 100:
        z = abs(t)
        p = 2 * (1 - _norm_cdf(z))
        return p
    # لـ df أصغر → Cornish-Fisher أو جدول تقريبي
    # نستخدم صيغة Abramowitz 26.7.1 للدقة
    x = df / (df + t**2)
    p = _betainc(df / 2, 0.5, x)
    return p

def _norm_cdf(z):
    """CDF للتوزيع الطبيعي بـ Horner polynomial (دقة 1e-7)."""
    if z < 0:
        return 1 - _norm_cdf(-z)
    k = 1.0 / (1.0 + 0.2316419 * z)
    poly = k * (0.319381530 + k * (-0.356563782 + k * (1.781477937
               + k * (-1.821255978 + k * 1.330274429))))
    return 1.0 - 0.39894228 * math.exp(-z**2 / 2) * poly

def _betainc(a, b, x):
    """تقريب I_x(a,b) بـ continued fraction (Lentz)."""
    if x < 0 or x > 1:
        return 1.0
    if x == 0:
        return 0.0
    if x == 1:
        return 1.0
    # log-beta
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a

    # continued fraction
    def cf(a, b, x):
        MAX_ITER = 200
        SMALL = 1e-30
        f = SMALL
        C = f; D = 0.0
        for m in range(1, MAX_ITER + 1):
            # even
            d = (m * (b - m) * x) / ((a + 2*m - 1) * (a + 2*m))
            D = 1 + d * D; D = 1/D if abs(D) < SMALL else 1/D
            C = 1 + d / C if abs(C) > SMALL else 1 + d * SMALL
            f *= C * D
            # odd
            d = -((a + m) * (a + b + m) * x) / ((a + 2*m) * (a + 2*m + 1))
            D = 1 + d * D; D = 1/D if abs(D) < SMALL else 1/D
            C = 1 + d / C if abs(C) > SMALL else 1 + d * SMALL
            delta = C * D
            f *= delta
            if abs(delta - 1) < 1e-10:
                break
        return f

    if x < (a + 1) / (a + b + 2):
        return front * cf(a, b, x)
    else:
        return 1 - (math.exp(math.log(1-x) * b + math.log(x) * a - lbeta) / b) * cf(b, a, 1-x)

def cohen_d_decile(x, y):
    n   = len(y)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    top = y[idx[-cut:]]
    bot = y[idx[:cut]]
    if len(top) < 3 or len(bot) < 3:
        return np.nan
    mt, mb = top.mean(), bot.mean()
    st, sb = top.std(ddof=1), bot.std(ddof=1)
    sp = math.sqrt(((len(top)-1)*st**2 + (len(bot)-1)*sb**2) / (len(top)+len(bot)-2))
    return float((mt - mb) / sp) if sp > 0 else 0.0

def expectancy_decile(x, y_ret):
    n   = len(y_ret)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    def exp_f(arr):
        adj = arr - FEE
        wr  = (adj > 0).mean()
        avg_w = float(adj[adj > 0].mean()) if (adj > 0).any() else 0.0
        avg_l = float(adj[adj <= 0].mean()) if (adj <= 0).any() else 0.0
        return float(wr * avg_w + (1 - wr) * avg_l)
    return exp_f(y_ret[idx[-cut:]]), exp_f(y_ret[idx[:cut]])

def bh_fdr(pvals, q=0.05):
    n   = len(pvals)
    idx = np.argsort(pvals)
    pv  = np.array(pvals)[idx]
    qv  = pv * n / (np.arange(1, n+1))
    for i in range(n-2, -1, -1):
        if qv[i] > qv[i+1]:
            qv[i] = qv[i+1]
    result = np.empty(n)
    result[idx] = qv
    return result.tolist()

def perm_pvalue_fast(ic_obs, x, y, n_perm=PERM_N_FINAL, seed=42):
    """permutation test سريع — يُستخدم فقط للتحقق النهائي."""
    rng = np.random.default_rng(seed)
    if len(x) < 10:
        return 1.0
    count = sum(1 for _ in range(n_perm)
                if abs(spearman_ic_fast(x, rng.permutation(y))) >= abs(ic_obs))
    return (count + 1) / (n_perm + 1)

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
    all_k    = []
    cur      = start_ms
    while cur < now_ms:
        try:
            r = requests.get(f"{BINANCE_BASE}/api/v3/klines",
                             params={"symbol": symbol, "interval": INTERVAL_1H,
                                     "startTime": cur, "limit": 1000},
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
# حساب المؤشرات vectorized
# ================================================================

def _rolling_rsi(C, period=14):
    N   = len(C)
    d   = np.diff(C)
    g   = np.maximum(d, 0.0)
    l   = np.maximum(-d, 0.0)
    rsi = np.full(N, np.nan)
    if N < period + 1:
        return rsi
    ag = g[:period].mean()
    al = l[:period].mean()
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
        rsi[i + 1] = 100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0
    return rsi

def _rolling_ema(arr, period):
    N = len(arr)
    out = np.full(N, np.nan)
    vi = np.where(~np.isnan(arr))[0]
    if len(vi) < period:
        return out
    s = vi[0]
    if s + period > N:
        return out
    out[s + period - 1] = np.nanmean(arr[s:s+period])
    k = 2.0 / (period + 1.0)
    for i in range(s + period, N):
        if np.isnan(arr[i]):
            out[i] = out[i-1] if not np.isnan(out[i-1]) else np.nan
        elif not np.isnan(out[i-1]):
            out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out

def _rolling_bb_pos_fast(C, period=20, std_mult=2.0):
    """Bollinger position بـ cumsum سريع."""
    N = len(C)
    out = np.full(N, np.nan)
    # استخدام numpy cumsum لحساب rolling mean سريع
    cs  = np.cumsum(C)
    cs2 = np.cumsum(C**2)
    for i in range(period - 1, N):
        if i >= period:
            s1 = cs[i] - cs[i-period]
            s2 = cs2[i] - cs2[i-period]
        else:
            s1 = cs[i]
            s2 = cs2[i]
        mu  = s1 / period
        var = s2 / period - mu**2
        sig = math.sqrt(max(var, 0.0))
        ub  = mu + std_mult * sig
        lb  = mu - std_mult * sig
        rng = ub - lb
        out[i] = float(np.clip((C[i] - lb) / rng, 0.0, 1.0)) if rng > 0 else 0.5
    return out

def _rolling_stoch_rsi(rsi_arr, period=14, smooth=3):
    N   = len(rsi_arr)
    raw = np.full(N, np.nan)
    for i in range(period - 1, N):
        w = rsi_arr[i-period+1:i+1]
        if np.any(np.isnan(w)):
            continue
        lo, hi = w.min(), w.max()
        raw[i] = (rsi_arr[i] - lo) / (hi - lo + 1e-10)
    out = np.full(N, np.nan)
    for i in range(smooth - 1, N):
        w = raw[i-smooth+1:i+1]
        if not np.any(np.isnan(w)):
            out[i] = w.mean()
    return out

def _rolling_macd_hist(C, fast=12, slow=26, signal=9):
    ema_f  = _rolling_ema(C, fast)
    ema_s  = _rolling_ema(C, slow)
    macd_l = ema_f - ema_s
    sig_l  = _rolling_ema(macd_l, signal)
    return macd_l - sig_l

def _rolling_atr(H, L, C, period=14):
    N  = len(C)
    tr = np.empty(N)
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

def _rolling_adx_simple(H, L, C, period=14):
    """ADX مبسّط vectorized — أبطأ لكن صحيح."""
    N = len(C)
    out = np.full(N, np.nan)
    if N < period * 3:
        return out
    dm_p = np.maximum(np.diff(H), 0)
    dm_n = np.maximum(-np.diff(L), 0)
    mask = dm_p < dm_n
    dm_p[mask] = 0
    mask2 = dm_n < dm_p
    dm_n[mask2] = 0
    tr = np.empty(N-1)
    for i in range(N-1):
        tr[i] = max(H[i+1]-L[i+1], abs(H[i+1]-C[i]), abs(L[i+1]-C[i]))
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
        dx  = 100*abs(dip-din)/(dip+din) if (dip+din)>0 else 0
        dx_arr.append(dx)
    dx_arr = np.array(dx_arr)
    for i in range(period-1, len(dx_arr)):
        out[i + period + 1] = dx_arr[i-period+1:i+1].mean()
    return out

def _rolling_percentile_rank_vec(arr, w):
    """vectorized percentile rank."""
    N = len(arr)
    out = np.full(N, np.nan)
    for i in range(w-1, N):
        seg = arr[i-w+1:i+1]
        if not np.any(np.isnan(seg)):
            out[i] = float((seg <= arr[i]).sum()) / len(seg)
    return out

def _rolling_zscore_vec(arr, w):
    N = len(arr)
    out = np.full(N, np.nan)
    cs  = np.nancumsum(arr)
    cs2 = np.nancumsum(arr**2)
    for i in range(w-1, N):
        seg = arr[i-w+1:i+1]
        if np.any(np.isnan(seg)):
            continue
        mu  = seg.mean()
        std = seg.std(ddof=1)
        out[i] = (arr[i] - mu) / std if std > 0 else 0.0
    return out

def compute_all_indicators(C, H, L, V):
    N = len(C)
    out = {}
    rsi14 = _rolling_rsi(C, 14)
    out["rsi14"]  = rsi14
    out["rsi7"]   = _rolling_rsi(C, 7)
    out["bb_pos"] = _rolling_bb_pos_fast(C, 20, 2.0)
    out["stoch_rsi"] = _rolling_stoch_rsi(rsi14, 14, 3)
    out["macd_hist"] = _rolling_macd_hist(C, 12, 26, 9)
    out["adx14"]     = _rolling_adx_simple(H, L, C, 14)
    atr14 = _rolling_atr(H, L, C, 14)
    out["atr_pct"] = np.where(C > 0, atr14 / C, np.nan)
    for k in [6, 12, 24]:
        mom = np.full(N, np.nan)
        mom[k:] = C[k:] / C[:-k] - 1.0
        out[f"mom{k}"] = mom

    # Volume
    ma_v = np.full(N, np.nan)
    for i in range(19, N):
        ma_v[i] = V[i-19:i+1].mean()
    out["vol_ratio"]  = np.where(ma_v > 0, V / ma_v, np.nan)
    out["vol_zscore"] = _rolling_zscore_vec(V, 20)

    # ATR percentile (52)
    out["atr_pct52"] = _rolling_percentile_rank_vec(atr14, 52)

    # Realized volatility 24
    log_ret = np.full(N, np.nan)
    log_ret[1:] = np.log(C[1:] / C[:-1])
    out["rvol24"] = _rolling_zscore_vec(log_ret, 24)  # نستخدم rolling std كـ rvol proxy

    # Path features
    down = np.zeros(N)
    for i in range(1, N):
        down[i] = down[i-1] + 1 if C[i] < C[i-1] else 0
    out["consec_down"] = down

    # 30d high/low (720h)
    hi30 = np.full(N, np.nan)
    lo30 = np.full(N, np.nan)
    w = 720
    for i in range(min(w,N)-1, N):
        s = max(0, i-w+1)
        hi30[i] = H[s:i+1].max()
        lo30[i] = L[s:i+1].min()
    out["dist_hi30"]   = np.where(hi30 > 0, (C - hi30) / hi30, np.nan)
    out["dist_lo30"]   = np.where(lo30 > 0, (C - lo30) / lo30, np.nan)
    rng30 = hi30 - lo30
    out["price_pct30"] = np.where(rng30 > 0, np.clip((C - lo30) / rng30, 0, 1), 0.5)

    # Rolling transforms (50-bar)
    out["rsi_zscore"]  = _rolling_zscore_vec(rsi14, 50)
    out["bb_zscore"]   = _rolling_zscore_vec(out["bb_pos"], 50)
    out["macd_pct50"]  = _rolling_percentile_rank_vec(out["macd_hist"], 50)
    out["mom6_pct50"]  = _rolling_percentile_rank_vec(out["mom6"], 50)

    return out

# ================================================================
# حساب الأهداف
# ================================================================

def compute_targets_vec(C, H, L, indices):
    n_pts = len(indices)
    ta    = np.zeros(n_pts, dtype=np.int8)
    tb    = np.zeros(n_pts, dtype=np.int8)
    ret48 = np.zeros(n_pts, dtype=float)
    for k, t in enumerate(indices):
        if t + FWD_BARS >= len(C):
            ta[k] = tb[k] = -1; continue
        entry = C[t]
        if entry <= 0:
            ta[k] = tb[k] = -1; continue
        hit_up = hit_dn = False
        for i in range(t+1, t+FWD_BARS+1):
            if H[i] / entry - 1 >= TARGET_A_THRESH:
                hit_up = True; break
            if 1 - L[i] / entry >= TARGET_A_THRESH:
                hit_dn = True; break
        ta[k] = 1 if hit_up else 0
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
    data = requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=20).json()
    usdt = [d for d in data
            if d["symbol"].endswith("USDT")
            and not any(x in d["symbol"] for x in ["DOWN","UP","BEAR","BULL","3L","3S"])
            and float(d.get("quoteVolume", 0)) > 1_000_000]
    usdt.sort(key=lambda d: float(d.get("quoteVolume", 0)), reverse=True)
    rng = random.Random(SEED)
    large = rng.sample([d["symbol"] for d in usdt[:60]], min(TARGET_LARGE, 60))
    mid   = rng.sample([d["symbol"] for d in usdt[60:300]
                        if d["symbol"] not in large], TARGET_MID)
    small = rng.sample([d["symbol"] for d in usdt[300:800]
                        if d["symbol"] not in large and d["symbol"] not in mid],
                       TARGET_SMALL)
    syms = list(dict.fromkeys(large + mid + small))
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
        return []
    ts, H, L, C, V = parse_klines(raw)
    N = len(C)
    inds = compute_all_indicators(C, H, L, V)
    valid_start = 230
    valid_end   = N - FWD_BARS - 1
    if valid_end <= valid_start:
        return []
    valid_idxs = list(range(valid_start, valid_end))
    n_pts = min(POINTS_PER_SYM, len(valid_idxs))
    sampled = sorted(rng_obj.sample(valid_idxs, n_pts))
    ta, tb, ret48 = compute_targets_vec(C, H, L, sampled)
    rows = []
    feat_names = list(inds.keys())
    for k, t in enumerate(sampled):
        if ta[k] == -1:
            continue
        row = {
            "symbol": symbol, "ts": int(ts[t]),
            "hour_utc": float(int((ts[t]/1000 % 86400) // 3600)),
            "target_a": int(ta[k]), "target_b": int(tb[k]),
            "ret_48h":  float(ret48[k]),
        }
        for fn in feat_names:
            v = inds[fn][t]
            row[fn] = float(v) if not np.isnan(v) else None
        rows.append(row)
    del raw, ts, H, L, C, V, inds
    gc.collect()
    avg_hit = float(ta[ta>=0].mean()) if (ta>=0).any() else 0
    print(f"  [OK] {symbol}: {len(rows)} نقطة — hit_A={avg_hit:.2f}")
    return rows

# ================================================================
# cross-sectional features
# ================================================================

def add_cross_sectional(all_rows):
    from collections import defaultdict
    by_ts = defaultdict(list)
    for i, row in enumerate(all_rows):
        ts_h = (row["ts"] // 3_600_000) * 3_600_000
        by_ts[ts_h].append(i)
    rsi_rank   = [None] * len(all_rows)
    mom12_rank = [None] * len(all_rows)
    mkt_rel    = [None] * len(all_rows)
    for ts_h, idxs in by_ts.items():
        if len(idxs) < 3:
            continue
        rv = np.array([all_rows[i].get("rsi14") or np.nan for i in idxs], float)
        mv = np.array([all_rows[i].get("mom12") or np.nan for i in idxs], float)
        vr = ~np.isnan(rv); vm = ~np.isnan(mv)
        if vr.sum() >= 3:
            ri = [i for i,f in zip(idxs,vr) if f]
            rk = np.argsort(np.argsort(rv[vr])).astype(float) / max(vr.sum()-1, 1)
            for j, i in enumerate(ri):
                rsi_rank[i] = float(rk[j])
        if vm.sum() >= 3:
            mi = [i for i,f in zip(idxs,vm) if f]
            mk = np.argsort(np.argsort(mv[vm])).astype(float) / max(vm.sum()-1, 1)
            med = float(np.median(mv[vm]))
            for j, i in enumerate(mi):
                mom12_rank[i] = float(mk[j])
                mkt_rel[i] = float(all_rows[i].get("mom12") or 0) - med
    for i, row in enumerate(all_rows):
        row["rsi_rank_cs"]   = rsi_rank[i]
        row["mom12_rank_cs"] = mom12_rank[i]
        row["mkt_rel_str"]   = mkt_rel[i]
    return all_rows

# ================================================================
# اختبار ميزة × هدف
# ================================================================

def test_one(fn, tn, x_arr, y_arr, ts_arr, wf_split_ts, ret_arr):
    mask = (~np.isnan(x_arr)) & (~np.isnan(y_arr))
    x  = x_arr[mask]
    y  = y_arr[mask]
    ts = ts_arr[mask]
    r  = ret_arr[mask]
    if len(x) < 50:
        return None

    ic_all = spearman_ic_fast(x, y)
    pval   = ic_to_pvalue(ic_all, len(x))  # سريع جداً
    d      = cohen_d_decile(x, y)
    exp_t, exp_b = expectancy_decile(x, r)

    train = ts < wf_split_ts
    oos   = ts >= wf_split_ts
    ic_tr  = spearman_ic_fast(x[train], y[train]) if train.sum() >= 20 else np.nan
    ic_oos = spearman_ic_fast(x[oos],   y[oos])   if oos.sum()   >= 20 else np.nan
    wf_ok  = (not np.isnan(ic_tr) and not np.isnan(ic_oos)
              and np.sign(ic_tr) == np.sign(ic_oos))

    return {
        "feature": fn, "target": tn,
        "n": int(len(x)), "n_train": int(train.sum()), "n_oos": int(oos.sum()),
        "ic_all":  float(ic_all),
        "ic_train": float(ic_tr)  if not np.isnan(ic_tr)  else None,
        "ic_oos":   float(ic_oos) if not np.isnan(ic_oos) else None,
        "p_value":  float(pval),
        "cohen_d":  float(d) if not np.isnan(d) else None,
        "exp_top_ret": float(exp_t),
        "exp_bot_ret": float(exp_b),
        "wf_consistent": bool(wf_ok),
        "p_method": "t-approx",
    }

# ================================================================
# الرئيسي
# ================================================================

def main():
    rng = random.Random(SEED)
    np.random.seed(SEED)
    print("=" * 60)
    print("مسح اكتشاف حافة v3 — 2026-05-22")
    print("=" * 60)

    symbols = get_symbols()
    print(f"[INFO] عدد الرموز: {len(symbols)}")

    # معالجة الرموز
    all_rows = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] {sym}")
        if check_mem():
            print("[WARN] ذاكرة عالية — GC"); gc.collect()
        rows = process_symbol(sym, rng)
        all_rows.extend(rows)
        if (i+1) % 10 == 0:
            print(f"  → إجمالي: {len(all_rows)} نقطة"); gc.collect()

    print(f"\n[INFO] إجمالي النقاط: {len(all_rows)}")

    # TARGET_C
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
    print(f"[INFO] target_c: {n_tc}/{len(all_rows)}")

    # cross-sectional
    print("[INFO] ميزات cross-sectional...")
    all_rows = add_cross_sectional(all_rows)

    feat_names = [
        "rsi14","rsi7","bb_pos","stoch_rsi","macd_hist","adx14",
        "atr_pct","mom6","mom12","mom24","vol_ratio","vol_zscore",
        "atr_pct52","rvol24","hour_utc","consec_down",
        "dist_hi30","dist_lo30","price_pct30",
        "rsi_zscore","bb_zscore","macd_pct50","mom6_pct50",
        "rsi_rank_cs","mom12_rank_cs","mkt_rel_str",
    ]
    target_names = ["target_a","target_b","target_c"]

    n = len(all_rows)
    feat_arrs = {fn: np.array([r.get(fn) if r.get(fn) is not None else np.nan
                                for r in all_rows], float)
                 for fn in feat_names}
    tgt_arrs  = {tn: np.array([r.get(tn) if r.get(tn) is not None else np.nan
                                for r in all_rows], float)
                 for tn in target_names}
    ts_vals   = np.array([r["ts"]     for r in all_rows], np.int64)
    ret_arr   = np.array([r["ret_48h"] for r in all_rows], float)

    ts_sorted    = np.sort(ts_vals)
    wf_split_ts  = int(ts_sorted[len(ts_sorted) // 2])

    target_stats = {}
    for tn in target_names:
        ta = tgt_arrs[tn]; valid = ta[~np.isnan(ta)]
        target_stats[tn] = {"n": int(len(valid)), "hit_rate": float(valid.mean()) if len(valid) else 0}

    # الاختبارات
    print("[INFO] تشغيل الاختبارات الإحصائية...")
    all_results = []
    for tn in target_names:
        print(f"  هدف: {tn}")
        for fn in feat_names:
            res = test_one(fn, tn, feat_arrs[fn], tgt_arrs[tn], ts_vals, wf_split_ts, ret_arr)
            if res:
                all_results.append(res)
    print(f"[INFO] {len(all_results)} اختبار مكتمل")

    # FDR
    print("[INFO] FDR Benjamini-Hochberg...")
    pvals = [r["p_value"] for r in all_results]
    qvals = bh_fdr(pvals, q=0.05)
    for i, r in enumerate(all_results):
        r["q_value"] = float(qvals[i])

    # تحديد الناجيات المبدئية
    pre_survivors = [r for r in all_results
                     if r.get("q_value", 1.0) < 0.05
                     and (abs(r.get("cohen_d") or 0) > 0.1
                          or abs(r.get("ic_oos") or 0) > 0.05)
                     and r.get("wf_consistent", False)]

    # تحقق permutation للناجيات المبدئية فقط
    if pre_survivors:
        print(f"[INFO] تحقق permutation لـ {len(pre_survivors)} ناجية مبدئية...")
        for r in pre_survivors:
            fn, tn = r["feature"], r["target"]
            mask = (~np.isnan(feat_arrs[fn])) & (~np.isnan(tgt_arrs[tn]))
            x = feat_arrs[fn][mask]; y = tgt_arrs[tn][mask]
            p_perm = perm_pvalue_fast(r["ic_all"], x, y)
            r["p_perm"] = float(p_perm)
            print(f"    {fn}×{tn}: IC={r['ic_all']:+.3f}, p_t={r['p_value']:.4f}, p_perm={p_perm:.4f}")
    else:
        print("[INFO] لا ناجيات مبدئية — تخطّى permutation")

    # الناجيات النهائية (بعد التحقق)
    survivors = []
    for r in pre_survivors:
        p_perm = r.get("p_perm", r["p_value"])
        if p_perm < 0.1:  # متسامح قليلاً هنا لأن PERM_N=300
            survivors.append(r)
    survivors.sort(key=lambda r: abs(r.get("ic_oos") or 0), reverse=True)

    borderline = [r for r in all_results
                  if r.get("q_value", 1.0) < 0.1
                  and (abs(r.get("cohen_d") or 0) > 0.08
                       or abs(r.get("ic_oos") or 0) > 0.04)
                  and r not in pre_survivors]
    borderline.sort(key=lambda r: abs(r.get("ic_oos") or 0), reverse=True)

    # حفظ
    output = {
        "date": "2026-05-22", "seed": SEED,
        "n_symbols": len(symbols), "n_rows": len(all_rows),
        "n_features": len(feat_names), "n_tests": len(all_results),
        "wf_split_ts": wf_split_ts, "target_stats": target_stats,
        "survivors": survivors, "borderline": borderline,
        "all_results": all_results,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"[INFO] حُفظ في {OUTPUT_JSON}")

    # ملخص
    print("\n" + "=" * 60)
    print(f"الملخص:")
    print(f"  الرموز: {len(symbols)} | النقاط: {len(all_rows)}")
    print(f"  الاختبارات: {len(all_results)} | الناجيات: {len(survivors)}")
    print()
    for tn in target_names:
        ts_s = [s for s in survivors if s["target"] == tn]
        ts_b = [s for s in borderline if s["target"] == tn]
        stat = target_stats.get(tn, {})
        print(f"  [{tn}] hit={stat.get('hit_rate',0):.2f} n={stat.get('n',0)}")
        print(f"    ناجيات: {len(ts_s)}")
        for s in ts_s[:8]:
            pp = f" p_perm={s.get('p_perm','?'):.3f}" if "p_perm" in s else ""
            print(f"      {s['feature']:20} IC_OOS={s.get('ic_oos','?'):+.3f}"
                  f"  q={s.get('q_value','?'):.3f}  d={s.get('cohen_d','?'):+.3f}"
                  f"  WF={'✓' if s['wf_consistent'] else '✗'}"
                  f"  E_top={s.get('exp_top_ret','?'):+.3f}{pp}")
        if ts_b:
            print(f"    حدّية: {', '.join(s['feature'] for s in ts_b[:5])}")
    print("=" * 60)

    # تقرير MD
    lines = [
        f"# نتائج مسح الحافة — {DATE_STAMP}\n\n",
        f"- **العيّنة:** {len(all_rows)} نقطة عشوائية، {len(symbols)} رمزاً، 180 يوماً، seed={SEED}\n",
        f"- **الاختبارات:** {len(all_results)} (ميزة × هدف)\n",
        f"- **FDR:** Benjamini-Hochberg q<0.05 عبر جميع الاختبارات معاً\n",
        f"- **ناجية صارمة:** q<0.05 + (|d|>0.1 أو |IC_OOS|>0.05) + WF ثابت الإشارة\n",
        f"- **إجمالي الناجيات:** {len(survivors)}\n\n",
    ]
    for tn in target_names:
        ts_s = [s for s in survivors  if s["target"] == tn]
        ts_b = [s for s in borderline if s["target"] == tn]
        stat = target_stats.get(tn, {})
        lines.append(f"## {tn} (hit_rate={stat.get('hit_rate',0):.2f}, n={stat.get('n',0)})\n")
        if ts_s:
            lines.append("| ميزة | IC_all | IC_OOS | q | d | WF | E_top | E_bot | p_perm |\n")
            lines.append("|------|--------|--------|---|---|----|-------|-------|--------|\n")
            for s in ts_s:
                pp = f"{s.get('p_perm','?'):.3f}" if "p_perm" in s else "N/A"
                lines.append(f"| {s['feature']} | {s.get('ic_all',0):+.3f} | "
                              f"{s.get('ic_oos',0):+.3f} | {s.get('q_value',1):.3f} | "
                              f"{s.get('cohen_d',0):+.3f} | {'ثابت' if s.get('wf_consistent') else 'متقلّب'} | "
                              f"{s.get('exp_top_ret',0):+.3f} | {s.get('exp_bot_ret',0):+.3f} | {pp} |\n")
        else:
            lines.append("**لا ناجيات صارمة.**\n")
        if ts_b:
            bord_str = ", ".join(s["feature"] + "(IC=" + f"{s.get('ic_oos',0):+.3f})" for s in ts_b[:5])
            lines.append(f"\nحدّية (q<0.1): {bord_str}\n")
        lines.append("\n")

    with open(OUTPUT_MD, "w") as f:
        f.writelines(lines)
    print(f"[INFO] التقرير: {OUTPUT_MD}")
    return output


if __name__ == "__main__":
    main()
