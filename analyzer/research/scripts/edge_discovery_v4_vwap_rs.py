#!/usr/bin/env python3
"""
مسح اكتشاف حافة v4 — VWAP-derived + Relative Strength
=======================================================
التاريخ: 2026-05-23
الاختلاف عن v3:
  - ميزات VWAP + Relative Strength (نوعياً مختلفة عن المؤشرات الكلاسيكية)
  - إطار 1h + سياق BTC للـ regime
  - أهداف أوسع: +5%/−5% خلال 7 أيام
  - تصحيحات إحصائية رئيسية مقارنة بالمحاولة الأولى:
      1. expectancy_decile يستخدم العائد الحقيقي (ret_7d) لا binary label
      2. target_B (تذبذب لا اتجاه) محذوف — غير قابل للتنفيذ long-only
      3. الميزات cross-coin (btc_regime, market_breadth, rs_btc_corr_30d)
         تُحلَّل بعد dedup على timestamp (effective n ≠ 93k)
      4. Walk-Forward بـ calendar cutoff زمني ثابت (لا positional split)

ملاحظة: الكاش موجود في /tmp/edge_cache_1h/ (4320 شمعة 1h × 59 رمزاً، 180 يوم)
"""

import os, sys, random, pickle, time, json, gc, math
import numpy as np
from datetime import datetime, timezone, timedelta

# ================================================================
# مسارات
# ================================================================
CACHE_1H_DIR  = "/tmp/edge_cache_1h"
RESULTS_DIR   = "/app/research/results"

os.makedirs(RESULTS_DIR, exist_ok=True)

DATE_STAMP  = "2026_05_23_v4"
OUTPUT_JSON = os.path.join(RESULTS_DIR, f"edge_discovery_{DATE_STAMP}.json")

# ================================================================
# ثوابت
# ================================================================
SEED          = 20260523
DAYS_BACK     = 180
FEE           = 0.003           # 0.3% رسوم ذهاباً + إياباً

# الأهداف: أفق 7 أيام (168 شمعة 1h)
FWD_HOURS     = 168
TARGET_A_PCT  = 0.05            # +5% قبل -5%

POINTS_PER_SYM = 1800           # عيّنة لكل رمز
WF_CALENDAR_SPLIT = 90          # أول 90 يوم IS، آخر 90 يوم OOS

BTC_DROP_THRESH = -0.03         # عتبة rs_btc_stress
MIN_COND_N      = 500           # الحد الأدنى للميزات الشرطية

# ================================================================
# أدوات مساعدة
# ================================================================

def check_mem_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def kline_to_row(k):
    """تحويل Binance kline list إلى dict."""
    return {
        't': int(k[0]),
        'o': float(k[1]),
        'h': float(k[2]),
        'l': float(k[3]),
        'c': float(k[4]),
        'v': float(k[5]),
    }

# ================================================================
# تحميل klines
# ================================================================

def load_1h_klines(symbol):
    """تحميل 1h klines من كاش v3 (/tmp/edge_cache_1h)."""
    path = os.path.join(CACHE_1H_DIR, f"{symbol}_1h.pkl")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        raw = pickle.load(f)
    if raw and isinstance(raw[0], list):
        return [kline_to_row(k) for k in raw]
    return raw

def klines_to_arrays(klines):
    """تحويل list of dicts إلى numpy arrays مرتّبة زمنياً."""
    if not klines:
        return None
    klines.sort(key=lambda x: x['t'])
    n  = len(klines)
    t  = np.array([k['t']  for k in klines], dtype=np.int64)
    c  = np.array([k['c']  for k in klines], dtype=np.float64)
    v  = np.array([k.get('v', 0.0) for k in klines], dtype=np.float64)
    h  = np.array([k['h']  for k in klines], dtype=np.float64)
    lo = np.array([k['l']  for k in klines], dtype=np.float64)
    return {'t': t, 'c': c, 'v': v, 'h': h, 'l': lo, 'n': n}

# ================================================================
# حساب الميزات
# ================================================================

def compute_vwap_window(arr, window):
    """VWAP منزلق على آخر window شمعة (no lookahead)."""
    c, v = arr['c'], arr['v']
    n = len(c)
    vwap = np.full(n, np.nan)
    for i in range(window, n):
        sc = c[i - window: i]
        sv = v[i - window: i]
        tv = sv.sum()
        vwap[i] = (sc * sv).sum() / tv if tv > 0 else sc.mean()
    return vwap

