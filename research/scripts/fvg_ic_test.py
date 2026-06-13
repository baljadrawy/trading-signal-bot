"""
FVG IC Test — هل الفجوات السعرية لها قدرة تنبؤية فعلية؟

المنطق:
1. لكل FVG مفلتر (حجم > 1.5×)، نسجّل سعر الدخول والاتجاه.
2. نقيس forward return عند 1d, 3d, 7d, 14d.
3. نطرح رسوم 0.3% (round-trip).
4. نقارن بـ baseline: نفس عدد الدخولات بشكل عشوائي.
5. نحسب: متوسط، win rate، IC، t-test، p-value.

سياسات الدخول المختبرة:
- close_impulse: دخول عند إغلاق شمعة الاندفاع (t-1)، فوراً.
- fvg_midpoint: دخول عند منتصف الفجوة (انتظار retest، قد لا يحدث).

المخرج: تقرير يحسم هل نواصل البحث في SMC أم نتركه.
"""
import json
import math
import os
import random
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime

BINANCE = "https://api.binance.com"
DAYS = 500
TOP_N_SYMBOLS = 80
VOL_MULTIPLIER = 1.5
VOL_WINDOW = 20
HORIZONS = [1, 3, 7, 14]
ROUND_TRIP_FEE = 0.003  # 0.3%
RETEST_WINDOW = 10      # شموع لانتظار retest قبل إلغاء الإشارة
N_BASELINE = 1000       # عدد دخولات عشوائية لكل horizon
REQUEST_DELAY = 0.15
random.seed(42)


def http_get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'fvg-ic/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_top_symbols():
    data = http_get(f"{BINANCE}/api/v3/ticker/24hr")
    usdt = [d for d in data if d['symbol'].endswith('USDT')
            and not any(x in d['symbol'] for x in ['UP', 'DOWN', 'BULL', 'BEAR'])]
    usdt.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
    return [d['symbol'] for d in usdt[:TOP_N_SYMBOLS]]


def fetch_klines(symbol):
    try:
        data = http_get(f"{BINANCE}/api/v3/klines",
                        {'symbol': symbol, 'interval': '1d', 'limit': 1000})
        # نخزن: (open_time, high, low, close, volume, open)
        return [(int(k[0]), float(k[2]), float(k[3]),
                 float(k[4]), float(k[5]), float(k[1])) for k in data]
    except Exception:
        return None


def detect_fvgs(klines):
    """يرجع قائمة FVG: dict(idx, direction, entry_close, fvg_low, fvg_high)."""
    out = []
    if not klines or len(klines) < VOL_WINDOW + 3 + max(HORIZONS):
        return out
    for i in range(VOL_WINDOW + 2, len(klines) - max(HORIZONS)):
        h_prev2 = klines[i-2][1]
        l_prev2 = klines[i-2][2]
        l_now = klines[i][2]
        h_now = klines[i][1]
        vol_mid = klines[i-1][4]
        vol_avg = sum(k[4] for k in klines[i-1-VOL_WINDOW:i-1]) / VOL_WINDOW
        if vol_avg == 0 or vol_mid <= VOL_MULTIPLIER * vol_avg:
            continue
        close_impulse = klines[i-1][3]
        if l_now > h_prev2:
            out.append({
                'idx': i, 'direction': 'bull',
                'entry_close': close_impulse,
                'fvg_low': h_prev2, 'fvg_high': l_now,
            })
        if h_now < l_prev2:
            out.append({
                'idx': i, 'direction': 'bear',
                'entry_close': close_impulse,
                'fvg_low': h_now, 'fvg_high': l_prev2,
            })
    return out


def forward_returns(klines, entry_idx, entry_price, direction, horizons):
    """يرجع dict: horizon → return صافي بعد رسوم 0.3%."""
    out = {}
    for h in horizons:
        if entry_idx + h >= len(klines):
            out[h] = None
            continue
        exit_price = klines[entry_idx + h][3]  # close
        raw = (exit_price - entry_price) / entry_price
        if direction == 'bear':
            raw = -raw
        out[h] = raw - ROUND_TRIP_FEE
    return out


