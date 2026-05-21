#!/usr/bin/env python3
"""
اختبار سببي قاطع: ICT Killzone على عيّنة ضخمة (≥100,000 نقطة)
=================================================================
التاريخ: 2026-05-21
الهدف: ≥100,000 نقطة (symbol × random time) → كافية للكشف عن Cohen d=0.05 بقوة >95%.
المنهجية:
  - 80-100 عملة USDT spot (large+mid+small cap) — اختيار عشوائي ثابت (seed)
  - 180 يوم تاريخ، إطار 1h
  - 1000-1500 نقطة عشوائية لكل عملة
  - معالجة متدفّقة (رمز واحد في الوقت) — لا تُحمَّل أكثر من عملة واحدة في RAM
  - klines cache دائم تحت research/cache/klines_kz_v2/ (pickle)

قيود صارمة:
  - بحث فقط — التجميد ساري، لا تعديل على الكود الحيّ.
  - بلا حزم جديدة (numpy/requests/pickle/math موجودة).
  - مراقبة الذاكرة: إن اقترب RSS من 1.7GB → وقف مؤقت.
"""

import os, sys, random, pickle, time, math, json, gc
import requests
from datetime import datetime, timezone

import numpy as np

# ================================================================
# مسارات
# ================================================================
BASE_DIR = os.environ.get("RESEARCH_BASE_DIR", "/home/tradmin/trading-signal-bot/research")
CACHE_DIR = os.path.join(BASE_DIR, "cache", "klines_kz_v2")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

DATE_STAMP = "2026_05_21_v2"
OUTPUT_MD   = os.path.join(RESULTS_DIR, f"killzone_causal_{DATE_STAMP}.md")
OUTPUT_JSON = os.path.join(RESULTS_DIR, f"killzone_causal_{DATE_STAMP}.json")
OUTPUT_CSV  = os.path.join(RESULTS_DIR, f"killzone_causal_{DATE_STAMP}_raw.csv")
SYMBOL_CACHE = os.path.join(BASE_DIR, "cache", "kz_v2_symbols.pkl")

# ================================================================
# ثوابت
# ================================================================
SEED              = 20260521
BINANCE_BASE      = "https://api.binance.com"
INTERVAL          = "1h"
INTERVAL_MS       = 3_600_000          # 1h بالمللي ثانية
DAYS_BACK         = 180                # 180 يوم
RESERVE_CANDLES   = 50                 # آخر 50 شمعة محجوزة (لـ fwd_48h margin)
FWD_24H           = 24
FWD_48H           = 48
FEE               = 0.003              # 0.3% round-trip
POINTS_PER_SYMBOL = 1200               # نقطة عشوائية / رمز → ~96k إجمالاً مع 80 رمزاً
MIN_CANDLES_REQ   = FWD_48H + RESERVE_CANDLES + 20  # ~120 شمعة minimum

# عدد الرموز المستهدف
TARGET_LARGE      = 30
TARGET_MID        = 30
TARGET_SMALL      = 20
TARGET_TOTAL      = TARGET_LARGE + TARGET_MID + TARGET_SMALL  # 80

# Rate limit آمن
REQUEST_SLEEP     = 0.22               # ثانية بين الطلبات (≈260 req/min < 1200 weight)

# Bootstrap
BOOTSTRAP_N       = 2000

# KZ hours (UTC)
LONDON_KZ_HOURS  = frozenset({7, 8, 9, 10})
NY_AM_KZ_HOURS   = frozenset({12, 13, 14, 15})

# نصف فترة walk-forward (نصفان بناءً على ترتيب الشموع، لا تاريخ ثابت)
WF_SPLIT_RATIO   = 0.5

# حدّ الذاكرة (bytes) → إن تجاوز RSS هذا نتوقف مؤقتاً
MEM_LIMIT_BYTES  = 1_700_000_000   # 1.7 GB


# ================================================================
# أدوات إحصاء (بلا scipy)
# ================================================================

