#!/usr/bin/env python3
"""
ICT Structural Causal Test — بحث سببي على مؤشرات ICT البنيوية
===============================================================
التاريخ: 2026-05-21
الهدف: اختبار قاطع هل Order Blocks / FVG / BOS / CHoCH / Liquidity Sweep
       لها حافة سببية على العوائد الأمامية (48h) في كريبتو Spot.

المنهجية:
  - 80-100 عملة USDT، إطار 1h، 180 يوم
  - عيّنة عشوائية كثيفة من نقاط القياس (هدف ≥100,000 نقطة)
  - معالجة متدفّقة: عملة واحدة → احسب OHLC → احسب ميزات → احفظ → احذف
  - بدون scipy — t-test وFDR بـ math/numpy فقط
  - إعادة استخدام كاش OHLC من research/cache/klines/ (49 رمز موجودة)

القيود:
  - بحث فقط — التجميد ساري، لا تعديل على الكود الحيّ
  - بلا حزم جديدة
  - معالجة متدفّقة إلزامية (RAM ~2.2GB)

التشغيل من داخل الـ container:
  docker compose exec analyzer python3 /app/research/scripts/ict_structural_causal.py
"""

import os, sys, random, pickle, time, math, json, gc, csv
import requests
from datetime import datetime, timezone

import numpy as np

# ================================================================
# مسارات (تعمل داخل container حيث ./analyzer مُعلَّق على /app)
# ================================================================
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
# /app/research/scripts → /app/research
APP_DIR      = os.path.join(SCRIPT_DIR, "..", "..")   # /app/
RESEARCH_DIR = os.path.join(APP_DIR, "research")      # /app/research/

# كاش OHLC كامل (o/h/l/c) من الباكتيستر — 49 عملة موجودة
OHLC_CACHE_FULL = os.path.join(RESEARCH_DIR, "cache", "klines")
# كاش ICT الجديد للرموز المُجلَبة حديثاً
ICT_CACHE_DIR   = os.path.join(RESEARCH_DIR, "cache", "ict_ohlc")
os.makedirs(ICT_CACHE_DIR, exist_ok=True)

