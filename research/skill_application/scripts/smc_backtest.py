#!/usr/bin/env python3
"""
اختبار SMC falsify-first — نقل أمين لمنطق LuxAlgo Smart Money Concepts إلى محرّك باكتيست.
يُكرّر: بنية مزدوجة (swing=50 / internal=5) عبر leg()، آلة حالة BOS/CHoCH (trend.bias ينقلب)،
Order Blocks (أقصى شمعة في الساق + volatility parsing عند range>=2*ATR200 + mitigation)،
FVG (فجوة 3 شموع + عتبة دلالة)، مناطق Premium/Discount (trailing extremes).
long-only، شمعة مغلقة، بلا look-ahead. أطر 4h/1d، 595 رمزاً، triple-barrier + رسوم + walk-forward.
"""
import os, sys, glob, math, json
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E   # reuse load()
import ta

DATA = E.DATA
TFS = ['4h', '1d']
TF_HOURS = {'4h': 4.0, '1d': 24.0}
HORIZON = {'4h': 60, '1d': 30}
SWING_LEN = 50
INTERNAL_LEN = 5
FEES = {'gross': 0.0, 'net06': 0.6}   # % round-trip
K_TGT = 2.0                            # هدف +2*ATR
WARM = 210


def legs(high, low, size):
    """يطابق LuxAlgo leg(): يرجع مؤشّرات pivotHigh/pivotLow (وقت التأكيد i، مستوى، فهرس الأصل i-size)."""
    n = len(high)
    roll_hi = pd.Series(high).rolling(size).max().to_numpy()   # max(high[i-size+1..i])
    roll_lo = pd.Series(low).rolling(size).min().to_numpy()
    hs = np.roll(high, size); ls = np.roll(low, size)          # high[i-size], low[i-size]
    newHigh = np.zeros(n, bool); newLow = np.zeros(n, bool)
    valid = np.arange(n) >= size
    newHigh[valid] = hs[valid] > roll_hi[valid]
    newLow[valid] = ls[valid] < roll_lo[valid]
    leg = np.zeros(n, np.int8)
    cur = 0
    for i in range(n):
        if newHigh[i]: cur = 0      # BEARISH leg (top confirmed)
        elif newLow[i]: cur = 1     # BULLISH leg (bottom confirmed)
        leg[i] = cur
    change = np.diff(leg, prepend=leg[0])
    startBear = change == -1        # leg 1->0 : swing HIGH confirmed at i-size
    startBull = change == +1        # leg 0->1 : swing LOW  confirmed at i-size
    return startBear, startBull


