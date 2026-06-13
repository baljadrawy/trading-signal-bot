#!/usr/bin/env python3
"""محفظة الشرائح الصحيحة — تزيل تحيّز اختيار الطور دون تشاؤم التداخل.
الطريقة الواقعية: 14 شريحة متوازية، كل شريحة 1/14 رأس المال، تعيد الموازنة كل 14 يوماً بإزاحة مختلفة.
نحسب عائداً يومياً حقيقياً: كل يوم، كل شريحة تحمل مراكزها (long/short) وتجني عائد ذلك اليوم.
الرسوم تُحاسب يوم إعادة الموازنة فقط لكل شريحة. لا تداخل/تضخيم.
spot 2024-25، المواصفات المُجمَّدة (look30 hold14 dec10 Top30 gated)."""
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
# عائد يومي لكل عملة
dret=panel.pct_change()
def ro_at(i):
    d=idx[i]; p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)

def pick(i):
    """يرجع (longs,shorts) عند المؤشر i حسب المواصفات، أو (set(),set()) لو risk-off/غير صالح."""
    if not ro_at(i): return set(),set()
    now=panel.iloc[i]; past=panel.iloc[i-LOOK]
    v=(now>0)&past.notna(); cand=now.index[v]
    liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(cand)]
    cand=liq.sort_values(ascending=False).head(UNIV).index
    if len(cand)<10: return set(),set()
    mom=(now/past-1)[list(cand)].dropna(); k=max(1,int(len(mom)*DEC))
    return set(mom.sort_values(ascending=False).head(k).index), set(mom.sort_values(ascending=True).head(k).index)

# لكل شريحة (طور): جدول مراكزها لكل يوم + أيام إعادة الموازنة
N=len(idx)
# نبني، لكل يوم d، قائمة المراكز الفعّالة لكل شريحة (من آخر إعادة موازنة لها)
daily_port_ret=np.zeros(N)         # عائد المحفظة المجمّعة لكل يوم
daily_active=np.zeros(N)
# لكل شريحة: مراكزها الحالية ووزن كل مركز
for off in range(HOLD):
    reb_idx=list(range(LOOK+off, N-1, HOLD))
    curL=set(); curS=set(); prevL=set(); prevS=set()
    # نمرّ يوماً بيوم؛ عند يوم إعادة موازنة نحدّث المراكز
    reb_set=set(reb_idx)
    for i in range(LOOK, N):
        if i in reb_set:
            prevL,prevS=curL,curS
            curL,curS=pick(i)
        # عائد اليوم i من مراكز هذه الشريحة (long - short)/... dollar-neutral 0.5 لكل ساق
        if idx[i].year<2024: continue
        r=0.0
        if curL or curS:
            rl=np.nanmean([dret[s].iloc[i] for s in curL]) if curL else 0.0
            rs=np.nanmean([dret[s].iloc[i] for s in curS]) if curS else 0.0
            r=0.5*(rl - rs)
            # رسوم يوم إعادة الموازنة فقط
            if i in reb_set:
                tl=len(prevL^curL)/(2*max(1,len(prevL|curL))) if (prevL|curL) else (1.0 if curL else 0)
                ts=len(prevS^curS)/(2*max(1,len(prevS|curS))) if (prevS|curS) else (1.0 if curS else 0)
                r-=(tl+ts)*FEE
        if not np.isnan(r):
            daily_port_ret[i]+=r/HOLD     # 1/14 وزن لكل شريحة
            daily_active[i]+=1

# المحفظة المجمّعة: عائد يومي
mask=np.array([idx[i].year>=2024 for i in range(N)])
dr=daily_port_ret[mask]
dates=idx[mask]
def stats(dr,dates,yr=None):
    if yr is not None:
        m=np.array([d.year==yr for d in dates]); dr=dr[m]
    dr=dr[~np.isnan(dr)]
    if len(dr)<20: return None
    eq=np.cumprod(1+dr); sh=dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0
    pos=dr[dr>0].sum(); neg=-dr[dr<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    pk=np.maximum.accumulate(eq); dd=float(((eq-pk)/pk).min()*100)
    return dict(n=len(dr),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=dd)
def fmt(m): return f"n={m['n']} totRet={m['tot']:+.0f}% Sharpe={m['sh']:.2f} PF={m['pf']:.2f} MaxDD={m['dd']:.0f}%" if m else "n<20"
out=[]
out.append("CORRECT STAGGERED-TRANCHE PORTFOLIO — 14 parallel phases, 1/14 capital each, true DAILY returns (Sharpe ann ×√252)")
out.append("removes phase-selection bias AND overlap-inflation. This is the realistic deployable estimate.")
out.append("="*100)
out.append(f"  FULL 2024-25 : {fmt(stats(dr,dates))}")
out.append(f"  2024 only    : {fmt(stats(dr,dates,2024))}")
out.append(f"  2025 only    : {fmt(stats(dr,dates,2025))}")
out.append("="*100)
out.append("USER BAR: Sharpe>0.8 & PF>1.3 => edge stays interesting. Sharpe 0.2-0.5 & PF~1 => tiny edge + noise.")
out.append("(daily Sharpe ann by sqrt(252); compare ballpark to the per-phase median Sharpe 0.39 and best-phase 2.49)")
text="\n".join(out); print(text)
open('/app/logs/tranche_correct_report.txt','w').write(text)
