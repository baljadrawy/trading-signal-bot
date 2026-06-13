#!/usr/bin/env python3
"""
اختبار سببي صارم: ICT Killzone على عيّنة عشوائية مستقلة عن منطق البوت.
التاريخ: 2026-05-21
المنهجية: عيّنة عشوائية multi-cap → نقاط زمنية عشوائية 1h → flags killzone → forward returns → Welch t-test + CI + Cohen d.

قيود:
- بحث فقط — لا تعديل على الكود الحيّ. التجميد ساري.
- معالجة متدفّقة (رمز-رمز) لتجنّب ضغط الذاكرة.
- بلا حزم جديدة: numpy/requests/pickle/math.
- Cache محلي تحت research/cache/klines_kz/ (مسار مختلف عن entry_filter لتجنّب التعارض).
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
BASE_DIR = os.environ.get("RESEARCH_BASE_DIR", "/home/tradmin/trading-signal-bot/research")
CACHE_DIR = os.path.join(BASE_DIR, "cache", "klines_kz")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

DATE_STAMP = "2026_05_21"
OUTPUT_MD = os.path.join(RESULTS_DIR, f"killzone_causal_{DATE_STAMP}.md")
OUTPUT_JSON = os.path.join(RESULTS_DIR, f"killzone_causal_{DATE_STAMP}.json")
SYMBOL_LIST_CACHE = os.path.join(BASE_DIR, "cache", "kz_symbols.pkl")

# ======== ثوابت ========
SEED = 20260521
BINANCE_BASE = "https://api.binance.com"
INTERVAL = "1h"            # الإطار الأساسي فقط (لا نحتاج 4h/1d هنا — KZ هو UTC hour فقط)
INTERVAL_MS = 3600_000     # 1h بالمللي ثانية
DAYS_BACK = 90
RESERVE_DAYS = 8           # آخر 8 أيام محجوزة للـ forward returns (7d + هامش)
FWD_24H = 24
FWD_48H = 48
FWD_7D = 168
FEE = 0.003                # 0.3% رسوم round-trip
POINTS_PER_SYMBOL = 130    # نقاط زمنية لكل رمز → ~4000 إجمالاً مع 37 رمزاً
BOOTSTRAP_N = 1000

# تصنيفات الرموز
LARGE_CAP_N = 12
MID_CAP_N = 13
SMALL_CAP_N = 12
TARGET_SYMBOLS = LARGE_CAP_N + MID_CAP_N + SMALL_CAP_N  # 37

# Rate limit
REQUEST_SLEEP = 0.18       # ثانية بين الطلبات

# ======== ICT Killzone Hours (UTC) ========
LONDON_KZ_HOURS = {7, 8, 9, 10}           # London Open Killzone
NY_AM_KZ_HOURS = {12, 13, 14, 15}         # NY AM Killzone (NY open 13:30 UTC ± 2h)

import numpy as np


# ======== t-test + إحصاء ========
def _betainc(a, b, x):
    """Regularized incomplete beta I_x(a,b) — continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
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


def _t_pvalue(t, df):
    t = abs(t)
    if df > 100:
        return float(math.erfc(t / math.sqrt(2)))
    x = df / (df + t * t)
    p_half = _betainc(df / 2, 0.5, x)
    return float(min(2 * p_half, 1.0))