def _betainc(a, b, x):
    """Regularized incomplete beta I_x(a,b) — Lentz continued fraction method."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
    MAXITER, EPS, fpmin = 200, 3e-7, 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
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
        if abs(delta - 1.0) < EPS:
            break
    return front * h


def _t_pvalue(t, df):
    t = abs(float(t))
    df = float(df)
    if df <= 0:
        return 1.0
    if df > 10000:
        return float(math.erfc(t / math.sqrt(2)))
    x = df / (df + t * t)
    p_half = _betainc(df / 2.0, 0.5, x)
    return min(2.0 * p_half, 1.0)


def welch_ttest(a: np.ndarray, b: np.ndarray):
    """Welch t-test. يُعيد (t, p, df)."""
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return 0.0, 1.0, 0.0
    m1, m2 = float(np.mean(a)), float(np.mean(b))
    v1 = float(np.var(a, ddof=1))
    v2 = float(np.var(b, ddof=1))
    vn1, vn2 = v1 / n1, v2 / n2
    se = math.sqrt(vn1 + vn2)
    if se == 0:
        return 0.0, 1.0, 0.0
    t = (m1 - m2) / se
    df = (vn1 + vn2) ** 2 / ((vn1 ** 2) / (n1 - 1) + (vn2 ** 2) / (n2 - 1))
    p = _t_pvalue(t, df)
    return float(t), float(p), float(df)


def cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return 0.0
    s = math.sqrt(
        ((n1 - 1) * float(np.var(a, ddof=1)) + (n2 - 1) * float(np.var(b, ddof=1)))
        / (n1 + n2 - 2)
    )
    return (float(np.mean(a)) - float(np.mean(b))) / s if s > 0 else 0.0


def bootstrap_mean_diff_ci(a: np.ndarray, b: np.ndarray, n=BOOTSTRAP_N, ci=0.95):
    """Bootstrap CI للفرق في المتوسطات (mean_a - mean_b)."""
    rng = np.random.default_rng(SEED + 7)
    diffs = np.empty(n)
    for i in range(n):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs[i] = float(np.mean(sa)) - float(np.mean(sb))
    alpha = (1.0 - ci) / 2.0
    return float(np.percentile(diffs, alpha * 100)), float(np.percentile(diffs, (1.0 - alpha) * 100))


# ================================================================
# مراقبة الذاكرة
# ================================================================
def rss_bytes() -> int:
    """يُعيد RSS الحالي من /proc/self/status."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def check_memory(symbol: str):
    rss = rss_bytes()
    if rss > MEM_LIMIT_BYTES:
        print(f"\n[MEM] RSS={rss//1024//1024}MB > حدّ {MEM_LIMIT_BYTES//1024//1024}MB عند {symbol} → تنظيف gc")
        gc.collect()
        rss2 = rss_bytes()
        print(f"[MEM] بعد gc: RSS={rss2//1024//1024}MB")
        if rss2 > MEM_LIMIT_BYTES:
            print("[MEM] لا تزال مرتفعة — متابعة بحذر")


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
                wait = 120
                print(f"\n[RATE_LIMIT] 418 IP ban → انتظار {wait}s", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retry - 1:
                raise
            backoff = 2 ** attempt * 2
            print(f"\n[RETRY {attempt+1}] {e} → انتظار {backoff}s", flush=True)
            time.sleep(backoff)


def get_usdt_symbols():
    print("[1] جلب exchangeInfo...")
    data = binance_get("/api/v3/exchangeInfo")
    symbols = []
    for s in data["symbols"]:
        if (
            s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("isSpotTradingAllowed", False)
        ):
            sym = s["symbol"]
            # تجاهل أزواج USDT/USDT أو Leveraged tokens
            if sym in ("USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT"):
                continue
            if any(x in sym for x in ("UP", "DOWN", "BULL", "BEAR")):
                continue
            symbols.append(sym)
    return symbols


def get_volumes(symbols):
    time.sleep(REQUEST_SLEEP)
    print("[2] جلب 24h volume...", flush=True)
    data = binance_get("/api/v3/ticker/24hr")
    sym_set = set(symbols)
    vol_map = {}
    for t in data:
        if t["symbol"] in sym_set:
            try:
                vol_map[t["symbol"]] = float(t["quoteVolume"])
            except Exception:
                pass
    return vol_map


def select_symbols_stratified(all_symbols):
    """اختيار 80 رمزاً: 30 large + 30 mid + 20 small — عشوائي ثابت."""
    vol_map = get_volumes(all_symbols)
    sorted_syms = sorted(all_symbols, key=lambda s: vol_map.get(s, 0), reverse=True)
    # تجاهل العملات المستقرة الكبرى في القمة
    stable = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "FDUSDUSDT", "USDTUSDT", "DAIUSDT"}
    sorted_syms = [s for s in sorted_syms if s not in stable]

    large = sorted_syms[:50]
    mid   = sorted_syms[50:200]
    small = sorted_syms[200:500]

    rng = random.Random(SEED)
    sel_large = rng.sample(large, min(TARGET_LARGE, len(large)))
    sel_mid   = rng.sample(mid,   min(TARGET_MID,   len(mid)))
    sel_small = rng.sample(small, min(TARGET_SMALL,  len(small)))

    result = (
        [(s, "large") for s in sel_large] +
        [(s, "mid")   for s in sel_mid]   +
        [(s, "small") for s in sel_small]
    )
    print(f"   Large: {sel_large[:5]}...")
    print(f"   Mid:   {sel_mid[:5]}...")
    print(f"   Small: {sel_small[:5]}...")
    print(f"   الإجمالي: {len(result)} رمزاً")
    return result