RESULTS_DIR  = os.path.join(RESEARCH_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

CACHE_ROOT   = os.path.join(RESEARCH_DIR, "cache")
os.makedirs(CACHE_ROOT, exist_ok=True)

DATE_STAMP   = "2026_05_21_ict"
OUTPUT_JSON  = os.path.join(RESULTS_DIR, f"ict_structural_causal_{DATE_STAMP}.json")
OUTPUT_CSV   = os.path.join(RESULTS_DIR, f"ict_structural_causal_{DATE_STAMP}_features.csv")
SYMBOL_CACHE = os.path.join(CACHE_ROOT, "ict_symbols.pkl")

# ================================================================
# ثوابت
# ================================================================
SEED              = 20260521_2
BINANCE_BASE      = "https://api.binance.com"
INTERVAL_MS       = 3_600_000
DAYS_BACK         = 180
FWD_48H           = 48
FEE               = 0.003
RESERVE_CANDLES   = FWD_48H + 10
POINTS_PER_SYMBOL = 1200
MIN_CANDLES_REQ   = 200

TARGET_TOTAL  = 90
TARGET_LARGE  = 30
TARGET_MID    = 30
TARGET_SMALL  = 30

REQUEST_SLEEP = 0.25

# معاملات حساب الميزات
FRACTAL_N     = 5
BOS_LOOKBACK  = 20
SWEEP_LOOKBACK = 10
OB_MAX_AGE    = 50
FVG_LOOKBACK  = 30
IMPULSE_MIN   = 3

MEM_LIMIT_BYTES = 1_700_000_000   # 1.7 GB


# ================================================================
# مراقبة الذاكرة
# ================================================================
def rss_bytes() -> int:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def check_memory(symbol: str = ""):
    rss = rss_bytes()
    if rss > MEM_LIMIT_BYTES:
        print(f"[MEM] RSS={rss//1024//1024}MB > حدّ → gc عند {symbol}", flush=True)
        gc.collect()


# ================================================================
# إحصاء (بلا scipy)
# ================================================================
def _betainc(a, b, x):
    if x <= 0.0: return 0.0
    if x >= 1.0: return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
    MAXITER, EPS, fpmin = 200, 3e-7, 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < fpmin: d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, MAXITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin: d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin: c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin: d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin: c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS: break
    return front * h


def _t_pvalue(t, df):
    t = abs(float(t))
    df = float(df)
    if df <= 0: return 1.0
    if df > 10000: return float(math.erfc(t / math.sqrt(2)))
    x = df / (df + t * t)
    return min(2.0 * _betainc(df / 2.0, 0.5, x), 1.0)


def welch_ttest(a: np.ndarray, b: np.ndarray):
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3: return 0.0, 1.0
    m1, m2 = float(np.mean(a)), float(np.mean(b))
    v1, v2 = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    vn1, vn2 = v1 / n1, v2 / n2
    se = math.sqrt(vn1 + vn2)
    if se == 0: return 0.0, 1.0
    t = (m1 - m2) / se
    df = (vn1 + vn2) ** 2 / ((vn1 ** 2) / (n1 - 1) + (vn2 ** 2) / (n2 - 1))
    return float(t), float(_t_pvalue(t, df))


def cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2: return 0.0
    s = math.sqrt(
        ((n1 - 1) * float(np.var(a, ddof=1)) + (n2 - 1) * float(np.var(b, ddof=1)))
        / (n1 + n2 - 2)
    )
    return (float(np.mean(a)) - float(np.mean(b))) / s if s > 0 else 0.0


def ci_95_diff(a: np.ndarray, b: np.ndarray):
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3: return (None, None)
    v1, v2 = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    se   = math.sqrt(v1 / n1 + v2 / n2)
    diff = float(np.mean(a)) - float(np.mean(b))
    return (diff - 1.96 * se, diff + 1.96 * se)


def bh_fdr(p_values: list) -> list:
    """Benjamini-Hochberg FDR → q-values."""
    n = len(p_values)
    if n == 0: return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    q = [1.0] * n
    min_q = 1.0
    for rank, (orig_idx, p) in enumerate(reversed(indexed), 1):
        q_val = p * n / (n - rank + 1)
        min_q = min(min_q, q_val)
        q[orig_idx] = min_q
    return q


# ================================================================
# Binance REST
# ================================================================
def binance_get(path, params=None, max_retry=5):
    url = BINANCE_BASE + path
    for attempt in range(max_retry):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"\n[RATE_LIMIT] 429 → انتظار {wait}s", flush=True)
                time.sleep(wait)
                continue
            if r.status_code == 418:
                print(f"\n[RATE_LIMIT] 418 → انتظار 120s", flush=True)
                time.sleep(120)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retry - 1:
                raise
            time.sleep(2 ** attempt * 2)


# ================================================================
# اختيار الرموز (مع إعادة استخدام الكاش الموجود)
# ================================================================
def get_cached_ohlc_symbols() -> list:
    """يُعيد قائمة الرموز ذات كاش OHLC كامل."""
    syms = []
    if os.path.isdir(OHLC_CACHE_FULL):
        for f in os.listdir(OHLC_CACHE_FULL):
            if f.endswith("_1h.pkl"):
                syms.append(f.replace("_1h.pkl", ""))
    return syms


def get_usdt_symbols():
    data = binance_get("/api/v3/exchangeInfo")
    symbols = []
    stable = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT", "DAIUSDT", "USDTUSDT"}
    for s in data["symbols"]:
        if (s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
                and s.get("isSpotTradingAllowed", False)):
            sym = s["symbol"]
            if sym in stable: continue
            if any(x in sym for x in ("UP", "DOWN", "BULL", "BEAR")): continue
            symbols.append(sym)
    return symbols


