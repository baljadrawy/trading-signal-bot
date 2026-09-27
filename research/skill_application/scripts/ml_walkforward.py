#!/usr/bin/env python3
"""
ML walk-forward على بيانات ml_dataset.parquet — falsify-first.
الهدف: هل يستطيع XGBoost (يدمج كل المؤشرات) اختيار مجموعة فرعية تتفوّق على معدّل الأساس
       وتكون رابحة صافياً OOS عبر السنوات؟
- تصنيف: hit_k{K} (يصل +k·ATR قبل -1·ATR).
- walk-forward موسّع بالسنة + embargo زمني (منع تسرّب نافذة التسمية).
- اختيار العتبة على التدريب فقط؛ تقييم OOS بالعائد الصافي بعد الرسوم.
- ضوابط: shuffle (يجب ≈صفر حافة)، ثبات عبر السنوات، SHAP لأهم الميزات.
الاستخدام: python ml_walkforward.py <tf=4h|1d> <k=1.5> [shuffle]
"""
import os, sys, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
OUT = f"{ROOT}/out"
FEE = 0.006           # round-trip 0.6% (واقعي شامل الانزلاق)
EMBARGO_DAYS = 40     # يغطّي أفق 1d(30 يوم) و4h(10 أيام) بهامش
MIN_TRAIN = 20000

META = {'symbol', 'tf', 't', 'year', 'regime'}

def load(tf):
    df = pd.read_parquet(f"{OUT}/ml_dataset.parquet")
    df = df[df.tf == tf].copy()
    # فلترة صفقات ATR المتطرّفة (بيانات غير قابلة للتنفيذ واقعياً: قفزات إدراج/شموع شاذة)
    n0 = len(df)
    df = df[(df['atr_pct'] > 0.003) & (df['atr_pct'] < 0.15)]
    print(f"[atr filter] dropped {n0-len(df):,}/{n0:,} rows with atr_pct outside (0.3%,15%)")
    df['dt'] = pd.to_datetime(df['t'], unit='ms', errors='coerce')
    df = df.sort_values('t').reset_index(drop=True)
    return df

def feat_cols(df):
    cols = [c for c in df.columns if c not in META and c != 'dt'
            and not c.startswith(('hit_', 'dir_', 'ret_', 'bars_'))]
    return cols

def add_regime_dummies(df, cols):
    d = pd.get_dummies(df['regime'], prefix='reg')
    for c in d.columns:
        df[c] = d[c].astype(float)
    return cols + list(d.columns)

def xgb():
    return XGBClassifier(
        n_estimators=350, max_depth=4, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
        reg_lambda=2.0, reg_alpha=0.5, eval_metric='logloss',
        tree_method='hist', n_jobs=8, random_state=42)

def pf(net):
    g = net[net > 0].sum(); l = -net[net < 0].sum()
    return g / l if l > 0 else float('inf')

def evaluate(proba, ret, hit, thr):
    sel = proba >= thr
    if sel.sum() == 0: return None
    net = ret[sel] - FEE
    return {'n': int(sel.sum()), 'frac': float(sel.mean()),
            'hit': float(hit[sel].mean() * 100), 'exp_net': float(net.mean() * 100),
            'pf': float(pf(net)), 'thr': float(thr)}

def best_threshold(proba, ret, grid=None):
    """عتبة تُعظّم التوقّع الصافي على التدريب (بحد أدنى 3% من العينة)."""
    if grid is None: grid = np.quantile(proba, np.arange(0.50, 0.96, 0.05))
    best = (0.5, -9e9)
    for t in grid:
        sel = proba >= t
        if sel.mean() < 0.03: continue
        e = (ret[sel] - FEE).mean()
        if e > best[1]: best = (t, e)
    return best[0]

