import sys, glob, zipfile
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK,HOLD,DEC,UNIV=30,14,0.10,30; FEE=0.004
OI="/app/logs/oi_data"
def load_oi(sym):
    fs=sorted(glob.glob(f"{OI}/{sym}/{sym}-metrics-*.zip"))
    if not fs: return None
    recs={}
    for f in fs:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]; lines=z.read(n).decode().splitlines()
            if len(lines)<2: continue
            last=lines[-1].split(','); recs[pd.Timestamp(last[0]).normalize()]=float(last[3])
        except: pass
    return pd.Series(recs).sort_index() if recs else None
syms=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
closes={}; dvol={}; ois={}
for s in syms:
    df=load(s,'1d')
    if df is not None:
        ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
        closes[s]=pd.Series(df['close'].values,index=ix).pipe(lambda x:x[~x.index.duplicated()])
        dvol[s]=pd.Series((df['close']*df['volume']).values,index=ix).pipe(lambda x:x[~x.index.duplicated()])
    oi=load_oi(s)
    if oi is not None: ois[s]=oi
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index); oip=pd.DataFrame(ois).reindex(panel.index)
idx=panel.index; btc=panel['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)
def oig(s,i):
    if s not in oip.columns: return np.nan
    ser=oip[s].iloc[max(0,i-LOOK):i+1].dropna()
    if len(ser)<5 or ser.iloc[0]<=0: return np.nan
    return ser.iloc[-1]/ser.iloc[0]-1
def metrics(rets):
    r=np.array([x for d,x in rets if abs(x)>1e-9])
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    pk=np.maximum.accumulate(eq); dd=float(((eq-pk)/pk).min()*100); srt=sorted(r,reverse=True)
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=dd,posrate=(r>0).mean()*100,
                top10=sum(srt[:10])/sum(r)*100 if sum(r)>0 else float('nan'))
def row(name,m):
    if not m: return f"  {name:<34} n<4"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return f"  {name:<34}n={m['n']:>3} Sharpe={m['sh']:>5.2f} PF={pf:>5} tot={m['tot']:>+5.0f}% DD={m['dd']:>4.0f}% posR={m['posrate']:>3.0f}% top10={m['top10']:>4.0f}%"

# الفرضية المنقّحة: ضمن المراكز الطويلة، رتّب حسب OI growth واقسم نصفين (معتدل مقابل متطرّف)
# + تباعد: السعر يصعد لكن OI لا يصعد بنفس القوة (مقابل ازدحام)
def run(mode='baseline'):
    pl=set();ps=set();rets=[];i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]
        if date.year<2024: i+=HOLD; continue
        now=panel.iloc[i];fut=panel.iloc[i+HOLD];past=panel.iloc[i-LOOK]
        fwd=(fut/now-1);ret=0.0;L=set();S=set()
        if ro(date):
            v=(now>0)&fwd.notna()&past.notna();cand=fwd.index[v]
            liq=dv.iloc[max(0,i-30):i].mean().dropna();liq=liq[liq.index.isin(cand)]
            cand=liq.sort_values(ascending=False).head(UNIV).index
            if len(cand)>=10:
                mom=(now/past-1)[list(cand)].dropna();k=max(1,int(len(mom)*DEC))
                Lall=list(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                if mode=='baseline': L=set(Lall)
                else:
                    pairs=[(s,oig(s,i),float(mom[s])) for s in Lall if not np.isnan(oig(s,i))]
                    if len(pairs)<2: L=set(Lall)
                    else:
                        gs=sorted(p[1] for p in pairs); med=gs[len(gs)//2]
                        if mode=='moderate_oi': L=set(s for s,g,m in pairs if g<=med)  # نمو OI أقل (أقل ازدحام)
                        elif mode=='extreme_oi': L=set(s for s,g,m in pairs if g>med)  # نمو OI أعلى (ازدحام)
                        elif mode=='divergence': # السعر يصعد أكثر من OI (نسبياً) = صحي
                            L=set(s for s,g,m in pairs if m>0 and g<m*3)  # OI لم يتضخّم أكثر من 3x حركة السعر
                if L:
                    lr=float(fwd[list(L)].mean());sr=-float(fwd[list(S)].mean());gross=0.5*(lr+sr)
                    tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                    tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                    ret=gross-(tl+tsh)*FEE
        rets.append((date,ret));pl=L;ps=S;i+=HOLD
    return rets
print("REFINED OI TEST — OI is collinear with momentum (92% rising). Test INTENSITY/divergence instead of direction:")
print(row("BASELINE (no OI)",metrics(run('baseline'))))
print(row("Moderate OI growth (below median)",metrics(run('moderate_oi'))))
print(row("Extreme OI growth (above median)",metrics(run('extreme_oi'))))
print(row("Price-leads-OI divergence (healthy)",metrics(run('divergence'))))
print("READ: if moderate-OI or divergence beats baseline on posRate/top10 => OI adds via crowding-avoidance, not direction.")