def select_symbols_stratified(all_symbols, cached_set):
    """اختيار 90 رمزاً مع إعطاء أولوية للرموز ذات كاش موجود."""
    print("[2] جلب 24h volume...", flush=True)
    time.sleep(REQUEST_SLEEP)
    data = binance_get("/api/v3/ticker/24hr")
    sym_set = set(all_symbols)
    vol_map = {}
    for t in data:
        if t["symbol"] in sym_set:
            try: vol_map[t["symbol"]] = float(t["quoteVolume"])
            except: pass

    stable = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT", "USDTUSDT", "DAIUSDT"}
    sorted_syms = sorted(all_symbols, key=lambda s: vol_map.get(s, 0), reverse=True)
    sorted_syms = [s for s in sorted_syms if s not in stable]

    large = sorted_syms[:50]
    mid   = sorted_syms[50:200]
    small = sorted_syms[200:500]

    rng = random.Random(SEED)
    sel_large = rng.sample(large, min(TARGET_LARGE, len(large)))
    sel_mid   = rng.sample(mid,   min(TARGET_MID, len(mid)))
    sel_small = rng.sample(small, min(TARGET_SMALL, len(small)))

    selected = set(sel_large + sel_mid + sel_small)

    # إضافة الرموز ذات كاش موجود إن كانت غير مُختارة (حتى 90 رمز)
    for sym in cached_set:
        if sym not in selected and len(selected) < TARGET_TOTAL + 10:
            selected.add(sym)

    result = []
    for s in sel_large: result.append((s, "large"))
    for s in sel_mid:   result.append((s, "mid"))
    for s in sel_small: result.append((s, "small"))
    for s in cached_set:
        if s not in {x[0] for x in result}:
            result.append((s, "cached"))

    print(f"   الإجمالي: {len(result)} رمزاً (منهم {len(cached_set)} من الكاش)", flush=True)
    return result[:TARGET_TOTAL + 15]   # حد أقصى معقول


# ================================================================
# كاش OHLC
# ================================================================
def _ict_cache_path(symbol):
    return os.path.join(ICT_CACHE_DIR, f"{symbol}_1h_ohlc.pkl")


def load_ohlc_cached(symbol) -> list:
    """يجلب OHLC من الكاش المتاح: ICT > full-backtest > None."""
    # 1. كاش ICT (أحدث، مجلوب لهذا السكريبت)
    p = _ict_cache_path(symbol)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    # 2. كاش الباكتيستر (OHLC كامل، نفس الشكل)
    p2 = os.path.join(OHLC_CACHE_FULL, f"{symbol}_1h.pkl")
    if os.path.exists(p2):
        with open(p2, "rb") as f:
            return pickle.load(f)
    return None


def save_ohlc_cached(symbol, data):
    with open(_ict_cache_path(symbol), "wb") as f:
        pickle.dump(data, f)


def fetch_ohlc_1h(symbol: str) -> list:
    """يجلب OHLC كامل (180 يوم، 1h) من Binance أو من الكاش."""
    cached = load_ohlc_cached(symbol)
    if cached is not None:
        return cached

    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - DAYS_BACK * 86_400_000
    candles  = []
    cur      = start_ms
    BATCH    = 1000

    while cur < now_ms - INTERVAL_MS:
        time.sleep(REQUEST_SLEEP)
        params = {"symbol": symbol, "interval": "1h", "startTime": cur, "limit": BATCH}
        try:
            rows = binance_get("/api/v3/klines", params=params)
        except Exception as e:
            print(f"\n   [FETCH_ERR] {symbol}: {e}", flush=True)
            break
        if not rows: break
        candles.extend(rows)
        last_ts = int(rows[-1][0])
        if last_ts >= now_ms - INTERVAL_MS: break
        cur = last_ts + INTERVAL_MS

    if not candles:
        return []

    result = [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
               "l": float(r[3]), "c": float(r[4])} for r in candles]
    save_ohlc_cached(symbol, result)
    return result