def compute_atr(arr, period=24):
    """ATR منزلق."""
    h, lo, c = arr['h'], arr['l'], arr['c']
    n = len(c)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    atr = np.full(n, np.nan)
    for i in range(period, n):
        atr[i] = tr[i - period: i].mean()
    return atr

def compute_ret(arr, lag):
    """عائد بعد lag bars (لا lookahead — يُحسب من bar i-lag)."""
    c = arr['c']
    n = len(c)
    ret = np.full(n, np.nan)
    for i in range(lag, n):
        if c[i - lag] > 0:
            ret[i] = (c[i] / c[i - lag]) - 1.0
    return ret

def compute_ema(arr, period):
    """EMA على close."""
    c = arr['c']
    n = len(c)
    ema = np.full(n, np.nan)
    k = 2.0 / (period + 1)
    if n >= period:
        ema[period - 1] = c[:period].mean()
        for i in range(period, n):
            ema[i] = c[i] * k + ema[i-1] * (1 - k)
    return ema

def align_arrays(ref_t, src_t, src_vals):
    """مُحاذاة src_vals على ref_t — يجلب آخر قيمة ≤ ref_t[i]."""
    out = np.full(len(ref_t), np.nan)
    j = 0
    src_n = len(src_t)
    for i, t in enumerate(ref_t):
        while j < src_n - 1 and src_t[j + 1] <= t:
            j += 1
        if src_t[j] <= t:
            out[i] = src_vals[j]
    return out

# ================================================================
# الأهداف
# ================================================================

def compute_targets_a_c(arr):
    """
    tA: +5% قبل -5% خلال 168 ساعة
    ret_fwd: العائد الفعلي بعد 168 ساعة (لحساب E الحقيقي)
    """
    c = arr['c']
    n = len(c)
    tA     = np.full(n, np.nan)
    ret_fwd = np.full(n, np.nan)

    for i in range(n - FWD_HOURS - 1):
        entry  = c[i]
        if entry <= 0:
            continue
        future = c[i+1: i+1+FWD_HOURS]
        ret    = (future / entry) - 1.0

        # target A
        hit_up   = np.where(ret >= TARGET_A_PCT)[0]
        hit_down = np.where(ret <= -TARGET_A_PCT)[0]
        if len(hit_up) > 0 and (len(hit_down) == 0 or hit_up[0] < hit_down[0]):
            tA[i] = 1.0
        elif len(hit_down) > 0:
            tA[i] = 0.0
        # else: np.nan (لم يصل لأي طرف)

        # العائد الحقيقي (لـ expectancy)
        ret_fwd[i] = float(ret[-1])

    return tA, ret_fwd

# ================================================================
# إحصائيات
# ================================================================

def spearman_ic(x, y):
    n = len(x)
    if n < 10:
        return np.nan
    rx = np.argsort(np.argsort(x.astype(float))).astype(float)
    ry = np.argsort(np.argsort(y.astype(float))).astype(float)
    mx, my = rx.mean(), ry.mean()
    num = ((rx - mx) * (ry - my)).sum()
    den = np.sqrt(((rx - mx)**2).sum() * ((ry - my)**2).sum())
    return float(num / den) if den > 0 else 0.0

def _norm_cdf(z):
    if z < 0:
        return 1 - _norm_cdf(-z)
    k = 1.0 / (1.0 + 0.2316419 * z)
    p = k * (0.319381530 + k * (-0.356563782 + k * (1.781477937
              + k * (-1.821255978 + k * 1.330274429))))
    return 1.0 - 0.39894228 * math.exp(-z**2 / 2) * p