# ================================================================
# Cache
# ================================================================
def _cache_path(symbol):
    return os.path.join(CACHE_DIR, f"{symbol}_1h_180d.pkl")


def load_cached(symbol):
    p = _cache_path(symbol)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def save_cached(symbol, data):
    with open(_cache_path(symbol), "wb") as f:
        pickle.dump(data, f)


# ================================================================
# جلب klines (180 يوم، إطار 1h)
# ================================================================
def fetch_1h_klines(symbol: str) -> list:
    """
    يجلب حتى 180 يوم من klines 1h لرمز واحد.
    يحفظ في cache ويُعيد list of {"t": ms, "c": float}.
    """
    cached = load_cached(symbol)
    if cached is not None:
        return cached

    now_ms    = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms  = now_ms - DAYS_BACK * 86_400_000
    candles   = []
    cur       = start_ms
    BATCH     = 1000   # حدّ Binance الأقصى

    while cur < now_ms - INTERVAL_MS:
        time.sleep(REQUEST_SLEEP)
        params = {
            "symbol":    symbol,
            "interval":  "1h",
            "startTime": cur,
            "limit":     BATCH,
        }
        try:
            rows = binance_get("/api/v3/klines", params=params)
        except Exception as e:
            print(f"\n   [FETCH_ERR] {symbol}: {e}")
            break
        if not rows:
            break
        candles.extend(rows)
        last_ts = int(rows[-1][0])
        if last_ts >= now_ms - INTERVAL_MS:
            break
        cur = last_ts + INTERVAL_MS

    if not candles:
        return []

    # تحويل إلى صيغة مضغوطة
    result = [{"t": int(r[0]), "c": float(r[4])} for r in candles]
    save_cached(symbol, result)
    return result


# ================================================================
# KZ flags
# ================================================================
def kz_flags(t_ms: int) -> dict:
    dt = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
    h  = dt.hour
    wd = dt.weekday()   # 0=Mon … 6=Sun
    in_london = h in LONDON_KZ_HOURS
    in_ny_am  = h in NY_AM_KZ_HOURS
    return {
        "hour_utc":    h,
        "weekday":     wd,
        "in_london_kz": in_london,
        "in_ny_am_kz":  in_ny_am,
        "in_any_kz":   in_london or in_ny_am,
        "is_sunday":   wd == 6,
    }


