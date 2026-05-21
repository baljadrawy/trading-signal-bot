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
  - معالجة متدفّقة: عملة واحدة → احسب OHLC → احسب ميزات → احفظ → احذف DataFrame
  - بدون scipy — t-test وFDR بـ math/numpy فقط
  - إعادة استخدام كاش OHLC من research/cache/klines/
  - حفظ ميزات جديدة في cache ict/ لتجنّب إعادة الحساب

القيود:
  - بحث فقط — التجميد ساري، لا تعديل على الكود الحيّ
  - بلا حزم جديدة
  - معالجة متدفّقة إلزامية (RAM ~2.2GB)
"""

import os, sys, random, pickle, time, math, json, gc, csv
import requests
from datetime import datetime, timezone

import numpy as np

# ================================================================
# مسارات
# ================================================================
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
# research/scripts → project root
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..", "..")

# كاش OHLC كامل (o/h/l/c) من باكتيستر قديم — 49 عملة
OHLC_CACHE_FULL = os.path.join(PROJECT_ROOT, "analyzer", "research", "cache", "klines")
# كاش ICT الجديد (OHLC كامل للرموز المُجلَبة حديثاً)
ICT_CACHE_DIR   = os.path.join(PROJECT_ROOT, "research", "cache", "ict_ohlc")
os.makedirs(ICT_CACHE_DIR, exist_ok=True)

RESULTS_DIR = os.path.join(PROJECT_ROOT, "research", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

CACHE_ROOT   = os.path.join(PROJECT_ROOT, "research", "cache")
os.makedirs(CACHE_ROOT, exist_ok=True)

DATE_STAMP    = "2026_05_21_ict"
OUTPUT_JSON   = os.path.join(RESULTS_DIR, f"ict_structural_causal_{DATE_STAMP}.json")
OUTPUT_CSV    = os.path.join(RESULTS_DIR, f"ict_structural_causal_{DATE_STAMP}_features.csv")
SYMBOL_CACHE  = os.path.join(CACHE_ROOT, "ict_symbols.pkl")

# ================================================================
# ثوابت
# ================================================================
SEED              = 20260521_2
BINANCE_BASE      = "https://api.binance.com"
INTERVAL          = "1h"
INTERVAL_MS       = 3_600_000
DAYS_BACK         = 180
FWD_48H           = 48          # نافذة الهدف
FEE               = 0.003       # 0.3% رسوم round-trip
RESERVE_CANDLES   = FWD_48H + 10   # هامش بعد آخر نقطة
POINTS_PER_SYMBOL = 1200        # نقطة عشوائية / رمز
MIN_CANDLES_REQ   = 200         # حد أدنى للشموع

# عدد الرموز المستهدف
TARGET_TOTAL   = 90             # 30 large + 30 mid + 30 small
TARGET_LARGE   = 30
TARGET_MID     = 30
TARGET_SMALL   = 30

REQUEST_SLEEP  = 0.25           # ثانية بين طلبات Binance
BOOTSTRAP_N    = 500            # معاينات bootstrap (محدودة بالذاكرة)

# معاملات حساب الميزات
FRACTAL_N      = 5              # N شموع قبل/بعد لـ pivot detection
BOS_LOOKBACK   = 20             # شموع للبحث عن BOS/CHoCH
SWEEP_LOOKBACK = 10             # شموع للبحث عن Liquidity Sweep
OB_MAX_AGE     = 50             # أقصى عمر للـ Order Block (شموع)
FVG_LOOKBACK   = 30             # شموع للبحث عن FVG
IMPULSE_MIN    = 3              # أقل عدد شموع صاعدة للـ impulse

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
        print(f"[MEM] RSS={rss//1024//1024}MB حدّ={MEM_LIMIT_BYTES//1024//1024}MB عند {symbol} → gc", flush=True)
        gc.collect()


# ================================================================
# إحصاء (بلا scipy)
# ================================================================
def _betainc(a, b, x):
    """Regularized incomplete beta — Lentz continued fraction."""
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
    """Welch t-test → (t, p)."""
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return 0.0, 1.0
    m1, m2 = float(np.mean(a)), float(np.mean(b))
    v1 = float(np.var(a, ddof=1))
    v2 = float(np.var(b, ddof=1))
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


def ci_95(a: np.ndarray, b: np.ndarray):
    """Welch t-based 95% CI للفرق mean_a - mean_b."""
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3: return (None, None)
    m1, m2 = float(np.mean(a)), float(np.mean(b))
    v1 = float(np.var(a, ddof=1))
    v2 = float(np.var(b, ddof=1))
    se = math.sqrt(v1 / n1 + v2 / n2)
    # t_critical at df≈min(n1,n2)-1 conservatively
    # استخدام t=1.96 تقريباً لـ n كبير
    t_crit = 1.96
    diff = m1 - m2
    return (diff - t_crit * se, diff + t_crit * se)


def bh_fdr(p_values: list) -> list:
    """Benjamini-Hochberg FDR correction → q-values."""
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
                print(f"\n[RATE_LIMIT] 418 IP ban → انتظار 120s", flush=True)
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


def select_symbols_stratified(all_symbols):
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

    result = (
        [(s, "large") for s in sel_large] +
        [(s, "mid")   for s in sel_mid]   +
        [(s, "small") for s in sel_small]
    )
    print(f"   الإجمالي: {len(result)} رمزاً", flush=True)
    return result


# ================================================================
# كاش OHLC
# ================================================================
def _ict_cache_path(symbol):
    return os.path.join(ICT_CACHE_DIR, f"{symbol}_1h_ohlc.pkl")


def _old_cache_path(symbol):
    """كاش من سكريبت backtest القديم (OHLC كامل)."""
    return os.path.join(OHLC_CACHE_FULL, f"{symbol}_1h.pkl")


def load_ohlc_cached(symbol) -> list:
    """يجلب OHLC من الكاش المتاح (ICT > full > None)."""
    p = _ict_cache_path(symbol)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    p2 = _old_cache_path(symbol)
    if os.path.exists(p2):
        with open(p2, "rb") as f:
            data = pickle.load(f)
        # كل سجل: {"t","o","h","l","c"} — نفس الشكل المطلوب
        return data
    return None


def save_ohlc_cached(symbol, data):
    with open(_ict_cache_path(symbol), "wb") as f:
        pickle.dump(data, f)


def fetch_ohlc_1h(symbol: str) -> list:
    """
    يجلب OHLC كامل (180 يوم، 1h) من Binance.
    يُعيد list of {"t":ms,"o":f,"h":f,"l":f,"c":f}.
    """
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

    result = [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])}
              for r in candles]
    save_ohlc_cached(symbol, result)
    return result


# ================================================================
# حساب ميزات ICT (بلا تسرّب مستقبل)
# الكل يعمل على بيانات حتى index t-1 فقط عند كل نقطة t
# ================================================================

def find_pivots(candles, n_left=FRACTAL_N, n_right=FRACTAL_N):
    """
    يُعيد قوائم pivot_highs و pivot_lows كـ indices.
    pivot_high[i] إذا candles[i].h = max في [i-n_left .. i+n_right]
    لا تسرّب: نستخدم هذه الدالة على سلايس [0..t-1]
    """
    n = len(candles)
    highs = [c["h"] for c in candles]
    lows  = [c["l"] for c in candles]
    ph, pl = [], []
    for i in range(n_left, n - n_right):
        window_h = highs[i - n_left: i + n_right + 1]
        window_l = lows[i - n_left: i + n_right + 1]
        if highs[i] == max(window_h):
            ph.append(i)
        if lows[i] == min(window_l):
            pl.append(i)
    return ph, pl


def compute_ict_features(candles: list, t: int) -> dict:
    """
    يحسب ميزات ICT الثنائية عند نقطة زمنية t.
    يستخدم candles[0..t-1] فقط (لا تسرّب).
    candles: list of {"t","o","h","l","c"}

    يُعيد dict من الميزات الثنائية.
    """
    # سلايس آمن (حتى t-1)
    hist = candles[:t]
    n    = len(hist)

    # قيم افتراضية
    feats = {
        "at_bullish_OB":       0,
        "in_FVG_bullish":      0,
        "recent_BOS_up":       0,
        "recent_CHoCH_up":     0,
        "recent_sellside_sweep": 0,
        "in_discount_zone":    0,
        "in_OTE":              0,
        "combo_OB_sweep":      0,
        "combo_discount_BOS":  0,
    }

    if n < 30:
        return feats

    # سعر الإغلاق الحالي (آخر شمعة في hist = شمعة t-1)
    price = hist[-1]["c"]

    # ----------------------------------------------------------------
    # Pivot highs / lows (على كامل hist)
    # ----------------------------------------------------------------
    ph_idx, pl_idx = find_pivots(hist, FRACTAL_N, FRACTAL_N)

    # ----------------------------------------------------------------
    # 1. Swing Range → Premium / Discount / OTE
    # ----------------------------------------------------------------
    in_discount = 0
    in_OTE      = 0
    if len(ph_idx) >= 1 and len(pl_idx) >= 1:
        last_sh = hist[ph_idx[-1]]["h"]   # آخر swing high
        last_sl = hist[pl_idx[-1]]["l"]   # آخر swing low
        if last_sh > last_sl:
            rng   = last_sh - last_sl
            mid   = last_sl + rng * 0.5
            ote_lo = last_sh - rng * 0.79  # Fibonacci 79%
            ote_hi = last_sh - rng * 0.62  # Fibonacci 62%
            if price < mid:
                in_discount = 1
            if ote_lo <= price <= ote_hi:
                in_OTE = 1

    feats["in_discount_zone"] = in_discount
    feats["in_OTE"]           = in_OTE

    # ----------------------------------------------------------------
    # 2. BOS / CHoCH
    # ----------------------------------------------------------------
    recent_bos_up   = 0
    recent_choch_up = 0

    # نبحث في آخر BOS_LOOKBACK شمعة
    lookback_start = max(0, n - BOS_LOOKBACK)
    sub = hist[lookback_start:]
    sub_ph, sub_pl = find_pivots(sub, 3, 3)   # fractal أصغر للنافذة الصغيرة

    # BOS Up: سعر يكسر فوق أعلى pivot high سابق
    if len(sub_ph) >= 2:
        prev_sh = sub[sub_ph[-2]]["h"]   # آخر swing high قبل الأخير
        # آخر شمعة فوق pivot high السابق
        if sub[-1]["c"] > prev_sh:
            recent_bos_up = 1

            # CHoCH Up: BOS صاعد بعد downtrend مؤكد
            # downtrend: آخر swing high كان أقل من السابق له
            if len(sub_ph) >= 3:
                sh_a = sub[sub_ph[-3]]["h"]
                sh_b = sub[sub_ph[-2]]["h"]
                if sh_b < sh_a:   # آخر قمة أقل من قبلها = downtrend
                    recent_choch_up = 1

    feats["recent_BOS_up"]   = recent_bos_up
    feats["recent_CHoCH_up"] = recent_choch_up

    # ----------------------------------------------------------------
    # 3. Liquidity Sweep (Sellside)
    # ----------------------------------------------------------------
    recent_sweep = 0
    sweep_start  = max(0, n - SWEEP_LOOKBACK)
    sweep_slice  = hist[sweep_start:]

    # Sellside sweep: low يكسر آخر swing low ثم close فوقه
    if len(pl_idx) >= 1:
        last_swing_low = hist[pl_idx[-1]]["l"]
        for c in sweep_slice:
            if c["l"] < last_swing_low and c["c"] > last_swing_low:
                recent_sweep = 1
                break

    feats["recent_sellside_sweep"] = recent_sweep

    # ----------------------------------------------------------------
    # 4. Fair Value Gap (FVG Bullish)
    # ----------------------------------------------------------------
    in_fvg = 0
    fvg_start = max(0, n - FVG_LOOKBACK)
    fvg_hist  = hist[fvg_start:]
    fvg_n     = len(fvg_hist)

    # FVG Bullish: fvg_hist[i-2].high < fvg_hist[i].low → الفجوة بينهما
    for i in range(2, fvg_n):
        fvg_lo = fvg_hist[i - 2]["h"]
        fvg_hi = fvg_hist[i]["l"]
        if fvg_hi > fvg_lo:   # فجوة حقيقية
            # هل السعر الحالي داخل الفجوة؟
            if fvg_lo <= price <= fvg_hi:
                in_fvg = 1
                break

    feats["in_FVG_bullish"] = in_fvg

    # ----------------------------------------------------------------
    # 5. Bullish Order Block
    # تعريف: آخر شمعة هابطة قبل impulse صاعد قوي
    # impulse = IMPULSE_MIN+ شموع صاعدة متتالية تتجاوز high الشمعة الهابطة
    # OB غير مرتشّف = السعر لم يعد إلى نطاق OB بعد التكوّن
    # ----------------------------------------------------------------
    at_ob = 0
    ob_start = max(0, n - OB_MAX_AGE)
    ob_hist  = hist[ob_start:]
    ob_n     = len(ob_hist)

    i = 0
    while i < ob_n - IMPULSE_MIN - 1:
        c = ob_hist[i]
        # هل شمعة هابطة؟ (close < open)
        if c["c"] < c["o"]:
            ob_high = max(c["o"], c["c"])   # top of OB body
            ob_low  = min(c["o"], c["c"])   # bottom of OB body
            ob_body_high = c["h"]           # wick top

            # تحقق من impulse صاعد بعدها
            up_count = 0
            broke_high = False
            for j in range(i + 1, min(i + 1 + IMPULSE_MIN + 3, ob_n)):
                cj = ob_hist[j]
                if cj["c"] > cj["o"]:   # شمعة صاعدة
                    up_count += 1
                    if cj["h"] > ob_body_high:
                        broke_high = True
                else:
                    break  # توقف إذا انكسر التسلسل

            if up_count >= IMPULSE_MIN and broke_high:
                # OB موجود من i، هل مرتشّف؟ (السعر عاد لنطاق OB)
                mitigated = False
                for k in range(i + 1 + up_count, ob_n):
                    if ob_hist[k]["l"] <= ob_low:
                        mitigated = True
                        break

                if not mitigated:
                    # هل السعر الحالي داخل نطاق OB؟
                    if ob_low <= price <= ob_body_high:
                        at_ob = 1
                        break
        i += 1

    feats["at_bullish_OB"] = at_ob

    # ----------------------------------------------------------------
    # 6. Combos
    # ----------------------------------------------------------------
    feats["combo_OB_sweep"]      = 1 if (at_ob and recent_sweep) else 0
    feats["combo_discount_BOS"]  = 1 if (in_discount and recent_bos_up) else 0

    return feats


# ================================================================
# معالجة رمز واحد (streaming)
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


def process_symbol(symbol: str, tier: str, rng: random.Random) -> list:
    """
    يعالج رمزاً واحداً ويُعيد قائمة من السجلات.
    كل سجل: dict {فيتشرات + fwd_return_48h + symbol + t_idx}.
    """
    candles = fetch_ohlc_1h(symbol)
    if not candles or len(candles) < MIN_CANDLES_REQ:
        print(f"   [{symbol}] بيانات غير كافية: {len(candles) if candles else 0} شمعة", flush=True)
        return []

    n = len(candles)
    # نطاق آمن: من FRACTAL_N*2 حتى n - RESERVE_CANDLES
    valid_end = n - RESERVE_CANDLES
    valid_start = FRACTAL_N * 2 + 20

    if valid_end <= valid_start:
        return []

    # اختيار نقاط عشوائية
    indices = list(range(valid_start, valid_end))
    sample_size = min(POINTS_PER_SYMBOL, len(indices))
    sampled = rng.sample(indices, sample_size)
    sampled.sort()   # ترتيب زمني (لا يؤثر على الحساب)

    records = []
    for t in sampled:
        # forward return 48h
        t_fwd = t + FWD_48H
        if t_fwd >= n:
            continue
        entry_price = candles[t]["c"]
        exit_price  = candles[t_fwd]["c"]
        if entry_price <= 0:
            continue
        fwd_return = (exit_price - entry_price) / entry_price - FEE

        # ميزات ICT (بيانات حتى t-1)
        feats = compute_ict_features(candles, t)

        rec = {"symbol": symbol, "tier": tier, "t_idx": t, "fwd_return_48h": fwd_return}
        rec.update(feats)
        records.append(rec)

    # تحرير الذاكرة
    del candles
    gc.collect()
    check_memory(symbol)

    return records


# ================================================================
# التحليل الإحصائي
# ================================================================
def analyze_feature(name: str, all_records: list):
    """يُعيد نتائج t-test لميزة واحدة."""
    treat = np.array([r["fwd_return_48h"] for r in all_records if r.get(name, 0) == 1])
    ctrl  = np.array([r["fwd_return_48h"] for r in all_records if r.get(name, 0) == 0])
    if len(treat) < 3 or len(ctrl) < 3:
        return None
    t, p   = welch_ttest(treat, ctrl)
    d      = cohen_d(treat, ctrl)
    ci_lo, ci_hi = ci_95(treat, ctrl)
    return {
        "feature":    name,
        "n_treat":    int(len(treat)),
        "n_ctrl":     int(len(ctrl)),
        "mean_treat": float(np.mean(treat)),
        "mean_ctrl":  float(np.mean(ctrl)),
        "diff":       float(np.mean(treat)) - float(np.mean(ctrl)),
        "p_value":    p,
        "cohen_d":    d,
        "ci_lo":      ci_lo,
        "ci_hi":      ci_hi,
    }


def walk_forward_analysis(name: str, all_records: list) -> dict:
    """يقسّم الـ records زمنياً (نصف أول / نصف ثاني) ويُعيد نتائج كل نصف."""
    # فرز بـ t_idx
    sorted_recs = sorted(all_records, key=lambda r: r["t_idx"])
    mid = len(sorted_recs) // 2
    first_half  = sorted_recs[:mid]
    second_half = sorted_recs[mid:]

    res = {}
    for label, half in [("first_half", first_half), ("second_half", second_half)]:
        treat = np.array([r["fwd_return_48h"] for r in half if r.get(name, 0) == 1])
        ctrl  = np.array([r["fwd_return_48h"] for r in half if r.get(name, 0) == 0])
        if len(treat) < 3 or len(ctrl) < 3:
            res[label] = None
            continue
        _, p = welch_ttest(treat, ctrl)
        d    = cohen_d(treat, ctrl)
        res[label] = {
            "n_treat": len(treat), "n_ctrl": len(ctrl),
            "mean_treat": float(np.mean(treat)), "mean_ctrl": float(np.mean(ctrl)),
            "diff": float(np.mean(treat)) - float(np.mean(ctrl)),
            "p": p, "cohen_d": d,
        }
    return res


# ================================================================
# Main
# ================================================================
def main():
    print("=" * 60)
    print("ICT Structural Causal Test — 2026-05-21")
    print("=" * 60)
    t_start = time.time()

    # ------------------------------------------------------------------
    # اختيار الرموز
    # ------------------------------------------------------------------
    if os.path.exists(SYMBOL_CACHE):
        print("[0] تحميل الرموز من كاش...", flush=True)
        with open(SYMBOL_CACHE, "rb") as f:
            selected = pickle.load(f)
    else:
        print("[1] جلب exchangeInfo...", flush=True)
        all_syms = get_usdt_symbols()
        selected = select_symbols_stratified(all_syms)
        with open(SYMBOL_CACHE, "wb") as f:
            pickle.dump(selected, f)

    n_symbols = len(selected)
    print(f"\n   الرموز: {n_symbols} | هدف النقاط: {n_symbols * POINTS_PER_SYMBOL:,}\n", flush=True)

    # ------------------------------------------------------------------
    # معالجة streaming
    # ------------------------------------------------------------------
    rng = random.Random(SEED + 1)
    all_records = []
    n_processed = 0
    n_skipped   = 0

    for i, (symbol, tier) in enumerate(selected):
        print(f"[{i+1}/{n_symbols}] {symbol} ({tier})... ", end="", flush=True)
        try:
            records = process_symbol(symbol, tier, rng)
            n_processed += 1
            all_records.extend(records)
            print(f"{len(records)} نقطة | إجمالي: {len(all_records):,}", flush=True)
        except Exception as e:
            print(f"خطأ: {e}", flush=True)
            n_skipped += 1

    total_pts = len(all_records)
    print(f"\n[تم] {n_processed} رمز معالَج، {n_skipped} مُهمَل")
    print(f"[تم] إجمالي نقاط القياس: {total_pts:,}", flush=True)

    # ------------------------------------------------------------------
    # حفظ CSV
    # ------------------------------------------------------------------
    if all_records:
        print(f"\n[CSV] حفظ {total_pts:,} سجل...", flush=True)
        fields = ["symbol", "tier", "t_idx", "fwd_return_48h"] + FEATURE_NAMES
        with open(OUTPUT_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_records)

    # ------------------------------------------------------------------
    # التحليل الإحصائي
    # ------------------------------------------------------------------
    print("\n[تحليل] حساب t-test لكل ميزة...", flush=True)
    feature_results = []
    p_values = []

    for name in FEATURE_NAMES:
        res = analyze_feature(name, all_records)
        if res:
            feature_results.append(res)
            p_values.append(res["p_value"])
        else:
            feature_results.append({"feature": name, "n_treat": 0, "n_ctrl": 0,
                                    "mean_treat": None, "mean_ctrl": None,
                                    "diff": None, "p_value": 1.0, "cohen_d": 0.0,
                                    "ci_lo": None, "ci_hi": None})
            p_values.append(1.0)

    # FDR correction
    q_values = bh_fdr(p_values)
    for res, q in zip(feature_results, q_values):
        res["q_value"] = q

    # ------------------------------------------------------------------
    # Walk-Forward
    # ------------------------------------------------------------------
    print("[تحليل] Walk-Forward...", flush=True)
    wf_results = {}
    for res in feature_results:
        name = res["feature"]
        wf_results[name] = walk_forward_analysis(name, all_records)

    # ------------------------------------------------------------------
    # الحكم على كل ميزة
    # ------------------------------------------------------------------
    survives = []
    for res in feature_results:
        name = res["feature"]
        q    = res.get("q_value", 1.0)
        d    = abs(res.get("cohen_d", 0.0))
        wf   = wf_results.get(name, {})

        # تحقق من اتجاه ثابت في walk-forward
        wf_consistent = False
        wf1 = wf.get("first_half")
        wf2 = wf.get("second_half")
        if wf1 and wf2:
            if (wf1["diff"] > 0 and wf2["diff"] > 0) or (wf1["diff"] < 0 and wf2["diff"] < 0):
                wf_consistent = True

        verdict = "SURVIVES" if (q < 0.05 and d > 0.1 and wf_consistent) else "REJECTED"
        res["verdict"] = verdict
        if verdict == "SURVIVES":
            survives.append(name)

    # ------------------------------------------------------------------
    # حفظ JSON
    # ------------------------------------------------------------------
    elapsed = time.time() - t_start
    output = {
        "meta": {
            "date": DATE_STAMP,
            "n_symbols": n_symbols,
            "n_processed": n_processed,
            "n_skipped": n_skipped,
            "total_points": total_pts,
            "fee_pct": FEE * 100,
            "fwd_window_h": FWD_48H,
            "elapsed_seconds": int(elapsed),
        },
        "feature_results": feature_results,
        "walk_forward": wf_results,
        "survivors": survives,
        "verdict": "ICT_HAS_CAUSAL_EDGE" if survives else "ICT_NO_CAUSAL_EDGE",
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # طباعة ملخص
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"  ICT Structural Causal Test — ملخص النتائج")
    print(f"  الرموز: {n_processed} | النقاط: {total_pts:,} | الوقت: {int(elapsed)}s")
    print("=" * 60)

    print("\n[ميزات مفردة]")
    header = f"{'Feature':<28} {'n_t':>7} {'n_c':>7} {'μ_treat':>8} {'μ_ctrl':>8} {'diff':>8} {'p':>7} {'q':>7} {'d':>6} {'verdict'}"
    print(header)
    print("-" * len(header))
    for res in feature_results:
        mt  = f"{res['mean_treat']:.4f}" if res['mean_treat'] is not None else "N/A"
        mc  = f"{res['mean_ctrl']:.4f}"  if res['mean_ctrl']  is not None else "N/A"
        dif = f"{res['diff']:.4f}"       if res['diff']        is not None else "N/A"
        print(
            f"{res['feature']:<28} {res['n_treat']:>7} {res['n_ctrl']:>7} "
            f"{mt:>8} {mc:>8} {dif:>8} "
            f"{res['p_value']:>7.4f} {res.get('q_value',1):>7.4f} "
            f"{res['cohen_d']:>6.3f} {res['verdict']}"
        )

    print(f"\n[Walk-Forward للميزات الناجية]: {survives if survives else 'لا شيء'}")
    for name in survives:
        wf = wf_results[name]
        h1 = wf.get("first_half")
        h2 = wf.get("second_half")
        print(f"  {name}:")
        if h1: print(f"    النصف1: diff={h1['diff']:.4f}, p={h1['p']:.4f}, d={h1['cohen_d']:.3f}, n={h1['n_treat']}")
        if h2: print(f"    النصف2: diff={h2['diff']:.4f}, p={h2['p']:.4f}, d={h2['cohen_d']:.3f}, n={h2['n_treat']}")

    print(f"\n[الحكم]: {output['verdict']}")
    if not survives:
        print("  لا توجد ميزة ICT بنيوية صامدة أمام FDR + Cohen d > 0.1 + walk-forward ثابت.")
    else:
        print(f"  مرشّحات ما بعد التجميد: {', '.join(survives)}")

    print(f"\n[نتائج محفوظة في]:\n  {OUTPUT_JSON}\n  {OUTPUT_CSV}")
    return output


if __name__ == "__main__":
    main()