# ================================================================
# حساب Pivot Points (fractal)
# ================================================================
def find_pivots(highs: list, lows: list, n: int = FRACTAL_N):
    """
    يُعيد (pivot_high_indices, pivot_low_indices).
    pivot_high[i] إذا highs[i] == max(highs[i-n:i+n+1]).
    لا تسرّب: يجب استدعاؤها على سلايس hist[0:t] فقط.
    """
    total = len(highs)
    ph, pl = [], []
    for i in range(n, total - n):
        window_h = highs[i - n: i + n + 1]
        window_l = lows[i - n:  i + n + 1]
        if highs[i] == max(window_h):
            ph.append(i)
        if lows[i]  == min(window_l):
            pl.append(i)
    return ph, pl


# ================================================================
# حساب ميزات ICT (صارم: لا تسرّب مستقبل)
# ================================================================
FEATURE_NAMES = [
    "at_bullish_OB",
    "in_FVG_bullish",
    "recent_BOS_up",
    "recent_CHoCH_up",
    "recent_sellside_sweep",
    "in_discount_zone",
    "in_OTE",
    "combo_OB_sweep",
    "combo_discount_BOS",
]

_ZERO_FEATS = {k: 0 for k in FEATURE_NAMES}


def compute_ict_features(candles: list, t: int) -> dict:
    """
    يحسب ميزات ICT عند نقطة t.
    يستخدم candles[0..t-1] فقط — لا تسرّب.
    """
    hist = candles[:t]     # بيانات حتى t-1
    n    = len(hist)
    if n < 30:
        return dict(_ZERO_FEATS)

    price = hist[-1]["c"]   # السعر الحالي = close آخر شمعة مرئية

    highs = [c["h"] for c in hist]
    lows  = [c["l"] for c in hist]
    opens = [c["o"] for c in hist]
    closes= [c["c"] for c in hist]

    ph_idx, pl_idx = find_pivots(highs, lows, FRACTAL_N)

    # ------------------------------------------------------------------
    # 1. Swing Range → Premium/Discount/OTE
    # ------------------------------------------------------------------
    in_discount = 0
    in_OTE      = 0
    if ph_idx and pl_idx:
        last_sh = highs[ph_idx[-1]]
        last_sl = lows[pl_idx[-1]]
        if last_sh > last_sl:
            rng    = last_sh - last_sl
            mid    = last_sl + rng * 0.5
            ote_lo = last_sh - rng * 0.79
            ote_hi = last_sh - rng * 0.62
            if price < mid:
                in_discount = 1
            if ote_lo <= price <= ote_hi:
                in_OTE = 1

    # ------------------------------------------------------------------
    # 2. BOS / CHoCH (نافذة BOS_LOOKBACK)
    # ------------------------------------------------------------------
    recent_bos_up   = 0
    recent_choch_up = 0

    lb_start = max(0, n - BOS_LOOKBACK)
    sub_h = highs[lb_start:]
    sub_l = lows[lb_start:]
    sub_c = closes[lb_start:]
    sub_ph, sub_pl = find_pivots(sub_h, sub_l, 3)

    if len(sub_ph) >= 2:
        prev_sh = sub_h[sub_ph[-2]]
        if sub_c[-1] > prev_sh:
            recent_bos_up = 1
            if len(sub_ph) >= 3:
                sh_a = sub_h[sub_ph[-3]]
                sh_b = sub_h[sub_ph[-2]]
                if sh_b < sh_a:
                    recent_choch_up = 1

    # ------------------------------------------------------------------
    # 3. Sellside Liquidity Sweep (نافذة SWEEP_LOOKBACK)
    # ------------------------------------------------------------------
    recent_sweep = 0
    if pl_idx:
        last_swing_low = lows[pl_idx[-1]]
        sw_start = max(0, n - SWEEP_LOOKBACK)
        for i in range(sw_start, n):
            if lows[i] < last_swing_low and closes[i] > last_swing_low:
                recent_sweep = 1
                break

    # ------------------------------------------------------------------
    # 4. Bullish FVG (نافذة FVG_LOOKBACK)
    # ------------------------------------------------------------------
    in_fvg  = 0
    fvg_start = max(0, n - FVG_LOOKBACK)
    fh = highs[fvg_start:]
    fl = lows[fvg_start:]
    fn = len(fh)
    for i in range(2, fn):
        gap_lo = fh[i - 2]   # candle[i-2].high
        gap_hi = fl[i]       # candle[i].low
        if gap_hi > gap_lo and gap_lo <= price <= gap_hi:
            in_fvg = 1
            break

    # ------------------------------------------------------------------
    # 5. Bullish Order Block (نافذة OB_MAX_AGE)
    # ------------------------------------------------------------------
    at_ob   = 0
    ob_start = max(0, n - OB_MAX_AGE)
    ob_n     = n - ob_start   # عدد الشموع في النافذة

    for i in range(ob_start, n - IMPULSE_MIN - 2):
        # شمعة هابطة
        if closes[i] >= opens[i]:
            continue
        ob_body_lo = min(opens[i], closes[i])
        ob_body_hi = max(opens[i], closes[i])
        ob_wick_hi = highs[i]

        # تحقق من impulse صاعد (IMPULSE_MIN+ شموع صاعدة متتالية تكسر high الشمعة)
        up_count   = 0
        broke_high = False
        for j in range(i + 1, min(i + 1 + IMPULSE_MIN + 3, n)):
            if closes[j] > opens[j]:   # شمعة صاعدة
                up_count += 1
                if highs[j] > ob_wick_hi:
                    broke_high = True
            else:
                break

        if up_count < IMPULSE_MIN or not broke_high:
            continue

        # تحقق إن لم يُرتشَف (السعر لم يعد لداخل OB بعد التكوّن)
        mitigated = False
        for k in range(i + 1 + up_count, n):
            if lows[k] <= ob_body_lo:
                mitigated = True
                break

        if not mitigated and ob_body_lo <= price <= ob_wick_hi:
            at_ob = 1
            break

    # ------------------------------------------------------------------
    # 6. Combos
    # ------------------------------------------------------------------
    return {
        "at_bullish_OB":         at_ob,
        "in_FVG_bullish":        in_fvg,
        "recent_BOS_up":         recent_bos_up,
        "recent_CHoCH_up":       recent_choch_up,
        "recent_sellside_sweep": recent_sweep,
        "in_discount_zone":      in_discount,
        "in_OTE":                in_OTE,
        "combo_OB_sweep":        1 if (at_ob and recent_sweep) else 0,
        "combo_discount_BOS":    1 if (in_discount and recent_bos_up) else 0,
    }