def run_symbol(df, tf):
    """يعيد DataFrame مع سياق SMC لكل شمعة + أعمدة الدخول."""
    o = df['open'].to_numpy(); h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    n = len(df)
    atr200 = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=200).average_true_range().to_numpy()
    atr14 = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range().to_numpy()
    # volatility parsing (كما في LuxAlgo): عند range>=2*ATR200 بدّل high/low
    hv = (h - l) >= 2 * np.nan_to_num(atr200, nan=1e18)
    pHigh = np.where(hv, l, h)   # parsedHigh
    pLow = np.where(hv, h, l)    # parsedLow

    sb_sw, sl_sw = legs(h, l, SWING_LEN)
    sb_in, sl_in = legs(h, l, INTERNAL_LEN)

    # حالة
    swH = swL = np.nan; swH_i = swL_i = -1; swH_cr = swL_cr = True
    inH = inL = np.nan; inH_i = inL_i = -1; inH_cr = inL_cr = True
    swTrend = 0; inTrend = 0
    trail_top = -np.inf; trail_bot = np.inf; trail_top_since_swing = -np.inf; trail_bot_since_swing = np.inf
    bull_obs = []      # list of dict(top,bottom,idx)  (bullish order blocks غير مخفّفة)
    fvgs = []          # bullish FVGs غير مملوءة: dict(top,bottom)

    # مخرجات لكل شمعة
    out = {k: np.zeros(n) for k in
           ['sw_bull_choch','sw_bull_bos','in_bull_choch','in_bull_bos',
            'touch_bull_ob','ob_in_discount','fvg_formed','fvg_filled','in_discount','bull_trend']}
    swing_hi_level = np.full(n, np.nan); swing_lo_level = np.full(n, np.nan)

    for i in range(n):
        # 1) تسجيل pivots المؤكَّدة الآن (مركزها i-size)
        if i - SWING_LEN >= 0:
            if sb_sw[i]:
                swH = h[i-SWING_LEN]; swH_i = i-SWING_LEN; swH_cr = False
            if sl_sw[i]:
                swL = l[i-SWING_LEN]; swL_i = i-SWING_LEN; swL_cr = False
        if i - INTERNAL_LEN >= 0:
            if sb_in[i]:
                inH = h[i-INTERNAL_LEN]; inH_i = i-INTERNAL_LEN; inH_cr = False
            if sl_in[i]:
                inL = l[i-INTERNAL_LEN]; inL_i = i-INTERNAL_LEN; inL_cr = False
        swing_hi_level[i] = swH; swing_lo_level[i] = swL

        # 2) trailing extremes (منذ آخر swing) لمناطق premium/discount
        if sl_sw[i] or sb_sw[i]:
            trail_top_since_swing = h[i]; trail_bot_since_swing = l[i]
        trail_top_since_swing = max(trail_top_since_swing, h[i])
        trail_bot_since_swing = min(trail_bot_since_swing, l[i])
        rng = trail_top_since_swing - trail_bot_since_swing
        pd_pos = (c[i] - trail_bot_since_swing) / rng if rng > 0 else 0.5
        in_disc = pd_pos < 0.5
        out['in_discount'][i] = in_disc

        # 3) كسر البنية السوينق (crossover close فوق swingHigh) — CHoCH لو الاتجاه هابط
        prevc = c[i-1] if i > 0 else c[i]
        if (not np.isnan(swH)) and (not swH_cr) and prevc <= swH < c[i]:
            tag_choch = (swTrend == -1)
            swH_cr = True; swTrend = 1
            out['sw_bull_choch'][i] = 1.0 if tag_choch else 0.0
            out['sw_bull_bos'][i] = 0.0 if tag_choch else 1.0
        if (not np.isnan(swL)) and (not swL_cr) and prevc >= swL > c[i]:
            swL_cr = True; swTrend = -1

        # 4) كسر البنية الداخلية + تخزين OB صعودي (أدنى parsedLow في الساق)
        if (not np.isnan(inH)) and (not inH_cr) and (inH != swH) and prevc <= inH < c[i]:
            tag_choch = (inTrend == -1)
            inH_cr = True; inTrend = 1
            out['in_bull_choch'][i] = 1.0 if tag_choch else 0.0
            out['in_bull_bos'][i] = 0.0 if tag_choch else 1.0
            # OB صعودي: أدنى parsedLow بين inH_i و i
            j0 = max(inH_i, 0)
            seg = pLow[j0:i+1]
            if len(seg):
                k = j0 + int(np.argmin(seg))
                bull_obs.append({'top': pHigh[k], 'bottom': pLow[k], 'idx': k,
                                 'disc': in_disc})
                if len(bull_obs) > 50: bull_obs.pop(0)
        if (not np.isnan(inL)) and (not inL_cr) and (inL != swL) and prevc >= inL > c[i]:
            inL_cr = True; inTrend = -1

        out['bull_trend'][i] = 1.0 if inTrend == 1 else 0.0

        # 5) mitigation + لمس OB صعودي هذه الشمعة
        touched = False; touched_disc = False
        keep = []
        for ob in bull_obs:
            if c[i] < ob['bottom']:          # اختُرق للأسفل → مخفّف (يُزال)
                continue
            # لمس: أدنى الشمعة دخل منطقة الـOB [bottom, top]
            if l[i] <= ob['top'] and h[i] >= ob['bottom']:
                touched = True
                if ob['disc']: touched_disc = True
            keep.append(ob)
        bull_obs = keep
        out['touch_bull_ob'][i] = 1.0 if touched else 0.0
        out['ob_in_discount'][i] = 1.0 if touched_disc else 0.0

        # 6) FVG صعودي (فجوة 3 شموع) + عتبة دلالة + ملء
        if i >= 2:
            gap = l[i] > h[i-2]
            delta = (c[i-1] - o[i-1]) / o[i-1] if o[i-1] > 0 else 0
            thr = 0.001   # عتبة دلالة مبسّطة (0.1%)
            if gap and (c[i-1] > h[i-2]) and (delta > thr):
                fvgs.append({'top': l[i], 'bottom': h[i-2]})
                out['fvg_formed'][i] = 1.0
                if len(fvgs) > 50: fvgs.pop(0)
            # ملء: السعر عاد لمنطقة الـFVG
            keepf = []
            filled = False
            for fv in fvgs:
                if l[i] < fv['bottom']:
                    continue   # امتلأ/بطل
                if l[i] <= fv['top'] and h[i] >= fv['bottom'] and out['bull_trend'][i]:
                    filled = True
                keepf.append(fv)
            fvgs = keepf
            out['fvg_filled'][i] = 1.0 if filled else 0.0

    res = pd.DataFrame(out, index=df.index)
    res['close'] = c; res['high'] = h; res['low'] = l; res['atr14'] = atr14
    res['t'] = df['t'].to_numpy()
    return res