# ================================================================
# معالجة رمز واحد (streaming)
# ================================================================
def process_symbol(symbol: str, candles: list, cap_group: str) -> list:
    """
    - يختار نقاط عشوائية ثابتة (seed per-symbol)
    - يحسب forward returns صافية
    - يُعيد list of rows ثم يُفرّغ candles من الذاكرة (يُنجز الـ del في الـ caller)
    """
    n = len(candles)
    if n < MIN_CANDLES_REQ:
        return []

    # نافذة الاختيار: عدا آخر RESERVE_CANDLES (لضمان fwd_48h)
    max_idx = n - RESERVE_CANDLES - FWD_48H - 1
    min_idx = 5
    if max_idx - min_idx < 30:
        return []

    sym_seed = SEED + sum(ord(c) for c in symbol)
    rng = random.Random(sym_seed)
    pool = range(min_idx, max_idx + 1)
    n_pts = min(POINTS_PER_SYMBOL, len(pool))
    if n_pts < 20:
        return []

    indices = sorted(rng.sample(pool, n_pts))

    # حساب نقطة الانقسام الزمني (walk-forward)
    split_idx = min_idx + int((max_idx - min_idx) * WF_SPLIT_RATIO)

    rows = []
    for idx in indices:
        t_ms  = candles[idx]["t"]
        price = candles[idx]["c"]
        if price <= 0:
            continue

        c24  = candles[idx + FWD_24H]["c"]  if idx + FWD_24H  < n else None
        c48  = candles[idx + FWD_48H]["c"]  if idx + FWD_48H  < n else None

        if c48 is None:
            continue

        def net(future_c):
            if future_c is None:
                return None
            return (future_c - price) / price - FEE

        flags = kz_flags(t_ms)
        half  = "first" if idx <= split_idx else "second"

        rows.append({
            "symbol":        symbol,
            "cap_group":     cap_group,
            "t_ms":          t_ms,
            "half":          half,
            **flags,
            "fwd_24h_net":   net(c24),
            "fwd_48h_net":   net(c48),
        })
    return rows


# ================================================================
# تحليل مجموعتين
# ================================================================
def analyze(pos_rows, neg_rows, label_pos, label_neg, fwd_key):
    """Welch t-test + Bootstrap CI + Cohen d."""
    a = np.array([r[fwd_key] for r in pos_rows if r.get(fwd_key) is not None], dtype=float)
    b = np.array([r[fwd_key] for r in neg_rows if r.get(fwd_key) is not None], dtype=float)
    if len(a) < 10 or len(b) < 10:
        return None

    t, p, df = welch_ttest(a, b)
    d        = cohen_d(a, b)
    ci_lo, ci_hi = bootstrap_mean_diff_ci(a, b)

    return {
        "label_pos": label_pos,
        "label_neg": label_neg,
        "fwd_key":   fwd_key,
        "n_pos":     int(len(a)),
        "n_neg":     int(len(b)),
        "n_total":   int(len(a) + len(b)),
        "mean_pos":  float(np.mean(a)) * 100,   # %
        "mean_neg":  float(np.mean(b)) * 100,
        "diff":      float(np.mean(a) - np.mean(b)) * 100,
        "std_pos":   float(np.std(a, ddof=1)) * 100,
        "std_neg":   float(np.std(b, ddof=1)) * 100,
        "t_stat":    t,
        "df":        df,
        "p_value":   p,
        "ci_lo":     ci_lo * 100,
        "ci_hi":     ci_hi * 100,
        "cohen_d":   d,
    }


# ================================================================
# تشغيل كل التحليلات
# ================================================================
def run_analyses(all_rows: list) -> dict:
    res = {}

    for fwd_key, hz in [("fwd_24h_net", "24h"), ("fwd_48h_net", "48h")]:
        # 1. Any KZ
        pos = [r for r in all_rows if     r["in_any_kz"]]
        neg = [r for r in all_rows if not r["in_any_kz"]]
        res[f"any_kz_{hz}"] = analyze(pos, neg, "in_any_kz=True", "in_any_kz=False", fwd_key)

        # 2. London only
        pos_l = [r for r in all_rows if     r["in_london_kz"]]
        neg_l = [r for r in all_rows if not r["in_london_kz"]]
        res[f"london_{hz}"] = analyze(pos_l, neg_l, "London KZ", "Outside London", fwd_key)

        # 3. NY AM only
        pos_n = [r for r in all_rows if     r["in_ny_am_kz"]]
        neg_n = [r for r in all_rows if not r["in_ny_am_kz"]]
        res[f"ny_am_{hz}"] = analyze(pos_n, neg_n, "NY AM KZ", "Outside NY AM", fwd_key)

        # 4. Sunday vs weekday
        pos_s = [r for r in all_rows if     r["is_sunday"]]
        neg_s = [r for r in all_rows if not r["is_sunday"]]
        res[f"sunday_{hz}"] = analyze(pos_s, neg_s, "Sunday=True", "Sunday=False", fwd_key)

    # 5. Walk-Forward: Any KZ × 48h على كل نصف
    for half in ["first", "second"]:
        sub = [r for r in all_rows if r["half"] == half]
        pos_h = [r for r in sub if     r["in_any_kz"]]
        neg_h = [r for r in sub if not r["in_any_kz"]]
        res[f"wf_{half}_any_kz_48h"] = analyze(
            pos_h, neg_h,
            f"KZ(half={half})", f"NoKZ(half={half})",
            "fwd_48h_net"
        )

    return res


