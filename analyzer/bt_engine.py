#!/usr/bin/env python3
"""باكتيست تاريخي: كل مؤشر standalone + الأزواج، على klines data.binance.vision.
يطابق منطق البوت: _calculate_levels + triple-barrier (break-even بعد T1، trailing 2.5% بعد T2، 24h/48h).
تجميع تدريجي (memory-safe) — لا تخزين صفقات خام (تفادي OOM). إحصاءات عند fee=0% و0.6%.
المخرجات: PF/Expectancy/WR/n لكل مؤشر ولكل زوج، إجمالي + per-year (walk-forward) + جدول مركّز للخمسة.

قيود الصلاحية: order_book غير قابل للاختبار (لا عمق سوق تاريخي) — مُستبعد.
داخل الشمعة: أهداف(high) قبل الستوب(low) = تحيّز متفائل (مقصود). غير متداخل.
"""
import os, sys, zipfile, glob, json
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
import ta

DATA="/app/logs/bt_data"
TFS=["1h","4h","1d"]
TF_HOURS={"1h":1.0,"4h":4.0,"1d":24.0}
FEES=[0.0,0.6]; PRIMARY=0.6
MAX_SL={'1d':0.03,'4h':0.05,'1h':0.04,'15m':0.02}
WARM=210
INDS=['rsi','bollinger','stoch_rsi','rsi_divergence','fibonacci','macd','ema_cross','volume','obv']
USED=['rsi','bollinger','stoch_rsi','rsi_divergence','fibonacci']

