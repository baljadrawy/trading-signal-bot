import sys, glob, zipfile
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
LOOK,HOLD,DEC,UNIV=30,14,0.10,30
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
# توزّع OI growth للمراكز الطويلة المختارة
all_growth=[]; n_long_total=0; n_with_oi=0
i=LOOK
while i+HOLD<len(idx):
    date=idx[i]
    if date.year>=2024 and ro(date):
        now=panel.iloc[i]; past=panel.iloc[i-LOOK]
        v=(now>0); cand=now.index[v]
        liq=dv.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(cand)]
        cand=liq.sort_values(ascending=False).head(UNIV).index
        if len(cand)>=10:
            mom=(now/past-1)[list(cand)].dropna(); k=max(1,int(len(mom)*DEC))
            L=list(mom.sort_values(ascending=False).head(k).index)
            n_long_total+=len(L)
            for s in L:
                if s in oip.columns:
                    ser=oip[s].iloc[max(0,i-LOOK):i+1].dropna()
                    if len(ser)>=5 and ser.iloc[0]>0:
                        g=ser.iloc[-1]/ser.iloc[0]-1; all_growth.append(g); n_with_oi+=1
    i+=HOLD
g=np.array(all_growth)
print(f"total long picks: {n_long_total} | with valid OI: {n_with_oi} ({n_with_oi/n_long_total*100:.0f}%)")
print(f"OI growth (30d) distribution over long picks:")
print(f"  rising >+5%  : {(g>0.05).sum()} ({(g>0.05).mean()*100:.0f}%)")
print(f"  flat -5..+5% : {((g>=-0.05)&(g<=0.05)).sum()} ({((g>=-0.05)&(g<=0.05)).mean()*100:.0f}%)")
print(f"  falling <-5% : {(g<-0.05).sum()} ({(g<-0.05).mean()*100:.0f}%)")
print(f"  median growth: {np.median(g)*100:+.1f}%  mean: {g.mean()*100:+.1f}%")
print(f"  per-period avg long picks: ~{n_long_total/33:.1f} (so 3-way split => ~1/bucket => many empty buckets)")