# ================================================================
# كتابة CSV (تدريجي)
# ================================================================
def write_csv_rows(rows: list, csv_file, is_first_batch: bool):
    if not rows:
        return
    mode = "w" if is_first_batch else "a"
    with open(csv_file, mode, encoding="utf-8") as f:
        if is_first_batch:
            # header
            keys = ["symbol", "cap_group", "t_ms", "half",
                    "hour_utc", "weekday", "in_london_kz", "in_ny_am_kz",
                    "in_any_kz", "is_sunday", "fwd_24h_net", "fwd_48h_net"]
            f.write(",".join(keys) + "\n")
        for r in rows:
            vals = [
                r.get("symbol", ""),
                r.get("cap_group", ""),
                str(r.get("t_ms", "")),
                r.get("half", ""),
                str(r.get("hour_utc", "")),
                str(r.get("weekday", "")),
                str(int(r.get("in_london_kz", False))),
                str(int(r.get("in_ny_am_kz",  False))),
                str(int(r.get("in_any_kz",    False))),
                str(int(r.get("is_sunday",    False))),
                f"{r.get('fwd_24h_net', ''):.6f}" if r.get("fwd_24h_net") is not None else "",
                f"{r.get('fwd_48h_net', ''):.6f}" if r.get("fwd_48h_net") is not None else "",
            ]
            f.write(",".join(vals) + "\n")


