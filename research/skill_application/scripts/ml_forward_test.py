#!/usr/bin/env python3
"""
الاختبار الأمامي (paper-forward) لحافة اليومي:
  1) يدرّب XGBoost نهائياً على كل تاريخ 1d (k=3.0) ويحفظ النموذج + قائمة الميزات + عتبة أفضل-10%.
  2) يُسجّل (score) آخر شمعة يومية مغلقة لكل عملة → يُرتّب → يُخرج ترشيحات اليوم
     (entry=الإغلاق، target=+3·ATR، stop=−1·ATR) مع السيولة والاحتمال.
  3) يحفظ الترشيحات في CSV مؤرَّخ للتتبّع الأمامي + بروتوكول الحكم لاحقاً.
الفلسفة: لا مال حقيقي — تتبّع ورقي للإشارة في الزمن الحقيقي (الحَكَم النهائي على الحافة الصغيرة).
"""
import os, sys, glob, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import ml_dataset as D
import target_policy_bt as E
import ml_walkforward as W
from xgboost import XGBClassifier
import joblib

OUT = W.OUT
TF = '1d'; K = '3.0'; kk = '30'
TGT = f'hit_k{kk}'
LIQ_MIN = 3e5          # حد سيولة أدنى للترشيحات (قابل للتنفيذ بحجم صغير) — $300k/يوم
ATR_K = 3.0

def train_final():
    df = W.load(TF)
    cols = W.feat_cols(df); cols = W.add_regime_dummies(df, cols)
    df = df.dropna(subset=[TGT]).reset_index(drop=True)
    df[cols] = df[cols].replace([np.inf, -np.inf], np.nan)
    m = W.xgb(); m.fit(df[cols].to_numpy(np.float32), df[TGT].to_numpy(int))
    # عتبة أفضل-10% من توزيع احتمالات التدريب (تقريب تشغيلي)
    p = m.predict_proba(df[cols].to_numpy(np.float32))[:, 1]
    thr = float(np.quantile(p, 0.90))
    joblib.dump({'model': m, 'cols': cols, 'thr': thr}, f"{OUT}/ml_model_1d_k30.joblib")
    print(f"trained final model on {len(df):,} daily rows | top-10% proba thr={thr:.3f} | feats={len(cols)}")
    return m, cols, thr

def score_today(m, cols, thr):
    """يحسب الميزات على آخر شمعة مغلقة لكل عملة ويُرتّب الترشيحات."""
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{D.DATA}/*") if os.path.isdir(p)})
    rows = []
    for sym in syms:
        df = E.load(sym, TF)
        if df is None or len(df) < D.WARM + 5:
            continue
        try:
            Ff = D.feats(df); Fi = D.ict_feats(df)
        except Exception:
            continue
        block = pd.concat([Ff, Fi], axis=1)
        block['regime'] = D.regime_col(df)
        last = block.iloc[[-1]].copy()      # آخر شمعة مغلقة (نقطة القرار «اليوم»)
        # أعمدة regime dummies
        for r in ('bearish', 'bullish', 'sideways', 'volatile'):
            last[f'reg_{r}'] = 1.0 if last['regime'].iloc[0] == r else 0.0
        X = last.reindex(columns=cols, fill_value=0.0).replace([np.inf, -np.inf], np.nan)
        atr_pct = float(Ff['atr_pct'].iloc[-1]) if 'atr_pct' in Ff else np.nan
        if not np.isfinite(atr_pct) or not (0.003 < atr_pct < 0.15):
            continue
        try:
            proba = float(m.predict_proba(X.to_numpy(np.float32))[:, 1][0])
        except Exception:
            continue
        close = float(df['close'].iloc[-1])
        dvol = float(10 ** Ff['log_dvol20'].iloc[-1] - 1) if 'log_dvol20' in Ff else np.nan
        t_ms = int(df['t'].iloc[-1])
        rows.append({'symbol': sym, 'proba': round(proba, 4), 'regime': last['regime'].iloc[0],
                     'close': close, 'atr_pct': round(atr_pct * 100, 2),
                     'target': round(close * (1 + ATR_K * atr_pct), 8),
                     'stop': round(close * (1 - atr_pct), 8),
                     'dvol_usd': int(dvol) if np.isfinite(dvol) else 0,
                     'bar_time': pd.to_datetime(t_ms, unit='ms').strftime('%Y-%m-%d')})
    res = pd.DataFrame(rows).sort_values('proba', ascending=False)
    return res

if __name__ == "__main__":
    m, cols, thr = train_final()
    res = score_today(m, cols, thr)
    res.to_csv(f"{OUT}/forward_picks_all.csv", index=False)
    # الترشيحات الفعّالة: فوق العتبة + سيولة قابلة للتنفيذ بحجم صغير
    picks = res[(res.proba >= thr) & (res.dvol_usd >= LIQ_MIN)].copy()
    picks.to_csv(f"{OUT}/forward_picks_today.csv", index=False)
    print(f"\nscored {len(res)} symbols | snapshot bar ~ {res['bar_time'].mode().iloc[0] if len(res) else 'NA'}")
    print(f"ACTIONABLE picks (proba>={thr:.3f} & dvol>=${LIQ_MIN/1e3:.0f}k): {len(picks)}")
    print("\n=== TOP 20 picks today ===")
    cols_show = ['symbol', 'proba', 'regime', 'atr_pct', 'close', 'target', 'stop', 'dvol_usd', 'bar_time']
    print(picks[cols_show].head(20).to_string(index=False))
    print(f"\nsaved: forward_picks_today.csv ({len(picks)}) + forward_picks_all.csv ({len(res)})")
    print("\nبروتوكول التتبّع الأمامي:")
    print("  - شغّل هذا يومياً على بيانات محدّثة → يُسجّل ترشيحات كل يوم.")
    print("  - بعد ~30 شمعة: تحقّق هل لمس +3·ATR قبل −1·ATR (paper) → احسب WR والصافي الواقعي.")
    print("  - معيار النجاح: net/trade موجب بعد كلفة واقعية عبر ≥3 أشهر أمامية.")
