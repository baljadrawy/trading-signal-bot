#!/usr/bin/env python3
"""
ICT Structural Causal Test v3 — Multi-Timeframe + 6 Fixes
==========================================================
التاريخ: 2026-05-22
المرجع: v1 (2026-05-21) أعطى ICT_NO_CAUSAL_EDGE لكن كُشف 6 ثغرات تطبيقية.

الثغرات الست المُصلَحة في v3:
  1. multi-timeframe: HTF 1d bias (HHHL/LHLH) + LTF 1h trigger → ict_aligned
  2. OB age: OB على 1d صالح 60 يوماً (لا حد 50 شمعة 1h)
  3. FVG mitigation: FVG صالح فقط إن لم يُملأ بعد
  4. Combo AMD: تسلسل زمني Accumulation→Sweep→BOS→Entry (لا AND اللحظي)
  5. HTF swing: pivots على بيانات 1d (N=2) لا fractal N=5 على 1h
  6. OTE من Dealing Range الحقيقي: آخر impulse على 1d

مصدر البيانات:
  - 1h: من الكاش الموجود (ict_ohlc/ أو klines/)
  - 1d: مُجمَّع من 1h بانتظام (00:00 UTC حتى 23:59 UTC) — لا جلب إضافي
  - لا تسرّب: 1d bias محسوب من الشمعة اليومية المُغلقة قبل t

المنهجية:
  - ≥100,000 نقطة، 80-100 عملة، 180 يوم، 1h trigger
  - Forward return 48h بعد رسوم 0.3%
  - t-test + FDR (Benjamini-Hochberg) + Cohen d + CI 95% + Walk-Forward نصف/نصف

القيود:
  - بحث فقط — التجميد ساري، لا تعديل على الكود الحي
  - بلا حزم جديدة (numpy + math + requests + pickle)
  - معالجة متدفقة إلزامية (RAM ~2.2GB)

التشغيل:
  docker compose exec analyzer python3 /app/research/scripts/ict_structural_causal_v3.py
"""

import os, sys, random, pickle, time, math, json, gc, csv
import requests
from datetime import datetime, timezone

import numpy as np

# ================================================================
# مسارات
# ================================================================
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
APP_DIR      = os.path.join(SCRIPT_DIR, "..", "..")   # /app/
RESEARCH_DIR = os.path.join(APP_DIR, "research")

OHLC_CACHE_FULL = os.path.join(RESEARCH_DIR, "cache", "klines")
ICT_CACHE_DIR   = os.path.join(RESEARCH_DIR, "cache", "ict_ohlc")
RESULTS_DIR     = os.path.join(RESEARCH_DIR, "results")
CACHE_ROOT      = os.path.join(RESEARCH_DIR, "cache")

for d in [ICT_CACHE_DIR, RESULTS_DIR, CACHE_ROOT]:
    os.makedirs(d, exist_ok=True)

DATE_STAMP   = "2026_05_22_ict_v3"
OUTPUT_JSON  = os.path.join(RESULTS_DIR, f"ict_structural_causal_{DATE_STAMP}.json")
OUTPUT_CSV   = os.path.join(RESULTS_DIR, f"ict_structural_causal_{DATE_STAMP}_features.csv")
SYMBOL_CACHE = os.path.join(CACHE_ROOT, "ict_v3_symbols.pkl")

# ================================================================
# ثوابت
# ================================================================
SEED              = 20260522_3
BINANCE_BASE      = "https://api.binance.com"
INTERVAL_1H_MS    = 3_600_000
INTERVAL_1D_MS    = 86_400_000
DAYS_BACK         = 180
FWD_48H           = 48
FEE               = 0.003
RESERVE_CANDLES   = FWD_48H + 10
POINTS_PER_SYMBOL = 1300
MIN_1H_CANDLES    = 200
MIN_1D_CANDLES    = 30   # حد أدنى للشموع اليومية (من 180 يوم → ~180)

TARGET_TOTAL  = 90
TARGET_LARGE  = 30
TARGET_MID    = 30
TARGET_SMALL  = 30

REQUEST_SLEEP = 0.25

# HTF bias parameters
HTF_SWING_N       = 2    # fractal N للشموع اليومية (أقل ضوضاء من 1h)
HTF_BIAS_LOOKBACK = 4    # عدد swing highs/lows للحكم (HHHL أو LHLH)
HTF_MIN_SWING_PTS = 2    # حد أدنى نقاط swing للحكم على bias

# OB parameters (Fix 2: OB على 1d صالح 60 يوم)
OB_1D_VALID_DAYS  = 60   # بدلاً من 50 شمعة 1h = ~2 يوم فقط
IMPULSE_MIN_1D    = 2    # شموع 1d صاعدة متتالية بعد OB

# AMD sequence parameters (Fix 4)
AMD_ACCUM_WINDOW  = 30   # نافذة التراكم (شموع 1h)
AMD_SWEEP_WINDOW  = 48   # نافذة البحث عن الـ sweep بعد التراكم
AMD_BOS_WINDOW    = 24   # نافذة البحث عن BOS بعد الـ sweep
AMD_ENTRY_WINDOW  = 20   # نافذة الدخول بعد BOS