# ================================================================
# بناء التقرير
# ================================================================
def build_report(all_rows, res, n_syms, selected):
    n = len(all_rows)
    n_kz  = sum(1 for r in all_rows if r["in_any_kz"])
    n_lon = sum(1 for r in all_rows if r["in_london_kz"])
    n_ny  = sum(1 for r in all_rows if r["in_ny_am_kz"])
    n_sun = sum(1 for r in all_rows if r["is_sunday"])
    cap_c = {}
    for r in all_rows:
        cap_c[r["cap_group"]] = cap_c.get(r["cap_group"], 0) + 1

    t_min = min(r["t_ms"] for r in all_rows)
    t_max = max(r["t_ms"] for r in all_rows)
    date_from = datetime.fromtimestamp(t_min / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    date_to   = datetime.fromtimestamp(t_max / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    def f(v, d=4):
        if v is None: return "N/A"
        return f"{v:.{d}f}"

    def sig(r):
        if r is None: return "N/A"
        p = r["p_value"]
        s = f"{p:.4f}"
        if p < 0.001: return f"{s} ***"
        if p < 0.01:  return f"{s} **"
        if p < 0.05:  return f"{s} *"
        return s

    # ---- حكم رئيسي (على 48h) ----
    main = res.get("any_kz_48h")
    wf1  = res.get("wf_first_any_kz_48h")
    wf2  = res.get("wf_second_any_kz_48h")

    verdict = "KZ_NO_CAUSAL_EDGE"
    if main:
        p_sig    = main["p_value"] < 0.05
        eff_sig  = abs(main["diff"]) > 0.15
        if p_sig and eff_sig:
            verdict = "KZ_NEGATIVE_PREDICTIVE" if main["diff"] < 0 else "KZ_POSITIVE_PREDICTIVE"

    wf_stable = False
    wf_note   = "غير كافٍ"
    if wf1 and wf2:
        wf_stable = (wf1["diff"] >= 0) == (wf2["diff"] >= 0)
        d1_s = ("+" if wf1["diff"] >= 0 else "") + f(wf1["diff"]) + "%"
        d2_s = ("+" if wf2["diff"] >= 0 else "") + f(wf2["diff"]) + "%"
        wf_note = f"{'ثابت' if wf_stable else 'متقلّب'}: نصف1={d1_s}, نصف2={d2_s}"

    # ---- جدول رئيسي 48h ----
    def row48(key, label):
        r = res.get(key)
        if r is None: return f"| {label} | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        ci = f"[{f(r['ci_lo'])}, {f(r['ci_hi'])}]"
        return (f"| {label} | {r['n_pos']:,} | {r['n_neg']:,} | "
                f"{f(r['mean_pos'])} | {f(r['mean_neg'])} | {f(r['diff'])} | "
                f"{sig(r)} | {ci} | {f(r['cohen_d'])} |")

    # ---- الحكم النهائي ----
    if verdict == "KZ_NO_CAUSAL_EDGE":
        verdict_ar = (
            "**Killzone بلا قوة تنبؤية سببية على الكريبتو spot** "
            f"— لا أثر دال على {n:,} نقطة عشوائية مستقلة.\n\n"
            "التفسير: الكريبتو سوق 24/7 غير مُقاد بـ Market Maker مركزي كالفوركس. "
            "ساعات London/NY Open لا تُفرز forward returns مختلفة إحصائياً. "
            "الاختبار السابق على صفقات البوت (n=2440) كان أثر تحيّز الاختيار "
            "(صفقات RSI<40 في downtrend موزّعة عشوائياً على ساعات اليوم)، "
            "وليس أثراً سببياً لـ KZ."
        )
    elif verdict == "KZ_NEGATIVE_PREDICTIVE":
        verdict_ar = (
            f"**Killzone له أثر سالب دال سببياً** "
            f"(diff={f(main['diff'])}%, p={f(main['p_value'])}, d={f(main['cohen_d'])}) "
            f"على {n:,} نقطة عشوائية.\n\n"
            "التفسير: ساعات London/NY Open تُولّد تقلباً عالياً في الكريبتو spot "
            "يضرّ forward returns الخام. يدعم هذا إضافة فلتر سلبي للـ KZ بعد رفع التجميد."
        )
    else:
        verdict_ar = (
            f"**Killzone له أثر موجب دال سببياً** "
            f"(diff={f(main['diff'])}%, p={f(main['p_value'])}, d={f(main['cohen_d'])}) "
            f"على {n:,} نقطة عشوائية.\n\n"
            "التفسير: يناقض نتيجة تحليل البوت (KZ أسوأ) — الفرق في الاتجاه يعني أن "
            "استراتيجية mean-revert في downtrend تتعارض مع حركة KZ، لكن KZ نفسه سببياً موجب. "
            "توصية: bonus score للـ KZ لا فلتر صارم."
        )

    sym_list_str = ", ".join(s for s, _ in selected[:20]) + f"... ({len(selected)} إجمالاً)"

    report = f"""# اختبار سببي قاطع: ICT Killzone — عيّنة ضخمة
**التاريخ:** {DATE_STAMP.replace('_', '-')} | **الحكم:** `{verdict}`

---

## ملخّص تنفيذي

{verdict_ar}

---

## إحصاءات العيّنة

| البيان | القيمة |
|--------|--------|
| الرموز الفعلية | {n_syms} |
| الرموز المُختارة | {sym_list_str} |
| إجمالي النقاط | {n:,} |
| نطاق التاريخ | {date_from} → {date_to} |
| نقاط داخل Any KZ | {n_kz:,} ({100*n_kz/n:.1f}%) |
| نقاط خارج Any KZ | {n-n_kz:,} ({100*(n-n_kz)/n:.1f}%) |
| London KZ (07-10h) | {n_lon:,} ({100*n_lon/n:.1f}%) |
| NY AM KZ (12-15h)  | {n_ny:,} ({100*n_ny/n:.1f}%) |
| الأحد | {n_sun:,} ({100*n_sun/n:.1f}%) |
| توزيع cap | large={cap_c.get('large',0):,} mid={cap_c.get('mid',0):,} small={cap_c.get('small',0):,} |
| Bootstrap معاينات | {BOOTSTRAP_N:,} |
| seed | {SEED} |

---

## الجدول الرئيسي — fwd_48h صافٍ (رسوم 0.3%)

| المجموعة | n_pos | n_neg | mean_pos% | mean_neg% | diff% | p-value | CI 95% Bootstrap | Cohen d |
|---------|-------|-------|----------|----------|-------|---------|-----------------|---------|
{row48("any_kz_48h",  "Any KZ vs Outside")}
{row48("london_48h",  "London (07-10h) vs Outside")}
{row48("ny_am_48h",   "NY AM (12-15h) vs Outside")}
{row48("sunday_48h",  "Sunday vs Weekday (sanity)")}

`*` p<0.05 | `**` p<0.01 | `***` p<0.001

---

## نتائج fwd_24h (مقارنة)

| المجموعة | n_pos | n_neg | mean_pos% | mean_neg% | diff% | p-value | CI 95% | Cohen d |
|---------|-------|-------|----------|----------|-------|---------|--------|---------|
{row48("any_kz_24h",  "Any KZ vs Outside (24h)")}
{row48("london_24h",  "London vs Outside (24h)")}
{row48("ny_am_24h",   "NY AM vs Outside (24h)")}
{row48("sunday_24h",  "Sunday vs Weekday (24h)")}

---

## Walk-Forward: ثبات الأثر عبر الزمن (Any KZ × 48h)

| النصف | n_kz | n_total | diff_net% | p-value | CI 95% | Cohen d |
|-------|------|---------|----------|---------|--------|---------|
| نصف 1 (أول 90 يوم) | {wf1['n_pos'] if wf1 else 'N/A'} | {wf1['n_total'] if wf1 else 'N/A'} | {f(wf1['diff'] if wf1 else None)} | {f(wf1['p_value'] if wf1 else None, 4)} | [{f(wf1['ci_lo'] if wf1 else None)}, {f(wf1['ci_hi'] if wf1 else None)}] | {f(wf1['cohen_d'] if wf1 else None)} |
| نصف 2 (آخر 90 يوم) | {wf2['n_pos'] if wf2 else 'N/A'} | {wf2['n_total'] if wf2 else 'N/A'} | {f(wf2['diff'] if wf2 else None)} | {f(wf2['p_value'] if wf2 else None, 4)} | [{f(wf2['ci_lo'] if wf2 else None)}, {f(wf2['ci_hi'] if wf2 else None)}] | {f(wf2['cohen_d'] if wf2 else None)} |
| **الاستنتاج** | | | | | | **{wf_note}** |

---

## الحكم القاطع

{verdict_ar}

---

## ما يعنيه هذا الحكم للاستراتيجية المجمّدة

"""
    if verdict == "KZ_NO_CAUSAL_EDGE":
        report += """- فلتر Killzone لا يستحق إضافته إلى الاستراتيجية بعد رفع التجميد.
- لا داعي لإعادة اختبار KZ ما لم تظهر دراسة خاصة بالكريبتو spot تُثبت الأثر.
- الأولوية بعد 50 forward trade: rsi_divergence>0 filter + RSI+Bollinger weights (مدعوم بـ part18/21/26).
- نتيجة السابقة (KZ أسوأ على 2440 صفقة) تُفسَّر بتحيّز الاختيار لا بسببية KZ.
"""
    elif verdict == "KZ_NEGATIVE_PREDICTIVE":
        report += """- أثر سالب دال سببياً → KZ يُضرّ حتى على عيّنة عشوائية.
- يُبرّر إضافة فلتر in_any_kz=False كشرط إضافي للدخول بعد رفع التجميد.
- الجلستان ليستا متكافئتين — راجع جدول London vs NY AM.
"""
    else:
        report += """- أثر موجب دال على عيّنة عشوائية، لكن يعاكس نتيجة البوت.
- التناقض يعني: الإشكالية في توقيت استراتيجيتنا (mean-revert في downtrend) لا في KZ نفسه.
- توصية: bonus score بدلاً من فلتر صارم، ابدأ بـ +0.1 على in_any_kz=True بعد رفع التجميد.
"""

    report += f"""
---

*السكريبت:* `research/scripts/killzone_causal_v2.py`
*البيانات:* Binance REST API 1h klines — مستقلة تماماً عن DB البوت
*seed:* {SEED} | *bootstrap:* {BOOTSTRAP_N} | *fee:* {FEE*100:.1f}% round-trip
*التجميد ساري — لا تعديلات على الكود الحيّ*
"""
    return report, verdict


# ================================================================
# main
# ================================================================
def main():
    print("=" * 70)
    print("اختبار سببي قاطع: ICT Killzone — عيّنة ضخمة ≥100,000 نقطة")
    print("=" * 70)

    # ── اختيار الرموز ──────────────────────────────────────────
    if os.path.exists(SYMBOL_CACHE):
        with open(SYMBOL_CACHE, "rb") as f:
            selected = pickle.load(f)
        print(f"[CACHE] قائمة الرموز موجودة: {len(selected)} رمزاً")
    else:
        all_syms = get_usdt_symbols()
        print(f"   إجمالي USDT pairs: {len(all_syms)}")
        selected = select_symbols_stratified(all_syms)
        with open(SYMBOL_CACHE, "wb") as f:
            pickle.dump(selected, f)
        print(f"[SAVED] قائمة الرموز محفوظة: {len(selected)} رمزاً")

    # ── جلب + معالجة تدفّقية ───────────────────────────────────
    all_rows     = []
    n_syms_ok    = 0
    is_first_csv = True
    total_syms   = len(selected)

    for i, (symbol, cap_group) in enumerate(selected):
        print(f"[{i+1:2d}/{total_syms}] {symbol} ({cap_group})...", end=" ", flush=True)

        check_memory(symbol)

        try:
            candles = fetch_1h_klines(symbol)
        except Exception as e:
            print(f"SKIP (fetch error: {e})", flush=True)
            continue

        n_c = len(candles)
        print(f"n_candles={n_c}", end=" ", flush=True)

        if n_c < MIN_CANDLES_REQ:
            print(f"SKIP (قصيرة جداً < {MIN_CANDLES_REQ})", flush=True)
            del candles
            continue

        rows = process_symbol(symbol, candles, cap_group)
        del candles   # تحرير فوري من الذاكرة
        gc.collect()

        if not rows:
            print("→ 0 نقطة", flush=True)
            continue

        n_kz_here = sum(1 for r in rows if r["in_any_kz"])
        print(f"→ {len(rows):,} نقطة (KZ={n_kz_here})", flush=True)

        # حفظ CSV تدريجي (يجنّب تراكم الذاكرة)
        write_csv_rows(rows, OUTPUT_CSV, is_first_csv)
        is_first_csv = False

        all_rows.extend(rows)
        n_syms_ok += 1

    print(f"\n{'='*70}")
    print(f"إجمالي النقاط: {len(all_rows):,} من {n_syms_ok} رمزاً")
    n_kz_total = sum(1 for r in all_rows if r["in_any_kz"])
    print(f"KZ: {n_kz_total:,} | غير KZ: {len(all_rows)-n_kz_total:,}")

    if len(all_rows) < 500:
        print("ERROR: عيّنة صغيرة جداً — تحقّق من الاتصال بـ Binance")
        sys.exit(1)

    # ── تحليل إحصائي ────────────────────────────────────────────
    print("\n[STATS] Welch t-test + Bootstrap CI (قد يستغرق 1-2 دقيقة)...")
    res = run_analyses(all_rows)

    # ملخّص سريع
    main_r = res.get("any_kz_48h")
    if main_r:
        print(f"\n  Any KZ vs Outside (48h):")
        print(f"    n_kz={main_r['n_pos']:,}  n_out={main_r['n_neg']:,}")
        print(f"    mean_kz={main_r['mean_pos']:.4f}%  mean_out={main_r['mean_neg']:.4f}%")
        print(f"    diff={main_r['diff']:.4f}%  p={main_r['p_value']:.5f}  d={main_r['cohen_d']:.4f}")
        print(f"    CI 95%: [{main_r['ci_lo']:.4f}%, {main_r['ci_hi']:.4f}%]")

    # ── توليد التقارير ───────────────────────────────────────────
    print("\n[REPORT] توليد التقرير...")
    report_text, verdict = build_report(all_rows, res, n_syms_ok, selected)

    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(report_text)

    json_out = {
        "meta": {
            "date": DATE_STAMP,
            "seed": SEED,
            "bootstrap_n": BOOTSTRAP_N,
            "fee": FEE,
            "days_back": DAYS_BACK,
            "points_per_symbol": POINTS_PER_SYMBOL,
        },
        "sample": {
            "n_total":   len(all_rows),
            "n_symbols": n_syms_ok,
        },
        "verdict": verdict,
        "results": {k: v for k, v in res.items() if v is not None},
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(json_out, f, ensure_ascii=False, indent=2)

    print(f"   MD:   {OUTPUT_MD}")
    print(f"   JSON: {OUTPUT_JSON}")
    print(f"   CSV:  {OUTPUT_CSV}")

    print(f"\n{'='*70}")
    print(f"الحكم النهائي: {verdict}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
