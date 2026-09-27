#!/usr/bin/env python3
"""
اختبار «منطقة الطلب كمكان دخول» (فكرة المستخدم) — التجسيد الصحيح لتداول SMC:
  - أمر معلّق (limit) عند قمة الـOB الصعودي (منطقة الطلب) → يملأ حين يعود السعر للمنطقة.
  - ستوب بنيوي ضيّق تحت قاع الـOB (R = قمة−قاع، صغيرة عادةً → R:R عالٍ).
  - أهداف بمضاعفات R (1/2/3/5). فلاتر: الكل / في الخصم / مع اتجاه صعودي داخلي.
مقارنة مع الدخول الساذج (سوق عند اللمس + ATR) الذي اختُبر سابقاً وكان سالباً.
595 رمزاً، 4h+1d، رسوم 0.6%، دلالة bootstrap، ثبات سنوي.
"""
import os, sys, glob, math
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E
import smc_backtest as S
import ta

TFS = ['4h', '1d']
FILL_WINDOW = {'4h': 120, '1d': 60}   # مهلة عودة السعر للمنطقة (شموع)
HOLD = {'4h': 120, '1d': 60}          # أقصى مدة للصفقة
KS = [1.0, 2.0, 3.0, 5.0]
STOP_BUF = 0.001                      # هامش تحت القاع
FEE = 0.6


def bullish_obs(df, tf):
    """يكتشف OBs الصعودية (مناطق الطلب) عبر بنية LuxAlgo الداخلية (size=5). يرجع list of dict."""
    o = df['open'].to_numpy(); h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    n = len(df)
    atr200 = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], 200).average_true_range().to_numpy()
    hv = (h - l) >= 2 * np.nan_to_num(atr200, nan=1e18)
    pHigh = np.where(hv, l, h); pLow = np.where(hv, h, l)
    sb_in, sl_in = S.legs(h, l, S.INTERNAL_LEN)
    inH = np.nan; inH_i = -1; inH_cr = True
    inL = np.nan; inL_i = -1; inL_cr = True
    inTrend = 0
    trail_top = -np.inf; trail_bot = np.inf
    obs = []
    for i in range(n):
        if i - S.INTERNAL_LEN >= 0:
            if sb_in[i]: inH = h[i-S.INTERNAL_LEN]; inH_i = i-S.INTERNAL_LEN; inH_cr = False
            if sl_in[i]: inL = l[i-S.INTERNAL_LEN]; inL_i = i-S.INTERNAL_LEN; inL_cr = False
        if sl_in[i] or sb_in[i]:
            trail_top = h[i]; trail_bot = l[i]
        trail_top = max(trail_top, h[i]); trail_bot = min(trail_bot, l[i])
        rng = trail_top - trail_bot
        in_disc = ((c[i]-trail_bot)/rng if rng > 0 else 0.5) < 0.5
        prevc = c[i-1] if i > 0 else c[i]
        if (not np.isnan(inH)) and (not inH_cr) and prevc <= inH < c[i]:
            inH_cr = True; inTrend = 1
            j0 = max(inH_i, 0); seg = pLow[j0:i+1]
            if len(seg):
                k = j0 + int(np.argmin(seg))
                obs.append({'idx': i, 'top': pHigh[k], 'bottom': pLow[k], 'disc': in_disc, 'trend': 1})
        if (not np.isnan(inL)) and (not inL_cr) and prevc >= inL > c[i]:
            inL_cr = True; inTrend = -1
    return obs, h, l, c


