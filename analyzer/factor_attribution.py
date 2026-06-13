#!/usr/bin/env python3
"""3 اختبارات: (1) مساهمة العوامل (Momentum/Regime/Universe + تفاعلها)،
(2) تركّز الأرباح (أفضل/أسوأ فترات)، (3) استقرار حول Top30 (25/30/35/40 + جوار).
كل شيء على بيانات السبوت 2024-2025 (نطاق الحافة)، long-short dollar-neutral، fee 0.4%/side."""
import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, DATA
HOLD=14; LOOK=30; FEE=0.004
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
closes={}; dvol={}
for s in syms:
    df=load(s,'1d')
    if df is None: continue
    ix=pd.to_datetime(df['t'],unit='ms').dt.normalize()
    c=pd.Series(df['close'].values,index=ix); closes[s]=c[~c.index.duplicated()]
    d=pd.Series((df['close']*df['volume']).values,index=ix); dvol[s]=d[~d.index.duplicated()]
panel=pd.DataFrame(closes).sort_index(); dv=pd.DataFrame(dvol).reindex(panel.index)
idx=panel.index
btc=panel['BTCUSDT'].dropna(); e5=btc.ewm(span=50).mean(); e2=btc.ewm(span=200).mean()
def ro(d):
    p=btc.get(d,np.nan); a=e5.get(d,np.nan); b=e2.get(d,np.nan)
    return True if (np.isnan(p) or np.isnan(b)) else (p>a and p>b)

def strat(use_momentum=True, use_regime=True, universe=30, dec=0.10, y0=2024):
    """use_momentum=False → ترتيب عشوائي ثابت (لا زخم). use_regime=False → تداول دائم.
       universe=0 → كل الكون السائل (بلا Top-N)."""
    pl=set(); ps=set(); rets=[]; i=LOOK
    while i+HOLD<len(idx):
        date=idx[i]
        if date.year<y0: i+=HOLD; continue
        now=panel.iloc[i]; fut=panel.iloc[i+HOLD]; past=panel.iloc[i-LOOK]
        fwd=(fut/now-1); ret=0.0; L=set(); S=set()
        on = ro(date) if use_regime else True
        if on:
            valid=(now>0)&fwd.notna()&past.notna()
            cand=fwd.index[valid]
            liq=dv.iloc[max(0,i-30):i].mean().dropna()
            if universe>0:
                liqc=liq[liq.index.isin(cand)]
                cand=liqc.sort_values(ascending=False).head(universe).index
            else:
                cand=[c for c in cand if c in liq.index]
            if len(cand)>=10:
                if use_momentum:
                    mom=(now/past-1)[list(cand)].dropna()
                else:
                    # بديل بلا زخم: ترتيب حسب hash ثابت للرمز (محايد، لا معلومة سعرية)
                    mom=pd.Series({c:(hash(c)%1000)/1000.0 for c in cand})
                k=max(1,int(len(mom)*dec))
                L=set(mom.sort_values(ascending=False).head(k).index)
                S=set(mom.sort_values(ascending=True).head(k).index)
                gross=0.5*(float(fwd[list(L)].mean())-float(fwd[list(S)].mean()))
                tl=len(pl^L)/(2*max(1,len(pl|L))) if (pl|L) else (1.0 if L else 0)
                tsh=len(ps^S)/(2*max(1,len(ps|S))) if (ps|S) else (1.0 if S else 0)
                ret=gross-(tl+tsh)*FEE
        rets.append((date,ret)); pl=L; ps=S; i+=HOLD
    return rets

def perf(rets):
    r=np.array([x for d,x in rets]);
    if len(r)<4: return None
    eq=np.cumprod(1+r); sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    pos=r[r>0].sum(); neg=-r[r<0].sum(); pf=(pos/neg) if neg>0 else float('inf')
    pk=np.maximum.accumulate(eq)
    return dict(n=len(r),tot=(eq[-1]-1)*100,sh=sh,pf=pf,dd=float(((eq-pk)/pk).min()*100))
def cell(m):
    if not m: return "n<4"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return f"Sharpe={m['sh']:>5.2f}  PF={pf:>5}  tot={m['tot']:>+6.0f}%  DD={m['dd']:>5.0f}%"

out=[]
out.append("FACTOR ATTRIBUTION + CONCENTRATION + Top-N STABILITY (spot 2024-2025, long-short, fee0.4%/side)")
out.append("="*100)
out.append("(1) FACTOR CONTRIBUTION — toggle one factor at a time:")
out.append(f"  {'Momentum only (no regime, full univ)':<42}{cell(perf(strat(True,False,0)))}")
out.append(f"  {'Regime only (no momentum=hash rank)':<42}{cell(perf(strat(False,True,30)))}")
out.append(f"  {'Universe only (no mom, no regime)':<42}{cell(perf(strat(False,False,30)))}")
out.append(f"  {'Momentum + Regime (full univ)':<42}{cell(perf(strat(True,True,0)))}")
out.append(f"  {'Momentum + Top30 (no regime)':<42}{cell(perf(strat(True,False,30)))}")
out.append(f"  {'Momentum + Regime + Top30 (FULL)':<42}{cell(perf(strat(True,True,30)))}")
out.append("  READ: if FULL >> any single/pair → interaction is the edge, not one factor.")
out.append("")
# (2) تركّز الأرباح للنموذج الكامل
full=strat(True,True,30)
pv=sorted([x for d,x in full],reverse=True); tot=sum(pv); npos=sum(1 for x in pv if x>0)
out.append("="*100)
out.append(f"(2) PROFIT CONCENTRATION (FULL model, {len(pv)} periods, total={tot*100:+.1f}%, positive={npos}/{len(pv)}):")
for n in [5,10]:
    out.append(f"  top {n:>2} periods = {sum(pv[:n])*100:+.1f}%  ({sum(pv[:n])/tot*100:.0f}% of total)")
out.append(f"  worst 5 periods = {sum(pv[-5:])*100:+.1f}%")
out.append(f"  bottom 80% of periods (the {int(len(pv)*0.8)} smallest) = {sum(sorted(pv)[:int(len(pv)*0.8)])*100:+.1f}%")
# نسبة الفترات التي تولّد 80% من الربح
cum=0; cnt=0
for x in pv:
    if x>0: cum+=x; cnt+=1
    if cum>=0.8*sum(p for p in pv if p>0): break
out.append(f"  periods generating 80% of gross profit: {cnt}/{npos} positive periods ({cnt/len(pv)*100:.0f}% of all periods)")
out.append("  READ: ~20% generating 80% = normal. 5% generating 90% = fragile.")
out.append("")
# (3) استقرار Top-N
out.append("="*100)
out.append("(3) STABILITY AROUND Top-30 (FULL model, vary universe size):")
out.append(f"  {'universe':<12}{'Sharpe':>8}{'PF':>7}{'tot':>8}{'MaxDD':>8}")
for u in [20,25,30,35,40,50]:
    m=perf(strat(True,True,u))
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    out.append(f"  Top-{u:<8}{m['sh']:>8.2f}{pf:>7}{m['tot']:>+7.0f}%{m['dd']:>7.0f}%")
out.append("  READ: if 25-40 all strong → robust plateau. if only 30 → overfit-sensitive.")
text="\n".join(out); print(text)
open('/app/logs/factor_attribution_report.txt','w').write(text)
