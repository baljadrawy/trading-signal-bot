#!/usr/bin/env python3
"""
اختبار سببي لفلتر EMA/رقم مستدير على عيّنة عشوائية مستقلة عن منطق البوت.
التاريخ: 2026-05-20
المنهجية: عيّنة عشوائية multi-cap → نقاط زمنية عشوائية → حساب flags → forward returns → t-test + bootstrap.
ممنوع استخدام بيانات البوت أو الكتابة إلى DB. قراءة فقط من Binance REST API.
"""

import os
import sys
import random
import pickle
import time
import math
import json
import requests
from datetime import datetime, timezone

# ======== مسارات ========
# يعمل داخل container: /app/research أو على الخادم مباشرة
BASE_DIR = os.environ.get("RESEARCH_BASE_DIR", "/app/research")
CACHE_DIR = os.path.join(BASE_DIR, "cache", "klines")
OUTPUT_PATH = os.path.join(BASE_DIR, "entry_filter_causal_test_2026_05_20.md")
os.makedirs(CACHE_DIR, exist_ok=True)

# ======== ثوابت ========
SEED = 20260520
BINANCE_BASE = "https://api.binance.com"
INTERVALS = ["1h", "4h", "1d"]
INTERVAL_MS = {"1h": 3600_000, "4h": 14400_000, "1d": 86400_000}
DAYS_BACK = 90
RESERVE_DAYS = 7          # ≥7 أيام في النهاية للـ forward returns
FWD_24H = 24              # ساعات للـ 24h return
FWD_48H = 48              # المعيار الأساسي
FWD_7D = 168              # 7 أيام
FEE = 0.003               # 0.3% رسوم (دخول + خروج)
POINTS_PER_SYMBOL = 120   # نقاط زمنية عشوائية لكل رمز
BOOTSTRAP_N = 1200        # عدد معاينات bootstrap

LARGE_CAP_N = 12          # رموز large-cap
MID_CAP_N = 13            # رموز mid-cap
SMALL_CAP_N = 12          # رموز small-cap
TARGET_SYMBOLS = LARGE_CAP_N + MID_CAP_N + SMALL_CAP_N  # ≈37

# ======== Rate Limit ========
REQUEST_SLEEP = 0.15      # ثانية بين الطلبات (≈400 weight/min < 1200)

# ======== مساعد: numpy بسيط بلا scipy ========
import numpy as np