# FVG
FVG_LOOKBACK_1H   = 50   # نافذة FVG على 1h

# BOS/CHoCH
BOS_LOOKBACK_1H   = 30   # نافذة BOS على 1h

MEM_LIMIT_BYTES = 1_700_000_000


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
        print(f"[MEM] RSS={rss//1024//1024}MB > حد → gc عند {symbol}", flush=True)
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
    """Benjamini-Hochberg FDR."""
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
# اختيار الرموز
# ================================================================
def get_cached_symbols_1h() -> set:
    syms = set()
    for cache_dir in [ICT_CACHE_DIR, OHLC_CACHE_FULL]:
        if os.path.isdir(cache_dir):
            for f in os.listdir(cache_dir):
                if f.endswith("_1h.pkl") or f.endswith("_1h_ohlc.pkl"):
                    sym = f.replace("_1h_ohlc.pkl", "").replace("_1h.pkl", "")
                    syms.add(sym)
    return syms


def get_usdt_symbols():
    data = binance_get("/api/v3/exchangeInfo")
    symbols = []
    stable = {"USDCUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT","DAIUSDT","USDTUSDT"}
    for s in data["symbols"]:
        if (s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
                and s.get("isSpotTradingAllowed", False)):
            sym = s["symbol"]
            if sym in stable: continue
            if any(x in sym for x in ("UP","DOWN","BULL","BEAR")): continue
            symbols.append(sym)
    return symbols


def select_symbols(all_symbols, cached_set):
    print("[2] جلب 24h volume...", flush=True)
    time.sleep(REQUEST_SLEEP)
    data = binance_get("/api/v3/ticker/24hr")
    sym_set = set(all_symbols)
    vol_map = {}
    for t in data:
        if t["symbol"] in sym_set:
            try: vol_map[t["symbol"]] = float(t["quoteVolume"])
            except: pass

    sorted_syms = sorted(all_symbols, key=lambda s: vol_map.get(s, 0), reverse=True)
    stable = {"USDCUSDT","BUSDUSDT","TUSDUSDT","FDUSDUSDT","USDTUSDT","DAIUSDT"}
    sorted_syms = [s for s in sorted_syms if s not in stable]

    large = sorted_syms[:50]
    mid   = sorted_syms[50:200]
    small = sorted_syms[200:500]

    rng = random.Random(SEED)
    sel_large = rng.sample(large, min(TARGET_LARGE, len(large)))
    sel_mid   = rng.sample(mid,   min(TARGET_MID, len(mid)))
    sel_small = rng.sample(small, min(TARGET_SMALL, len(small)))

    selected = []
    seen = set()
    for s in sel_large:
        if s not in seen: selected.append((s,"large")); seen.add(s)
    for s in sel_mid:
        if s not in seen: selected.append((s,"mid")); seen.add(s)
    for s in sel_small:
        if s not in seen: selected.append((s,"small")); seen.add(s)

    # إضافة رموز الكاش الغير مختارة
    for s in cached_set:
        if s not in seen and len(selected) < TARGET_TOTAL + 15:
            selected.append((s,"cached"))
            seen.add(s)

    print(f"   الإجمالي: {len(selected)} رمز (منهم {len(cached_set & seen)} من الكاش)", flush=True)
    # أولوية الكاش للسرعة
    selected.sort(key=lambda x: 0 if x[0] in cached_set else 1)
    return selected[:TARGET_TOTAL + 15]


# ================================================================
# كاش OHLC 1h
# ================================================================
def load_1h_cached(symbol) -> list:
    for path in [
        os.path.join(ICT_CACHE_DIR,   f"{symbol}_1h_ohlc.pkl"),
        os.path.join(OHLC_CACHE_FULL, f"{symbol}_1h.pkl"),
    ]:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return pickle.load(f)
    return None


def save_1h_cached(symbol, data):
    path = os.path.join(ICT_CACHE_DIR, f"{symbol}_1h_ohlc.pkl")
    with open(path, "wb") as f:
        pickle.dump(data, f)


def fetch_1h(symbol: str) -> list:
    """يجلب 1h OHLC (180 يوم) من Binance أو الكاش."""
    cached = load_1h_cached(symbol)
    if cached is not None:
        return cached

    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - DAYS_BACK * INTERVAL_1D_MS
    candles  = []
    cur      = start_ms

    while cur < now_ms - INTERVAL_1H_MS:
        time.sleep(REQUEST_SLEEP)
        params = {"symbol": symbol, "interval": "1h", "startTime": cur, "limit": 1000}
        try:
            rows = binance_get("/api/v3/klines", params=params)
        except Exception as e:
            print(f"\n   [FETCH_ERR] {symbol}: {e}", flush=True)
            break
        if not rows: break
        candles.extend(rows)
        last_ts = int(rows[-1][0])
        if last_ts >= now_ms - INTERVAL_1H_MS: break
        cur = last_ts + INTERVAL_1H_MS

    if not candles:
        return []

    result = [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
               "l": float(r[3]), "c": float(r[4])} for r in candles]
    save_1h_cached(symbol, result)
    return result