def retest_entry(klines, fvg):
    """يحاول الدخول عند منتصف الفجوة خلال RETEST_WINDOW شمعة. يرجع (idx, price) أو None."""
    mid = (fvg['fvg_low'] + fvg['fvg_high']) / 2
    start = fvg['idx']
    for j in range(start, min(start + RETEST_WINDOW, len(klines))):
        low_j = klines[j][2]
        high_j = klines[j][1]
        if low_j <= mid <= high_j:
            return j, mid
    return None


def compute_stats(returns):
    """يحسب: n, mean, std, median, win_rate, t_stat, approx p-value (two-tailed)."""
    valid = [r for r in returns if r is not None]
    n = len(valid)
    if n < 2:
        return {'n': n, 'mean': None, 'std': None,
                'win_rate': None, 't_stat': None, 'p_approx': None}
    mean = sum(valid) / n
    var = sum((r - mean) ** 2 for r in valid) / (n - 1)
    std = math.sqrt(var)
    wins = sum(1 for r in valid if r > 0)
    win_rate = wins / n
    se = std / math.sqrt(n) if std > 0 else 0
    t_stat = mean / se if se > 0 else 0
    # تقريب p-value عبر التوزيع الطبيعي (n كبير)
    z = abs(t_stat)
    # Φ تقريب abramowitz & stegun
    p_one = 0.5 * math.erfc(z / math.sqrt(2))
    p_two = 2 * p_one
    return {'n': n, 'mean': mean, 'std': std,
            'win_rate': win_rate, 't_stat': t_stat, 'p_approx': p_two}


def random_baseline(all_klines, horizons, n_samples=N_BASELINE):
    """دخولات عشوائية على نفس البيانات للمقارنة."""
    pool = []
    for s, k in all_klines.items():
        if len(k) < VOL_WINDOW + 3 + max(horizons):
            continue
        for i in range(VOL_WINDOW + 2, len(k) - max(horizons)):
            pool.append((s, i))
    if not pool:
        return {h: {} for h in horizons}
    sample = random.sample(pool, min(n_samples, len(pool)))
    results = {h: [] for h in horizons}
    for s, i in sample:
        klines = all_klines[s]
        # نختار اتجاه عشوائي
        direction = random.choice(['bull', 'bear'])
        entry = klines[i][3]
        rets = forward_returns(klines, i, entry, direction, horizons)
        for h in horizons:
            if rets[h] is not None:
                results[h].append(rets[h])
    return {h: compute_stats(results[h]) for h in horizons}


