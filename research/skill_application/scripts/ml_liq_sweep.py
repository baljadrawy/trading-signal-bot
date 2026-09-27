#!/usr/bin/env python3
"""
التحقق الحاسم: هل تصمد حافة اليومي بعد فلتر السيولة + الانزلاق الواقعي حسب حجم تداول كل عملة؟
مسح: k ∈ {2.0,2.5,3.0} × فلتر سيولة ∈ {all, >$1M, >$5M}، تقييم بكلفة لكل صفقة حسب السيولة.
"""
import sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import ml_walkforward as W
from sklearn.metrics import roc_auc_score

OUT = W.OUT
TF = '1d'

def realistic_cost(dvol):
    """كلفة ذهاب-عودة واقعية (رسوم+انزلاق) حسب حجم التداول اليومي بالدولار."""
    dvol = np.asarray(dvol, float)
    c = np.full(len(dvol), 0.015)               # <100k: 1.5%
    c[dvol >= 1e5] = 0.008                       # 100k-1M: 0.8%
    c[dvol >= 1e6] = 0.004                       # 1M-10M: 0.4%
    c[dvol >= 1e7] = 0.002                       # >10M: 0.2%
    return c

def run(K, liq_min, df0, cols):
    kk = K.replace('.', ''); tgt = f'hit_k{kk}'; retc = f'ret_k{kk}'
    df = df0.dropna(subset=[tgt, retc]).reset_index(drop=True)
    dvol = 10 ** df['log_dvol20'].to_numpy() - 1.0
    df = df[dvol >= liq_min].reset_index(drop=True)
    if len(df) < 30000:
        return f"k={K} liq>={liq_min/1e6:.0f}M: n too small ({len(df)})"
    dvol = 10 ** df['log_dvol20'].to_numpy() - 1.0
    cost = realistic_cost(dvol)
    q01, q99 = df[retc].quantile([0.01, 0.99]); ret = df[retc].clip(q01, q99).to_numpy()
    net = ret - cost                                   # صافٍ بكلفة واقعية لكل صفقة
    years = df['year'].to_numpy()
    oos = np.full(len(df), np.nan)
    for ty in [y for y in sorted(np.unique(years[~np.isnan(years)]).astype(int)) if y >= 2021]:
        tr = df[df.year < ty]; te = df[df.year == ty]
        if len(tr):
            cut = te['t'].min() - W.EMBARGO_DAYS * 86400 * 1000; tr = tr[tr['t'] <= cut]
        if len(tr) < 15000 or len(te) < 300: continue
        m = W.xgb(); m.fit(tr[cols].to_numpy(np.float32), tr[tgt].to_numpy(int))
        oos[te.index.to_numpy()] = m.predict_proba(te[cols].to_numpy(np.float32))[:, 1]
    mask = ~np.isnan(oos)
    p = oos[mask]; nt = net[mask]; yr = years[mask]; hh = df[tgt].to_numpy()[mask]
    try: auc = roc_auc_score(df[tgt].to_numpy()[mask], p)
    except Exception: auc = float('nan')
    thr = np.quantile(p, 0.90); sel = p >= thr
    base = nt.mean() * 100
    line = (f"k={K} liq>={liq_min/1e6:>2.0f}M | n={mask.sum():>6} AUC={auc:.3f} "
            f"base_net={base:+.3f}% | TOP10%: n={sel.sum():>5} "
            f"net/trade={nt[sel].mean()*100:+.3f}% hit={hh[sel].mean()*100:.1f}%")
    # ثبات السنوات الأخيرة
    yrs = []
    for y in (2023, 2024, 2025, 2026):
        m2 = sel & (yr == y)
        if m2.sum() >= 20: yrs.append(f"{y}:{nt[m2].mean()*100:+.2f}%/{m2.sum()}")
    return line + "\n        recent: " + "  ".join(yrs)

if __name__ == "__main__":
    df0 = W.load(TF)                          # يطبّق atr filter
    cols = W.feat_cols(df0); cols = W.add_regime_dummies(df0, cols)
    df0[cols] = df0[cols].replace([np.inf, -np.inf], np.nan)
    out = ["=" * 100, f"LIQUIDITY + REALISTIC-SLIPPAGE SWEEP — {TF} (cost: >10M=0.2% 1-10M=0.4% 100k-1M=0.8% <100k=1.5%)", "=" * 100]
    for K in ('2.0', '2.5', '3.0'):
        for liq in (0.0, 1e6, 5e6):
            r = run(K, liq, df0, cols)
            print(r, flush=True); out.append(r)
        out.append("-" * 100)
    open(f"{OUT}/ml_liq_sweep.txt", "w").write("\n".join(out))
    print(f"\nWROTE {OUT}/ml_liq_sweep.txt")