# ================================================================
# معالجة رمز واحد (streaming)
# ================================================================
def process_symbol(symbol: str, tier: str, rng: random.Random) -> list:
    candles = fetch_ohlc_1h(symbol)
    if not candles or len(candles) < MIN_CANDLES_REQ:
        print(f"   [{symbol}] بيانات غير كافية ({len(candles) if candles else 0})", flush=True)
        return []

    n         = len(candles)
    valid_end = n - RESERVE_CANDLES
    valid_start = FRACTAL_N * 2 + 20

    if valid_end <= valid_start:
        return []

    indices    = list(range(valid_start, valid_end))
    sample_sz  = min(POINTS_PER_SYMBOL, len(indices))
    sampled    = rng.sample(indices, sample_sz)
    sampled.sort()

    records = []
    for t in sampled:
        t_fwd = t + FWD_48H
        if t_fwd >= n: continue
        entry = candles[t]["c"]
        exit_ = candles[t_fwd]["c"]
        if entry <= 0: continue
        fwd_ret = (exit_ - entry) / entry - FEE

        feats = compute_ict_features(candles, t)
        rec   = {"symbol": symbol, "tier": tier, "t_idx": t, "t_ms": candles[t]["t"],
                 "fwd_return_48h": fwd_ret}
        rec.update(feats)
        records.append(rec)

    del candles
    gc.collect()
    check_memory(symbol)
    return records


