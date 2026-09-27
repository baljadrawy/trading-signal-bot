#!/usr/bin/env python3
"""تدقيق عدائي حاسم لحافة «دخول منطقة الطلب» — التركّز (ذيول سمينة؟) + السنوات الأخيرة + السيولة الواقعية.
يركّز على 1d (الأقوى) ويلتقط كل صفقة: العائد، السنة، الرمز، حجم الدولار، لأهداف 2R/3R/5R."""
import os, sys, glob, math
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E
import smc_backtest as S
import smc_demand_entry as D

TF = '1d'; FW = D.FILL_WINDOW[TF]; HOLD = D.HOLD[TF]; FEE = 0.6
KS = [2.0, 3.0, 5.0]


def realistic_cost(dvol):
    dvol = np.asarray(dvol, float); c = np.full(len(dvol), 1.5)
    c[dvol >= 1e5] = 0.8; c[dvol >= 1e6] = 0.4; c[dvol >= 1e7] = 0.2
    return c   # % round-trip


def boot(x, it=4000):
    x = np.asarray(x, float)
    if len(x) < 5: return (np.nan, np.nan)
    m = np.random.RandomState(11).choice(x, (it, len(x)), replace=True).mean(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{S.DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{S.DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    recs = {k: [] for k in KS}   # k -> list(outcome, year, symbol, dvol)
    ns = 0
    for sym in syms:
        df = E.load(sym, TF)
        if df is None or len(df) < S.WARM + HOLD + 10: continue
        try:
            obs, h, l, c = D.bullish_obs(df, TF)
        except Exception:
            continue
        vol = df['volume'].to_numpy(); dvolm = pd.Series(c*vol).rolling(20).median().to_numpy()
        years = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
        for ob in obs:
            f0 = ob['idx']
            if f0 < S.WARM: continue
            entry = ob['top']; stop = ob['bottom']*(1-D.STOP_BUF); R = entry-stop
            if R <= 0 or entry <= 0 or R/entry > 0.20: continue
            fill = -1
            for j in range(f0+1, min(f0+FW, len(c)-1)):
                if l[j] <= entry: fill = j; break
                if l[j] <= stop: break
            if fill < 0: continue
            yr = int(years[fill]) if not np.isnan(years[fill]) else 0
            dv = dvolm[fill] if np.isfinite(dvolm[fill]) else 0.0
            for k in KS:
                tgt = entry + k*R; out = None
                for j in range(fill+1, min(fill+HOLD, len(c))):
                    if l[j] <= stop: out = -R/entry*100; break
                    if h[j] >= tgt: out = k*R/entry*100; break
                if out is None: out = (c[min(fill+HOLD, len(c)-1)]-entry)/entry*100
                recs[k].append((out, yr, sym, dv))
        ns += 1
        if ns % 100 == 0: print(f"  {ns}/{len(syms)}", flush=True)

    for k in KS:
        d = pd.DataFrame(recs[k], columns=['g', 'year', 'symbol', 'dvol'])
        g = d['g'].to_numpy(); net = g - FEE
        print("\n" + "="*96)
        print(f"■ all/{k:.0f}R/1d | n={len(d)} | WR={ (g>0).mean()*100:.1f}% | net06E={net.mean():+.3f} PF={ (net[net>0].sum()/max(1e-9,-net[net<0].sum())):.2f}")
        print("="*96)
        # تركّز: حذف أعلى الصفقات
        s = np.sort(net)[::-1]
        print(f"  تركّز: net/صفقة={net.mean():+.3f} | حذف أعلى1%={s[max(1,len(s)//100):].mean():+.3f} | "
              f"أعلى5%={s[max(1,len(s)//20):].mean():+.3f} | أعلى10%={s[max(1,len(s)//10):].mean():+.3f}")
        pos_sym = (d.groupby('symbol')['g'].mean() > FEE).mean()*100
        print(f"  نسبة الرموز الموجبة (net): {pos_sym:.0f}% من {d.symbol.nunique()}")
        # السنوات (net@0.6%)
        cells = []
        for y in sorted(d.year.unique()):
            m = d.year.to_numpy() == y
            if m.sum() < 20: continue
            lo, hi = boot(net[m]); cells.append(f"{y}:{net[m].mean():+.2f}({'✅' if lo>0 else '❌' if hi<0 else 'ns'},n{m.sum()})")
        print("  سنوياً net@0.6%: " + "  ".join(cells))
        # سيولة واقعية
        dv = d['dvol'].to_numpy(); cost = realistic_cost(dv)
        print("  سيولة (كلفة واقعية):", end=" ")
        for liq, lbl in ((0, 'الكل'), (1e6, '>1M'), (5e6, '>5M'), (1e7, '>10M')):
            m = dv >= liq
            if m.sum() < 30: continue
            nr = g[m] - cost[m]; lo, hi = boot(nr)
            print(f"{lbl}={nr.mean():+.2f}({'✅' if lo>0 else '❌' if hi<0 else 'ns'},n{m.sum()})", end="  ")
        print()
