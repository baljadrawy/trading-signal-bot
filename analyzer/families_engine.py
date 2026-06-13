#!/usr/bin/env python3
"""باكتيست عائلات OHLCV غير الانعكاسية على نفس بيانات data.binance.vision المخزّنة.
العائلات: breakout, volatility_expansion, trend_following (لكل رمز، خروج ATR-trailing)
        + cross_sectional_momentum (محفظة: أقوى 10% عائداً، إعادة موازنة أسبوعية، 1d).
long-only (spot). رسوم 0.6%. مخرجات: PF/Exp/WR/n + per-year + مقياس ثبات min(yearly PF).
الخروج هنا 'let winners run' (ATR-trailing) — مناسب للترند/الكسر، عكس خروج البوت الانعكاسي.
"""
import sys, glob, json
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from bt_engine import load, indicators, TF_HOURS, FEE_PCT, WARM, DATA, agg

TFS=["1h","4h","1d"]
ATR_MULT=2.0
MAX_HOLD={"1h":48,"4h":30,"1d":20}

def extras(df):
    df['hh20']=df['high'].rolling(20).max().shift(1)
    df['width']=(df['bb_u']-df['bb_l'])
    df['wmin50']=df['width'].rolling(50).min()
    return df

def trg_breakout(df,i):
    r=df.iloc[i]
    return (not pd.isna(r['hh20'])) and r['close']>r['hh20'] and (not pd.isna(r['vratio'])) and r['vratio']>1.5

def trg_volexp(df,i):
    r=df.iloc[i]; p=df.iloc[i-1]
    if pd.isna(r['wmin50']) or pd.isna(p['width']): return False
    squeeze = p['width'] <= r['wmin50']*1.15      # كان في انضغاط
    return squeeze and r['close']>r['bb_u']        # انفجار صعودي فوق العلوي

def trg_trend(df,i):
    r=df.iloc[i]; p=df.iloc[i-1]
    if pd.isna(r['ema200']): return False
    return r['close']>r['ema200'] and p['close']<=p['ema20'] and r['close']>r['ema20']

TRIGS={'breakout':trg_breakout,'volatility_expansion':trg_volexp,'trend_following':trg_trend}

def sim_trail(df,i,tf):
    entry=float(df.iat[i,4]); atr=float(df['atr'].iat[i])
    if entry<=0 or pd.isna(atr) or atr<=0: return None
    stop=entry-ATR_MULT*atr; peak=entry; mh=MAX_HOLD[tf]
    end=min(len(df),i+1+mh)
    for j in range(i+1,end):
        hi=float(df.iat[j,2]); lo=float(df.iat[j,3])
        if hi>peak:
            peak=hi; stop=max(stop,peak-ATR_MULT*atr)
        if lo<=stop:
            return ((stop-entry)/entry*100, j)
    j=min(len(df)-1,i+mh)
    return ((float(df.iat[j,4])-entry)/entry*100, j)

def run_persymbol(syms):
    res={k:[] for k in TRIGS}
    for si,sym in enumerate(syms):
        for tf in TFS:
            df=load(sym,tf)
            if df is None: continue
            df=extras(indicators(df))
            years=pd.to_datetime(df['t'],unit='ms').dt.year.values
            for fam,fn in TRIGS.items():
                nxt=WARM
                for i in range(WARM,len(df)-1):
                    if i<nxt: continue
                    try: fire=fn(df,i)
                    except Exception: fire=False
                    if not fire: continue
                    s=sim_trail(df,i,tf)
                    if s is None: continue
                    res[fam].append((s[0],int(years[i]),'na'))
                    nxt=s[1]+1
        if (si+1)%25==0: print(f"  [persymbol] {si+1}/{len(syms)}",flush=True)
    return res

def run_xsec(syms):
    """cross-sectional momentum على 1d: أسبوعياً، long أقوى 10% بعائد 30 يوم، حجز 7 أيام."""
    closes={}
    for sym in syms:
        df=load(sym,"1d")
        if df is None: continue
        s=pd.Series(df['close'].values, index=pd.to_datetime(df['t'],unit='ms').dt.normalize())
        closes[sym]=s[~s.index.duplicated()]
    if len(closes)<20: return []
    panel=pd.DataFrame(closes).sort_index()
    panel=panel.dropna(how='all')
    trades=[]
    idx=panel.index
    LOOK=30; HOLD=7
    i=LOOK
    while i+HOLD < len(idx):
        date=idx[i]
        past=panel.iloc[i-LOOK]; now=panel.iloc[i]
        ret=(now/past-1).dropna()
        ret=ret[(past.notna())&(now.notna())]
        if len(ret)>=20:
            k=max(1,int(len(ret)*0.10))
            top=ret.sort_values(ascending=False).head(k).index
            fut=(panel.iloc[i+HOLD]/panel.iloc[i]-1)
            for sym in top:
                v=fut.get(sym,np.nan)
                if not pd.isna(v):
                    trades.append((float(v*100), int(date.year),'na'))
        i+=HOLD
    return trades

def stab(trades):
    cells={}
    for y in (2023,2024,2025):
        m=agg([t for t in trades if t[1]==y])
        cells[y]=m['pf'] if m else None
    vals=[v for v in cells.values() if v is not None]
    minpf=min(vals) if vals else None
    allpos=all((v is not None and v>1.0) for v in cells.values())
    return cells,minpf,allpos

def line(fam,trades):
    m=agg(trades)
    if not m: return f"{fam:<24} n=0"
    cells,minpf,allpos=stab(trades)
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.3f}"
    def yc(y):
        v=cells[y]; return 'n0' if v is None else ('inf' if v==float('inf') else f"{v:.2f}")
    mp='-' if minpf is None else f"{minpf:.2f}"
    return (f"{fam:<24}n={m['n']:>6} PF={pf:>6} Exp%={m['exp']:>+6.2f}  "
            f"2023:{yc(2023):>5} 2024:{yc(2024):>5} 2025:{yc(2025):>5}  minPF={mp:>5} allYrs>1={allpos}")

if __name__=="__main__":
    limit=int(sys.argv[1]) if len(sys.argv)>1 else 0
    syms=[s.strip() for s in open("/app/bt_symbols.txt") if s.strip()]
    syms=[s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms=syms[:limit]
    print(f"families backtest on {len(syms)} symbols, fee={FEE_PCT}%",flush=True)
    ps=run_persymbol(syms)
    print("computing cross-sectional momentum...",flush=True)
    xs=run_xsec(syms)
    allres={**ps,'cross_sectional_momentum':xs}
    with open('/app/logs/families_raw.json','w') as f:
        json.dump({k:[[round(p,4),y,c] for p,y,c in v] for k,v in allres.items()}, f)
    out=[]
    out.append(f"OHLCV NON-REVERSION FAMILIES — {len(syms)} symbols, TFs={TFS}, fee={FEE_PCT}% net, long-only, ATR-trailing exit")
    out.append("ranking priority: annual STABILITY (minPF) over headline PF")
    out.append("="*120)
    order=sorted(allres.items(), key=lambda kv:(stab(kv[1])[1] if stab(kv[1])[1] is not None else -9), reverse=True)
    for fam,tr in order:
        out.append(line(fam,tr))
    out.append("")
    out.append("SUCCESS bar: family PF>1.05 with stable (all years >1.0) and large n.")
    text="\n".join(out); print(text)
    with open('/app/logs/families_result.txt','w') as f: f.write(text)
