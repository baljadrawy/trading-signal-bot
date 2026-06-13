"""
FVG Census — يعدّ الفجوات السعرية الصالحة على إطار 1d قبل بناء أي شيء.

التعريف:
- Bullish FVG: low[t] > high[t-2]  (ثلاث شموع، الوسطى هي شمعة الاندفاع)
- Bearish FVG: high[t] < low[t-2]
- فلتر الحجم: حجم الشمعة الوسطى (t-1) > 1.5 × متوسط 20-شمعة

الهدف: معرفة هل العيّنة كافية إحصائياً (نريد > 500 إجمالاً بعد الفلترة).
يستخدم stdlib فقط (urllib) لتجنب الاعتماديات.
"""
import json
import os
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
REQUEST_DELAY = 0.15  # ثانية بين الطلبات (احترام rate limit)


def http_get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'fvg-census/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_top_symbols():
    data = http_get(f"{BINANCE}/api/v3/ticker/24hr")
    usdt = [d for d in data if d['symbol'].endswith('USDT')
            and not any(x in d['symbol'] for x in ['UP', 'DOWN', 'BULL', 'BEAR'])]
    usdt.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
    return [d['symbol'] for d in usdt[:TOP_N_SYMBOLS]]


def fetch_klines(symbol, interval='1d', limit=1000):
    try:
        data = http_get(f"{BINANCE}/api/v3/klines",
                        {'symbol': symbol, 'interval': interval, 'limit': limit})
        return [(int(k[0]), float(k[2]), float(k[3]), float(k[5])) for k in data]
    except Exception as e:
        return None


def count_fvgs(klines):
    if not klines or len(klines) < VOL_WINDOW + 3:
        return 0, 0, 0, 0
    bull_raw = bull_filt = bear_raw = bear_filt = 0
    for i in range(VOL_WINDOW + 2, len(klines)):
        h_prev2 = klines[i-2][1]
        l_prev2 = klines[i-2][2]
        l_now = klines[i][2]
        h_now = klines[i][1]
        vol_mid = klines[i-1][3]
        vol_avg = sum(k[3] for k in klines[i-1-VOL_WINDOW:i-1]) / VOL_WINDOW
        vol_ok = vol_avg > 0 and vol_mid > VOL_MULTIPLIER * vol_avg
        if l_now > h_prev2:
            bull_raw += 1
            if vol_ok:
                bull_filt += 1
        if h_now < l_prev2:
            bear_raw += 1
            if vol_ok:
                bear_filt += 1
    return bull_raw, bear_raw, bull_filt, bear_filt


def main():
    print(f"[1/3] جلب أعلى {TOP_N_SYMBOLS} رمز حسب حجم التداول...")
    symbols = get_top_symbols()
    print(f"      → {len(symbols)} رمز")

    print(f"[2/3] جلب آخر {DAYS} يوم لكل رمز...")
    all_klines = {}
    for i, s in enumerate(symbols, 1):
        k = fetch_klines(s)
        if k and len(k) >= VOL_WINDOW + 3:
            all_klines[s] = k[-DAYS:] if len(k) > DAYS else k
        if i % 10 == 0:
            print(f"      ... {i}/{len(symbols)}")
        time.sleep(REQUEST_DELAY)
    print(f"      → بيانات صالحة لـ {len(all_klines)} رمز")

    print(f"[3/3] فحص FVG ...")
    per_symbol = {}
    totals = defaultdict(int)
    for s, k in all_klines.items():
        br, ber, brf, berf = count_fvgs(k)
        per_symbol[s] = (br, ber, brf, berf, len(k))
        totals['bull_raw'] += br
        totals['bear_raw'] += ber
        totals['bull_filt'] += brf
        totals['bear_filt'] += berf
        totals['candles'] += len(k)

    print("\n" + "=" * 78)
    print(f"{'الرمز':<12} {'شموع':>6} {'bull_raw':>9} {'bear_raw':>9} "
          f"{'bull_1.5×':>10} {'bear_1.5×':>10}")
    print("-" * 78)
    ranked = sorted(per_symbol.items(),
                    key=lambda x: x[1][2] + x[1][3], reverse=True)
    for s, (br, ber, brf, berf, n) in ranked:
        print(f"{s:<12} {n:>6} {br:>9} {ber:>9} {brf:>10} {berf:>10}")
    print("=" * 78)
    print(f"{'الإجمالي':<12} {totals['candles']:>6} "
          f"{totals['bull_raw']:>9} {totals['bear_raw']:>9} "
          f"{totals['bull_filt']:>10} {totals['bear_filt']:>10}")
    print()
    bull = totals['bull_filt']
    bear = totals['bear_filt']
    total_filt = bull + bear
    print(f"📊 الإجمالي بعد فلتر الحجم 1.5×: {total_filt} FVG")
    print(f"   - صاعدة: {bull}")
    print(f"   - هابطة: {bear}")
    print()
    print("الحُكم على الحجم:")
    if total_filt >= 500:
        print(f"   ✅ {total_filt} ≥ 500 — عيّنة كافية للاختبار الإحصائي.")
    elif total_filt >= 200:
        print(f"   ⚠️  {total_filt} في النطاق 200-500 — حدّي. يُفضّل توسيع البيانات.")
    else:
        print(f"   🚫 {total_filt} < 200 — غير كافٍ. يجب توسيع العيّنة:")
        print("      - أضف فريم 4h (يضرب العدد ×6)")
        print("      - أو خفّض شرط الحجم لـ 1.3×")
        print("      - أو ارفع عدد الرموز إلى 150+")

    out = {
        'generated_at': datetime.utcnow().isoformat(),
        'params': {'days': DAYS, 'top_n': TOP_N_SYMBOLS,
                   'vol_mult': VOL_MULTIPLIER, 'vol_window': VOL_WINDOW},
        'totals': dict(totals),
        'per_symbol': {s: {'candles': n, 'bull_raw': br, 'bear_raw': ber,
                           'bull_filt': brf, 'bear_filt': berf}
                       for s, (br, ber, brf, berf, n) in per_symbol.items()},
    }
    out_path = '/home/tradmin/trading-signal-bot/research/results/fvg_census.json'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n💾 محفوظ: {out_path}")


if __name__ == '__main__':
    main()