# ================================================================
# FIX 1 & 5 & 6: بناء شموع 1d من 1h (بدون تسرّب)
# ================================================================
def build_1d_candles(candles_1h: list) -> list:
    """
    يُجمّع شموع 1h إلى شموع 1d (00:00 UTC → 23:59 UTC).
    نقطة حرجة: شمعة 1d تُعتبر مُغلقة فقط إذا وُجدت شمعة 1h تالية لها.
    يُعيد قائمة: [{"day_ts": ..., "o":..., "h":..., "l":..., "c":..., "closed_before_ms": ...}]
    حيث closed_before_ms = الطابع الزمني للشمعة 1h الأولى في اليوم التالي.
    """
    if not candles_1h:
        return []

    # تجميع الشموع بحسب اليوم UTC
    day_map = {}  # day_key → {"candles": [...], "day_ts": ...}
    for c in candles_1h:
        # ts الشمعة = وقت افتتاحها. اليوم = floor(ts / 1d)
        day_ts = (c["t"] // INTERVAL_1D_MS) * INTERVAL_1D_MS
        if day_ts not in day_map:
            day_map[day_ts] = {"candles": [], "day_ts": day_ts}
        day_map[day_ts]["candles"].append(c)

    # فرز الأيام
    sorted_days = sorted(day_map.keys())
    result = []
    for i, day_ts in enumerate(sorted_days):
        day_candles = day_map[day_ts]["candles"]
        o = day_candles[0]["o"]
        h = max(c["h"] for c in day_candles)
        l = min(c["l"] for c in day_candles)
        c_close = day_candles[-1]["c"]

        # الشمعة اليومية مُغلقة فقط إذا يوجد يوم تالٍ (أي 24 ساعة اكتملت)
        if i < len(sorted_days) - 1:
            next_day_ts = sorted_days[i + 1]
            # أول 1h في اليوم التالي
            next_day_candles = day_map[next_day_ts]["candles"]
            closed_before_ms = next_day_candles[0]["t"]
        else:
            closed_before_ms = None  # اليوم الحالي لم يُغلق بعد

        result.append({
            "day_ts":          day_ts,
            "o":               o,
            "h":               h,
            "l":               l,
            "c":               c_close,
            "closed_before_ms": closed_before_ms,  # أول ms في اليوم التالي
        })

    return result


def get_closed_1d_before(candles_1d: list, t_ms: int) -> list:
    """
    يُعيد قائمة شموع 1d المُغلقة قبل t_ms.
    FIX 1: لا تسرّب — نأخذ فقط الشموع التي closed_before_ms <= t_ms.
    """
    return [d for d in candles_1d if d["closed_before_ms"] is not None and d["closed_before_ms"] <= t_ms]


# ================================================================
# FIX 5: HTF Pivots (على 1d، N=2)
# ================================================================
def find_pivots_htf(highs: list, lows: list, n: int = HTF_SWING_N):
    """
    يُحدّد نقاط swing على HTF.
    pivot_high[i]: highs[i] == max(highs[i-n:i+n+1])
    """
    total = len(highs)
    ph, pl = [], []
    for i in range(n, total - n):
        window_h = highs[max(0,i-n): i+n+1]
        window_l = lows[max(0,i-n):  i+n+1]
        if highs[i] == max(window_h):
            ph.append(i)
        if lows[i] == min(window_l):
            pl.append(i)
    return ph, pl


# ================================================================
# FIX 1: HTF Bias (1d) — Higher Highs + Higher Lows
# ================================================================
def compute_htf_bias(closed_1d: list) -> str:
    """
    يحسب bias HTF من شموع 1d المُغلقة.
    bullish = آخر نقطتا swing high أعلى + آخر نقطتا swing low أعلى
    bearish = آخر نقطتا swing high أقل  + آخر نقطتا swing low أقل
    neutral = غير ذلك أو بيانات غير كافية.
    """
    if len(closed_1d) < MIN_1D_CANDLES:
        return "neutral"

    highs_1d = [d["h"] for d in closed_1d]
    lows_1d  = [d["l"] for d in closed_1d]

    ph, pl = find_pivots_htf(highs_1d, lows_1d, HTF_SWING_N)

    if len(ph) < HTF_MIN_SWING_PTS or len(pl) < HTF_MIN_SWING_PTS:
        return "neutral"

    # آخر نقطتين من كل نوع
    last_shs = [highs_1d[i] for i in ph[-2:]]
    last_sls = [lows_1d[i]  for i in pl[-2:]]

    hh = last_shs[-1] > last_shs[-2]  # higher high
    hl = last_sls[-1] > last_sls[-2]  # higher low
    lh = last_shs[-1] < last_shs[-2]  # lower high
    ll = last_sls[-1] < last_sls[-2]  # lower low

    if hh and hl:
        return "bullish"
    elif lh and ll:
        return "bearish"
    else:
        return "neutral"


# ================================================================
# FIX 2 & 6: OB على HTF 1d + OTE من Dealing Range الحقيقي
# ================================================================
def compute_htf_ob_and_ote(closed_1d: list, price: float):
    """
    FIX 2: OB على 1d، صالح 60 يوم (≈ 60 شمعة 1d).
    FIX 6: OTE من آخر impulse (Dealing Range) على 1d — لا من last high & last low اعتباطيين.

    يُعيد:
      at_htf_ob: 1 إن السعر داخل OB على 1d غير مرتشف
      in_ote:    1 إن السعر في نطاق Fibonacci 62-79% من آخر impulse على 1d
      in_discount: 1 إن السعر أقل من منتصف آخر dealing range
    """
    at_htf_ob   = 0
    in_ote      = 0
    in_discount = 0

    if len(closed_1d) < 10:
        return at_htf_ob, in_ote, in_discount

    highs_1d = [d["h"] for d in closed_1d]
    lows_1d  = [d["l"] for d in closed_1d]
    opens_1d = [d["o"] for d in closed_1d]
    closes_1d= [d["c"] for d in closed_1d]
    n = len(closed_1d)

    ph, pl = find_pivots_htf(highs_1d, lows_1d, HTF_SWING_N)

    # ------------------------------------------------------------------
    # FIX 6: Dealing Range من آخر impulse على 1d
    # impulse = من swing low → swing high اللاحق (يُمثّل حركة صاعدة حقيقية)
    # ------------------------------------------------------------------
    if ph and pl:
        last_ph_i = ph[-1]
        last_pl_i = pl[-1]

        # آخر impulse صاعد: swing low قبل أو في نفس منطقة swing high الأخير
        if last_pl_i < last_ph_i:
            swing_lo = lows_1d[last_pl_i]
            swing_hi = highs_1d[last_ph_i]
        elif len(pl) >= 2 and pl[-2] < last_ph_i:
            swing_lo = lows_1d[pl[-2]]
            swing_hi = highs_1d[last_ph_i]
        else:
            swing_lo = min(lows_1d[-20:]) if len(lows_1d) >= 20 else min(lows_1d)
            swing_hi = max(highs_1d[-20:]) if len(highs_1d) >= 20 else max(highs_1d)

        rng = swing_hi - swing_lo
        if rng > 0:
            mid    = swing_lo + rng * 0.5
            ote_lo = swing_hi - rng * 0.79   # 79% retracement من القمة
            ote_hi = swing_hi - rng * 0.62   # 62% retracement من القمة

            if price < mid:
                in_discount = 1
            if ote_lo <= price <= ote_hi:
                in_ote = 1

    # ------------------------------------------------------------------
    # FIX 2: HTF OB على 1d (صالح OB_1D_VALID_DAYS يوم)
    # OB = شمعة 1d هابطة يتبعها impulse صاعد يكسر قمتها
    # ------------------------------------------------------------------
    ob_lookback_1d = min(OB_1D_VALID_DAYS, n - 1)
    ob_start = max(0, n - ob_lookback_1d)

    for i in range(ob_start, n - IMPULSE_MIN_1D - 1):
        # شمعة هابطة على 1d
        if closes_1d[i] >= opens_1d[i]:
            continue
        ob_lo = min(opens_1d[i], closes_1d[i])
        ob_hi = max(opens_1d[i], closes_1d[i])
        ob_wick_hi = highs_1d[i]

        # impulse صاعد: IMPULSE_MIN_1D+ شموع صاعدة تكسر ob_wick_hi
        up_count   = 0
        broke_high = False
        for j in range(i + 1, min(i + 1 + IMPULSE_MIN_1D + 3, n)):
            if closes_1d[j] > opens_1d[j]:
                up_count += 1
                if highs_1d[j] > ob_wick_hi:
                    broke_high = True
            else:
                break

        if up_count < IMPULSE_MIN_1D or not broke_high:
            continue

        # FIX 3 مُطبَّق على HTF OB أيضاً: تحقق عدم الارتشاف
        mitigated = False
        for k in range(i + 1 + up_count, n):
            if lows_1d[k] <= ob_lo:
                mitigated = True
                break

        if not mitigated and ob_lo <= price <= ob_wick_hi:
            at_htf_ob = 1
            break

    return at_htf_ob, in_ote, in_discount


# ================================================================
# LTF Pivot (1h) — للميزات الأدنى إطاراً
# ================================================================
def find_pivots_ltf(highs: list, lows: list, n: int = 5):
    """Fractal N=5 على 1h للميزات اللحظية (LTF)."""
    total = len(highs)
    ph, pl = [], []
    for i in range(n, total - n):
        window_h = highs[i-n: i+n+1]
        window_l = lows[i-n:  i+n+1]
        if highs[i] == max(window_h): ph.append(i)
        if lows[i]  == min(window_l): pl.append(i)
    return ph, pl


# ================================================================
# FIX 3: FVG مع فحص الملء (في-progress)
# ================================================================
def compute_fvg_valid(candles_hist: list, price: float) -> int:
    """
    FVG صالح فقط إن:
    1. وُجد gap بين candle[i-2].high و candle[i].low
    2. السعر الحالي داخل الـ gap
    3. لم يُملأ: لا شمعة بعد تكوّنه تداولت داخل الـ gap (أي high[k] >= gap_lo وlow[k] <= gap_hi)
    """
    n = len(candles_hist)
    fvg_start = max(0, n - FVG_LOOKBACK_1H)
    highs = [c["h"] for c in candles_hist]
    lows  = [c["l"] for c in candles_hist]

    for i in range(fvg_start + 2, n):
        gap_lo = highs[i - 2]   # candle[i-2].high
        gap_hi = lows[i]        # candle[i].low
        if gap_hi <= gap_lo:
            continue  # لا gap

        # FIX 3: تحقق من عدم الملء بعد تكوّن الـ gap
        filled = False
        for k in range(i + 1, n):
            # أي شمعة تداولت داخل الـ gap تُعتبر ملأ
            if lows[k] <= gap_hi and highs[k] >= gap_lo:
                filled = True
                break

        if not filled and gap_lo <= price <= gap_hi:
            return 1

    return 0


# ================================================================
# LTF BOS/CHoCH و Sweep (على 1h)
# ================================================================
def compute_ltf_structure(candles_hist: list) -> dict:
    """
    يحسب ميزات LTF البنيوية على 1h.
    يُعيد: recent_bos_up, recent_choch_up, recent_sweep, ltf_trigger
    """
    n = len(candles_hist)
    highs  = [c["h"] for c in candles_hist]
    lows   = [c["l"] for c in candles_hist]
    closes = [c["c"] for c in candles_hist]

    lb_start = max(0, n - BOS_LOOKBACK_1H)
    sub_h = highs[lb_start:]
    sub_l = lows[lb_start:]
    sub_c = closes[lb_start:]
    sub_ph, sub_pl = find_pivots_ltf(sub_h, sub_l, 3)

    recent_bos_up   = 0
    recent_choch_up = 0

    if len(sub_ph) >= 2:
        prev_sh = sub_h[sub_ph[-2]]
        if sub_c[-1] > prev_sh:
            recent_bos_up = 1
            if len(sub_ph) >= 3:
                sh_a = sub_h[sub_ph[-3]]
                sh_b = sub_h[sub_ph[-2]]
                if sh_b < sh_a:
                    recent_choch_up = 1

    # Sellside Sweep (1h)
    recent_sweep = 0
    ph_all, pl_all = find_pivots_ltf(highs, lows, 5)
    if pl_all:
        last_swing_low = lows[pl_all[-1]]
        sw_start = max(0, n - 10)
        for i in range(sw_start, n):
            if lows[i] < last_swing_low and closes[i] > last_swing_low:
                recent_sweep = 1
                break

    # LTF trigger: BOS صاعد على 1h (الأقوى كمحفّز)
    ltf_trigger = 1 if recent_bos_up else 0

    return {
        "recent_bos_up_ltf":   recent_bos_up,
        "recent_choch_up_ltf": recent_choch_up,
        "recent_sweep_ltf":    recent_sweep,
        "ltf_trigger":         ltf_trigger,
    }


# ================================================================
# FIX 4: AMD Sequence (تسلسل زمني)
# ================================================================
def compute_amd_sequence(candles_hist: list) -> int:
    """
    FIX 4: Accumulation → Manipulation (Sweep) → Distribution (BOS up) → Entry (retest OB/FVG)
    التسلسل الزمني إلزامي: t_accum < t_sweep < t_bos < t (حالي في نافذة entry)

    يُعيد 1 إن اكتمل التسلسل بالترتيب الصحيح، 0 إن لم يكتمل.
    """
    n = len(candles_hist)
    if n < AMD_ACCUM_WINDOW + AMD_SWEEP_WINDOW + AMD_BOS_WINDOW + 10:
        return 0

    highs  = [c["h"] for c in candles_hist]
    lows   = [c["l"] for c in candles_hist]
    closes = [c["c"] for c in candles_hist]
    opens  = [c["o"] for c in candles_hist]
    price  = closes[-1]

    # --- مرحلة 1: Accumulation (تضيّق النطاق)
    # نبحث في النافذة الأخيرة (AMD_ACCUM_WINDOW...) عن فترة تضيّق
    # نعرّف: Accumulation = آخر AMD_ACCUM_WINDOW شمعة لديها نطاق (h-l) متوسط أقل من المعتاد
    lookback_range = min(n, AMD_ACCUM_WINDOW * 3)
    recent_ranges = [highs[i] - lows[i] for i in range(n - lookback_range, n - AMD_ACCUM_WINDOW)]
    if not recent_ranges:
        return 0
    avg_range = sum(recent_ranges) / len(recent_ranges)

    accum_start = n - AMD_ACCUM_WINDOW - AMD_SWEEP_WINDOW - AMD_BOS_WINDOW
    if accum_start < 0:
        return 0

    # البحث عن نافذة تراكم: فترة تضيّق
    found_accum_end = None
    for i in range(accum_start, n - AMD_SWEEP_WINDOW - AMD_BOS_WINDOW - AMD_ENTRY_WINDOW):
        window = [highs[j] - lows[j] for j in range(i, min(i + AMD_ACCUM_WINDOW, n))]
        if not window: continue
        w_avg = sum(window) / len(window)
        if w_avg <= avg_range * 0.85:   # نطاق أضيق من المعتاد بـ 15%
            found_accum_end = i + len(window) - 1
            break

    if found_accum_end is None:
        return 0

    t_accum = found_accum_end

    # --- مرحلة 2: Manipulation (Sweep under accum range)
    # accum_low = أدنى نقطة في فترة التراكم
    accum_lo = min(lows[max(0, t_accum - AMD_ACCUM_WINDOW): t_accum + 1])
    found_sweep = None
    for i in range(t_accum + 1, min(t_accum + AMD_SWEEP_WINDOW + 1, n - AMD_BOS_WINDOW - 5)):
        if lows[i] < accum_lo and closes[i] > accum_lo:
            found_sweep = i
            break

    if found_sweep is None:
        return 0

    t_sweep = found_sweep

    # --- مرحلة 3: Distribution (BOS up — close يكسر آخر swing high قبل الـ sweep)
    # نحتاج swing high قبل t_sweep
    pre_sweep_highs = highs[:t_sweep]
    if len(pre_sweep_highs) < 10:
        return 0
    recent_sh = max(pre_sweep_highs[-20:])  # آخر swing high مرجعي

    found_bos = None
    for i in range(t_sweep + 1, min(t_sweep + AMD_BOS_WINDOW + 1, n - 5)):
        if closes[i] > recent_sh:
            found_bos = i
            break

    if found_bos is None:
        return 0

    t_bos = found_bos

    # --- مرحلة 4: Entry (السعر يرتد لمنطقة OB/FVG بعد BOS في نافذة AMD_ENTRY_WINDOW)
    # الشرط: السعر الحالي (t=n) يجب أن يكون في نافذة الدخول بعد BOS
    if (n - 1) - t_bos > AMD_ENTRY_WINDOW:
        return 0   # منقضي — الدخول تأخّر

    # الشرط: السعر تراجع نسبياً بعد BOS (pullback)
    bos_high = max(highs[t_bos: min(t_bos + AMD_ENTRY_WINDOW + 1, n)])
    if price < bos_high * 0.95:   # تراجع >5% من القمة
        return 1

    return 0


# ================================================================
# حساب كل الميزات لنقطة t
# ================================================================
FEATURE_NAMES = [
    "htf_bullish_bias",      # FIX 1: HTF 1d bias صاعد
    "at_htf_ob",             # FIX 2: OB على 1d صالح 60 يوم
    "in_fvg_valid",          # FIX 3: FVG صالح غير مملوء
    "recent_bos_up_ltf",     # LTF BOS صاعد (1h)
    "recent_choch_up_ltf",   # LTF CHoCH صاعد
    "recent_sweep_ltf",      # Sweep على 1h
    "in_discount_htf",       # FIX 6: Discount من dealing range الحقيقي
    "in_ote_htf",            # FIX 6: OTE من dealing range الحقيقي
    "ict_aligned",           # FIX 1: HTF bullish + LTF trigger
    "combo_amd",             # FIX 4: تسلسل AMD الزمني الكامل
]

_ZERO_FEATS = {k: 0 for k in FEATURE_NAMES}


def compute_features_v3(candles_1h: list, candles_1d_all: list, t: int) -> dict:
    """
    يحسب الميزات عند نقطة 1h رقم t.
    candles_1h: كل الشموع 1h
    candles_1d_all: كل شموع 1d (مبنية من 1h)
    لا تسرّب: يستخدم candles_1h[0:t] وcandles_1d مُغلقة قبل candles_1h[t].t
    """
    hist_1h = candles_1h[:t]
    n = len(hist_1h)
    if n < 30:
        return dict(_ZERO_FEATS)

    price   = hist_1h[-1]["c"]
    t_ms    = candles_1h[t]["t"]  # الطابع الزمني للشمعة t (المستقبل للبيانات الماضية)

    # FIX 1 & لا تسرّب: شموع 1d مُغلقة قبل t_ms
    closed_1d = get_closed_1d_before(candles_1d_all, t_ms)

    # HTF bias
    htf_bias = compute_htf_bias(closed_1d)
    htf_bullish = 1 if htf_bias == "bullish" else 0

    # HTF OB + OTE + Discount (FIX 2 & 6)
    at_htf_ob, in_ote, in_discount = compute_htf_ob_and_ote(closed_1d, price)

    # FVG valid (FIX 3)
    in_fvg_valid = compute_fvg_valid(hist_1h, price)

    # LTF structure (1h)
    ltf = compute_ltf_structure(hist_1h)

    # AMD sequence (FIX 4)
    combo_amd = compute_amd_sequence(hist_1h)

    # ict_aligned: HTF bullish + LTF trigger (FIX 1)
    ict_aligned = 1 if (htf_bullish == 1 and ltf["ltf_trigger"] == 1) else 0

    return {
        "htf_bullish_bias":    htf_bullish,
        "at_htf_ob":           at_htf_ob,
        "in_fvg_valid":        in_fvg_valid,
        "recent_bos_up_ltf":   ltf["recent_bos_up_ltf"],
        "recent_choch_up_ltf": ltf["recent_choch_up_ltf"],
        "recent_sweep_ltf":    ltf["recent_sweep_ltf"],
        "in_discount_htf":     in_discount,
        "in_ote_htf":          in_ote,
        "ict_aligned":         ict_aligned,
        "combo_amd":           combo_amd,
    }


# ================================================================
# معالجة رمز واحد (streaming)
# ================================================================
def process_symbol(symbol: str, tier: str, rng: random.Random) -> list:
    candles_1h = fetch_1h(symbol)
    if not candles_1h or len(candles_1h) < MIN_1H_CANDLES:
        print(f"   [{symbol}] بيانات غير كافية ({len(candles_1h) if candles_1h else 0})", flush=True)
        return []

    # بناء 1d من 1h (لا جلب إضافي)
    candles_1d = build_1d_candles(candles_1h)
    if len(candles_1d) < MIN_1D_CANDLES:
        print(f"   [{symbol}] شموع 1d غير كافية ({len(candles_1d)})", flush=True)
        # نكمل مع bias neutral (لا نرفض الرمز)
        candles_1d = []

    n = len(candles_1h)
    valid_end   = n - RESERVE_CANDLES
    valid_start = max(30, 24 * MIN_1D_CANDLES // 1)  # نحتاج على الأقل MIN_1D_CANDLES يوم قبل t

    if valid_end <= valid_start:
        return []

    indices   = list(range(valid_start, valid_end))
    sample_sz = min(POINTS_PER_SYMBOL, len(indices))
    sampled   = rng.sample(indices, sample_sz)
    sampled.sort()

    records = []
    for t in sampled:
        t_fwd = t + FWD_48H
        if t_fwd >= n: continue
        entry = candles_1h[t]["c"]
        exit_ = candles_1h[t_fwd]["c"]
        if entry <= 0: continue
        fwd_ret = (exit_ - entry) / entry - FEE

        feats = compute_features_v3(candles_1h, candles_1d, t)
        rec   = {
            "symbol":         symbol,
            "tier":           tier,
            "t_idx":          t,
            "t_ms":           candles_1h[t]["t"],
            "fwd_return_48h": fwd_ret,
        }
        rec.update(feats)
        records.append(rec)

    del candles_1h, candles_1d
    gc.collect()
    check_memory(symbol)
    return records


# ================================================================
# التحليل الإحصائي
# ================================================================
def analyze_feature(name: str, records: list) -> dict:
    treat = np.array([r["fwd_return_48h"] for r in records if r.get(name, 0) == 1])
    ctrl  = np.array([r["fwd_return_48h"] for r in records if r.get(name, 0) == 0])
    if len(treat) < 3 or len(ctrl) < 3:
        return None
    t_stat, p = welch_ttest(treat, ctrl)
    d         = cohen_d(treat, ctrl)
    ci_lo, ci_hi = ci_95_diff(treat, ctrl)
    powered   = len(treat) >= 100
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
        "powered":    powered,
    }


def walk_forward(name: str, records: list) -> dict:
    sorted_recs = sorted(records, key=lambda r: r["t_ms"])
    mid = len(sorted_recs) // 2
    res = {}
    for label, half in [("first_half", sorted_recs[:mid]), ("second_half", sorted_recs[mid:])]:
        treat = np.array([r["fwd_return_48h"] for r in half if r.get(name, 0) == 1])
        ctrl  = np.array([r["fwd_return_48h"] for r in half if r.get(name, 0) == 0])
        if len(treat) < 3 or len(ctrl) < 3:
            res[label] = None
            continue
        _, p = welch_ttest(treat, ctrl)
        d    = cohen_d(treat, ctrl)
        res[label] = {
            "n_treat":    int(len(treat)),
            "n_ctrl":     int(len(ctrl)),
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
    print("=" * 70)
    print("ICT Structural Causal Test v3 — Multi-Timeframe (6 Fixes)")
    print(f"التاريخ: 2026-05-22 | Seed: {SEED}")
    print(f"Fixes: MTF bias + OB age + FVG mitigation + AMD sequence + HTF swing + OTE dealing range")
    print("=" * 70, flush=True)
    t0 = time.time()

    # 0. رموز الكاش
    cached_syms = get_cached_symbols_1h()
    print(f"[0] كاش 1h موجود: {len(cached_syms)} رمز", flush=True)

    # 1. اختيار الرموز
    if os.path.exists(SYMBOL_CACHE):
        print("[1] تحميل الرموز من كاش v3...", flush=True)
        with open(SYMBOL_CACHE, "rb") as f:
            selected = pickle.load(f)
    else:
        print("[1] جلب exchangeInfo...", flush=True)
        all_syms  = get_usdt_symbols()
        selected  = select_symbols(all_syms, cached_syms)
        with open(SYMBOL_CACHE, "wb") as f:
            pickle.dump(selected, f)

    # أولوية الكاش
    selected.sort(key=lambda x: 0 if x[0] in cached_syms else 1)
    n_sym = len(selected)
    print(f"   الرموز: {n_sym} | هدف النقاط: {n_sym * POINTS_PER_SYMBOL:,}\n", flush=True)

    # 2. معالجة streaming
    rng_main    = random.Random(SEED + 1)
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
            import traceback; traceback.print_exc()

    total_pts = len(all_records)
    print(f"\n[تم] معالجة: {n_ok} | مُهمَل: {n_skip} | نقاط: {total_pts:,}", flush=True)

    if total_pts < 100:
        print("[خطأ] بيانات غير كافية.", flush=True)
        return {}

    # 3. حفظ CSV
    print(f"\n[CSV] {total_pts:,} سجل → {OUTPUT_CSV}", flush=True)
    fields = ["symbol","tier","t_idx","t_ms","fwd_return_48h"] + FEATURE_NAMES
    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_records)

    # 4. إحصاء توزيع الميزات
    print("\n[توزيع الميزات]:", flush=True)
    for feat in FEATURE_NAMES:
        n_treat = sum(1 for r in all_records if r.get(feat, 0) == 1)
        pct = 100.0 * n_treat / total_pts if total_pts > 0 else 0
        print(f"  {feat:<28}: {n_treat:>7} ({pct:.1f}%)", flush=True)

    # 5. التحليل الإحصائي
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
                "ci_lo": None, "ci_hi": None, "powered": False,
            })
            p_values.append(1.0)

    q_values = bh_fdr(p_values)
    for res, q in zip(feat_results, q_values):
        res["q_value"] = round(q, 6)

    # 6. Walk-Forward
    print("[تحليل] Walk-Forward (نصف أول / نصف ثانٍ)...", flush=True)
    wf_results = {}
    for res in feat_results:
        wf_results[res["feature"]] = walk_forward(res["feature"], all_records)

    # 7. الحكم
    survivors       = []
    underpowered    = []
    for res in feat_results:
        name = res["feature"]
        q    = res.get("q_value", 1.0)
        d    = abs(res.get("cohen_d", 0.0))
        powered = res.get("powered", True)
        wf   = wf_results.get(name, {})
        wf1  = wf.get("first_half")
        wf2  = wf.get("second_half")
        wf_consistent = (
            wf1 and wf2 and
            ((wf1["diff"] > 0 and wf2["diff"] > 0) or
             (wf1["diff"] < 0 and wf2["diff"] < 0))
        )

        if not powered and res["n_treat"] < 100:
            verdict = "UNDERPOWERED"
            underpowered.append(name)
        elif q < 0.05 and d > 0.1 and wf_consistent:
            verdict = "SURVIVES"
            survivors.append(name)
        else:
            verdict = "REJECTED"

        res["verdict"] = verdict

    # 8. حفظ JSON
    elapsed = int(time.time() - t0)
    output = {
        "meta": {
            "version":         "v3",
            "date":            DATE_STAMP,
            "n_symbols":       n_sym,
            "n_processed":     n_ok,
            "n_skipped":       n_skip,
            "total_points":    total_pts,
            "fee_pct":         FEE * 100,
            "fwd_window_h":    FWD_48H,
            "elapsed_seconds": elapsed,
            "fixes_applied": [
                "1_multi_timeframe_htf_bias_1d",
                "2_ob_age_60d_valid",
                "3_fvg_mitigation_check",
                "4_amd_temporal_sequence",
                "5_htf_swing_on_1d",
                "6_ote_from_dealing_range",
            ],
        },
        "feature_results": feat_results,
        "walk_forward":    wf_results,
        "survivors":       survivors,
        "underpowered":    underpowered,
        "verdict":         "ICT_HAS_CAUSAL_EDGE" if survivors else "ICT_NO_CAUSAL_EDGE",
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    # 9. طباعة الملخص
    print("\n" + "=" * 80)
    print("ICT STRUCTURAL CAUSAL TEST v3 — النتائج")
    print(f"الرموز: {n_ok} | النقاط: {total_pts:,} | الوقت: {elapsed}s")
    print("=" * 80)

    hdr = f"{'Feature':<28} {'n_t':>6} {'n_c':>6} {'μ_t':>8} {'μ_c':>8} {'diff':>8} {'p':>8} {'q':>8} {'d':>7} {'verdict'}"
    print(f"\n{hdr}")
    print("-" * 110)
    for res in feat_results:
        mt  = f"{res['mean_treat']:.4f}" if res['mean_treat']  is not None else "  N/A"
        mc  = f"{res['mean_ctrl']:.4f}"  if res['mean_ctrl']   is not None else "  N/A"
        dif = f"{res['diff']:.4f}"       if res['diff']         is not None else "  N/A"
        print(
            f"{res['feature']:<28} {res['n_treat']:>6} {res['n_ctrl']:>6} "
            f"{mt:>8} {mc:>8} {dif:>8} "
            f"{res['p_value']:>8.5f} {res.get('q_value',1):>8.5f} "
            f"{res['cohen_d']:>7.4f} {res.get('verdict','?')}"
        )

    print(f"\n{'='*50}")
    print(f"[الحكم النهائي]: {output['verdict']}")
    if survivors:
        print(f"  ميزات صامدة (SURVIVES): {', '.join(survivors)}")
        print("  تحذير: لا تُطبَّق في التجميد — للدراسة فقط")
    else:
        print("  لا توجد ميزة ICT متعدد الأطر صامدة أمام FDR < 0.05 + |d| > 0.1 + WF ثابت")
    if underpowered:
        print(f"  ميزات ناقصة القوة (n<100): {', '.join(underpowered)}")

    print(f"\n[ملفات النتائج]:")
    print(f"  JSON: {OUTPUT_JSON}")
    print(f"  CSV:  {OUTPUT_CSV}")

    return output


if __name__ == "__main__":
    main()