def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else '4h'
    K = sys.argv[2] if len(sys.argv) > 2 else '1.5'
    shuffle = 'shuffle' in sys.argv
    kk = K.replace('.', '')
    tgt = f'hit_k{kk}'; retc = f'ret_k{kk}'
    df = load(tf)
    cols = feat_cols(df)
    cols = add_regime_dummies(df, cols)
    df = df.dropna(subset=[tgt, retc]).reset_index(drop=True)
    # نظّف ميزات لا نهائية
    df[cols] = df[cols].replace([np.inf, -np.inf], np.nan)
    # winsorize العائد (يمنع هيمنة ذيول متطرّفة على التوقّع) — قصّ عند 1/99 بالمئة
    q01, q99 = df[retc].quantile([0.01, 0.99])
    df[retc] = df[retc].clip(q01, q99)
    print(f"[winsorize] {retc} clipped to [{q01*100:+.1f}%, {q99*100:+.1f}%]")

    years = sorted(df['year'].dropna().unique().astype(int))
    test_years = [y for y in years if y >= 2021]
    out = []
    out.append(f"{'='*100}")
    out.append(f"ML WALK-FORWARD — tf={tf} target={tgt} (reach +{K}*ATR before -1*ATR) "
               f"fee={FEE*100:.1f}% {'[SHUFFLE CONTROL]' if shuffle else ''}")
    out.append(f"rows={len(df):,} features={len(cols)} base_hit={df[tgt].mean()*100:.1f}% "
               f"base_net_exp={(df[retc].mean()-FEE)*100:+.3f}%")
    out.append(f"{'='*100}")
    oos_proba = np.full(len(df), np.nan); oos_idx = []
    rng = np.random.RandomState(7)
    per_year = []
    for ty in test_years:
        tr = df[df['year'] < ty]
        te = df[df['year'] == ty]
        # embargo: احذف آخر EMBARGO_DAYS من التدريب
        if len(tr):
            cut = te['t'].min() - EMBARGO_DAYS * 86400 * 1000
            tr = tr[tr['t'] <= cut]
        if len(tr) < MIN_TRAIN or len(te) < 500:
            continue
        Xtr = tr[cols].to_numpy(np.float32); ytr = tr[tgt].to_numpy(int)
        Xte = te[cols].to_numpy(np.float32); yte = te[tgt].to_numpy(int)
        if shuffle:
            ytr = rng.permutation(ytr)
        m = xgb(); m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        oos_proba[te.index.to_numpy()] = p
        try: auc = roc_auc_score(yte, p)
        except Exception: auc = float('nan')
        # عتبة من التدريب
        ptr = m.predict_proba(Xtr)[:, 1]
        thr = best_threshold(ptr, tr[retc].to_numpy())
        ev = evaluate(p, te[retc].to_numpy(), te[tgt].to_numpy(), thr)
        base = (te[retc].mean() - FEE) * 100
        per_year.append((ty, len(te), auc, base, ev))
        es = (f"sel n={ev['n']} ({ev['frac']*100:.0f}%) hit={ev['hit']:.1f}% "
              f"net_exp={ev['exp_net']:+.3f}% PF={ev['pf']:.2f}" if ev else "sel none")
        out.append(f"  {ty}: n={len(te):>6} AUC={auc:.3f}  base_net={base:+.3f}%  | {es}")

    # تجميع OOS عبر كل السنوات
    mask = ~np.isnan(oos_proba)
    sub = df[mask]; p_all = oos_proba[mask]
    auc_all = roc_auc_score(sub[tgt], p_all) if sub[tgt].nunique() > 1 else float('nan')
    out.append(f"{'-'*100}")
    out.append(f"POOLED OOS: n={mask.sum():,}  AUC={auc_all:.4f}")
    out.append(f"selection sweep (top quantile by model proba) — net@{FEE*100:.1f}%:")
    for q in (0.50, 0.20, 0.10, 0.05, 0.02):
        thr = np.quantile(p_all, 1 - q)
        ev = evaluate(p_all, sub[retc].to_numpy(), sub[tgt].to_numpy(), thr)
        if ev:
            out.append(f"  top {q*100:>4.0f}%: n={ev['n']:>6} hit={ev['hit']:.1f}% "
                       f"net_exp={ev['exp_net']:+.3f}% PF={ev['pf']:.2f}  (base hit={sub[tgt].mean()*100:.1f}%)")
    # ثبات عبر السنوات للمجموعة المختارة top10%
    out.append("per-year net_exp of top-10% selected (consistency):")
    thr10 = np.quantile(p_all, 0.90)
    cells = []
    for ty in test_years:
        m2 = mask & (df['year'] == ty).to_numpy()
        if m2.sum() == 0: continue
        pp = oos_proba[m2]; rr = df[retc].to_numpy()[m2]; hh = df[tgt].to_numpy()[m2]
        s = pp >= thr10
        if s.sum() >= 20:
            cells.append(f"{ty}:{(rr[s]-FEE).mean()*100:+.2f}%/{s.sum()}")
        else:
            cells.append(f"{ty}:n{s.sum()}")
    out.append("  " + "  ".join(cells))

    text = "\n".join(out)
    print(text)
    suffix = f"{tf}_k{kk}" + ("_shuffle" if shuffle else "")
    with open(f"{OUT}/ml_wf_{suffix}.txt", "w") as f:
        f.write(text)

    # SHAP لأهم الميزات (نموذج أخير، عيّنة) — فقط في الوضع الحقيقي
    if not shuffle:
        try:
            import shap
            samp = sub.sample(min(4000, len(sub)), random_state=1)
            mlast = xgb();
            trall = df[df['year'] < test_years[-1]]
            mlast.fit(trall[cols].to_numpy(np.float32), trall[tgt].to_numpy(int))
            expl = shap.TreeExplainer(mlast)
            sv = expl.shap_values(samp[cols].to_numpy(np.float32))
            imp = np.abs(sv).mean(axis=0)
            order = np.argsort(imp)[::-1][:20]
            sh = ["TOP-20 SHAP features (mean |impact|):"]
            for i in order:
                sh.append(f"  {cols[i]:<18} {imp[i]:.4f}")
            shtext = "\n".join(sh)
            print("\n" + shtext)
            with open(f"{OUT}/ml_shap_{suffix}.txt", "w") as f:
                f.write(shtext)
        except Exception as ex:
            print(f"SHAP skipped: {ex}")

if __name__ == "__main__":
    main()