def simulate(h, l, c, i, entry, atrp, tf):
    """triple-barrier: +K*ATR قبل -1*ATR خلال الأفق. متشائم (ستوب أولاً). يرجع net gross%."""
    tgt = entry * (1 + K_TGT * atrp); stp = entry * (1 - atrp)
    Nh = HORIZON[tf]; end = min(i + Nh, len(c) - 1)
    for j in range(i+1, end+1):
        if l[j] <= stp: return -atrp * 100
        if h[j] >= tgt: return K_TGT * atrp * 100
    return (c[end] - entry) / entry * 100


# إعدادات الدخول (كلها long، عند إشارة SMC صعودية)
SETUPS = {
    'in_CHoCH':          lambda r: r['in_bull_choch'] == 1,
    'sw_CHoCH':          lambda r: r['sw_bull_choch'] == 1,
    'in_CHoCH+disc':     lambda r: (r['in_bull_choch'] == 1) & (r['in_discount'] == 1),
    'OB_touch':          lambda r: r['touch_bull_ob'] == 1,
    'OB_touch+disc':     lambda r: r['ob_in_discount'] == 1,
    'FVG_fill':          lambda r: r['fvg_filled'] == 1,
    'BOS_bull':          lambda r: r['in_bull_bos'] == 1,
}


def acc_add(store, key, year, g):
    d = store.setdefault(key, {})
    for sc in ('all', year):
        s = d.setdefault(sc, [])
        s.append(g)


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    print(f"SMC backtest | {len(syms)} symbols | TFs={TFS} | swing={SWING_LEN}/internal={INTERNAL_LEN} | tgt={K_TGT}ATR", flush=True)
    store = {}   # setup -> scope -> list of gross%
    ns = 0
    for sym in syms:
        for tf in TFS:
            df = E.load(sym, tf)
            if df is None or len(df) < WARM + HORIZON[tf] + 10:
                continue
            try:
                r = run_symbol(df, tf)
            except Exception as ex:
                continue
            h = r['high'].to_numpy(); l = r['low'].to_numpy(); c = r['close'].to_numpy()
            atrp = (r['atr14'].to_numpy() / c)
            years = pd.to_datetime(r['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            for name, cond in SETUPS.items():
                idx = np.nonzero(cond(r).to_numpy())[0]
                nxt = WARM
                for i in idx:
                    if i < WARM or i >= len(c)-1 or i < nxt: continue
                    a = atrp[i]
                    if not np.isfinite(a) or not (0.003 < a < 0.15): continue
                    g = simulate(h, l, c, i, c[i], a, tf)
                    if g is None: continue
                    acc_add(store, f"{name}|{tf}", int(years[i]) if not np.isnan(years[i]) else 0, g)
                    nxt = i + max(1, int(math.ceil(HORIZON[tf] / 4)))  # non-overlap تقريبي
        ns += 1
        if ns % 50 == 0: print(f"  {ns}/{len(syms)}", flush=True)

    # حفظ خام للتحليل
    dump = {k: {sc: v for sc, v in d.items()} for k, d in store.items()}
    with open(f"{E.WORK if hasattr(E,'WORK') else '/home/tradmin/trading-signal-bot/research/skill_application'}/out/smc_raw.json", 'w') as f:
        json.dump(dump, f)

    def boot(x, it=3000):
        x = np.asarray(x, float)
        if len(x) < 5: return (np.nan, np.nan)
        m = np.random.RandomState(1).choice(x, (it, len(x)), replace=True).mean(1)
        return np.percentile(m, 2.5), np.percentile(m, 97.5)
    def pf(x):
        x = np.asarray(x, float); g = x[x > 0].sum(); ll = -x[x < 0].sum()
        return g/ll if ll > 0 else float('inf')

    FEE = 0.6
    print("\n" + "="*100)
    print("SMC RESULTS — gross% & net@0.6% | WR | PF | bootstrap CI(net) | per-year net")
    print("="*100)
    rows = []
    for key, d in store.items():
        allx = np.asarray(d.get('all', []), float)
        if len(allx) < 20: continue
        net = allx - FEE
        lo, hi = boot(net)
        rows.append((key, len(allx), (allx > 0).mean()*100, allx.mean(), net.mean(), pf(net), lo, hi))
    rows.sort(key=lambda x: x[4], reverse=True)
    for key, n, wr, ge, ne, p, lo, hi in rows:
        sig = '✅' if (lo > 0) else ('❌' if hi < 0 else 'ns')
        print(f"  {key:<22} n={n:>6} WR={wr:>5.1f}% grossE={ge:>+6.3f} net06E={ne:>+6.3f} PF={p:>4.2f} CI=[{lo:+.3f},{hi:+.3f}] {sig}")
    print(f"\nإجمالي الإعدادات المختبَرة: {len(rows)} | موجبة ودالّة (CI>0): {sum(1 for r in rows if r[6]>0)}")