# ================================================================
# التحليل الإحصائي
# ================================================================
def analyze_feature(name: str, records: list):
    treat = np.array([r["fwd_return_48h"] for r in records if r.get(name, 0) == 1])
    ctrl  = np.array([r["fwd_return_48h"] for r in records if r.get(name, 0) == 0])
    if len(treat) < 3 or len(ctrl) < 3:
        return None
    t_stat, p = welch_ttest(treat, ctrl)
    d         = cohen_d(treat, ctrl)
    ci_lo, ci_hi = ci_95_diff(treat, ctrl)
    return {
        "feature":    name,
        "n_treat":    int(len(treat)),
        "n_ctrl":     int(len(ctrl)),
        "mean_treat": round(float(np.mean(treat)), 6),
        "mean_ctrl":  round(float(np.mean(ctrl)),  6),
        "diff":       round(float(np.mean(treat)) - float(np.mean(ctrl)), 6),
        "t_stat":     round(t_stat, 4),
        "p_value":    round(p, 6),
        "cohen_d":    round(d, 4),
        "ci_lo":      round(ci_lo, 6) if ci_lo is not None else None,
        "ci_hi":      round(ci_hi, 6) if ci_hi is not None else None,
    }


def walk_forward_analysis(name: str, records: list) -> dict:
    sorted_recs = sorted(records, key=lambda r: r["t_ms"])
    mid  = len(sorted_recs) // 2
    halves = [("first_half", sorted_recs[:mid]), ("second_half", sorted_recs[mid:])]
    res = {}
    for label, half in halves:
        treat = np.array([r["fwd_return_48h"] for r in half if r.get(name, 0) == 1])
        ctrl  = np.array([r["fwd_return_48h"] for r in half if r.get(name, 0) == 0])
        if len(treat) < 3 or len(ctrl) < 3:
            res[label] = None
            continue
        _, p = welch_ttest(treat, ctrl)
        d    = cohen_d(treat, ctrl)
        res[label] = {
            "n_treat": int(len(treat)), "n_ctrl": int(len(ctrl)),
            "mean_treat": round(float(np.mean(treat)), 6),
            "mean_ctrl":  round(float(np.mean(ctrl)),  6),
            "diff":  round(float(np.mean(treat)) - float(np.mean(ctrl)), 6),
            "p":     round(p, 6),
            "cohen_d": round(d, 4),
        }
    return res


