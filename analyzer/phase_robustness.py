#!/usr/bin/env python3
"""تقدير مُزال-التحيّز لمشكلة طور إعادة الموازنة (اكتشاف التحقّق المستقل).
يشغّل كل 14 طوراً (إزاحة الدخول 0..13)، ويبني:
  1) توزيع الأداء عبر الأطوار (min/median/mean/max) لـ 2025 و full.
  2) محفظة الشرائح المتداخلة (1/14 في كل طور، الطريقة الواقعية) = التقدير الصادق.
spot 2024-25، نفس المواصفات المُجمَّدة."""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK,HOLD,DEC,UNIV=30,14,0.10,30; FEE=0.004
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    closes[s]=pd.Series(df['close'].values,index=ix).pipe(lambda x:x[~x.index.duplicated()])
    dvol[s]=pd.Series((df['close']*df['volume']).values,index=ix).pipe(lambda x:x[~x.index.duplicated()])
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index; btc=panel['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)

def phase_returns(offset):
    """يرجع dict date->ret لطور يبدأ عند LOOK+offset، خطوة HOLD."""
    pl=set(); ps=set(); out={}; i=LOOK+offset
    while i+HOLD<len(idx):
        date=idx[i]
        if date.year<2024: i+=HOLD; continue
        now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if ro(date):
            v=(now>0)&fwd.notna()&past.notna(); cand=fwd.index[v]
            liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(cand)]
            cand=liq.sort_values(ascending=False).head(UNIV).index
            if len(cand)>=10:
                mom=(now/past-1)[list(cand)].dropna(); k=max(1,int(len(mom)*DEC))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                gross=0.5*(float(fwd[list(L)].mean())-float(fwd[list(S)].mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*FEE
        out[date]=ret; pl=L; ps=S; i+=HOLD
    return out

def stats(series, yr=None):
    items=[(d,v) for d,v in series.items() if (yr is None or d.year==yr)]
    r=np.array([v for d,v in items if abs(v)>1e-9])
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf)

phases=[phase_returns(o) for o in range(HOLD)]
out=[]
out.append("PHASE ROBUSTNESS — 14 rebalance phases (offset 0..13). de-biasing the 'best phase' headline.")
out.append("="*100)
out.append(f"  {'phase':>5}{'FULL_Sh':>9}{'FULL_PF':>9}{'FULL_tot':>10}{'2025_Sh':>9}{'2025_PF':>9}{'2025_tot':>10}")
fs=[]; fp=[]; ft=[]; ys=[]; yp=[]; yt=[]
for o in range(HOLD):
    F=stats(phases[o]); Y=stats(phases[o],2025)
    if F: fs.append(F['sh']); fp.append(F['pf'] if F['pf']!=float('inf') else 5); ft.append(F['tot'])
    if Y: ys.append(Y['sh']); yp.append(Y['pf'] if Y['pf']!=float('inf') else 5); yt.append(Y['tot'])
    pfF='inf' if (F and F['pf']==float('inf')) else (f"{F['pf']:.2f}" if F else '-')
    pfY='inf' if (Y and Y['pf']==float('inf')) else (f"{Y['pf']:.2f}" if Y else '-')
    tag=' <-- reference' if o==0 else ''
    out.append(f"  {o:>5}{(F['sh'] if F else 0):>9.2f}{pfF:>9}{(F['tot'] if F else 0):>+9.0f}%{(Y['sh'] if Y else 0):>9.2f}{pfY:>9}{(Y['tot'] if Y else 0):>+9.0f}%{tag}")
out.append("-"*100)
def dist(name,a):
    a=np.array(a); return f"  {name:<14} min={a.min():>6.2f}  median={np.median(a):>6.2f}  mean={a.mean():>6.2f}  max={a.max():>6.2f}"
out.append("DISTRIBUTION across 14 phases:")
out.append(dist("2025 PF",yp)); out.append(dist("2025 Sharpe",ys)); out.append(dist("2025 total%",yt))
out.append(f"  phases profitable in 2025 (PF>1): {sum(1 for x in yp if x>1)}/{len(yp)}")
out.append("")
# محفظة الشرائح المتداخلة: متوسط عوائد الأطوار النشطة عند كل تاريخ
alld=sorted(set(d for ph in phases for d in ph))
combo=[]
for d in alld:
    vals=[ph[d] for ph in phases if d in ph]
    if vals: combo.append((d,np.mean(vals)))
comb_s=dict(combo)
C=stats(comb_s); C25=stats(comb_s,2025)
out.append("="*100)
out.append("STAGGERED TRANCHE PORTFOLIO (1/14 per phase — the realistic, de-biased deployment):")
def fmt(m): return f"n={m['n']} tot={m['tot']:+.0f}% Sharpe={m['sh']:.2f} PF={m['pf']:.2f}" if m else "n<4"
out.append(f"  FULL 2024-25 : {fmt(C)}")
out.append(f"  2025 only    : {fmt(C25)}")
out.append("="*100)
out.append("READ: tranche portfolio = honest expectation (you can't pick the lucky phase live). compare to headline 2025 PF 2.36.")
text="\n".join(out); print(text)
open('/app/logs/phase_robustness_report.txt','w').write(text)