def test_demand(syms):
    # store[(filter,k,tf)] -> list of (net_pct, year, symbol, dvol)
    store = {}
    ns = 0
    for sym in syms:
        for tf in TFS:
            df = E.load(sym, tf)
            if df is None or len(df) < S.WARM + HOLD[tf] + 10: continue
            try:
                obs, h, l, c = bullish_obs(df, tf)
            except Exception:
                continue
            vol = df['volume'].to_numpy()
            dvolm = pd.Series(c*vol).rolling(20).median().to_numpy()
            years = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            for ob in obs:
                f0 = ob['idx']
                if f0 < S.WARM: continue
                entry = ob['top']; stop = ob['bottom'] * (1 - STOP_BUF)
                R = entry - stop
                if R <= 0 or entry <= 0 or R/entry > 0.20: continue   # استبعد OB مشوّه/ضخم
                # ابحث عن أول عودة للمنطقة (low <= entry) خلال المهلة
                fill = -1
                for j in range(f0+1, min(f0+FILL_WINDOW[tf], len(c)-1)):
                    if l[j] <= entry:
                        fill = j; break
                    if l[j] <= stop:   # اخترق قبل الملء → المنطقة بطلت
                        break
                if fill < 0: continue
                # simulate من الملء: أهداف بمضاعفات R، متشائم (ستوب أولاً)
                yr = int(years[fill]) if not np.isnan(years[fill]) else 0
                dv = dvolm[fill] if np.isfinite(dvolm[fill]) else 0.0
                for k in KS:
                    tgt = entry + k*R
                    outcome = None
                    for j in range(fill+1, min(fill+HOLD[tf], len(c))):
                        if l[j] <= stop: outcome = -R/entry*100; break
                        if h[j] >= tgt: outcome = k*R/entry*100; break
                    if outcome is None:
                        outcome = (c[min(fill+HOLD[tf], len(c)-1)] - entry)/entry*100
                    for filt, ok in (('all', True), ('disc', ob['disc']), ('trend', ob['trend'] == 1)):
                        if ok:
                            store.setdefault((filt, k, tf), []).append((outcome, yr, sym, dv))
        ns += 1
        if ns % 100 == 0: print(f"  {ns}/{len(syms)}", flush=True)
    return store


def boot(x, it=3000):
    x = np.asarray(x, float)
    if len(x) < 5: return (np.nan, np.nan)
    m = np.random.RandomState(5).choice(x, (it, len(x)), replace=True).mean(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)
def pf(x):
    x=np.asarray(x,float); g=x[x>0].sum(); ll=-x[x<0].sum(); return g/ll if ll>0 else float('inf')


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{S.DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{S.DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    print(f"Demand-zone entry test | {len(syms)} syms | limit@OBtop, stop@OBbottom, targets={KS}R", flush=True)
    store = test_demand(syms)
    print("\n"+"="*104)
    print("النتائج — دخول limit عند منطقة الطلب + ستوب بنيوي | net@0.6% | WR | PF | CI")
    print("="*104)
    rows = []
    for (filt, k, tf), lst in store.items():
        g = np.array([x[0] for x in lst], float)
        if len(g) < 30: continue
        net = g - FEE; lo, hi = boot(net)
        rows.append((f"{filt}/{k:.0f}R/{tf}", len(g), (g>0).mean()*100, g.mean(), net.mean(), pf(net), lo, hi))
    rows.sort(key=lambda r: r[4], reverse=True)
    for name, n, wr, ge, ne, p, lo, hi in rows:
        sig = '✅' if lo>0 else ('❌' if hi<0 else 'ns')
        print(f"  {name:<16} n={n:>6} WR={wr:>5.1f}% grossE={ge:>+6.3f} net06E={ne:>+6.3f} PF={p:>4.2f} CI=[{lo:+.2f},{hi:+.2f}] {sig}")
    pos = [r for r in rows if r[6] > 0]
    print(f"\nإعدادات موجبة ودالّة (CI>0): {len(pos)}  {[r[0] for r in pos]}")
    # للأفضل: ثبات سنوي + سيولة
    if rows:
        best = rows[0][0]
        fk = best.split('/'); filt = fk[0]; kk = float(fk[1][:-1]); tf = fk[2]
        lst = store[(filt, kk, tf)]
        g = np.array([x[0] for x in lst]); yrs = np.array([x[1] for x in lst]); dv = np.array([x[3] for x in lst])
        print(f"\n■ الأفضل={best} — ثبات سنوي (net@0.6%)")
        for y in sorted(set(yrs)):
            m = yrs==y
            if m.sum()<15: continue
            lo,hi=boot(g[m]-FEE); print(f"   {y}: n={m.sum():>4} net={np.mean(g[m]-FEE):>+.3f} CI=[{lo:+.2f},{hi:+.2f}] {'✅' if lo>0 else ('❌' if hi<0 else 'ns')}")
        print(f"■ الأفضل={best} — سيولة")
        for liq,lbl in ((0,'الكل'),(1e6,'>1M'),(5e6,'>5M')):
            m=dv>=liq
            if m.sum()<20: continue
            lo,hi=boot(g[m]-FEE); print(f"   {lbl:<5} n={m.sum():>5} net={np.mean(g[m]-FEE):>+.3f} CI=[{lo:+.2f},{hi:+.2f}] {'✅' if lo>0 else ('❌' if hi<0 else 'ns')}")