# ================================================================
# Main
# ================================================================
def main():
    print("=" * 65)
    print("ICT Structural Causal Test — 2026-05-21")
    print(f"OHLC Cache: {OHLC_CACHE_FULL}")
    print(f"ICT Cache:  {ICT_CACHE_DIR}")
    print("=" * 65, flush=True)
    t0 = time.time()

    # ---------------------------------------------------------------
    # 0. رموز ذات كاش موجود
    # ---------------------------------------------------------------
    cached_syms = set(get_cached_ohlc_symbols())
    print(f"[0] كاش OHLC موجود: {len(cached_syms)} رمز", flush=True)

    # ---------------------------------------------------------------
    # 1. اختيار الرموز
    # ---------------------------------------------------------------
    if os.path.exists(SYMBOL_CACHE):
        print("[1] تحميل الرموز من كاش...", flush=True)
        with open(SYMBOL_CACHE, "rb") as f:
            selected = pickle.load(f)
    else:
        print("[1] جلب exchangeInfo...", flush=True)
        all_syms = get_usdt_symbols()
        selected = select_symbols_stratified(all_syms, cached_syms)
        with open(SYMBOL_CACHE, "wb") as f:
            pickle.dump(selected, f)

    # ضمان الرموز ذات الكاش في المقدمة (لتجنب جلب جديد)
    selected.sort(key=lambda x: 0 if x[0] in cached_syms else 1)

    n_sym = len(selected)
    print(f"   الرموز: {n_sym} | هدف النقاط: {n_sym * POINTS_PER_SYMBOL:,}\n", flush=True)

    # ---------------------------------------------------------------
    # 2. معالجة streaming
    # ---------------------------------------------------------------
    rng_main   = random.Random(SEED + 1)
    all_records = []
    n_ok = n_skip = 0

    for i, (symbol, tier) in enumerate(selected):
        cached_mark = "(cache)" if symbol in cached_syms else "(fetch)"
        print(f"[{i+1}/{n_sym}] {symbol} {cached_mark}... ", end="", flush=True)
        try:
            recs = process_symbol(symbol, tier, rng_main)
            all_records.extend(recs)
            n_ok += 1
            print(f"{len(recs)} نقطة | إجمالي: {len(all_records):,}", flush=True)
        except Exception as e:
            print(f"خطأ: {e}", flush=True)
            n_skip += 1

    total_pts = len(all_records)
    print(f"\n[تم] معالجة: {n_ok} | مُهمَل: {n_skip} | نقاط: {total_pts:,}", flush=True)

    if total_pts < 100:
        print("[خطأ] بيانات غير كافية للتحليل.", flush=True)
        return {}

    # ---------------------------------------------------------------
    # 3. حفظ CSV
    # ---------------------------------------------------------------
    print(f"\n[CSV] حفظ {total_pts:,} سجل → {OUTPUT_CSV}", flush=True)
    fields = ["symbol", "tier", "t_idx", "t_ms", "fwd_return_48h"] + FEATURE_NAMES
    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_records)

    # ---------------------------------------------------------------
    # 4. التحليل الإحصائي
    # ---------------------------------------------------------------
    print("\n[تحليل] t-test + Cohen d + CI لكل ميزة...", flush=True)
    feat_results = []
    p_values     = []

    for name in FEATURE_NAMES:
        res = analyze_feature(name, all_records)
        if res:
            feat_results.append(res)
            p_values.append(res["p_value"])
        else:
            feat_results.append({
                "feature": name, "n_treat": 0, "n_ctrl": 0,
                "mean_treat": None, "mean_ctrl": None, "diff": None,
                "t_stat": 0.0, "p_value": 1.0, "cohen_d": 0.0,
                "ci_lo": None, "ci_hi": None,
            })
            p_values.append(1.0)

    q_values = bh_fdr(p_values)
    for res, q in zip(feat_results, q_values):
        res["q_value"] = round(q, 6)

    # ---------------------------------------------------------------
    # 5. Walk-Forward
    # ---------------------------------------------------------------
    print("[تحليل] Walk-Forward (نصف أول / نصف ثانٍ)...", flush=True)
    wf_results = {}
    for res in feat_results:
        wf_results[res["feature"]] = walk_forward_analysis(res["feature"], all_records)

    # ---------------------------------------------------------------
    # 6. الحكم
    # ---------------------------------------------------------------
    survivors = []
    for res in feat_results:
        name = res["feature"]
        q    = res.get("q_value", 1.0)
        d    = abs(res.get("cohen_d", 0.0))
        wf   = wf_results.get(name, {})
        wf1  = wf.get("first_half")
        wf2  = wf.get("second_half")
        wf_consistent = (
            wf1 and wf2 and
            ((wf1["diff"] > 0 and wf2["diff"] > 0) or
             (wf1["diff"] < 0 and wf2["diff"] < 0))
        )
        verdict = "SURVIVES" if (q < 0.05 and d > 0.1 and wf_consistent) else "REJECTED"
        res["verdict"] = verdict
        if verdict == "SURVIVES":
            survivors.append(name)

    # ---------------------------------------------------------------
    # 7. حفظ JSON
    # ---------------------------------------------------------------
    elapsed = int(time.time() - t0)
    output = {
        "meta": {
            "date": DATE_STAMP,
            "n_symbols": n_sym,
            "n_processed": n_ok,
            "n_skipped": n_skip,
            "total_points": total_pts,
            "fee_pct": FEE * 100,
            "fwd_window_h": FWD_48H,
            "fractal_n": FRACTAL_N,
            "elapsed_seconds": elapsed,
        },
        "feature_results": feat_results,
        "walk_forward": wf_results,
        "survivors": survivors,
        "verdict": "ICT_HAS_CAUSAL_EDGE" if survivors else "ICT_NO_CAUSAL_EDGE",
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    # ---------------------------------------------------------------
    # 8. طباعة الملخص
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("ICT STRUCTURAL CAUSAL TEST — النتائج")
    print(f"الرموز: {n_ok} | النقاط: {total_pts:,} | الوقت: {elapsed}s")
    print("=" * 70)

    # جدول الميزات
    print(f"\n{'Feature':<28} {'n_t':>7} {'n_c':>7} {'μ_treat':>9} {'μ_ctrl':>9} "
          f"{'diff':>9} {'p':>8} {'q(FDR)':>8} {'d':>7} {'verdict'}")
    print("-" * 105)
    for res in feat_results:
        mt  = f"{res['mean_treat']:.5f}" if res['mean_treat'] is not None else "   N/A"
        mc  = f"{res['mean_ctrl']:.5f}"  if res['mean_ctrl']  is not None else "   N/A"
        dif = f"{res['diff']:.5f}"       if res['diff']        is not None else "   N/A"
        print(
            f"{res['feature']:<28} {res['n_treat']:>7} {res['n_ctrl']:>7} "
            f"{mt:>9} {mc:>9} {dif:>9} "
            f"{res['p_value']:>8.5f} {res.get('q_value',1):>8.5f} "
            f"{res['cohen_d']:>7.4f} {res.get('verdict','?')}"
        )

    # Walk-Forward للناجيات
    if survivors:
        print(f"\n[Walk-Forward للناجيات]:")
        for name in survivors:
            wf = wf_results[name]
            h1 = wf.get("first_half")
            h2 = wf.get("second_half")
            print(f"  {name}:")
            if h1: print(f"    نصف1: diff={h1['diff']:+.5f}, p={h1['p']:.4f}, d={h1['cohen_d']:.3f}, n_t={h1['n_treat']}")
            if h2: print(f"    نصف2: diff={h2['diff']:+.5f}, p={h2['p']:.4f}, d={h2['cohen_d']:.3f}, n_t={h2['n_treat']}")
    else:
        print("\n[Walk-Forward]: لا ناجيات — تحقق جدول كامل في JSON")

    print(f"\n{'='*40}")
    print(f"[الحكم النهائي]: {output['verdict']}")
    if not survivors:
        print("  لا توجد ميزة ICT بنيوية صامدة أمام FDR < 0.05 + |d| > 0.1 + walk-forward ثابت")
        print("  الاستنتاج: ICT البنيوي بلا حافة سببية قابلة للقياس في كريبتو Spot")
    else:
        print(f"  ميزات صامدة: {', '.join(survivors)}")
        print("  → مرشّحات لاختبار ما بعد التجميد (لا تُطبَّق الآن)")

    print(f"\n[ملفات النتائج]:")
    print(f"  JSON: {OUTPUT_JSON}")
    print(f"  CSV:  {OUTPUT_CSV}")

    return output


if __name__ == "__main__":
    main()