def _betainc(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x)*a + math.log(1-x)*b - lbeta) / a
    SMALL = 1e-30
    def cf(a, b, x):
        f = SMALL; C = f; D = 0.0
        for m in range(1, 201):
            d  = (m*(b-m)*x) / ((a+2*m-1)*(a+2*m))
            D  = 1/(1+d*D if abs(1+d*D)>SMALL else SMALL)
            C  = 1+d/C if abs(C)>SMALL else 1+d*SMALL
            f *= C*D
            d  = -((a+m)*(a+b+m)*x) / ((a+2*m)*(a+2*m+1))
            D  = 1/(1+d*D if abs(1+d*D)>SMALL else SMALL)
            C  = 1+d/C if abs(C)>SMALL else 1+d*SMALL
            delta = C*D; f *= delta
            if abs(delta-1) < 1e-10: break
        return f
    if x < (a+1)/(a+b+2):
        return front * cf(a, b, x)
    lbeta2 = math.lgamma(b)+math.lgamma(a)-math.lgamma(a+b)
    return 1 - math.exp(math.log(1-x)*b+math.log(x)*a-lbeta2)/b * cf(b, a, 1-x)

def ic_pvalue(ic, n):
    if np.isnan(ic) or n < 4: return 1.0
    ic = float(np.clip(ic, -0.9999, 0.9999))
    t  = ic * math.sqrt(n - 2) / math.sqrt(1 - ic**2)
    df = n - 2
    if df > 100:
        return 2 * (1 - _norm_cdf(abs(t)))
    x = df / (df + t**2)
    return _betainc(df/2, 0.5, x)

def cohen_d_decile(x, y):
    n   = len(y)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    top = y[idx[-cut:]]
    bot = y[idx[:cut]]
    if len(top) < 3 or len(bot) < 3: return np.nan
    mt, mb = top.mean(), bot.mean()
    st, sb = top.std(ddof=1), bot.std(ddof=1)
    sp = math.sqrt(((len(top)-1)*st**2 + (len(bot)-1)*sb**2) / (len(top)+len(bot)-2))
    return float((mt - mb) / sp) if sp > 0 else 0.0