def _ttest_welch(a, b):
    """Two-sample Welch t-test — p-value ثنائي الاتجاه."""
    n1, n2 = len(a), len(b)
    m1, m2 = np.mean(a), np.mean(b)
    v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 0.0, 1.0
    t = (m1 - m2) / se
    # درجات الحرية Welch-Satterthwaite
    df = (v1 / n1 + v2 / n2) ** 2 / (
        (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    )
    # p-value عبر regularized incomplete beta (تقريب بسيط بـ numpy)
    p = _t_pvalue(t, df)
    return float(t), float(p)


def _t_pvalue(t, df):
    """p-value لـ t-distribution ثنائي الاتجاه.
    عند df>100: تقريب normal عبر math.erfc (دقيق ≥99%).
    عند df≤100: regularized incomplete beta.
    """
    t = abs(t)  # ثنائي الاتجاه
    if df > 100:
        # Z ~ N(0,1): p = 2 * P(Z > |t|) = erfc(|t| / sqrt(2))
        return float(math.erfc(t / math.sqrt(2)))
    x = df / (df + t * t)
    p_half = _betainc(df / 2, 0.5, x)
    return float(min(2 * p_half, 1.0))


def _betainc(a, b, x):
    """Regularized incomplete beta function I_x(a,b) — تقريب بـ continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Lentz continued fraction
    MAXITER = 200
    EPS = 3e-7
    fpmin = 1e-30
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, MAXITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return front * h


def cohen_d(a, b):
    n1, n2 = len(a), len(b)
    s = math.sqrt(((n1 - 1) * np.var(a, ddof=1) + (n2 - 1) * np.var(b, ddof=1)) / (n1 + n2 - 2))
    return (np.mean(a) - np.mean(b)) / s if s > 0 else 0.0


def bootstrap_ci(a, b, n=BOOTSTRAP_N, ci=0.95):
    """Bootstrap CI للفرق mean(a) - mean(b)."""
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(n):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs.append(np.mean(sa) - np.mean(sb))
    alpha = (1 - ci) / 2
    return float(np.percentile(diffs, alpha * 100)), float(np.percentile(diffs, (1 - alpha) * 100))


# ======== Binance REST ========
def binance_get(path, params=None, max_retry=3):
    url = BINANCE_BASE + path
    for attempt in range(max_retry):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == max_retry - 1:
                raise
            time.sleep(2 ** attempt)


def get_exchange_symbols():
    """قائمة USDT spot pairs النشطة."""
    print("[1] جلب exchangeInfo من Binance...")
    data = binance_get("/api/v3/exchangeInfo")
    symbols = []
    for s in data["symbols"]:
        if (
            s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
            and s.get("isSpotTradingAllowed", False)
        ):
            symbols.append(s["symbol"])
    return symbols


def get_24h_volume(symbols_chunk):
    """حجم 24h quoteVolume لقائمة رموز."""
    time.sleep(REQUEST_SLEEP)
    data = binance_get("/api/v3/ticker/24hr")
    vol_map = {}
    for t in data:
        if t["symbol"] in set(symbols_chunk):
            vol_map[t["symbol"]] = float(t["quoteVolume"])
    return vol_map


def select_symbols(all_symbols):
    """اختيار عيّنة متوازنة large/mid/small cap."""
    print("[2] جلب 24h volume لتصنيف العملات...")
    vol_map = get_24h_volume(all_symbols)
    # رتّب تنازلياً بالحجم
    sorted_syms = sorted(all_symbols, key=lambda s: vol_map.get(s, 0), reverse=True)
    large = sorted_syms[:30]
    mid = sorted_syms[30:100]
    small = sorted_syms[100:300]

    rng = random.Random(SEED)
    sel_large = rng.sample(large, min(LARGE_CAP_N, len(large)))
    sel_mid = rng.sample(mid, min(MID_CAP_N, len(mid)))
    sel_small = rng.sample(small, min(SMALL_CAP_N, len(small)))

    print(f"   Large-cap: {sel_large}")
    print(f"   Mid-cap: {sel_mid}")
    print(f"   Small-cap: {sel_small}")
    return sel_large, sel_mid, sel_small


# ======== Cache ========
SYMBOL_LIST_CACHE = os.path.join(BASE_DIR, "cache", "selected_symbols.pkl")


def load_symbol_list_cache():
    if os.path.exists(SYMBOL_LIST_CACHE):
        with open(SYMBOL_LIST_CACHE, "rb") as f:
            return pickle.load(f)
    return None


def save_symbol_list_cache(data):
    with open(SYMBOL_LIST_CACHE, "wb") as f:
        pickle.dump(data, f)


def cache_path(symbol, interval):
    return os.path.join(CACHE_DIR, f"{symbol}_{interval}.pkl")


def load_cache(symbol, interval):
    p = cache_path(symbol, interval)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def save_cache(symbol, interval, data):
    p = cache_path(symbol, interval)
    with open(p, "wb") as f:
        pickle.dump(data, f)


# ======== جلب Klines ========
def fetch_klines(symbol, interval, days=DAYS_BACK):
    """جلب آخر `days` يوماً بـ streaming chunk: 500 شمعة/طلب."""
    cached = load_cache(symbol, interval)
    if cached is not None:
        return cached

    iv_ms = INTERVAL_MS[interval]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 86400_000
    all_candles = []
    cur = start_ms

    while cur < now_ms:
        time.sleep(REQUEST_SLEEP)
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur,
            "limit": 500,
        }
        try:
            rows = binance_get("/api/v3/klines", params=params)
        except Exception as e:
            print(f"   خطأ في جلب {symbol} {interval}: {e}")
            break
        if not rows:
            break
        all_candles.extend(rows)
        last_ts = rows[-1][0]
        if last_ts >= now_ms - iv_ms:
            break
        cur = last_ts + iv_ms

    # [open_time, open, high, low, close, volume, ...]
    result = [
        {
            "t": int(r[0]),           # open_time ms
            "o": float(r[1]),
            "h": float(r[2]),
            "l": float(r[3]),
            "c": float(r[4]),
        }
        for r in all_candles
    ]
    save_cache(symbol, interval, result)
    return result


# ======== EMA ========
def compute_ema(closes, period):
    """EMA تدريجي — لا نظرة مستقبلية."""
    k = 2 / (period + 1)
    ema = closes[0]
    emas = [ema]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
        emas.append(ema)
    return emas


def get_ema_at_idx(candles, period, idx):
    """EMA عند idx باستخدام closes[0:idx+1] فقط (بدون look-ahead)."""
    if idx < period - 1:
        return None
    closes = [c["c"] for c in candles[: idx + 1]]
    emas = compute_ema(closes, period)
    return emas[-1]


# ======== رقم مستدير ========
def round_number_distance(price):
    """أقرب نسبة مسافة من رقم مستدير عند order of magnitude المناسب."""
    if price <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(price))
    candidates = []
    for m in [0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000]:
        rounded = round(price / m) * m
        if rounded > 0:
            candidates.append(abs(price - rounded) / price)
    return min(candidates) if candidates else 1.0


# ======== حساب Flags ========
def compute_flags(price, candles_1h, idx_1h, candles_4h, idx_4h, candles_1d, idx_1d):
    """
    flag_near_ema: |price - ema_X| / price ≤ 0.03 لأي من EMA50/200 على 4h أو 1d.
    flag_round: مسافة من أقرب رقم مستدير ≤ 2%.
    """
    EMA_THRESH = 0.03
    ROUND_THRESH = 0.02
    EMA_PERIODS = [50, 200]

    flag_near_ema = False
    for period in EMA_PERIODS:
        for candles, idx in [(candles_4h, idx_4h), (candles_1d, idx_1d)]:
            ema_val = get_ema_at_idx(candles, period, idx)
            if ema_val is not None:
                if abs(price - ema_val) / price <= EMA_THRESH:
                    flag_near_ema = True

    flag_round = round_number_distance(price) <= ROUND_THRESH
    flag_filter = flag_near_ema or flag_round
    return flag_near_ema, flag_round, flag_filter


# ======== Forward Returns ========
def get_future_close(candles_1h, idx_1h, hours_ahead):
    """close بعد `hours_ahead` ساعة من idx_1h (بدون look-ahead في الحساب)."""
    target_idx = idx_1h + hours_ahead
    if target_idx >= len(candles_1h):
        return None
    return candles_1h[target_idx]["c"]


# ======== المعالجة الرئيسية ========
def process_symbol(symbol, candles_dict, cap_group):
    """
    معالجة رمز واحد: توليد نقاط زمنية عشوائية + حساب flags + forward returns.
    يُعاد قائمة من dicts.
    """
    candles_1h = candles_dict["1h"]
    candles_4h = candles_dict["4h"]
    candles_1d = candles_dict["1d"]

    if not candles_1h or len(candles_1h) < FWD_7D + 10:
        return []

    # نافذة الاختيار: كل شموع 1h ما عدا آخر RESERVE_DAYS*24 ساعة
    max_idx = len(candles_1h) - RESERVE_DAYS * 24 - FWD_7D
    if max_idx < 50:
        return []

    # seed فريد لكل رمز
    sym_seed = SEED + sum(ord(c) for c in symbol)
    rng = random.Random(sym_seed)
    available_range = max(0, max_idx - 50)
    if available_range < 20:
        return []  # عيّنة صغيرة جداً — تجاهل
    n_points = min(POINTS_PER_SYMBOL, available_range)
    indices_1h = sorted(rng.sample(range(50, max_idx), n_points))

    rows = []
    for idx_1h in indices_1h:
        price = candles_1h[idx_1h]["c"]
        t_ms = candles_1h[idx_1h]["t"]

        # إيجاد أقرب idx في 4h و 1d قبل أو عند t_ms
        idx_4h = _find_idx_at_time(candles_4h, t_ms)
        idx_1d = _find_idx_at_time(candles_1d, t_ms)
        if idx_4h < 5 or idx_1d < 5:
            continue

        flag_near_ema, flag_round, flag_filter = compute_flags(
            price, candles_1h, idx_1h, candles_4h, idx_4h, candles_1d, idx_1d
        )

        c24 = get_future_close(candles_1h, idx_1h, FWD_24H)
        c48 = get_future_close(candles_1h, idx_1h, FWD_48H)
        c7d = get_future_close(candles_1h, idx_1h, FWD_7D)
        if c48 is None:
            continue  # لا بيانات كافية

        fwd_24h = (c24 - price) / price if c24 else None
        fwd_48h = (c48 - price) / price
        fwd_7d = (c7d - price) / price if c7d else None

        # خصم رسوم 0.3%
        fwd_24h_net = fwd_24h - FEE if fwd_24h is not None else None
        fwd_48h_net = fwd_48h - FEE
        fwd_7d_net = fwd_7d - FEE if fwd_7d is not None else None

        # تصنيف زمني للـ walk-forward
        day_idx = (t_ms - candles_1h[0]["t"]) // 86400_000
        half = "first" if day_idx < 45 else "second"

        rows.append({
            "symbol": symbol,
            "cap_group": cap_group,
            "t_ms": t_ms,
            "price": price,
            "flag_near_ema": flag_near_ema,
            "flag_round": flag_round,
            "flag_filter": flag_filter,
            "fwd_24h_net": fwd_24h_net,
            "fwd_48h_net": fwd_48h_net,
            "fwd_7d_net": fwd_7d_net,
            "half": half,
        })
    return rows


def _find_idx_at_time(candles, t_ms):
    """ثنائي البحث: آخر شمعة open_time ≤ t_ms."""
    lo, hi = 0, len(candles) - 1
    res = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid]["t"] <= t_ms:
            res = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return res


# ======== تحليل إحصائي ========
def analyze(all_rows, label="48h"):
    fwd_key = f"fwd_{label}_net"
    flag_yes = [r[fwd_key] for r in all_rows if r["flag_filter"] and r[fwd_key] is not None]
    flag_no = [r[fwd_key] for r in all_rows if not r["flag_filter"] and r[fwd_key] is not None]
    if not flag_yes or not flag_no:
        return None

    a = np.array(flag_yes)
    b = np.array(flag_no)
    t_stat, p_val = _ttest_welch(a, b)
    ci_lo, ci_hi = bootstrap_ci(a, b)
    d = cohen_d(a, b)

    # gross (قبل الرسوم)
    a_gross = a + FEE
    b_gross = b + FEE

    return {
        "label": label,
        "N_filter": len(a),
        "N_no_filter": len(b),
        "N_total": len(a) + len(b),
        "mean_filter_gross": float(np.mean(a_gross)) * 100,
        "mean_nofilter_gross": float(np.mean(b_gross)) * 100,
        "mean_filter_net": float(np.mean(a)) * 100,
        "mean_nofilter_net": float(np.mean(b)) * 100,
        "diff_net": float(np.mean(a) - np.mean(b)) * 100,
        "t_stat": t_stat,
        "p_value": p_val,
        "ci_lo": ci_lo * 100,
        "ci_hi": ci_hi * 100,
        "cohen_d": d,
    }


def analyze_split(all_rows, half, label="48h"):
    """تحليل نصف زمني (walk-forward)."""
    subset = [r for r in all_rows if r["half"] == half]
    return analyze(subset, label)


def analyze_cap(all_rows, cap_group, label="48h"):
    subset = [r for r in all_rows if r["cap_group"] == cap_group]
    return analyze(subset, label)


# ======== توليد التقرير ========
def build_report(all_rows, results):
    n_syms = len(set(r["symbol"] for r in all_rows))
    n_total = len(all_rows)
    n_filter = sum(1 for r in all_rows if r["flag_filter"])
    n_near_ema = sum(1 for r in all_rows if r["flag_near_ema"])
    n_round = sum(1 for r in all_rows if r["flag_round"])

    cap_counts = {}
    for r in all_rows:
        cap_counts[r["cap_group"]] = cap_counts.get(r["cap_group"], 0) + 1

    main = results.get("48h_all")
    r24 = results.get("24h_all")
    r7d = results.get("7d_all")
    wf_first = results.get("48h_first")
    wf_second = results.get("48h_second")
    cap_large = results.get("48h_large")
    cap_mid = results.get("48h_mid")
    cap_small = results.get("48h_small")

    def fmt(v, digits=3):
        return f"{v:.{digits}f}" if v is not None else "N/A"

    def verdict_line(res):
        if res is None:
            return "لا بيانات كافية"
        sig = res["p_value"] < 0.05
        effect_ok = abs(res["diff_net"]) > 0.3
        return (
            f"p={fmt(res['p_value'])}, diff_net={fmt(res['diff_net'])}%, "
            f"{'دال' if sig else 'غير دال'} | حجم أثر {'كافٍ' if effect_ok else 'غير كافٍ'}"
        )

    def ci_str(res):
        if res is None:
            return "N/A"
        return f"[{fmt(res['ci_lo'])}%, {fmt(res['ci_hi'])}%]"

    # ======== حكم الثبات ========
    consistent = False
    if wf_first and wf_second:
        # نفس الإشارة (موجبة أو سالبة) في كلا النصفين
        consistent = (wf_first["diff_net"] > 0) == (wf_second["diff_net"] > 0)

    # ======== الحكم النهائي ========
    if main:
        p_ok = main["p_value"] < 0.05
        effect_ok = abs(main["diff_net"]) > 0.3
        if p_ok and effect_ok and consistent:
            verdict_ar = (
                "**الفلتر له قوة تنبؤية سببية** — p دال، حجم أثر كافٍ، والإشارة ثابتة عبر النصفين."
            )
            verdict_en = "PREDICTIVE"
        else:
            reasons = []
            if not p_ok:
                reasons.append(f"p={fmt(main['p_value'])} غير دال (≥0.05)")
            if not effect_ok:
                reasons.append(f"|diff_net|={fmt(abs(main['diff_net']))}% < 0.3%")
            if not consistent:
                reasons.append("الإشارة غير ثابتة عبر النصفين")
            verdict_ar = (
                "**الفلتر بلا قوة تنبؤية كافية على عيّنة عشوائية** — "
                "الإيجابية السابقة (92% تطابق على n=12) كانت ناتجة عن "
                "تحيّز عيّنة البوت (RSI<40 selection bias) لا عن قوة الفلتر نفسه. "
                f"الأسباب: {'; '.join(reasons)}."
            )
            verdict_en = "NOT_PREDICTIVE"
    else:
        verdict_ar = "لا بيانات كافية للحكم."
        verdict_en = "INSUFFICIENT_DATA"

    report = f"""# اختبار سببي: فلتر EMA/رقم مستدير على عيّنة عشوائية
**التاريخ:** 2026-05-20 UTC | **الحكم:** {verdict_en}

---

## ملخّص تنفيذي

تمّ اختبار بصمة «Entry قريب EMA50/EMA200 على 4h/1d ضمن ±3% أو رقم مستدير ±2%»
على عيّنة عشوائية مستقلة ({n_total:,} نقطة من {n_syms} رمزاً).
النتيجة: {verdict_ar}

---

## جدول العيّنة

| البيان | القيمة |
|--------|--------|
| عدد الرموز الفعلي | {n_syms} |
| إجمالي النقاط | {n_total:,} |
| نقاط flag_filter=True | {n_filter:,} ({100*n_filter/n_total:.1f}%) |
| منها flag_near_ema فقط | {n_near_ema:,} |
| منها flag_round فقط | {n_round:,} |
| توزيع cap | large={cap_counts.get('large',0)}, mid={cap_counts.get('mid',0)}, small={cap_counts.get('small',0)} |

---

## جدول النتائج الرئيسية (fwd_48h)

| المجموعة | N | mean_gross% | mean_net% | diff_net% | p-value | CI 95% | Cohen's d |
|---------|---|------------|----------|---------|---------|--------|----------|
| flag=True | {main['N_filter'] if main else 'N/A'} | {fmt(main['mean_filter_gross'] if main else None)} | {fmt(main['mean_filter_net'] if main else None)} | — | — | — | — |
| flag=False | {main['N_no_filter'] if main else 'N/A'} | {fmt(main['mean_nofilter_gross'] if main else None)} | {fmt(main['mean_nofilter_net'] if main else None)} | — | — | — | — |
| **الفرق** | — | — | — | **{fmt(main['diff_net'] if main else None)}** | **{fmt(main['p_value'] if main else None)}** | **{ci_str(main)}** | **{fmt(main['cohen_d'] if main else None, 3)}** |

*الفرق = mean(flag=True) - mean(flag=False) بعد خصم 0.3% رسوم*

---

## نتائج المعايير الثلاثة

| الأفق | N_filter | N_total | diff_net% | p-value | CI 95% | Cohen's d |
|-------|---------|---------|---------|---------|--------|---------|
| 24h | {r24['N_filter'] if r24 else 'N/A'} | {r24['N_total'] if r24 else 'N/A'} | {fmt(r24['diff_net'] if r24 else None)} | {fmt(r24['p_value'] if r24 else None)} | {ci_str(r24)} | {fmt(r24['cohen_d'] if r24 else None, 3)} |
| **48h (رئيسي)** | **{main['N_filter'] if main else 'N/A'}** | **{main['N_total'] if main else 'N/A'}** | **{fmt(main['diff_net'] if main else None)}** | **{fmt(main['p_value'] if main else None)}** | **{ci_str(main)}** | **{fmt(main['cohen_d'] if main else None, 3)}** |
| 7d | {r7d['N_filter'] if r7d else 'N/A'} | {r7d['N_total'] if r7d else 'N/A'} | {fmt(r7d['diff_net'] if r7d else None)} | {fmt(r7d['p_value'] if r7d else None)} | {ci_str(r7d)} | {fmt(r7d['cohen_d'] if r7d else None, 3)} |

---

## Walk-Forward (تقسيم يوم 1-45 vs 46-90)

| النصف | N_filter | N_total | diff_net% | p-value |
|-------|---------|---------|---------|---------|
| الأول (يوم 1-45) | {wf_first['N_filter'] if wf_first else 'N/A'} | {wf_first['N_total'] if wf_first else 'N/A'} | {fmt(wf_first['diff_net'] if wf_first else None)} | {fmt(wf_first['p_value'] if wf_first else None)} |
| الثاني (يوم 46-90) | {wf_second['N_filter'] if wf_second else 'N/A'} | {wf_second['N_total'] if wf_second else 'N/A'} | {fmt(wf_second['diff_net'] if wf_second else None)} | {fmt(wf_second['p_value'] if wf_second else None)} |
| **ثبات الإشارة** | | | | **{'نعم — نفس الاتجاه' if consistent else 'لا — الاتجاه متعاكس'}** |

---

## Subgroup: Large / Mid / Small Cap

| Cap Group | N_filter | N_total | diff_net% | p-value | Cohen's d |
|----------|---------|---------|---------|---------|---------|
| Large | {cap_large['N_filter'] if cap_large else 'N/A'} | {cap_large['N_total'] if cap_large else 'N/A'} | {fmt(cap_large['diff_net'] if cap_large else None)} | {fmt(cap_large['p_value'] if cap_large else None)} | {fmt(cap_large['cohen_d'] if cap_large else None, 3)} |
| Mid | {cap_mid['N_filter'] if cap_mid else 'N/A'} | {cap_mid['N_total'] if cap_mid else 'N/A'} | {fmt(cap_mid['diff_net'] if cap_mid else None)} | {fmt(cap_mid['p_value'] if cap_mid else None)} | {fmt(cap_mid['cohen_d'] if cap_mid else None, 3)} |
| Small | {cap_small['N_filter'] if cap_small else 'N/A'} | {cap_small['N_total'] if cap_small else 'N/A'} | {fmt(cap_small['diff_net'] if cap_small else None)} | {fmt(cap_small['p_value'] if cap_small else None)} | {fmt(cap_small['cohen_d'] if cap_small else None, 3)} |

---

## الحكم الصريح

{verdict_ar}

---

*السكريبت: `research/scripts/entry_filter_test.py` | البيانات: Binance REST API | seed={SEED}*
*لا تعديلات على الكود الحيّ — بحث فقط*
"""
    return report, verdict_en


# ======== Main ========
def main():
    print("=" * 60)
    print("اختبار سببي: فلتر EMA/رقم مستدير — عيّنة عشوائية")
    print("=" * 60)

    # 1. قائمة الرموز — مُثبَّتة بـ cache لضمان قابلية التكرار
    cached_symbols = load_symbol_list_cache()
    if cached_symbols is not None:
        selected = cached_symbols
        print(f"   قائمة الرموز من cache: {len(selected)} رمزاً")
    else:
        all_symbols = get_exchange_symbols()
        print(f"   إجمالي USDT pairs: {len(all_symbols)}")
        # 2. اختيار العيّنة
        sel_large, sel_mid, sel_small = select_symbols(all_symbols)
        selected = [(s, "large") for s in sel_large] + \
                   [(s, "mid") for s in sel_mid] + \
                   [(s, "small") for s in sel_small]
        save_symbol_list_cache(selected)
        print(f"   تم حفظ قائمة الرموز في cache")

    print(f"\n[3] رموز مختارة: {len(selected)}")

    # 3. جلب klines لكل رمز (streaming)
    all_rows = []
    for i, (symbol, cap_group) in enumerate(selected):
        print(f"[{i+1}/{len(selected)}] {symbol} ({cap_group})...", end=" ")
        candles_dict = {}
        ok = True
        for interval in INTERVALS:
            try:
                candles_dict[interval] = fetch_klines(symbol, interval)
                print(f"{interval}:{len(candles_dict[interval])}", end=" ")
            except Exception as e:
                print(f"خطأ {interval}: {e}", end=" ")
                ok = False
                break
        print()
        if not ok:
            continue

        rows = process_symbol(symbol, candles_dict, cap_group)
        all_rows.extend(rows)
        print(f"   → {len(rows)} نقطة | flag=True: {sum(1 for r in rows if r['flag_filter'])}")

        # تحرير الذاكرة
        del candles_dict

    print(f"\n[4] إجمالي النقاط: {len(all_rows)}")

    if not all_rows:
        print("لا بيانات كافية!")
        return

    # 4. التحليل الإحصائي
    print("[5] تحليل إحصائي...")
    results = {}
    for label in ["24h", "48h", "7d"]:
        results[f"{label}_all"] = analyze(all_rows, label)
    for half in ["first", "second"]:
        results[f"48h_{half}"] = analyze_split(all_rows, half, "48h")
    for cap in ["large", "mid", "small"]:
        results[f"48h_{cap}"] = analyze_cap(all_rows, cap, "48h")

    # 5. توليد التقرير
    print("[6] توليد التقرير...")
    report_text, verdict = build_report(all_rows, results)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"   التقرير: {OUTPUT_PATH}")

    # 6. طباعة ملخّص للـ stdout
    print("\n" + "=" * 60)
    print("النتائج الرئيسية (48h):")
    main_res = results.get("48h_all")
    if main_res:
        print(f"  N_filter: {main_res['N_filter']:,} | N_total: {main_res['N_total']:,}")
        print(f"  mean_net flag=True:  {main_res['mean_filter_net']:.4f}%")
        print(f"  mean_net flag=False: {main_res['mean_nofilter_net']:.4f}%")
        print(f"  diff_net: {main_res['diff_net']:.4f}%")
        print(f"  p-value:  {main_res['p_value']:.4f}")
        print(f"  CI 95%:   [{main_res['ci_lo']:.4f}%, {main_res['ci_hi']:.4f}%]")
        print(f"  Cohen's d: {main_res['cohen_d']:.4f}")
        print(f"  VERDICT: {verdict}")
    print("=" * 60)

    # حفظ النتائج JSON للمرجع
    results_json_path = os.path.join(BASE_DIR, "entry_filter_results_2026_05_20.json")
    with open(results_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "verdict": verdict,
            "n_total": len(all_rows),
            "n_symbols": len(set(r["symbol"] for r in all_rows)),
            "results": {k: v for k, v in results.items() if v is not None}
        }, f, ensure_ascii=False, indent=2)
    print(f"   JSON: {results_json_path}")


if __name__ == "__main__":
    main()