def load(sym,tf):
    files=sorted(glob.glob(f"{DATA}/{sym}/{tf}/{sym}-{tf}-*.zip"))
    if not files: return None
    rows=[]
    for f in files:
        try:
            z=zipfile.ZipFile(f); n=z.namelist()[0]
            for ln in z.read(n).decode().splitlines():
                p=ln.split(',')
                rows.append((int(p[0]),float(p[1]),float(p[2]),float(p[3]),float(p[4]),float(p[5])))
        except Exception: pass
    if len(rows)<WARM+5: return None
    df=pd.DataFrame(rows,columns=['t','open','high','low','close','volume']).drop_duplicates('t').sort_values('t').reset_index(drop=True)
    df['t']=df['t'].apply(lambda x: x//1000 if x>1e14 else x)  # 2025 files use microseconds
    return df

def indicators(df):
    df['rsi']=ta.momentum.RSIIndicator(df['close'],window=14).rsi()
    df['ema20']=ta.trend.EMAIndicator(df['close'],window=20).ema_indicator()
    df['ema50']=ta.trend.EMAIndicator(df['close'],window=50).ema_indicator()
    df['ema200']=ta.trend.EMAIndicator(df['close'],window=200).ema_indicator()
    bb=ta.volatility.BollingerBands(df['close'],window=20,window_dev=2.0)
    df['bb_u']=bb.bollinger_hband(); df['bb_l']=bb.bollinger_lband()
    df['atr']=ta.volatility.AverageTrueRange(df['high'],df['low'],df['close'],window=14).average_true_range()
    st=ta.momentum.StochRSIIndicator(df['close'],window=14,smooth1=14,smooth2=3)
    df['stoch_k']=st.stochrsi_k(); df['stoch_d']=st.stochrsi_d()
    df['obv']=ta.volume.OnBalanceVolumeIndicator(df['close'],df['volume']).on_balance_volume()
    df['obv_ema']=ta.trend.EMAIndicator(df['obv'],window=20).ema_indicator()
    df['vma']=df['volume'].rolling(20).mean(); df['vratio']=df['volume']/df['vma']
    macd=ta.trend.MACD(df['close'],window_slow=26,window_fast=12,window_sign=9)
    df['macd']=macd.macd(); df['macd_sig']=macd.macd_signal()
    return df

def rsi_div(df,i,lb=14):
    if i<lb*2: return False
    try:
        recent=df.iloc[i-lb:i]; older=df.iloc[i-2*lb:i-lb]
        rli=recent['low'].idxmin(); oli=older['low'].idxmin()
        return (recent.loc[rli,'low']<older.loc[oli,'low']) and (recent.loc[rli,'rsi']>older.loc[oli,'rsi'])
    except Exception: return False

def fib_hit(df,i,lb=50):
    if i<lb: return False
    r=df.iloc[i-lb:i]; hi=r['high'].max(); lo=r['low'].min()
    if hi<=lo: return False
    d=hi-lo; cp=df.iloc[i]['close']
    for lv in (hi-0.382*d,hi-0.5*d,hi-0.618*d):
        if lv>0 and abs(cp-lv)/lv<=0.02: return True
    return False

def levels(df,i,tf):
    last=df.iloc[i]; atr=float(last['atr']); close=float(last['close'])
    rec=df.iloc[max(0,i-19):i+1]; sup=float(rec['low'].min()); res=float(rec['high'].max())
    entry=close; stop=max(entry-atr*1.5, sup*0.99)
    if stop>=entry: stop=entry*0.97
    cap=MAX_SL.get(tf,0.04); mr=entry*cap
    if (entry-stop)>mr: stop=entry-mr
    risk=entry-stop
    t1=entry+risk*1.0; t2=entry+risk*1.8; t3=entry+risk*2.2
    if t1>res>entry: t1=res*0.99
    return entry,stop,t1,t2,t3

def simulate(df,i,tf):
    entry,stop,t1,t2,t3=levels(df,i,tf)
    if entry<=0 or pd.isna(stop): return None
    hh=TF_HOURS[tf]; peak=entry; ht=0; n=len(df)
    for j in range(i+1,n):
        hi=df.iat[j,2]; lo=df.iat[j,3]; cl=df.iat[j,4]
        hours=(j-i)*hh
        if hi>=t3 and ht<3: ht=3
        elif hi>=t2 and ht<2: ht=2
        elif hi>=t1 and ht<1: ht=1
        if hi>peak: peak=hi
        if ht==3: return ((t3-entry)/entry*100, j)
        if ht>=2: eff=max(t1, peak*(1-2.5/100))
        elif ht>=1: eff=entry
        else: eff=stop
        if lo<=eff: return ((eff-entry)/entry*100, j)
        if hours>=24 and ht==1: return ((cl-entry)/entry*100, j)
        if hours>=48: return ((cl-entry)/entry*100, j)
    return None

# ---- incremental accumulator ----
def _blank():
    return {'n':0,'gsum':0.0,'pos':{f:0.0 for f in FEES},'neg':{f:0.0 for f in FEES},'win':{f:0 for f in FEES}}
def add(store,key,year,g):
    d=store.setdefault(key,{})
    for scope in ('all',year):
        s=d.get(scope)
        if s is None: s=_blank(); d[scope]=s
        s['n']+=1; s['gsum']+=g
        for f in FEES:
            net=g-f
            if net>0: s['pos'][f]+=net; s['win'][f]+=1
            else: s['neg'][f]+=-net
def met(s,fee=PRIMARY):
    if not s or s['n']==0: return None
    n=s['n']; pos=s['pos'][fee]; neg=s['neg'][fee]
    pf=(pos/neg) if neg>0 else float('inf')
    return {'n':n,'wr':s['win'][fee]/n*100,'exp':s['gsum']/n-fee,'pf':pf}

def trigger(df,i,ind):
    r=df.iloc[i]
    if ind=='rsi': return 20<=r['rsi']<40
    if ind=='bollinger':
        rng=r['bb_u']-r['bb_l']; return rng>0 and (r['close']-r['bb_l'])/rng<=0.3
    if ind=='stoch_rsi': return (not pd.isna(r['stoch_k'])) and r['stoch_k']<0.2 and r['stoch_k']>r['stoch_d']
    if ind=='rsi_divergence': return rsi_div(df,i)
    if ind=='fibonacci': return fib_hit(df,i)
    if ind=='macd':
        p=df.iloc[i-1]; return (not pd.isna(r['macd'])) and (p['macd']<=p['macd_sig']) and (r['macd']>r['macd_sig'])
    if ind=='ema_cross':
        p=df.iloc[i-1]; return (not pd.isna(r['ema50'])) and (p['ema20']<=p['ema50']) and (r['ema20']>r['ema50'])
    if ind=='volume': return (not pd.isna(r['vratio'])) and r['vratio']>1.5
    if ind=='obv': return (not pd.isna(r['obv_ema'])) and r['obv']>r['obv_ema']
    return False

def run(syms,tag=""):
    single={}; pairs={}
    for si,sym in enumerate(syms):
        for tf in TFS:
            df=load(sym,tf)
            if df is None: continue
            df=indicators(df)
            L=len(df)
            years=pd.to_datetime(df['t'],unit='ms').dt.year.values
            trig={k:np.zeros(L,bool) for k in INDS}
            for i in range(WARM,L-1):
                for k in INDS:
                    try:
                        if trigger(df,i,k): trig[k][i]=True
                    except Exception: pass
            # SINGLE non-overlapping
            for k in INDS:
                idx=np.nonzero(trig[k])[0]; nxt=WARM
                for i in idx:
                    if i<nxt or i>=L-1: continue
                    res=simulate(df,i,tf)
                    if res is None: continue
                    add(single,k,int(years[i]),res[0]); nxt=res[1]+1
            # PAIRS non-overlapping
            for a in range(len(INDS)):
                for b in range(a+1,len(INDS)):
                    ka,kb=INDS[a],INDS[b]
                    both=np.nonzero(trig[ka]&trig[kb])[0]
                    if len(both)==0: continue
                    key=f"{ka}+{kb}"; nxt=WARM
                    for i in both:
                        if i<nxt or i>=L-1: continue
                        res=simulate(df,i,tf)
                        if res is None: continue
                        add(pairs,key,int(years[i]),res[0]); nxt=res[1]+1
        if (si+1)%25==0: print(f"  [{tag}] processed {si+1}/{len(syms)} symbols",flush=True)
    return single,pairs

def fmt(m):
    if not m: return "n=0"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.3f}"
    return f"n={m['n']:>7}  WR={m['wr']:>5.1f}%  Exp(net%)={m['exp']:>+7.3f}  PF={pf}"

