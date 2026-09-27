#!/usr/bin/env python3
"""تحقق عدائي لحافة 1d k=2.0: تركّز الرموز/الصفقات + متانة السنوات الأخيرة فقط.
يحفظ proba OOS لكل صفقة مع الرمز والسنة، ثم: مساهمة كل رمز، صافي بعد حذف أعلى الرموز/الصفقات."""
import sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import ml_walkforward as W

tf, K = '1d', '2.0'; kk = '20'; tgt = f'hit_k{kk}'; retc = f'ret_k{kk}'
df = W.load(tf)
cols = W.feat_cols(df); cols = W.add_regime_dummies(df, cols)
df = df.dropna(subset=[tgt, retc]).reset_index(drop=True)
df[cols] = df[cols].replace([np.inf, -np.inf], np.nan)
q01, q99 = df[retc].quantile([0.01, 0.99]); df[retc] = df[retc].clip(q01, q99)

oos = np.full(len(df), np.nan)
for ty in [y for y in sorted(df.year.dropna().unique().astype(int)) if y >= 2021]:
    tr = df[df.year < ty]; te = df[df.year == ty]
    if len(tr):
        cut = te['t'].min() - W.EMBARGO_DAYS * 86400 * 1000; tr = tr[tr['t'] <= cut]
    if len(tr) < W.MIN_TRAIN or len(te) < 500: continue
    m = W.xgb(); m.fit(tr[cols].to_numpy(np.float32), tr[tgt].to_numpy(int))
    oos[te.index.to_numpy()] = m.predict_proba(te[cols].to_numpy(np.float32))[:, 1]

mask = ~np.isnan(oos)
sub = df[mask].copy(); sub['proba'] = oos[mask]
sub['net'] = sub[retc] - W.FEE
thr = sub['proba'].quantile(0.90)          # أفضل 10%
sel = sub[sub['proba'] >= thr].copy()
print(f"=== 1d k=2.0 — TOP-10% selected: n={len(sel):,}, distinct symbols={sel.symbol.nunique()} ===")
print(f"pooled net/trade = {sel.net.mean()*100:+.3f}%  total_net(%units)={sel.net.sum()*100:.0f}")

# تركّز الرموز
bysym = sel.groupby('symbol')['net'].agg(['sum', 'count']).sort_values('sum', ascending=False)
tot = sel.net.sum()
print("\n-- top 8 symbols by net contribution --")
print((bysym.head(8) * np.array([100, 1])).round(2).to_string())
for n in (5, 10, 20):
    top = bysym.head(n)['sum'].sum()
    print(f"net excl top-{n} symbols = {(tot-top)*100:.0f} (of {tot*100:.0f}) -> per-trade "
          f"{(sel[~sel.symbol.isin(bysym.head(n).index)].net.mean())*100:+.3f}%")

# تركّز الصفقات: احذف أعلى 1% و5% صفقات ربحاً
s = sel.net.sort_values(ascending=False).to_numpy()
for p in (0.01, 0.05):
    cut = int(len(s) * p)
    print(f"net/trade excl top-{int(p*100)}% trades = {s[cut:].mean()*100:+.3f}%")

# متانة السنوات الأخيرة فقط
print("\n-- recent-only robustness (top-10% selected) --")
for yr in (2024, 2025, 2026):
    y = sel[sel.year == yr]
    if len(y): print(f"  {yr}: n={len(y):,} symbols={y.symbol.nunique()} net/trade={y.net.mean()*100:+.3f}% hit={ (y[tgt].mean()*100):.1f}%")
# توزيع: كم رمزاً موجب الصافي؟
pos = (bysym['sum'] > 0).mean() * 100
print(f"\nshare of selected symbols with POSITIVE net = {pos:.0f}% (n_symbols={len(bysym)})")
