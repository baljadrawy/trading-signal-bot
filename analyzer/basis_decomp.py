#!/usr/bin/env python3
"""تشريح فجوة الـ Basis: لماذا spot +139% -> futures +45%؟
المنهج الصارم: نولّد الإشارة من السبوت (نفس الترتيب بالضبط)، ثم نقيس عائد كل مركز
على السبوت مقابل الآجلة لنفس الرمز ونفس النافذة. هكذا نعزل فرق 'العائد المتحقق' فقط،
لا فرق اختيار العملات. ثم نشرّح الفجوة لكل رمز + تركّزها."""
import sys, glob, zipfile
import numpy as np, pandas as pd
from collections import defaultdict
sys.path.insert(0,'/app')
from bt_engine import load as load_spot, DATA as SPOT_DATA

FUT="/app/logs/fut_data"; LOOK,HOLD,DEC,UNIV=30,14,0.10,30

def load_fut(sym):
    fs=sorted(glob.glob(f"{FUT}/klines/{sym}/1d/{sym}-1d-*.zip"))
    if not fs: return None
    rows=[]
    for f in fs:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]
            for ln in z.read(n).decode().splitlines():
                if ln.startswith('open_time'): continue
                p=ln.split(','); rows.append((int(p[0]),float(p[4])))
        except Exception: pass
    if len(rows)<5: return None
    s=pd.Series([r[1] for r in rows],index=pd.to_datetime([r[0] if r[0]<1e14 else r[0]//1000 for r in rows],unit='ms').normalize())
    return s[~s.index.duplicated()]

covered=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
sclose={}; sdv={}; fclose={}
for s in covered:
    df=load_spot(s,'1d')
    if df is not None:
        ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
        c=pd.Series(df['close'].values,index=ix); sclose[s]=c[~c.index.duplicated()]
        d=pd.Series((df['close']*df['volume']).values,index=ix); sdv[s]=d[~d.index.duplicated()]
    f=load_fut(s)
    if f is not None: fclose[s]=f
sp=pd.DataFrame(sclose).sort_index(); sdvp=pd.DataFrame(sdv).reindex(sp.index)
fp=pd.DataFrame(fclose).reindex(sp.index)
idx=sp.index
btc=sp['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)

# نولّد الإشارة من السبوت، ونقيس عائد كل ساق على السبوت والآجلة لنفس الرمز/النافذة
gap_by_coin=defaultdict(lambda:[0.0,0.0,0])  # sym -> [spot_contrib, fut_contrib, count]
side_of=defaultdict(str)
spot_cum=0.0; fut_cum=0.0; missing=0; i=LOOK
while i+HOLD<len(idx):
    date=idx[i]
    if date.year<2024: i+=HOLD; continue
    now=sp.iloc[i]; fut_s=sp.iloc[i+HOLD]; past=sp.iloc[i-LOOK]
    if ro(date):
        mom=(now/past-1); fwd_s=(fut_s/now-1)
        v=mom.notna()&fwd_s.notna()&past.notna()&(now>0); mom=mom[v]
        liq=sdvp.iloc[max(0,i-30):i].mean().dropna(); liq=liq[liq.index.isin(mom.index)]
        mom=mom[mom.index.isin(set(liq.sort_values(ascending=False).head(UNIV).index))]
        if len(mom)>=10:
            k=max(1,int(len(mom)*DEC))
            L=list(mom.sort_values(ascending=False).head(k).index)
            S=list(mom.sort_values(ascending=True).head(k).index)
            fnow=fp.iloc[i]; ffut=fp.iloc[i+HOLD]
            for s in L:
                rs=float(fwd_s[s])  # spot long return
                rf=(float(ffut[s])/float(fnow[s])-1) if (not pd.isna(fnow.get(s)) and not pd.isna(ffut.get(s)) and fnow.get(s,0)>0) else rs
                spot_cum+=0.5*rs/k; fut_cum+=0.5*rf/k
                gap_by_coin[s][0]+=0.5*rs/k; gap_by_coin[s][1]+=0.5*rf/k; gap_by_coin[s][2]+=1; side_of[s]='L'
            for s in S:
                rs=-float(fwd_s[s])
                rf=-((float(ffut[s])/float(fnow[s])-1)) if (not pd.isna(fnow.get(s)) and not pd.isna(ffut.get(s)) and fnow.get(s,0)>0) else rs
                spot_cum+=0.5*rs/k; fut_cum+=0.5*rf/k
                gap_by_coin[s][0]+=0.5*rs/k; gap_by_coin[s][1]+=0.5*rf/k; gap_by_coin[s][2]+=1; side_of[s]='S'
    i+=HOLD

out=[]
out.append("BASIS GAP DECOMPOSITION — identical spot-generated signals, return measured on spot vs futures per position")
out.append(f"(2024-25, same signals, paired by symbol+window — isolates realized-return gap, not selection)")
out.append("="*100)
out.append(f"  cumulative spot contribution : {spot_cum*100:+.1f}%")
out.append(f"  cumulative futures contrib   : {fut_cum*100:+.1f}%")
out.append(f"  TOTAL GAP (spot - fut)       : {(spot_cum-fut_cum)*100:+.1f}%")
out.append("")
# الفجوة لكل رمز = spot_contrib - fut_contrib
gaps=[(s,v[0]*100,v[1]*100,(v[0]-v[1])*100,v[2],side_of[s]) for s,v in gap_by_coin.items()]
gaps.sort(key=lambda x:abs(x[3]),reverse=True)
total_gap=sum(g[3] for g in gaps)
out.append(f"per-symbol gap (spot_contrib - fut_contrib). total gap={total_gap:+.1f}%")
out.append(f"  {'symbol':<14}{'side':>5}{'picks':>6}{'spot%':>9}{'fut%':>9}{'GAP%':>9}{'cumShare':>10}")
cum=0
for s,sc,fc,g,cnt,side in gaps[:25]:
    cum+=g
    out.append(f"  {s:<14}{side:>5}{cnt:>6}{sc:>+8.1f}{fc:>+8.1f}{g:>+8.1f}{cum/total_gap*100:>9.0f}%")
# تركّز
for topn in [5,10,20]:
    c=sum(g[3] for g in gaps[:topn])
    out.append(f"  --> top {topn} symbols = {c:+.1f}% of gap ({c/total_gap*100:.0f}%)")
out.append("")
# الفجوة حسب الساق
gl=sum((v[0]-v[1]) for s,v in gap_by_coin.items() if side_of[s]=='L')*100
gs=sum((v[0]-v[1]) for s,v in gap_by_coin.items() if side_of[s]=='S')*100
out.append(f"GAP by leg:  LONG leg gap={gl:+.1f}%   SHORT leg gap={gs:+.1f}%  (which leg loses most going to futures?)")
out.append("="*100)
out.append("READ: if few symbols dominate gap => filter them. if gap is broad/short-leg => structural basis (weak coins cheaper on futures).")
text="\n".join(out); print(text)
open('/app/logs/basis_decomp_report.txt','w').write(text)