def expectancy_top_decile(x, y_ret_continuous):
    """
    expectancy حقيقي: أخذ أعلى decile من x، احسب متوسط y_ret بعد طرح رسوم.
    y_ret = عائد حقيقي (مثل ret_fwd = c[t+168]/c[t] - 1).
    E = mean(y_ret_top) - FEE
    """
    n   = len(y_ret_continuous)
    cut = max(1, n // 10)
    idx = np.argsort(x)
    top_ret = y_ret_continuous[idx[-cut:]]
    # expectancy: mean return بعد رسوم
    return float(top_ret.mean() - FEE)

def bh_fdr(pvals):
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

# ================================================================
# اختيار الرموز
# ================================================================

def get_symbols():
    stables = {'USDCUSDT', 'USD1USDT', 'RLUSDUSDT', 'UUSDT'}
    files = [f.replace('_1h.pkl','') for f in os.listdir(CACHE_1H_DIR) if f.endswith('_1h.pkl')]
    syms  = [s for s in files if s not in stables and s != 'BTCUSDT']
    syms.sort()
    log(f"عدد الرموز (بعد حذف stables+BTC): {len(syms)}")
    return syms

# ================================================================
# التشغيل الرئيسي
# ================================================================

def main():
    log("=" * 60)
    log("مسح اكتشاف حافة v4b — VWAP + RS (مُصلَح إحصائياً)")
    log(f"التاريخ: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    log("=" * 60)

    rng = np.random.default_rng(SEED)

    # --- 1. الرموز ---
    syms = get_symbols()

    # --- 2. BTC 1h ---
    log("تحميل BTC 1h...")
    btc_raw = load_1h_klines('BTCUSDT')
    if not btc_raw:
        log("خطأ: BTCUSDT غير موجود!")
        return
    arr_btc = klines_to_arrays(btc_raw)
    btc_ret24 = compute_ret(arr_btc, 24)
    btc_ema50 = compute_ema(arr_btc, 50)
    btc_ema200 = compute_ema(arr_btc, 200)
    # btc_regime: +1 bullish (EMA50 > EMA200×1.005), -1 bearish, 0 neutral
    btc_regime_full = np.where(
        ~np.isnan(btc_ema50) & ~np.isnan(btc_ema200),
        np.where(btc_ema50 > btc_ema200 * 1.005, 1.0,
                 np.where(btc_ema50 < btc_ema200 * 0.995, -1.0, 0.0)),
        np.nan)
    log(f"BTC: {arr_btc['n']} شمعة | "
        f"{datetime.fromtimestamp(arr_btc['t'][0]/1000, tz=timezone.utc).strftime('%Y-%m-%d')} → "
        f"{datetime.fromtimestamp(arr_btc['t'][-1]/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")

    # --- 3. تحميل كل الرموز ---
    log("تحميل 1h كل الرموز...")
    all_1h = {}
    for sym in syms:
        raw = load_1h_klines(sym)
        if not raw:
            continue
        arr = klines_to_arrays(raw)
        if arr['n'] < 500:
            continue
        all_1h[sym] = arr
    log(f"رموز محمّلة: {len(all_1h)} | ذاكرة: {check_mem_mb()} MB")

    # --- 4. panel لـ cross-coin features ---
    log("بناء panel for cross-coin features...")
    ts_ref = arr_btc['t']
    n_ts   = len(ts_ref)
    # panel_ret24[sym] = array مُحاذاة على ts_ref
    panel_ret24 = {}
    for sym, arr in all_1h.items():
        r24 = compute_ret(arr, 24)
        panel_ret24[sym] = align_arrays(ts_ref, arr['t'], r24)
    panel_matrix = np.array(list(panel_ret24.values()))  # n_syms × n_ts
    log(f"panel: {panel_matrix.shape[0]} رمز × {panel_matrix.shape[1]} timestamp")

    # market_breadth على ts_ref (deduped cross-coin)
    market_breadth_ts = np.full(n_ts, np.nan)
    for i in range(24, n_ts):
        col = panel_matrix[:, i]
        valid = col[~np.isnan(col)]
        if len(valid) >= 5:
            market_breadth_ts[i] = float(np.mean(valid > 0))

    # btc_regime على ts_ref
    btc_regime_ts = btc_regime_full  # نفس الطول بالفعل

    # --- 5. تحديد حدود WF (calendar-based) ---
    # أول 90 يوم = IS، آخر 90 يوم = OOS
    wf_cutoff_ms = arr_btc['t'][0] + (WF_CALENDAR_SPLIT * 86_400_000)
    log(f"WF split: IS حتى {datetime.fromtimestamp(wf_cutoff_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")

    # --- 6. جمع نقاط العيّنة (per-symbol) ---
    log("جمع نقاط العيّنة...")
    all_points = []
    btc_stress_count = 0

    sym_list = sorted(all_1h.keys())
    for sym in sym_list:
        arr = all_1h[sym]
        t_sym = arr['t']
        n_sym = arr['n']

        # حساب الأهداف
        tA, ret_fwd = compute_targets_a_c(arr)

        # ميزات VWAP
        vwap24  = compute_vwap_window(arr, 24)
        vwap168 = compute_vwap_window(arr, 168)
        atr24   = compute_atr(arr, 24)
        ret24   = compute_ret(arr, 24)

        # v_mean20 لـ vwap_break_vol
        v = arr['v']
        v_mean20 = np.full(n_sym, np.nan)
        for i in range(20, n_sym):
            v_mean20[i] = v[i-20:i].mean()
        prev_c = np.roll(arr['c'], 1); prev_c[0] = np.nan
        prev_vwap24 = np.roll(vwap24, 1); prev_vwap24[0] = np.nan

        # ميزات RS
        # rs_vs_btc: عائد 24h العملة - BTC
        btc_r24_aligned = align_arrays(t_sym, arr_btc['t'], btc_ret24)
        rs_vs_btc = np.where(
            ~np.isnan(ret24) & ~np.isnan(btc_r24_aligned),
            ret24 - btc_r24_aligned, np.nan)

        # rs_btc_stress: عائد العملة / عائد BTC حين BTC هبط >=3%
        btc_down_mask = (~np.isnan(btc_r24_aligned)) & (btc_r24_aligned <= BTC_DROP_THRESH)
        rs_btc_stress = np.where(
            btc_down_mask & ~np.isnan(ret24) & (btc_r24_aligned != 0),
            ret24 / btc_r24_aligned, np.nan)

        # rs_rank24 (per-symbol aligned to ts_ref then back)
        sym_r24_on_ts = panel_ret24.get(sym, np.full(n_ts, np.nan))
        rs_rank24_ts = np.full(n_ts, np.nan)
        for i in range(24, n_ts):
            col = panel_matrix[:, i]
            valid_col = col[~np.isnan(col)]
            if len(valid_col) < 5 or np.isnan(sym_r24_on_ts[i]):
                continue
            rs_rank24_ts[i] = float(np.mean(valid_col < sym_r24_on_ts[i]))
        rs_rank24 = align_arrays(t_sym, ts_ref, rs_rank24_ts)

        # rs_btc_corr_30d
        btc_r24_sym = btc_r24_aligned
        rs_btc_corr = np.full(n_sym, np.nan)
        for i in range(720, n_sym):
            x_seg = ret24[i-720:i]
            y_seg = btc_r24_sym[i-720:i]
            valid = ~np.isnan(x_seg) & ~np.isnan(y_seg)
            if valid.sum() >= 50:
                rs_btc_corr[i] = spearman_ic(x_seg[valid], y_seg[valid])

        # ميزات cross-coin (مُحاذَاة من ts_ref)
        btc_reg_sym = align_arrays(t_sym, ts_ref, btc_regime_ts)
        mkt_bread_sym = align_arrays(t_sym, ts_ref, market_breadth_ts)

        # حد النافذة
        min_idx = 200
        max_idx = n_sym - FWD_HOURS - 2
        if max_idx <= min_idx:
            continue

        valid_range = np.arange(min_idx, max_idx + 1)
        n_sample = min(POINTS_PER_SYM, len(valid_range))
        chosen = sorted(rng.choice(valid_range, size=n_sample, replace=False).tolist())

        for i in chosen:
            if np.isnan(tA[i]) or np.isnan(ret_fwd[i]):
                continue

            pt = {
                'sym':   sym,
                't':     int(t_sym[i]),
                'is_wf_oos': int(t_sym[i] >= wf_cutoff_ms),
                # الأهداف
                'tA':      float(tA[i]),
                'ret_fwd': float(ret_fwd[i]),  # العائد الحقيقي
                # ميزات VWAP
                'dist_vwap_daily':  float((arr['c'][i] - vwap24[i]) / vwap24[i])
                                    if not np.isnan(vwap24[i]) and vwap24[i] > 0 else np.nan,
                'dist_vwap_weekly': float((arr['c'][i] - vwap168[i]) / vwap168[i])
                                    if not np.isnan(vwap168[i]) and vwap168[i] > 0 else np.nan,
                'vwap_regime':      float((arr['c'][i] > vwap24[i]) and (vwap24[i] > vwap168[i]))
                                    if not np.isnan(vwap24[i]) and not np.isnan(vwap168[i]) else np.nan,
                'vwap_oversold':    float(arr['c'][i] < vwap24[i] - 0.01 * atr24[i])
                                    if not np.isnan(vwap24[i]) and not np.isnan(atr24[i]) else np.nan,
                'vwap_break_vol':   float((arr['c'][i] > vwap24[i]) and
                                          (prev_c[i] < prev_vwap24[i]) and
                                          (v[i] > v_mean20[i]))
                                    if (not np.isnan(vwap24[i]) and not np.isnan(v_mean20[i])
                                        and not np.isnan(prev_c[i]) and not np.isnan(prev_vwap24[i]))
                                    else np.nan,
                # ميزات RS
                'rs_vs_btc':        float(rs_vs_btc[i]),
                'rs_btc_stress':    float(rs_btc_stress[i]),
                'rs_rank24':        float(rs_rank24[i]),
                'rs_btc_corr_30d':  float(rs_btc_corr[i]),
                # سياق سوقي
                'btc_regime':       float(btc_reg_sym[i]),
                'market_breadth':   float(mkt_bread_sym[i]),
            }
            all_points.append(pt)
            btc_down_cnt = int(btc_down_mask[i])
            btc_stress_count += btc_down_cnt

        del (vwap24, vwap168, atr24, ret24, v_mean20, rs_vs_btc,
             rs_btc_stress, rs_btc_corr, btc_reg_sym, mkt_bread_sym,
             rs_rank24, tA, ret_fwd)
        gc.collect()

    log(f"إجمالي نقاط العيّنة: {len(all_points):,}")
    log(f"نقاط rs_btc_stress صالحة (BTC down >=3%): {btc_stress_count:,}")
    log(f"ذاكرة: {check_mem_mb()} MB")

    if len(all_points) < 500:
        log("خطأ: عيّنة غير كافية!")
        return

    # --- 7. التحقق من rs_btc_stress ---
    stress_valid = [p for p in all_points if not np.isnan(p.get('rs_btc_stress', np.nan))]
    stress_n = len(stress_valid)
    drop_btc_stress = stress_n < MIN_COND_N
    if drop_btc_stress:
        log(f"تحذير: rs_btc_stress n={stress_n} < {MIN_COND_N} → مستبعد")

    # --- 8. تعريف الميزات ---
    feature_names = [
        'dist_vwap_daily', 'dist_vwap_weekly', 'vwap_regime',
        'vwap_oversold', 'vwap_break_vol',
        'rs_vs_btc', 'rs_rank24', 'rs_btc_corr_30d',
        'btc_regime', 'market_breadth',
    ]
    if not drop_btc_stress:
        feature_names.append('rs_btc_stress')

    # الهدفان فقط:
    # tA: ثنائي (هل ارتفعت 5% قبل أن تنزل 5%) — لكن E يُحسب بـ ret_fwd الحقيقي
    # tC (ret_fwd): عائد مستمر — تحليل IC مباشر
    target_configs = [
        ('tA',      'ret_fwd', False),  # (label, y_for_E, is_crosscoin)
        ('ret_fwd', 'ret_fwd', False),
    ]

    # --- 9. تحليل per-symbol features (all_points) ---
    log("تحليل (ميزة × هدف) — per-symbol features...")
    results_persym = []
    n_all = len(all_points)

    for feat in feature_names:
        # تحقق إن كانت هذه ميزة cross-coin
        is_crosscoin = feat in ('btc_regime', 'market_breadth', 'rs_btc_corr_30d')

        for (tgt_label, tgt_y, _) in target_configs:
            # استخراج نقاط صالحة
            pts_valid = [
                (p['t'], p[feat], p[tgt_label], p[tgt_y], p['is_wf_oos'])
                for p in all_points
                if not np.isnan(p.get(feat, np.nan))
                and not np.isnan(p.get(tgt_label, np.nan))
                and not np.isnan(p.get(tgt_y, np.nan))
            ]

            if len(pts_valid) < 100:
                continue

            pts_valid.sort(key=lambda x: x[0])  # ترتيب زمني

            # للميزات cross-coin: dedup على timestamp
            if is_crosscoin:
                seen_ts = {}
                deduped = []
                for row in pts_valid:
                    ts_key = row[0]
                    if ts_key not in seen_ts:
                        seen_ts[ts_key] = row
                        deduped.append(row)
                    # else: نأخذ أول رمز فقط
                pts_valid = deduped

            if len(pts_valid) < 50:
                continue

            # WF calendar split
            pts_is  = [p for p in pts_valid if p[4] == 0]  # IS
            pts_oos = [p for p in pts_valid if p[4] == 1]  # OOS

            if len(pts_is) < 30 or len(pts_oos) < 30:
                continue

            x_all = np.array([p[1] for p in pts_valid])
            y_all = np.array([p[2] for p in pts_valid])
            r_all = np.array([p[3] for p in pts_valid])  # y العائد الحقيقي

            x_is  = np.array([p[1] for p in pts_is])
            y_is  = np.array([p[2] for p in pts_is])
            x_oos = np.array([p[1] for p in pts_oos])
            y_oos = np.array([p[2] for p in pts_oos])
            r_oos = np.array([p[3] for p in pts_oos])

            ic_is   = spearman_ic(x_is, y_is)
            ic_oos  = spearman_ic(x_oos, y_oos)
            p_is    = ic_pvalue(ic_is, len(x_is))
            p_oos   = ic_pvalue(ic_oos, len(x_oos))
            d       = cohen_d_decile(x_all, r_all)  # d على العائد الحقيقي

            # E_top: متوسط العائد الحقيقي (ret_fwd) للـ top decile في x، بعد رسوم
            e_top = expectancy_top_decile(x_oos, r_oos)

            # WR ضمن top decile (لـ tA فقط)
            if tgt_label == 'tA':
                cut = max(1, len(x_oos) // 10)
                idx_oos = np.argsort(x_oos)
                top_tA  = np.array([pts_oos[i][2] for i in idx_oos[-cut:]])
                wr_top  = float(top_tA.mean()) if len(top_tA) > 0 else np.nan
            else:
                wr_top = np.nan

            results_persym.append({
                'feature':      feat,
                'target_label': tgt_label,
                'crosscoin':    is_crosscoin,
                'n_total':      len(pts_valid),
                'n_is':         len(pts_is),
                'n_oos':        len(pts_oos),
                'IC_IS':        round(ic_is, 4),
                'IC_OOS':       round(ic_oos, 4),
                'p_IS':         round(p_is, 6),
                'p_OOS':        round(p_oos, 6),
                'cohen_d':      round(d, 3) if not np.isnan(d) else None,
                'E_top_oos':    round(e_top, 4),
                'WR_top_oos':   round(wr_top, 3) if not np.isnan(wr_top) else None,
            })

    log(f"اختبارات كاملة: {len(results_persym)}")

    # --- 10. FDR على p_OOS ---
    if not results_persym:
        log("لا نتائج!")
        return

    pvals_oos = [r['p_OOS'] for r in results_persym]
    qvals     = bh_fdr(pvals_oos)
    for r, q in zip(results_persym, qvals):
        r['q_OOS'] = round(q, 6)

    # --- 11. الناجيات (معيار صارم) ---
    # معيار tA: q<0.05 AND |d|>0.1 AND IC_IS/IC_OOS نفس الإشارة AND E_top>0
    # معيار ret_fwd: q<0.05 AND |d|>0.1 AND IC stable AND E_top>0
    survivors = []
    for r in results_persym:
        if r['q_OOS'] >= 0.05:
            continue
        if r['cohen_d'] is None or abs(r['cohen_d']) <= 0.1:
            continue
        if np.sign(r['IC_IS']) != np.sign(r['IC_OOS']):
            continue
        if r['E_top_oos'] <= 0:
            continue
        survivors.append(r)

    log(f"ناجيات صارمة: {len(survivors)}")

    # --- 12. نتائج مُفصَّلة ---
    log("\nأعلى 20 نتيجة بـ p_OOS (مرتّبة):")
    sorted_all = sorted(results_persym, key=lambda x: x['p_OOS'])
    for r in sorted_all[:20]:
        flag = " *** SURVIVOR" if r in survivors else ""
        log(f"  {r['feature']:25s}|{r['target_label']:10s}| "
            f"IC_OOS={r['IC_OOS']:+.3f} d={r['cohen_d']} "
            f"E_top={r['E_top_oos']:+.4f} q={r['q_OOS']:.4f}{flag}")

    # --- 13. حفظ ---
    output = {
        'meta': {
            'date':           datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'seed':           SEED,
            'n_symbols':      len(all_1h),
            'n_points_total': len(all_points),
            'n_features':     len(feature_names),
            'n_tests':        len(results_persym),
            'btc_stress_n':   stress_n,
            'drop_btc_stress':drop_btc_stress,
            'wf_calendar_split_days': WF_CALENDAR_SPLIT,
            'fwd_hours':      FWD_HOURS,
            'target_a_pct':   TARGET_A_PCT,
            'fee':            FEE,
        },
        'survivors':   survivors,
        'all_results': sorted(results_persym, key=lambda x: x['p_OOS']),
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log(f"\nالنتائج → {OUTPUT_JSON}")

    log("\n" + "="*60)
    log("الحكم النهائي:")
    if survivors:
        log(f"وُجدت {len(survivors)} ميزة ناجية — تفاصيل أدناه:")
        for r in sorted(survivors, key=lambda x: x['q_OOS']):
            log(f"  {r['feature']} | {r['target_label']} | "
                f"IC_OOS={r['IC_OOS']:+.3f} | d={r['cohen_d']} | "
                f"E_top={r['E_top_oos']:+.4f} | q={r['q_OOS']:.4f}")
    else:
        log("0 ناجيات: حتى VWAP+RS بلا حافة بعد الرسوم")
        log("الكون التقني الكامل ميت على الكريبتو spot بعد 0.3% رسوم")
    log("="*60)

    return output

if __name__ == "__main__":
    main()