def ycell(store,key,y):
    s=store.get(key,{}).get(y); m=met(s,PRIMARY)
    if not m: return 'n0'
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.2f}"
    return f"PF{pf}(n{m['n']})"

if __name__=="__main__":
    limit=int(sys.argv[1]) if len(sys.argv)>1 else 0
    syms=[s.strip() for s in open("/app/bt_symbols.txt") if s.strip()]
    syms=[s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms=syms[:limit]
    print(f"running on {len(syms)} symbols (with data). fees={FEES}",flush=True)
    single,pairs=run(syms,tag="main")
    # persist compact aggregated stats (tiny) for re-analysis
    def dump(store):
        return {k:{str(sc):{'n':s['n'],'gsum':s['gsum'],
                'pos':s['pos'],'neg':s['neg'],'win':s['win']} for sc,s in d.items()} for k,d in store.items()}
    with open('/app/logs/bt_stats.json','w') as f:
        json.dump({'fees':FEES,'n_symbols':len(syms),'single':dump(single),'pairs':dump(pairs)},f)

    out=[]
    out.append(f"HISTORICAL BACKTEST — {len(syms)} symbols, TFs={TFS}, fee={PRIMARY}% net (gross also stored), order_book EXCLUDED")
    out.append("="*96)
    out.append("STANDALONE INDICATORS (net, non-overlapping). gross PF in []")
    out.append("="*96)
    rows=sorted([(k,met(single[k].get('all'))) for k in single], key=lambda x:(x[1]['exp'] if x[1] else -9), reverse=True)
    for k,m in rows:
        g=met(single[k].get('all'),0.0)
        gp='inf' if (g and g['pf']==float('inf')) else (f"{g['pf']:.3f}" if g else '-')
        out.append(f"{k:<16}{fmt(m)}   [grossPF={gp}]")
    out.append("")
    out.append("="*96)
    out.append("FOCUSED — currently-USED mean-reversion indicators (the key table). net@%.1f%%, per-year." % PRIMARY)
    out.append("="*96)
    out.append(f"{'indicator':<16}{'n':>8}{'PF':>7}{'gPF':>7}{'Exp%':>8}   {'2023':>15}{'2024':>15}{'2025':>15}")
    out.append("-"*94)
    for k in USED:
        m=met(single[k].get('all')); g=met(single[k].get('all'),0.0)
        pf='inf' if (m and m['pf']==float('inf')) else (f"{m['pf']:.3f}" if m else 'n0')
        gpf='inf' if (g and g['pf']==float('inf')) else (f"{g['pf']:.3f}" if g else '-')
        ex=f"{m['exp']:+.3f}" if m else '-'; n=m['n'] if m else 0
        out.append(f"{k:<16}{n:>8}{pf:>7}{gpf:>7}{ex:>8}   {ycell(single,k,2023):>15}{ycell(single,k,2024):>15}{ycell(single,k,2025):>15}")
    out.append("gPF = gross PF (0% fee) — used for order_book inference vs live gross PF 0.73.")
    out.append("SUCCESS bar: single PF>1.05 large-n | pair PF>1.10 n>=100 | stable across years.")
    out.append("")
    out.append("="*96)
    out.append("per-YEAR PF (walk-forward) — all standalone indicators:")
    for k in INDS:
        out.append(f"  {k:<16}2023:{ycell(single,k,2023):>15} 2024:{ycell(single,k,2024):>15} 2025:{ycell(single,k,2025):>15}")
    out.append("")
    out.append("="*96)
    out.append("TOP 20 PAIRS by net Expectancy (min n=100)")
    out.append("="*96)
    pr=[(k,met(pairs[k].get('all'))) for k in pairs]
    pr=[(k,m) for k,m in pr if m and m['n']>=100]
    pr.sort(key=lambda x:x[1]['exp'],reverse=True)
    for k,m in pr[:20]:
        out.append(f"{k:<28}{fmt(m)}")
    out.append("")
    out.append(f"pairs n>=100: {len(pr)} | net PF>1: {sum(1 for _,m in pr if m['pf']>1)}")
    prof=[(k,m) for k,m in (rows+pr) if m and m['n']>=100 and m['pf']>1]
    out.append(f"ANY config (single or pair) n>=100 AND net PF>1: {len(prof)}")
    for k,m in sorted(prof,key=lambda x:x[1]['pf'],reverse=True)[:10]:
        out.append(f"  {k:<28}{fmt(m)}")
    text="\n".join(out); print(text)
    with open('/app/logs/bt_result.txt','w') as f: f.write(text)
    print("WROTE /app/logs/bt_result.txt",flush=True)
