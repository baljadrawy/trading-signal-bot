#!/usr/bin/env python3
"""
«ادخل عند الطلب، اخرج عند العرض» — التجسيد الأوفى لـSMC (فكرة المستخدم).
- كشف مناطق الطلب (bullish OB) والعرض (bearish OB) معاً عبر بنية LuxAlgo الداخلية + mitigation.
- دخول limit عند قمة منطقة الطلب؛ ستوب تحت قاعها (بنيوي)؛
- الهدف = قاع أقرب منطقة عرض (bearish OB) غير مخترقة فوق الدخول (لا مضاعف R ثابت).
- التقييم: WR، R:R ضمنية، net@0.6%، دلالة، + تدقيق (تركّز/سنوات/سيولة واقعية).
595 رمزاً، 4h+1d.
"""
import os, sys, glob, math
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E
import smc_backtest as S
import ta

TFS = ['4h', '1d']
FILL_WINDOW = {'4h': 120, '1d': 60}
HOLD = {'4h': 120, '1d': 60}
STOP_BUF = 0.001
MAX_TGT = 0.35     # أقصى بُعد للهدف (35%) — نتجاهل مناطق عرض بعيدة جداً
FEE = 0.6


def zones(df, tf):
    """يكتشف مناطق الطلب (bull OB) والعرض (bear OB) مع أزمنة التكوين والتخفيف."""
    o = df['open'].to_numpy(); h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    n = len(df)
    atr200 = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], 200).average_true_range().to_numpy()
    hv = (h - l) >= 2 * np.nan_to_num(atr200, nan=1e18)
    pHigh = np.where(hv, l, h); pLow = np.where(hv, h, l)
    sb_in, sl_in = S.legs(h, l, S.INTERNAL_LEN)
    inH = np.nan; inH_i = -1; inH_cr = True
    inL = np.nan; inL_i = -1; inL_cr = True
    trail_top = -np.inf; trail_bot = np.inf
    demand = []   # {idx, top, bottom, disc}
    supply = []   # {idx, top, bottom}
    for i in range(n):
        if i - S.INTERNAL_LEN >= 0:
            if sb_in[i]: inH = h[i-S.INTERNAL_LEN]; inH_i = i-S.INTERNAL_LEN; inH_cr = False
            if sl_in[i]: inL = l[i-S.INTERNAL_LEN]; inL_i = i-S.INTERNAL_LEN; inL_cr = False
        if sl_in[i] or sb_in[i]: trail_top = h[i]; trail_bot = l[i]
        trail_top = max(trail_top, h[i]); trail_bot = min(trail_bot, l[i])
        rng = trail_top - trail_bot
        in_disc = ((c[i]-trail_bot)/rng if rng > 0 else 0.5) < 0.5
        prevc = c[i-1] if i > 0 else c[i]
        # كسر صعودي → منطقة طلب (أدنى parsedLow في الساق)
        if (not np.isnan(inH)) and (not inH_cr) and prevc <= inH < c[i]:
            inH_cr = True
            j0 = max(inH_i, 0); seg = pLow[j0:i+1]
            if len(seg):
                k = j0 + int(np.argmin(seg))
                demand.append({'idx': i, 'top': pHigh[k], 'bottom': pLow[k], 'disc': in_disc})
        # كسر هبوطي → منطقة عرض (أعلى parsedHigh في الساق)
        if (not np.isnan(inL)) and (not inL_cr) and prevc >= inL > c[i]:
            inL_cr = True
            j0 = max(inL_i, 0); seg = pHigh[j0:i+1]
            if len(seg):
                k = j0 + int(np.argmax(seg))
                supply.append({'idx': i, 'top': pHigh[k], 'bottom': pLow[k]})
    # زمن تخفيف كل منطقة عرض (أول إغلاق فوق قمتها)
    for sup in supply:
        sup['mitig'] = len(c)
        for j in range(sup['idx']+1, len(c)):
            if c[j] > sup['top']: sup['mitig'] = j; break
    return demand, supply, h, l, c