def main():
    print(f"[1/4] جلب رموز ...")
    symbols = get_top_symbols()
    print(f"      → {len(symbols)} رمز")

    print(f"[2/4] جلب klines ...")
    all_klines = {}
    for i, s in enumerate(symbols, 1):
        k = fetch_klines(s)
        if k and len(k) >= VOL_WINDOW + 3 + max(HORIZONS):
            all_klines[s] = k[-DAYS:] if len(k) > DAYS else k
        if i % 20 == 0:
            print(f"      ... {i}/{len(symbols)}")
        time.sleep(REQUEST_DELAY)
    print(f"      → {len(all_klines)} رمز جاهز")

    print(f"[3/4] استخراج FVGs + حساب forward returns ...")
    # تجميع returns حسب (direction, policy, horizon)
    buckets = defaultdict(list)
    fvg_total = 0
    retest_hits = 0
    for s, k in all_klines.items():
        fvgs = detect_fvgs(k)
        fvg_total += len(fvgs)
        for f in fvgs:
            # سياسة 1: دخول فوري عند إغلاق شمعة الاندفاع
            rets_imm = forward_returns(k, f['idx'], f['entry_close'],
                                       f['direction'], HORIZONS)
            for h in HORIZONS:
                if rets_imm[h] is not None:
                    buckets[(f['direction'], 'close_impulse', h)].append(rets_imm[h])
                    buckets[('all', 'close_impulse', h)].append(rets_imm[h])

            # سياسة 2: دخول عند retest منتصف الفجوة
            retest = retest_entry(k, f)
            if retest:
                retest_hits += 1
                ridx, rprice = retest
                rets_mid = forward_returns(k, ridx, rprice,
                                           f['direction'], HORIZONS)
                for h in HORIZONS:
                    if rets_mid[h] is not None:
                        buckets[(f['direction'], 'fvg_midpoint', h)].append(rets_mid[h])
                        buckets[('all', 'fvg_midpoint', h)].append(rets_mid[h])

    print(f"      → {fvg_total} FVG مفلتر، {retest_hits} منها حقّقت retest خلال {RETEST_WINDOW} شموع ({retest_hits*100//max(fvg_total,1)}%)")

    print(f"[4/4] baseline عشوائي ...")
    baseline = random_baseline(all_klines, HORIZONS)

    # طباعة التقرير
    print("\n" + "=" * 90)
    print("📊 نتائج الـ Forward Returns (صافي بعد رسوم 0.3% round-trip)")
    print("=" * 90)

    def fmt(stats):
        if stats['mean'] is None:
            return f"n={stats['n']:>4}  --"
        sig = '★' if stats['p_approx'] < 0.01 else ('•' if stats['p_approx'] < 0.05 else ' ')
        return (f"n={stats['n']:>4}  μ={stats['mean']*100:+6.2f}%  "
                f"WR={stats['win_rate']*100:5.1f}%  "
                f"t={stats['t_stat']:+5.2f}  p={stats['p_approx']:.3f} {sig}")

    for policy in ['close_impulse', 'fvg_midpoint']:
        print(f"\n— سياسة: {policy} —")
        for direction in ['bull', 'bear', 'all']:
            print(f"  {direction.upper():4}")
            for h in HORIZONS:
                stats = compute_stats(buckets.get((direction, policy, h), []))
                print(f"    {h:>2}d: {fmt(stats)}")

    print(f"\n— baseline (دخول عشوائي، اتجاه عشوائي) —")
    for h in HORIZONS:
        print(f"    {h:>2}d: {fmt(baseline[h])}")

    print("\n" + "=" * 90)
    print("الترميز:  ★ p<0.01 (قوي)   • p<0.05 (مقبول)   فراغ = غير معنوي")
    print("=" * 90)

    # حُكم نهائي
    print("\n🏁 الحُكم:")
    best_signal = None
    for direction in ['bull', 'bear']:
        for policy in ['close_impulse', 'fvg_midpoint']:
            for h in HORIZONS:
                stats = compute_stats(buckets.get((direction, policy, h), []))
                if (stats['mean'] is not None and stats['mean'] > 0
                        and stats['p_approx'] < 0.05 and stats['n'] >= 50):
                    if (best_signal is None or
                            stats['mean'] > best_signal[3]['mean']):
                        best_signal = (direction, policy, h, stats)
    if best_signal:
        d, p, h, s = best_signal
        print(f"   ✅ أفضل إشارة معنوية: {d.upper()} / {p} / {h}d")
        print(f"      μ={s['mean']*100:+.2f}%  WR={s['win_rate']*100:.1f}%  "
              f"n={s['n']}  p={s['p_approx']:.4f}")
        print("   → يستحق التطوير لمرحلة CHoCH + entry policy")
    else:
        print("   🚫 لا توجد إشارة معنوية (p<0.05, μ>0, n≥50) في أي تركيبة.")
        print("   → SMC وحده (FVG + volume) لا يكفي. يجب إضافة CHoCH/Sweep")
        print("     أو الاعتراف بأن الحافة غير موجودة في هذه البيانات.")

    # حفظ
    out = {
        'generated_at': datetime.now().isoformat(),
        'params': {'days': DAYS, 'top_n': TOP_N_SYMBOLS,
                   'vol_mult': VOL_MULTIPLIER, 'horizons': HORIZONS,
                   'fee': ROUND_TRIP_FEE, 'retest_window': RETEST_WINDOW},
        'fvg_total': fvg_total,
        'retest_hits': retest_hits,
        'results': {
            f"{d}|{p}|{h}d": compute_stats(buckets.get((d, p, h), []))
            for d in ['bull', 'bear', 'all']
            for p in ['close_impulse', 'fvg_midpoint']
            for h in HORIZONS
        },
        'baseline': {f"{h}d": baseline[h] for h in HORIZONS},
    }
    out_path = '/home/tradmin/trading-signal-bot/research/results/fvg_ic_test.json'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n💾 محفوظ: {out_path}")


if __name__ == '__main__':
    main()
