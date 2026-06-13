#!/usr/bin/env python3
"""اختبار فرضية OI: هل أفضل فرص الـmomentum هي التي يتوافق فيها السعر مع تدفق رأس المال (OI يرتفع)؟
4 سلال (تقسيم الساق الطويلة top-decile حسب اتجاه OI خلال الـlookback):
  1) Momentum + OI Rising   2) + OI Flat   3) + OI Falling   4) Baseline (بلا OI).
المعيار الحاسم (ليس Sharpe وحده): نسبة الفترات الموجبة + تركّز أفضل-10.
البيانات: spot prices للإشارة/العائد (مثبت سابقاً = futures)، OI من futures metrics. 2024-25.
"""
import sys, glob, zipfile
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK,HOLD,DEC,UNIV=30,14,0.10,30; FEE=0.004
OI="/app/logs/oi_data"

def load_oi(sym):
    """يرجع Series: date -> sum_open_interest_value (آخر صف يومي)."""
    fs=sorted(glob.glob(f"{OI}/{sym}/{sym}-metrics-*.zip"))
    if not fs: return None
    recs={}
    for f in fs:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]
            lines=z.read(n).decode().splitlines()
            if len(lines)<2: continue
            last=lines[-1].split(',')  # آخر لقطة في اليوم
            # cols: create_time,symbol,sum_open_interest,sum_open_interest_value,...
            day=pd.Timestamp(last[0]).normalize()
            recs[day]=float(last[3])
        except Exception: pass
    if not recs: return None
    return pd.Series(recs).sort_index()

syms=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
closes={}; dvol={}; ois={}
for s in syms:
    df=load(s,'1d')
    if df is not None:
        ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
        c=pd.Series(df['close'].values,index=ix); closes[s]=c[~c.index.duplicated()]
        d=pd.Series((df['close']*df['volume']).values,index=ix); dvol[s]=d[~d.index.duplicated()]
    oi=load_oi(s)
    if oi is not None: ois[s]=oi
print(f"klines={len(closes)} OI loaded={len(ois)}",flush=True)
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
oip=pd.DataFrame(ois).reindex(panel.index)
idx=panel.index
btc=panel['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)

def oi_growth(sym,i):
    """نمو OI خلال LOOK يوم حتى i. يرجع نسبة أو nan."""
    if sym not in oip.columns: return np.nan
    s=oip[sym]
    a=s.iloc[max(0,i-LOOK):i+1].dropna()
    if len(a)<5: return np.nan
    first=a.iloc[0]; last=a.iloc[-1]
    return (last/first-1) if first>0 else np.nan

def run(bucket='baseline'):
    """bucket: baseline | rising | flat | falling — يقسّم الساق الطويلة فقط حسب OI.
       الساق القصيرة تبقى كما هي في كل السلال (للعزل)."""
    pl=set(); ps=set(); rets=[]; i=LOOK
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
                mom=(now/past-1)[list(cand)].dropna()
                k=max(1,int(len(mom)*DEC))
                Lall=list(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                if bucket=='baseline':
                    L=set(Lall)
                else:
                    # صنّف الساق الطويلة حسب OI growth
                    gr={s:oi_growth(s,i) for s in Lall}
                    valid=[s for s in Lall if not np.isnan(gr[s])]
                    if not valid: i+=HOLD; rets.append((date,0.0)); continue
                    gvals=sorted(gr[s] for s in valid)
                    # عتبات: rising>+5%, falling<-5%, flat بينهما
                    if bucket=='rising': L=set(s for s in valid if gr[s]>0.05)
                    elif bucket=='falling': L=set(s for s in valid if gr[s]<-0.05)
                    else: L=set(s for s in valid if -0.05<=gr[s]<=0.05)
                if L:
                    lr=float(fwd[list(L)].mean()); sr=-float(fwd[list(S)].mean())
                    gross=0.5*(lr+sr)
                    tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                    tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                    ret=gross-(tl+tsh)*FEE
        rets.append((date,ret)); pl=L; ps=S; i+=HOLD
    return rets

def metrics(rets):
    vals=[x for d,x in rets]; r=np.array([x for x in vals if abs(x)>1e-9])
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    pk=np.maximum.accumulate(eq); dd=float(((eq-pk)/pk).min()*100)
    posrate=(r>0).mean()*100
    srt=sorted(r,reverse=True); top10share=sum(srt[:10])/sum(r)*100 if sum(r)>0 else float('nan')
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=dd,posrate=posrate,top10=top10share)
def row(name,m):
    if not m: return f"  {name:<28} n<4"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return (f"  {name:<28}n={m['n']:>3}  Sharpe={m['sh']:>5.2f}  PF={pf:>5}  tot={m['tot']:>+6.0f}%  "
            f"MaxDD={m['dd']:>5.0f}%  posRate={m['posrate']:>3.0f}%  top10={m['top10']:>4.0f}%")

out=[]
out.append("OI HYPOTHESIS TEST — does aligning momentum with capital flow (OI rising) improve the GOOD/BAD period ratio?")
out.append("buckets split the LONG leg by 30d OI growth (rising>+5%, flat, falling<-5%); short leg unchanged. spot 2024-25.")
out.append("="*118)
base=metrics(run('baseline'))
out.append(row("4) BASELINE (no OI)",base))
out.append(row("1) Momentum + OI Rising",metrics(run('rising'))))
out.append(row("2) Momentum + OI Flat",metrics(run('flat'))))
out.append(row("3) Momentum + OI Falling",metrics(run('falling'))))
out.append("="*118)
out.append("VERDICT (user bar): real edge if OI-Rising IMPROVES posRate or LOWERS top10-concentration vs baseline,")
out.append("                    not just higher Sharpe from 1-2 lucky periods.")
text="\n".join(out); print(text)
open('/app/logs/oi_report.txt','w').write(text)