def run(syms):
    recs = []   # (outcome%, year, symbol, dvol, rr, filt_disc)
    ns = 0
    for sym in syms:
        for tf in TFS:
            df = E.load(sym, tf)
            if df is None or len(df) < S.WARM + HOLD[tf] + 10: continue
            try:
                demand, supply, h, l, c = zones(df, tf)
            except Exception:
                continue
            vol = df['volume'].to_numpy(); dvolm = pd.Series(c*vol).rolling(20).median().to_numpy()
            years = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            sup_idx = np.array([s['idx'] for s in supply]); sup_bot = np.array([s['bottom'] for s in supply])
            sup_mit = np.array([s['mitig'] for s in supply])
            for ob in demand:
                f0 = ob['idx']
                if f0 < S.WARM: continue
                entry = ob['top']; stop = ob['bottom']*(1-STOP_BUF); Rr = entry-stop
                if Rr <= 0 or entry <= 0 or Rr/entry > 0.20: continue
                fill = -1
                for j in range(f0+1, min(f0+FILL_WINDOW[tf], len(c)-1)):
                    if l[j] <= entry: fill = j; break
                    if l[j] <= stop: break
                if fill < 0: continue
                # أقرب منطقة عرض غير مخترقة فوق الدخول كما في وقت الملء
                if len(supply):
                    valid = (sup_idx < fill) & (sup_mit > fill) & (sup_bot > entry) & (sup_bot < entry*(1+MAX_TGT))
                    if not valid.any(): continue
                    tgt = sup_bot[valid].min()
                else:
                    continue
                rr = (tgt-entry)/Rr
                out = None
                for j in range(fill+1, min(fill+HOLD[tf], len(c))):
                    if l[j] <= stop: out = -Rr/entry*100; break
                    if h[j] >= tgt: out = (tgt-entry)/entry*100; break
                if out is None: out = (c[min(fill+HOLD[tf], len(c)-1)]-entry)/entry*100
                yr = int(years[fill]) if not np.isnan(years[fill]) else 0
                dv = dvolm[fill] if np.isfinite(dvolm[fill]) else 0.0
                recs.append((out, yr, sym, dv, rr, ob['disc'], tf))
        ns += 1
        if ns % 100 == 0: print(f"  {ns}/{len(syms)}", flush=True)
    return pd.DataFrame(recs, columns=['g', 'year', 'symbol', 'dvol', 'rr', 'disc', 'tf'])


def boot(x, it=4000):
    x = np.asarray(x, float)
    if len(x) < 5: return (np.nan, np.nan)
    m = np.random.RandomState(13).choice(x, (it, len(x)), replace=True).mean(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)
def pf(x): x=np.asarray(x,float); g=x[x>0].sum(); ll=-x[x<0].sum(); return g/ll if ll>0 else float('inf')


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{S.DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{S.DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    print(f"Demand→Supply | {len(syms)} syms | entry=OB.top, stop=OB.bottom, target=أقرب عرض", flush=True)
    d = run(syms)
    print(f"\n{'='*96}\nإجمالي: n={len(d)} | R:R ضمنية وسيطة={d['rr'].median():.2f} | WR={ (d['g']>0).mean()*100:.1f}%\n{'='*96}")
    for tf in TFS + ['كل']:
        sub = d if tf == 'كل' else d[d.tf == tf]
        if len(sub) < 30: continue
        for lbl, s2 in (('all', sub), ('disc', sub[sub.disc])):
            g = s2['g'].to_numpy(); net = g - FEE; lo, hi = boot(net)
            sig = '✅' if lo>0 else ('❌' if hi<0 else 'ns')
            print(f"  {lbl}/{tf:<4} n={len(s2):>6} WR={(g>0).mean()*100:>5.1f}% RR={s2['rr'].median():>4.2f} net06E={net.mean():>+6.3f} PF={pf(net):>4.2f} CI=[{lo:+.2f},{hi:+.2f}] {sig}")
    # تدقيق للأفضل (all/1d)
    best = d[d.tf == '1d']
    if len(best) > 50:
        g = best['g'].to_numpy(); net = g - FEE
        print(f"\n■ تدقيق all/1d (n={len(best)}):")
        s = np.sort(net)[::-1]
        print(f"  تركّز: net={net.mean():+.3f} | حذف أعلى1%={s[max(1,len(s)//100):].mean():+.3f} | أعلى5%={s[max(1,len(s)//20):].mean():+.3f} | أعلى10%={s[max(1,len(s)//10):].mean():+.3f}")
        print("  سنوياً: " + "  ".join(f"{y}:{net[best.year.to_numpy()==y].mean():+.2f}(n{(best.year.to_numpy()==y).sum()})" for y in sorted(best.year.unique()) if (best.year.to_numpy()==y).sum()>=20))
        dv = best['dvol'].to_numpy(); cost = np.where(dv>=1e7,0.2,np.where(dv>=1e6,0.4,np.where(dv>=1e5,0.8,1.5)))
        print("  سيولة واقعية: " + "  ".join(f"{lbl}={ (g[dv>=liq]-cost[dv>=liq]).mean():+.2f}({'✅' if boot(g[dv>=liq]-cost[dv>=liq])[0]>0 else 'ns'},n{(dv>=liq).sum()})" for liq,lbl in ((0,'الكل'),(1e6,'>1M'),(5e6,'>5M')) if (dv>=liq).sum()>=30))
