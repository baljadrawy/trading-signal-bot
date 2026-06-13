#!/usr/bin/env python3
"""Capacity & Liquidity — هل الحافة momentum حقيقي قابل للتوسّع، أم listing-momentum في عملات صغيرة؟
A) استبعاد تدريجي لأقل السيولة (20/40/60%) من كون واسع — هل تبقى الحافة؟
B) كون كبير فقط (top-15/top-30 ADV مطلق) — الحافة في الكبار؟
C) تشريح الربح: long-leg حسب عمر الأصل (new<90d / mid 90-180 / mature>180) — من أين الربح؟
D) ADV الفعلي للساق الطويلة (هل العملات قابلة للتنفيذ بحجم؟).
الإعداد الفائز: look30 hold14 dec0.10 gated. long-short dollar-neutral. fee 0.4%/side + funding 0.3%/wk.
"""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA

LOOK,HOLD,DEC=30,14,0.10
FEE=0.004; FUND=0.003
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}; firsts={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); c=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); d=d[~d.index.duplicated()]
    closes[s]=c; dvol[s]=d; firsts[s]=ix.min()
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index
btc=panel['BTCUSDT'].dropna(); ema50=btc.ewm(span=50).mean(); ema200=btc.ewm(span=200).mean()
def riskon(date):
    p=btc.get(date,np.nan); e50=ema50.get(date,np.nan); e200=ema200.get(date,np.nan)
    if np.isnan(p) or np.isnan(e200): return True
    return p>e50 and p>e200
def maxdd(eq):
    eq=np.array(eq); pk=np.maximum.accumulate(eq); return float(((eq-pk)/pk).min()*100)
def perf(rets):
    r=np.array([x for d,x in rets]);
    if len(r)<5: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    r25=np.array([x for d,x in rets if d.year==2025])
    eq25=np.cumprod(1+r25) if len(r25)>0 else [1]
    sh25=r25.mean()/r25.std()*np.sqrt(52) if len(r25)>1 and r25.std()>0 else 0
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=maxdd(eq),
                t25=(eq25[-1]-1)*100,sh25=sh25)
def fmt(m):
    if not m: return "n<5"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return f"tot={m['tot']:>+6.0f}%  Sh={m['sh']:>5.2f}  PF={pf:>5}  DD={m['dd']:>5.0f}%  |2025 ret={m['t25']:>+5.0f}% Sh={m['sh25']:>5.2f}"

def liq_rank(i):
    return dv.iloc[max(0,i-30):i].mean().dropna()  # ADV لكل رمز عند i

def strat(universe_size=30, drop_low_frac=0.0, big_only=0):
    """universe_size: حجم الكون السائل. drop_low_frac: استبعد أقل X% سيولة داخله.
       big_only: لو>0، الكون = أكبر big_only رمزاً بـADV مطلق فقط."""
    pl=set(); ps=set(); rets=[]; i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        if riskon(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            liq=liq_rank(i); liq=liq[liq.index.isin(mom.index)]
            if big_only>0:
                keep=set(liq.sort_values(ascending=False).head(big_only).index)
            else:
                ranked=liq.sort_values(ascending=False)
                pool=ranked.head(universe_size)
                if drop_low_frac>0:
                    cut=int(len(pool)*(1-drop_low_frac))
                    pool=pool.head(max(6,cut))  # أبقِ على الأعلى سيولة
                keep=set(pool.index)
            mom=mom[mom.index.isin(keep)]
            if len(mom)>=10:
                k=max(1,int(len(mom)*DEC))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                gross=0.5*(float(fwd[list(L)].mean())-float(fwd[list(S)].mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*FEE-FUND*0.5
        rets.append((date,ret)); pl=L; ps=S; i+=HOLD
    return rets

def age_attribution(universe_size=30):
    """يشرّح متوسط عائد الساق الطويلة حسب عمر الأصل وقت الدخول."""
    buckets={'new<90d':[], 'mid90-180':[], 'mature>180':[]}; i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]; now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1)
        if riskon(date):
            mom=(now/past-1); v=mom.notna()&fwd.notna()&past.notna()&(now>0); mom=mom[v]
            liq=liq_rank(i); liq=liq[liq.index.isin(mom.index)]
            keep=set(liq.sort_values(ascending=False).head(universe_size).index)
            mom=mom[mom.index.isin(keep)]
            if len(mom)>=10:
                k=max(1,int(len(mom)*DEC))
                for s in mom.sort_values(ascending=False).head(k).index:
                    age=(date-firsts.get(s,date)).days
                    b='new<90d' if age<90 else ('mid90-180' if age<180 else 'mature>180')
                    buckets[b].append(float(fwd[s]))
        i+=HOLD
    return buckets

out=[]
out.append("CAPACITY & LIQUIDITY — winning cfg look30/hold14/dec10%, gated. is edge scalable momentum or small/new-coin listing-momentum?")
out.append("="*120)
out.append("A) progressive liquidity exclusion (drop lowest-liquidity fraction from a 50-coin pool):")
for frac in [0.0,0.2,0.4,0.6]:
    out.append(f"   drop lowest {int(frac*100):>2}% liq : {fmt(perf(strat(universe_size=50,drop_low_frac=frac)))}")
out.append("")
out.append("B) BIG-ONLY universe (absolute top-ADV coins only — most executable):")
for big in [15,30,50]:
    out.append(f"   top-{big:>2} ADV only : {fmt(perf(strat(big_only=big)))}")
out.append("")
out.append("C) LONG-LEG PROFIT ATTRIBUTION BY AGE (where does the long-leg return come from?):")
bk=age_attribution(30)
for name,vals in bk.items():
    if vals:
        a=np.array(vals); out.append(f"   {name:<12} picks={len(a):>4}  mean_fwd_ret={a.mean()*100:>+6.2f}%  share_of_picks={len(a)/sum(len(x) for x in bk.values())*100:>4.0f}%")
    else:
        out.append(f"   {name:<12} picks=0")
out.append("")
out.append("D) ACTUAL ADV of long-leg picks (executability):")
# نقيس متوسط ADV للمختارين في كون top-30
advs=[]; i=LOOK
while i+HOLD<len(idx):
    date=idx[i]; now=panel.iloc[i]; past=panel.iloc[i-LOOK]
    if riskon(date):
        mom=(now/past-1); v=mom.notna()&past.notna()&(now>0); mom=mom[v]
        liq=liq_rank(i); liq=liq[liq.index.isin(mom.index)]
        keep=set(liq.sort_values(ascending=False).head(30).index)
        mom=mom[mom.index.isin(keep)]
        if len(mom)>=10:
            k=max(1,int(len(mom)*DEC))
            for s in mom.sort_values(ascending=False).head(k).index:
                advs.append(float(liq.get(s,np.nan)))
    i+=HOLD
advs=np.array([a for a in advs if not np.isnan(a)])
if len(advs):
    out.append(f"   long-leg ADV (30d avg $vol): median=${np.median(advs)/1e6:.1f}M  p25=${np.percentile(advs,25)/1e6:.1f}M  p75=${np.percentile(advs,75)/1e6:.1f}M")
out.append("="*120)
out.append("VERDICT: if edge SURVIVES dropping 40-60% low-liq AND big-only top-15/30 => scalable real momentum.")
out.append("         if edge VANISHES when small coins removed => listing-momentum, capacity-limited.")
text="\n".join(out); print(text)
with open('/app/logs/capacity_report.txt','w') as f: f.write(text)
