#!/usr/bin/env python3
"""
دراسة فضاء الخروج لدخول مناطق الطلب (الدخول ثابت، نتعلّم الخروج).
الدخول = limit عند قمة منطقة الطلب، ستوب أوّلي تحت قاعها. على 9 سنوات / 595 رمزاً.
نُقيّم لكل صفقة عدّة سياسات خروج من نافذة السعر الأمامية، ثم نُدقّق كلّاً (تركّز/سنوات/سيولة).
الهدف: هل توجد سياسة خروج تجعل دخول الطلب رابحاً صافياً وصامداً (ليس ذيولاً)؟
"""
import os, sys, glob, math
import numpy as np, pandas as pd
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E
import smc_backtest as S
import smc_demand_supply as DS
import ta

TFS = ['4h', '1d']
FW = {'4h': 120, '1d': 60}
HOLD = {'4h': 160, '1d': 80}
FEE = 0.6
STOP_BUF = 0.001


def eval_exits(entry, S0, atrp, hh, ll, cc, sup_tgt, swinglows):
    """يرجع dict{policy: net_ret%} من نافذة السعر الأمامية. متشائم (ستوب قبل هدف داخل الشمعة)."""
    R = entry - S0
    a = atrp * entry                     # ATR بالسعر عند الدخول
    n = len(cc)
    out = {}

    def run_fixed(k):
        tgt = entry + k * R
        for j in range(n):
            if ll[j] <= S0: return -R / entry * 100
            if hh[j] >= tgt: return k * R / entry * 100
        return (cc[-1] - entry) / entry * 100
    for k in (1, 2, 3, 5):
        out[f'fix{k}R'] = run_fixed(k)

    # عرض (أقرب منطقة عرض)
    if sup_tgt and sup_tgt > entry:
        for j in range(n):
            if ll[j] <= S0: out['supply'] = -R / entry * 100; break
            if hh[j] >= sup_tgt: out['supply'] = (sup_tgt - entry) / entry * 100; break
        else:
            out['supply'] = (cc[-1] - entry) / entry * 100
    else:
        out['supply'] = np.nan

    # ATR-trailing (يترك الرابح يركض، الستوب يتبع القمة)
    def run_trail(m, after_1r=False):
        peak = entry; stop = S0; armed = not after_1r
        for j in range(n):
            if hh[j] > peak: peak = hh[j]
            if after_1r and not armed and hh[j] >= entry + R:
                armed = True; stop = max(stop, entry)          # break-even عند 1R
            if armed:
                stop = max(stop, peak - m * a)
            if ll[j] <= stop:
                return (stop - entry) / entry * 100
        return (cc[-1] - entry) / entry * 100
    for m in (1.5, 2.5):
        out[f'trail{m}'] = run_trail(m, after_1r=False)
        out[f'be+trail{m}'] = run_trail(m, after_1r=True)

    # جني جزئي: 50% عند 1R + 50% trailing(2.5) للباقي
    def run_partial(k1=1.0, m=2.5):
        banked = None; peak = entry; stop = S0; rest = None
        for j in range(n):
            if hh[j] > peak: peak = hh[j]
            if banked is None:
                if ll[j] <= S0: return -R / entry * 100          # قبل جني أي شيء
                if hh[j] >= entry + k1 * R:
                    banked = k1 * R / entry * 100; stop = entry   # BE للباقي
                    continue
            else:
                stop = max(stop, peak - m * a)
                if ll[j] <= stop:
                    rest = (stop - entry) / entry * 100; break
        if banked is None: banked = (cc[-1] - entry) / entry * 100; return banked
        if rest is None: rest = (cc[-1] - entry) / entry * 100
        return 0.5 * banked + 0.5 * rest
    out['partial'] = run_partial()

    # خروج هيكلي: الستوب يتبع أدنى قاع داخلي مؤكَّد
    def run_struct():
        stop = S0
        for j in range(n):
            if not np.isnan(swinglows[j]) and swinglows[j] > stop and swinglows[j] < cc[j]:
                stop = swinglows[j] * (1 - STOP_BUF)
            if ll[j] <= stop:
                return (stop - entry) / entry * 100
        return (cc[-1] - entry) / entry * 100
    out['struct'] = run_struct()

    # زمني
    for N in (20, 60):
        end = min(N, n) - 1
        stopped = False
        for j in range(end + 1):
            if ll[j] <= S0: out[f'time{N}'] = -R / entry * 100; stopped = True; break
        if not stopped:
            out[f'time{N}'] = (cc[end] - entry) / entry * 100
    return out