def welch_ttest(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return 0.0, 1.0, 0
    m1, m2 = np.mean(a), np.mean(b)
    v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 0.0, 1.0, 0
    t = (m1 - m2) / se
    df = (v1 / n1 + v2 / n2) ** 2 / (
        (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    )
    p = _t_pvalue(t, df)
    return float(t), float(p), float(df)


def cohen_d(a, b):
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return 0.0
    s = math.sqrt(
        ((n1 - 1) * np.var(a, ddof=1) + (n2 - 1) * np.var(b, ddof=1)) / (n1 + n2 - 2)
    )
    return (np.mean(a) - np.mean(b)) / s if s > 0 else 0.0


def bootstrap_ci(a, b, n=BOOTSTRAP_N, ci=0.95):
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(n):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs.append(float(np.mean(sa) - np.mean(sb)))
    alpha = (1 - ci) / 2
    return float(np.percentile(diffs, alpha * 100)), float(np.percentile(diffs, (1 - alpha) * 100))


# ======== Binance REST ========
def binance_get(path, params=None, max_retry=4):
    url = BINANCE_BASE + path
    for attempt in range(max_retry):
        try:
            r = requests.get(url, params=params, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == max_retry - 1:
                raise
            time.sleep(2 ** attempt)


def get_exchange_symbols():
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


def get_24h_volume(all_symbols):
    time.sleep(REQUEST_SLEEP)
    data = binance_get("/api/v3/ticker/24hr")
    sym_set = set(all_symbols)
    vol_map = {}
    for t in data:
        if t["symbol"] in sym_set:
            vol_map[t["symbol"]] = float(t["quoteVolume"])
    return vol_map


def select_symbols(all_symbols):
    print("[2] جلب 24h volume لتصنيف العملات...")
    vol_map = get_24h_volume(all_symbols)
    sorted_syms = sorted(all_symbols, key=lambda s: vol_map.get(s, 0), reverse=True)
    large = sorted_syms[:30]
    mid = sorted_syms[30:100]
    small = sorted_syms[100:300]

    rng = random.Random(SEED)
    sel_large = rng.sample(large, min(LARGE_CAP_N, len(large)))
    sel_mid = rng.sample(mid, min(MID_CAP_N, len(mid)))
    sel_small = rng.sample(small, min(SMALL_CAP_N, len(small)))

    print(f"   Large-cap: {sel_large}")
    print(f"   Mid-cap:   {sel_mid}")
    print(f"   Small-cap: {sel_small}")
    return sel_large, sel_mid, sel_small


# ======== Cache ========
def cache_path_kz(symbol):
    return os.path.join(CACHE_DIR, f"{symbol}_1h.pkl")


def load_cache_kz(symbol):
    p = cache_path_kz(symbol)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def save_cache_kz(symbol, data):
    p = cache_path_kz(symbol)
    with open(p, "wb") as f:
        pickle.dump(data, f)


# ======== Fetch 1h klines فقط ========
def fetch_klines_1h(symbol, days=DAYS_BACK):
    cached = load_cache_kz(symbol)
    if cached is not None:
        return cached

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 86400_000
    all_candles = []
    cur = start_ms

    while cur < now_ms:
        time.sleep(REQUEST_SLEEP)
        params = {
            "symbol": symbol,
            "interval": "1h",
            "startTime": cur,
            "limit": 500,
        }
        try:
            rows = binance_get("/api/v3/klines", params=params)
        except Exception as e:
            print(f"   خطأ {symbol}: {e}", end=" ")
            break
        if not rows:
            break
        all_candles.extend(rows)
        last_ts = rows[-1][0]
        if last_ts >= now_ms - INTERVAL_MS:
            break
        cur = last_ts + INTERVAL_MS

    result = [
        {"t": int(r[0]), "c": float(r[4])}
        for r in all_candles
    ]
    save_cache_kz(symbol, result)
    return result


# ======== Killzone Flags ========
def compute_kz_flags(t_ms):
    """
    من timestamp UTC:
    - in_london_kz: hour ∈ {7,8,9,10}
    - in_ny_am_kz:  hour ∈ {12,13,14,15}
    - in_any_kz:    London OR NY_AM
    - is_sunday:    weekday() == 6
    """
    dt = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
    h = dt.hour
    wd = dt.weekday()  # 0=Mon … 6=Sun

    in_london = h in LONDON_KZ_HOURS
    in_ny_am = h in NY_AM_KZ_HOURS
    in_any = in_london or in_ny_am
    is_sunday = (wd == 6)

    return {
        "hour_utc": h,
        "weekday": wd,
        "in_london_kz": in_london,
        "in_ny_am_kz": in_ny_am,
        "in_any_kz": in_any,
        "is_sunday": is_sunday,
    }


# ======== Forward Returns ========
def get_future_close(candles, idx, hours_ahead):
    target_idx = idx + hours_ahead
    if target_idx >= len(candles):
        return None
    return candles[target_idx]["c"]


# ======== معالجة رمز واحد ========
def process_symbol_kz(symbol, candles, cap_group):
    """
    توليد نقاط عشوائية → flags KZ → forward returns.
    كل معالجة داخل هذه الدالة فقط (لا حفظ في RAM عدا القائمة المُعادة).
    """
    if not candles or len(candles) < FWD_7D + 50:
        return []

    # نافذة الاختيار: ما عدا آخر RESERVE_DAYS*24 ساعة + FWD_7D
    max_idx = len(candles) - RESERVE_DAYS * 24 - FWD_7D - 1
    min_idx = 5  # هامش بداية صغير

    if max_idx - min_idx < 30:
        return []

    sym_seed = SEED + sum(ord(c) for c in symbol)
    rng = random.Random(sym_seed)
    available_range = max_idx - min_idx
    n_points = min(POINTS_PER_SYMBOL, available_range)
    if n_points < 20:
        return []

    indices = sorted(rng.sample(range(min_idx, max_idx + 1), n_points))

    rows = []
    for idx in indices:
        candle = candles[idx]
        t_ms = candle["t"]
        price = candle["c"]
        if price <= 0:
            continue

        flags = compute_kz_flags(t_ms)

        c24 = get_future_close(candles, idx, FWD_24H)
        c48 = get_future_close(candles, idx, FWD_48H)
        c7d = get_future_close(candles, idx, FWD_7D)

        # يُلغى إن لم يتوفر c48
        if c48 is None:
            continue

        def fwd_net(future_c):
            if future_c is None:
                return None
            return (future_c - price) / price - FEE

        # تصنيف نصف للـ walk-forward (يوم 0-44 = نصف أول، 45-89 = ثانٍ)
        first_t = candles[0]["t"]
        day_idx = (t_ms - first_t) // 86400_000
        half = "first" if day_idx < 45 else "second"

        row = {
            "symbol": symbol,
            "cap_group": cap_group,
            "t_ms": t_ms,
            "price": price,
            "half": half,
            "fwd_24h_net": fwd_net(c24),
            "fwd_48h_net": fwd_net(c48),
            "fwd_7d_net": fwd_net(c7d),
        }
        row.update(flags)
        rows.append(row)

    return rows


# ======== تحليل مجموعة ========
def analyze_group(pos_list, neg_list, label_pos, label_neg, fwd_key):
    """
    Welch t-test + bootstrap CI + Cohen d لمجموعتين.
    يُعيد dict أو None إن n صغير.
    """
    a = np.array([r[fwd_key] for r in pos_list if r[fwd_key] is not None])
    b = np.array([r[fwd_key] for r in neg_list if r[fwd_key] is not None])

    if len(a) < 5 or len(b) < 5:
        return None

    t_stat, p_val, df = welch_ttest(a, b)
    ci_lo, ci_hi = bootstrap_ci(a, b)
    d = cohen_d(a, b)

    return {
        "label_pos": label_pos,
        "label_neg": label_neg,
        "fwd_key": fwd_key,
        "n_pos": len(a),
        "n_neg": len(b),
        "n_total": len(a) + len(b),
        "mean_pos": float(np.mean(a)) * 100,
        "mean_neg": float(np.mean(b)) * 100,
        "diff": float(np.mean(a) - np.mean(b)) * 100,
        "std_pos": float(np.std(a, ddof=1)) * 100,
        "std_neg": float(np.std(b, ddof=1)) * 100,
        "t_stat": t_stat,
        "df": df,
        "p_value": p_val,
        "ci_lo": ci_lo * 100,
        "ci_hi": ci_hi * 100,
        "cohen_d": d,
    }


def run_all_analyses(all_rows):
    """
    تحليلات متعددة:
    1. in_any_kz True vs False — كل آفاق
    2. London فقط vs الباقي
    3. NY_AM فقط vs الباقي
    4. is_sunday True vs False
    5. Walk-forward: نصف 1 vs نصف 2 (لـ in_any_kz × fwd_48h)
    """
    results = {}

    for fwd_key, horizon in [("fwd_24h_net", "24h"), ("fwd_48h_net", "48h"), ("fwd_7d_net", "7d")]:
        # 1. Any KZ
        pos = [r for r in all_rows if r["in_any_kz"]]
        neg = [r for r in all_rows if not r["in_any_kz"]]
        results[f"any_kz_{horizon}"] = analyze_group(pos, neg, "in_any_kz=True", "in_any_kz=False", fwd_key)

        # 2. London only
        pos_lon = [r for r in all_rows if r["in_london_kz"]]
        neg_lon = [r for r in all_rows if not r["in_london_kz"]]
        results[f"london_{horizon}"] = analyze_group(pos_lon, neg_lon, "London KZ", "Outside London", fwd_key)

        # 3. NY AM only
        pos_ny = [r for r in all_rows if r["in_ny_am_kz"]]
        neg_ny = [r for r in all_rows if not r["in_ny_am_kz"]]
        results[f"ny_am_{horizon}"] = analyze_group(pos_ny, neg_ny, "NY AM KZ", "Outside NY AM", fwd_key)

        # 4. Sunday
        pos_sun = [r for r in all_rows if r["is_sunday"]]
        neg_sun = [r for r in all_rows if not r["is_sunday"]]
        results[f"sunday_{horizon}"] = analyze_group(pos_sun, neg_sun, "is_sunday=True", "is_sunday=False", fwd_key)

    # 5. Walk-forward: in_any_kz × 48h
    for half in ["first", "second"]:
        subset = [r for r in all_rows if r["half"] == half]
        pos_h = [r for r in subset if r["in_any_kz"]]
        neg_h = [r for r in subset if not r["in_any_kz"]]
        results[f"wf_{half}_any_kz_48h"] = analyze_group(
            pos_h, neg_h, f"KZ(half={half})", f"No-KZ(half={half})", "fwd_48h_net"
        )

    return results


# ======== توليد التقرير ========
def build_report(all_rows, results, n_syms_actual):
    n_total = len(all_rows)
    n_kz = sum(1 for r in all_rows if r["in_any_kz"])
    n_london = sum(1 for r in all_rows if r["in_london_kz"])
    n_ny = sum(1 for r in all_rows if r["in_ny_am_kz"])
    n_sunday = sum(1 for r in all_rows if r["is_sunday"])
    n_non_kz = n_total - n_kz

    # توزيع الساعات
    hour_counts = {}
    for r in all_rows:
        h = r["hour_utc"]
        hour_counts[h] = hour_counts.get(h, 0) + 1

    cap_counts = {}
    for r in all_rows:
        cap_counts[r["cap_group"]] = cap_counts.get(r["cap_group"], 0) + 1

    def fmt(v, d=3):
        if v is None:
            return "N/A"
        return f"{v:.{d}f}"

    def sig_str(r):
        if r is None:
            return "N/A"
        p = r["p_value"]
        if p < 0.01:
            return f"**{fmt(p)} ***"
        elif p < 0.05:
            return f"**{fmt(p)} **"
        else:
            return fmt(p)

    # ======== حكم الثبات عبر Walk-Forward ========
    wf1 = results.get("wf_first_any_kz_48h")
    wf2 = results.get("wf_second_any_kz_48h")
    wf_consistent = False
    wf_note = "لا بيانات كافية"
    if wf1 and wf2:
        same_sign = (wf1["diff"] >= 0) == (wf2["diff"] >= 0)
        wf_consistent = same_sign
        wf_note = f"نفس الاتجاه في النصفين ({'+' if wf1['diff']>=0 else '-'}{fmt(abs(wf1['diff']))}% / {'+' if wf2['diff']>=0 else '-'}{fmt(abs(wf2['diff']))}%)" if same_sign else f"اتجاه متعاكس (نصف1={fmt(wf1['diff'])}% vs نصف2={fmt(wf2['diff'])}%)"

    # ======== الحكم النهائي ========
    main_48h = results.get("any_kz_48h")
    verdict_en = "INSUFFICIENT_DATA"
    verdict_ar = "لا بيانات كافية للحكم."

    if main_48h:
        p_ok = main_48h["p_value"] < 0.05
        effect_ok = abs(main_48h["diff"]) > 0.2  # عتبة الأثر 0.2% (أدنى من 0.3% لأن KZ أثره متوقع صغير)
        signed_effect = main_48h["diff"]  # موجب = KZ أفضل، سالب = KZ أسوأ

        if p_ok and effect_ok:
            if signed_effect > 0:
                verdict_en = "KZ_POSITIVE_PREDICTIVE"
                verdict_ar = (
                    f"**Killzone له أثر موجب دال** على عيّنة عشوائية "
                    f"(diff={fmt(signed_effect)}%, p={fmt(main_48h['p_value'])}, d={fmt(main_48h['cohen_d'])}).\n\n"
                    "**التفسير:** التناقض مع الاختبار المنحاز (الاختبار السابق: KZ أسوأ) يدلّ أن فلاتر "
                    "mean-revert لدينا (RSI<40 في تراجع) هي ما يتعارض مع KZ لا أن KZ سالب سببياً. "
                    "ربما دخولنا في downtrend يُضعف أي تأثير KZ."
                )
            else:
                verdict_en = "KZ_NEGATIVE_PREDICTIVE"
                verdict_ar = (
                    f"**Killzone له أثر سالب دال** على عيّنة عشوائية "
                    f"(diff={fmt(signed_effect)}%, p={fmt(main_48h['p_value'])}, d={fmt(main_48h['cohen_d'])}).\n\n"
                    "**التفسير:** تأكيد سببي للاختبار السابق — KZ فعلاً أسوأ على عيّنة عشوائية أيضاً. "
                    "ضخّ السيولة في هذه الجلسات يُولّد تقلباً لا اتجاهاً، مما يضرّ الاستراتيجية mean-revert."
                )
        else:
            reasons = []
            if not p_ok:
                reasons.append(f"p={fmt(main_48h['p_value'])} غير دال (≥0.05)")
            if not effect_ok:
                reasons.append(f"|diff|={fmt(abs(main_48h['diff']))}% < 0.2%")
            if not wf_consistent:
                reasons.append("الإشارة غير ثابتة عبر النصفين")
            verdict_en = "KZ_NO_CAUSAL_EDGE"
            verdict_ar = (
                "**Killzone بلا قوة تنبؤية سببية على الكريبتو** — لا أثر دال "
                f"على عيّنة عشوائية ({n_total:,} نقطة).\n\n"
                f"الأسباب: {'; '.join(reasons)}.\n\n"
                "**التفسير:** ساعات London/NY Open ليست أفضل ولا أسوأ من باقي الساعات للعملات الرقمية. "
                "على عكس الفوركس، لا يوجد market maker مركزي يُفعّل هذه الجلسات في الكريبتو 24/7. "
                "الاختبار السابق (KZ أسوأ على 2435 صفقة) كان أثراً لتحيّز الاختيار "
                "(صفقات RSI<40 في downtrend تُولَد عشوائياً في جميع الساعات)."
            )

    # تاريخ البيانات
    if all_rows:
        t_min = min(r["t_ms"] for r in all_rows)
        t_max = max(r["t_ms"] for r in all_rows)
        date_from = datetime.fromtimestamp(t_min / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        date_to = datetime.fromtimestamp(t_max / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        date_from = date_to = "N/A"

    # ======== بناء الجدول الرئيسي ========
    def row_48h(key, label):
        r = results.get(key)
        if r is None:
            return f"| {label} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        return (
            f"| {label} | {r['n_pos']:,} | {r['n_neg']:,} | "
            f"{fmt(r['mean_pos'])} | {fmt(r['mean_neg'])} | "
            f"{fmt(r['diff'])} | {sig_str(r)} | "
            f"[{fmt(r['ci_lo'])}, {fmt(r['ci_hi'])}] | {fmt(r['cohen_d'])} |"
        )

    def multirow(key, label):
        r = results.get(key)
        if r is None:
            return f"| {label} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        return (
            f"| {label} | {r['n_pos']:,} | {r['n_total']:,} | "
            f"{fmt(r['mean_pos'])} | {fmt(r['diff'])} | "
            f"{sig_str(r)} | [{fmt(r['ci_lo'])}, {fmt(r['ci_hi'])}] | {fmt(r['cohen_d'])} |"
        )

    report = f"""# اختبار سببي: ICT Killzone على عيّنة عشوائية
**التاريخ:** {DATE_STAMP.replace('_', '-')} UTC | **الحكم:** {verdict_en}

---

## ملخّص تنفيذي

تمّ اختبار تأثير ساعات ICT Killzone (London Open: 07-10 UTC، NY AM: 12-15 UTC)
على forward returns على عيّنة عشوائية مستقلة تماماً عن منطق البوت
({n_total:,} نقطة من {n_syms_actual} رمزاً — {date_from} إلى {date_to}).

**النتيجة:** {verdict_ar}

---

## إحصاءات العيّنة

| البيان | القيمة |
|--------|--------|
| الرموز الفعلية | {n_syms_actual} |
| إجمالي النقاط | {n_total:,} |
| نقاط داخل Any KZ | {n_kz:,} ({100*n_kz/n_total:.1f}%) |
| نقاط خارج Any KZ | {n_non_kz:,} ({100*n_non_kz/n_total:.1f}%) |
| London KZ فقط | {n_london:,} ({100*n_london/n_total:.1f}%) |
| NY AM KZ فقط | {n_ny:,} ({100*n_ny/n_total:.1f}%) |
| الأحد (Sunday) | {n_sunday:,} ({100*n_sunday/n_total:.1f}%) |
| توزيع cap | large={cap_counts.get('large',0)}, mid={cap_counts.get('mid',0)}, small={cap_counts.get('small',0)} |
| نطاق البيانات | {date_from} → {date_to} |

---

## الجدول الرئيسي: فصل by KZ (fwd_48h، رسوم 0.3%)

| المجموعة | n_pos | n_neg | mean_pos% | mean_neg% | diff% | p-value | CI 95% | Cohen d |
|---------|-------|-------|----------|----------|-------|---------|--------|---------|
{row_48h("any_kz_48h", "Any KZ vs Outside")}
{row_48h("london_48h", "London KZ vs Outside")}
{row_48h("ny_am_48h", "NY AM KZ vs Outside")}
{row_48h("sunday_48h", "Sunday vs Weekday")}

*diff = mean(pos) − mean(neg) بعد خصم 0.3%*
**** p<0.01 | ** p<0.05*

---

## نتائج الآفاق الثلاثة (Any KZ vs Outside)

| الأفق | n_kz | n_total | mean_kz% | diff% | p-value | CI 95% | Cohen d |
|-------|------|---------|---------|-------|---------|--------|---------|
{multirow("any_kz_24h", "24h")}
{multirow("any_kz_48h", "48h (رئيسي)")}
{multirow("any_kz_7d", "7d")}

---

## Walk-Forward (نصف 1 يوم 0-44 vs نصف 2 يوم 45-89)

| النصف | n_kz | n_total | diff_net% | p-value |
|-------|------|---------|---------|---------|
| نصف 1 (يوم 0-44) | {wf1['n_pos'] if wf1 else 'N/A'} | {wf1['n_total'] if wf1 else 'N/A'} | {fmt(wf1['diff'] if wf1 else None)} | {fmt(wf1['p_value'] if wf1 else None)} |
| نصف 2 (يوم 45-89) | {wf2['n_pos'] if wf2 else 'N/A'} | {wf2['n_total'] if wf2 else 'N/A'} | {fmt(wf2['diff'] if wf2 else None)} | {fmt(wf2['p_value'] if wf2 else None)} |
| **ثبات الإشارة** | | | | **{wf_note}** |

---

## London vs NY AM (مقارنة بين الجلستين، fwd_48h)

| الجلسة | n_kz | n_total | mean_net% | diff% | p-value | Cohen d |
|--------|------|---------|---------|-------|---------|---------|
| London (07-10 UTC) | {results.get('london_48h', {}).get('n_pos', 'N/A') if results.get('london_48h') else 'N/A'} | {results.get('london_48h', {}).get('n_total', 'N/A') if results.get('london_48h') else 'N/A'} | {fmt(results.get('london_48h', {}).get('mean_pos') if results.get('london_48h') else None)} | {fmt(results.get('london_48h', {}).get('diff') if results.get('london_48h') else None)} | {fmt(results.get('london_48h', {}).get('p_value') if results.get('london_48h') else None)} | {fmt(results.get('london_48h', {}).get('cohen_d') if results.get('london_48h') else None)} |
| NY AM (12-15 UTC) | {results.get('ny_am_48h', {}).get('n_pos', 'N/A') if results.get('ny_am_48h') else 'N/A'} | {results.get('ny_am_48h', {}).get('n_total', 'N/A') if results.get('ny_am_48h') else 'N/A'} | {fmt(results.get('ny_am_48h', {}).get('mean_pos') if results.get('ny_am_48h') else None)} | {fmt(results.get('ny_am_48h', {}).get('diff') if results.get('ny_am_48h') else None)} | {fmt(results.get('ny_am_48h', {}).get('p_value') if results.get('ny_am_48h') else None)} | {fmt(results.get('ny_am_48h', {}).get('cohen_d') if results.get('ny_am_48h') else None)} |

---

## الحكم الصريح

{verdict_ar}

---

## ما يعنيه هذا للاستراتيجية المجمّدة

بناءً على نتيجة **{verdict_en}**:

"""

    if verdict_en == "KZ_NO_CAUSAL_EDGE":
        report += """\
- فلتر Killzone لا يُبرّر أي تغيير في الاستراتيجية بعد رفع التجميد.
- الكريبتو سوق 24/7 — مشاركة Market Maker الكلاسيكي (Forex institutions) هي نظرية غير مثبتة.
- الأولوية بعد 50 forward trade: فلتر rsi_divergence>0 وتعديل RSI+Bollinger weights (مدعوم بـ part18/part21/part26).
- لا داعي لاختبار KZ مرة أخرى ما لم تتوفر بيانات جديدة post-2026 أو دراسة محددة للكريبتو spot.
"""
    elif verdict_en == "KZ_POSITIVE_PREDICTIVE":
        report += """\
- KZ يُحسّن forward returns على عيّنة عشوائية → قد يكون مفيداً كـ تحسين للتوقيت لا فلتر صارم.
- التناقض مع نتيجة البوت (KZ أسوأ على الصفقات المنحازة) يعني: استراتيجية mean-revert في downtrend مُضادة لحركة KZ.
- توصية بعد التجميد: اختبر منح bonus score لـ in_any_kz=True بدلاً من حظره كـ فلتر صارم.
- القرار يظل مشروطاً بصمود حافة 1d+bearish/sideways+score3 على 50 صفقة أمامية.
"""
    else:
        report += """\
- أثر سالب دال سببياً → Killzone يُضرّ الاستراتيجية حتى على عيّنة عشوائية.
- الفلتر الحالي (رفض KZ إن أُضيف) مُبرَّر سببياً.
- توصية بعد التجميد: إضافة فلتر in_any_kz=False كـ شرط إضافي للدخول.
"""

    report += f"""
---

*السكريبت:* `research/scripts/killzone_causal_test.py`
*البيانات:* Binance REST API 1h klines — bلا استخدام لبيانات البوت أو DB
*seed:* {SEED} | *bootstrap:* {BOOTSTRAP_N} عيّنة
*لا تعديلات على الكود الحيّ — بحث فقط*
"""
    return report, verdict_en


# ======== Main ========
def main():
    print("=" * 65)
    print("اختبار سببي: ICT Killzone — عيّنة عشوائية مستقلة")
    print("=" * 65)

    # 1. قائمة الرموز (من cache أو من Binance)
    if os.path.exists(SYMBOL_LIST_CACHE):
        with open(SYMBOL_LIST_CACHE, "rb") as f:
            selected = pickle.load(f)
        print(f"[1] قائمة الرموز من cache: {len(selected)} رمزاً")
    else:
        all_symbols = get_exchange_symbols()
        print(f"   إجمالي USDT pairs: {len(all_symbols)}")
        sel_large, sel_mid, sel_small = select_symbols(all_symbols)
        selected = (
            [(s, "large") for s in sel_large]
            + [(s, "mid") for s in sel_mid]
            + [(s, "small") for s in sel_small]
        )
        with open(SYMBOL_LIST_CACHE, "wb") as f:
            pickle.dump(selected, f)
        print(f"   تم حفظ قائمة الرموز: {len(selected)} رمزاً")

    # 2. جلب klines + معالجة (رمز واحد في الوقت)
    all_rows = []
    n_syms_actual = 0
    for i, (symbol, cap_group) in enumerate(selected):
        print(f"[{i+1}/{len(selected)}] {symbol} ({cap_group})...", end=" ", flush=True)
        try:
            candles = fetch_klines_1h(symbol)
            print(f"n={len(candles)}", end=" ", flush=True)
        except Exception as e:
            print(f"SKIP ({e})", flush=True)
            continue

        rows = process_symbol_kz(symbol, candles, cap_group)
        del candles  # تحرير ذاكرة فوراً

        if rows:
            n_syms_actual += 1
            all_rows.extend(rows)
            n_kz_here = sum(1 for r in rows if r["in_any_kz"])
            print(f"→ {len(rows)} نقطة (KZ: {n_kz_here})", flush=True)
        else:
            print("→ 0 نقطة (عيّنة صغيرة)", flush=True)

    print(f"\n[3] إجمالي النقاط: {len(all_rows):,} من {n_syms_actual} رمزاً")

    if len(all_rows) < 100:
        print("ERROR: عيّنة صغيرة جداً")
        sys.exit(1)

    # 3. تحليل إحصائي
    print("[4] تحليل إحصائي (Welch t-test + Bootstrap CI)...")
    results = run_all_analyses(all_rows)

    # طباعة ملخّص سريع
    main_r = results.get("any_kz_48h")
    if main_r:
        print(f"\n  Any KZ vs Outside (48h):")
        print(f"    n_kz={main_r['n_pos']:,}  n_outside={main_r['n_neg']:,}")
        print(f"    mean_kz={main_r['mean_pos']:.4f}%  mean_out={main_r['mean_neg']:.4f}%")
        print(f"    diff={main_r['diff']:.4f}%  p={main_r['p_value']:.4f}  d={main_r['cohen_d']:.4f}")
        print(f"    CI 95%: [{main_r['ci_lo']:.4f}%, {main_r['ci_hi']:.4f}%]")

    # 4. توليد التقرير
    print("\n[5] توليد التقرير...")
    report_text, verdict = build_report(all_rows, results, n_syms_actual)

    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"   MD: {OUTPUT_MD}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "verdict": verdict,
                "n_total": len(all_rows),
                "n_symbols": n_syms_actual,
                "results": {k: v for k, v in results.items() if v is not None},
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"   JSON: {OUTPUT_JSON}")

    print("\n" + "=" * 65)
    print(f"الحكم النهائي: {verdict}")
    print("=" * 65)


if __name__ == "__main__":
    main()
