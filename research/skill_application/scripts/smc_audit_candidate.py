#!/usr/bin/env python3
"""
تدقيق عدائي للخيط الوحيد الواعد: SMC 'CHoCH داخلي صعودي + خصم' على اليومي.
نفس منهج تدقيق حافة ML: فلتر سيولة + انزلاق واقعي لكل عملة + ثبات per-year + تركّز الرموز.
يُعيد استخدام محرّك smc_backtest.run_symbol لكن يسجّل لكل صفقة: العائد، السنة، الرمز، حجم الدولار.
"""
import os, sys, glob, math
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E
import smc_backtest as S

TF = '1d'; H = S.HORIZON[TF]; K = S.K_TGT


def realistic_cost(dvol):
    dvol = np.asarray(dvol, float)
    c = np.full(len(dvol), 0.015)      # <100k
    c[dvol >= 1e5] = 0.008
    c[dvol >= 1e6] = 0.004
    c[dvol >= 1e7] = 0.002
    return c


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{S.DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{S.DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    rows = []
    ns = 0
    for sym in syms:
        df = E.load(sym, TF)
        if df is None or len(df) < S.WARM + H + 10:
            continue
        try:
            r = S.run_symbol(df, TF)
        except Exception:
            continue
        h = r['high'].to_numpy(); l = r['low'].to_numpy(); c = r['close'].to_numpy()
        atrp = r['atr14'].to_numpy() / c
        vol = df['volume'].to_numpy()
        dvol_med = pd.Series(c * vol).rolling(20).median().to_numpy()   # $-volume وسيط 20 يوم
        years = pd.to_datetime(r['t'], unit='ms', errors='coerce').dt.year.to_numpy()
        cond = (r['in_bull_choch'] == 1) & (r['in_discount'] == 1)      # الخيط الواعد
        idx = np.nonzero(cond.to_numpy())[0]
        nxt = S.WARM
        for i in idx:
            if i < S.WARM or i >= len(c)-1 or i < nxt: continue
            a = atrp[i]
            if not np.isfinite(a) or not (0.003 < a < 0.15): continue
            g = S.simulate(h, l, c, i, c[i], a, TF)
            if g is None: continue
            rows.append((sym, int(years[i]) if not np.isnan(years[i]) else 0, g,
                         dvol_med[i] if np.isfinite(dvol_med[i]) else 0.0))
            nxt = i + max(1, int(math.ceil(H/4)))
        ns += 1
        if ns % 100 == 0: print(f"  {ns}/{len(syms)}", flush=True)

    d = pd.DataFrame(rows, columns=['symbol', 'year', 'gross', 'dvol'])
    print(f"\n{'='*96}\nتدقيق CHoCH+خصم يومي | n={len(d)} | {d.year.min()}–{d.year.max()}\n{'='*96}")

    def boot(x, it=4000):
        x = np.asarray(x, float)
        if len(x) < 5: return (np.nan, np.nan)
        m = np.random.RandomState(3).choice(x, (it, len(x)), replace=True).mean(1)
        return np.percentile(m, 2.5), np.percentile(m, 97.5)

    # 1) بفلتر السيولة + انزلاق واقعي لكل عملة
    print("\n■ بفلتر السيولة + انزلاق واقعي (كلفة حسب حجم كل عملة)")
    dvol = d['dvol'].to_numpy(); cost = realistic_cost(dvol) * 100  # %
    for liq, lbl in ((0, 'الكل'), (1e6, '>$1M'), (5e6, '>$5M'), (1e7, '>$10M')):
        m = dvol >= liq
        if m.sum() < 20:
            print(f"  {lbl:<8} n={m.sum()} (قليلة)"); continue
        net = d['gross'].to_numpy()[m] - cost[m]
        lo, hi = boot(net)
        sig = '✅' if lo > 0 else ('❌' if hi < 0 else 'ns')
        print(f"  {lbl:<8} n={m.sum():>5}  grossE={d['gross'].to_numpy()[m].mean():>+.3f}  net_realE={net.mean():>+.3f}  CI=[{lo:+.3f},{hi:+.3f}] {sig}")

    # 2) ثبات per-year (net واقعي، كل العملات)
    print("\n■ الثبات السنوي (net واقعي)")
    net_all = d['gross'].to_numpy() - cost
    for y in sorted(d.year.unique()):
        m = d.year.to_numpy() == y
        if m.sum() < 15:
            print(f"  {y}: n={m.sum()} (قليلة)"); continue
        lo, hi = boot(net_all[m])
        print(f"  {y}: n={m.sum():>4} net_realE={net_all[m].mean():>+.3f} CI=[{lo:+.2f},{hi:+.2f}] {'✅' if lo>0 else ('❌' if hi<0 else 'ns')}")

    # 3) تركّز الرموز (net@0.6% ثابت للمقارنة)
    print("\n■ تركّز الرموز (net@0.6%)")
    d['net06'] = d['gross'] - 0.6
    tot = d['net06'].sum()
    by = d.groupby('symbol')['net06'].sum().sort_values(ascending=False)
    print(f"  إجمالي net06={tot:+.1f} (n_symbols={d.symbol.nunique()}) | حذف أعلى5 رموز → {tot - by.head(5).sum():+.1f}")
    print(f"  نسبة الرموز الموجبة: {(by>0).mean()*100:.0f}%")
    # حذف أعلى 5% صفقات
    s = np.sort(d['net06'].to_numpy())[::-1]
    print(f"  net06/صفقة={d['net06'].mean():+.3f} | حذف أعلى1%: {np.sort(d['net06'])[:-max(1,len(d)//100)].mean():+.3f} | أعلى5%: {np.sort(d['net06'])[:-max(1,len(d)//20)].mean():+.3f}")