def build(syms):
    recs = []   # (policy, net%, year, symbol, dvol, tf)
    ns = 0
    for sym in syms:
        for tf in TFS:
            df = E.load(sym, tf)
            if df is None or len(df) < S.WARM + HOLD[tf] + 10: continue
            try:
                demand, supply, h, l, c = DS.zones(df, tf)
            except Exception:
                continue
            atr14 = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], 14).average_true_range().to_numpy()
            atrp_arr = atr14 / c
            vol = df['volume'].to_numpy(); dvolm = pd.Series(c*vol).rolling(20).median().to_numpy()
            years = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            # أدنى قاع داخلي مؤكَّد لكل شمعة (للخروج الهيكلي)
            _, sl_in = S.legs(h, l, S.INTERNAL_LEN)
            cur_lo = np.nan; swlo = np.full(len(c), np.nan)
            for i in range(len(c)):
                if i - S.INTERNAL_LEN >= 0 and sl_in[i]: cur_lo = l[i-S.INTERNAL_LEN]
                swlo[i] = cur_lo
            sup_idx = np.array([s['idx'] for s in supply]); sup_bot = np.array([s['bottom'] for s in supply]); sup_mit = np.array([s['mitig'] for s in supply])
            for ob in demand:
                f0 = ob['idx']
                if f0 < S.WARM: continue
                entry = ob['top']; S0 = ob['bottom']*(1-STOP_BUF); R = entry-S0
                if R <= 0 or entry <= 0 or R/entry > 0.20: continue
                fill = -1
                for j in range(f0+1, min(f0+FW[tf], len(c)-1)):
                    if l[j] <= entry: fill = j; break
                    if l[j] <= S0: break
                if fill < 0: continue
                end = min(fill+HOLD[tf], len(c))
                hh = h[fill+1:end]; ll = l[fill+1:end]; cc = c[fill+1:end]; sw = swlo[fill+1:end]
                if len(cc) < 3: continue
                sup_tgt = np.nan
                if len(supply):
                    v = (sup_idx < fill) & (sup_mit > fill) & (sup_bot > entry) & (sup_bot < entry*1.35)
                    if v.any(): sup_tgt = sup_bot[v].min()
                res = eval_exits(entry, S0, atrp_arr[fill], hh, ll, cc, sup_tgt, sw)
                yr = int(years[fill]) if not np.isnan(years[fill]) else 0
                dv = dvolm[fill] if np.isfinite(dvolm[fill]) else 0.0
                for pol, r in res.items():
                    if np.isfinite(r): recs.append((pol, r, yr, sym, dv, tf))
        ns += 1
        if ns % 100 == 0: print(f"  {ns}/{len(syms)}", flush=True)
    return pd.DataFrame(recs, columns=['pol', 'g', 'year', 'symbol', 'dvol', 'tf'])


def boot(x, it=3000):
    x = np.asarray(x, float)
    if len(x) < 5: return (np.nan, np.nan)
    m = np.random.RandomState(17).choice(x, (it, len(x)), replace=True).mean(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{S.DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{S.DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    print(f"Exit study on demand entries | {len(syms)} syms | policies=fix/supply/trail/be+trail/partial/struct/time", flush=True)
    d = build(syms)
    d.to_parquet('/home/tradmin/trading-signal-bot/research/skill_application/out/smc_exit.parquet')
    for tf in ['1d', '4h']:
        sub = d[d.tf == tf]
        print("\n" + "="*104)
        print(f"■ إطار {tf} — سياسات الخروج (net@0.6%, تركّز, سنوات أخيرة, سيولة) | مرتّبة بالصمود")
        print("="*104)
        rows = []
        for pol in sub['pol'].unique():
            g = sub[sub.pol == pol]['g'].to_numpy()
            if len(g) < 50: continue
            net = g - FEE; lo, hi = boot(net)
            s = np.sort(net)[::-1]; ex5 = s[max(1, len(s)//20):].mean()
            yy = sub[sub.pol == pol]
            rec_net = yy[yy.year >= 2024]['g']; rec = (rec_net.mean()-FEE) if len(rec_net) > 30 else np.nan
            dv = yy['dvol'].to_numpy(); liq = g[dv >= 5e6] - FEE; liqm = liq.mean() if len(liq) > 30 else np.nan
            rows.append((pol, len(g), (g > 0).mean()*100, net.mean(), lo, hi, ex5, rec, liqm))
        # صمود = موجب دالّ AND excl-top5%>0 AND recent>0 AND liquid>0
        def robust(r): return r[4] > 0 and r[6] > 0 and (np.isnan(r[7]) or r[7] > 0) and (np.isnan(r[8]) or r[8] > 0)
        rows.sort(key=lambda r: (robust(r), r[3]), reverse=True)
        print(f"  {'policy':<12}{'n':>7}{'WR%':>6}{'net06':>8}{'CIlo':>8}{'exTop5':>8}{'2024+':>8}{'>5M':>8}  صمود")
        for pol, n, wr, ne, lo, hi, ex5, rec, liqm in rows:
            rob = '✅ROBUST' if robust((pol,n,wr,ne,lo,hi,ex5,rec,liqm)) else ('sig' if lo > 0 else '')
            print(f"  {pol:<12}{n:>7}{wr:>6.1f}{ne:>+8.3f}{lo:>+8.3f}{ex5:>+8.3f}{rec:>+8.3f}{liqm:>+8.3f}  {rob}")
