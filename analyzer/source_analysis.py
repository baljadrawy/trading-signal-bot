#!/usr/bin/env python3
"""تحليل مصدر الـ2461 صفقة: حسب الرمز/الفريم/حالة السوق. net بعد 0.3% رسوم، مركز 50$."""
import sys, asyncio, json
import numpy as np, pandas as pd
sys.path.insert(0, '/app')
from shared.database import Database

POS=50.0; FEE=0.3; FEE_U=FEE/100*POS  # 0.15

def grp_metrics(g):
    n=len(g); wins=int((g.result=='WIN').sum())
    net_u=g.profit_usdt.values-FEE_U
    net_p=g.profit_percent.values-FEE
    pos=net_u[net_u>0].sum(); neg=-net_u[net_u<0].sum()
    pf=(pos/neg) if neg>0 else (np.inf if pos>0 else 0.0)
    return dict(n=n, wr=wins/n*100, exp=float(net_u.mean()),
                pf=pf, avg_ret=float(net_p.mean()), total=float(net_u.sum()))

def table(df, key, out, title, min_n=1, sort_desc=True, top=None):
    rows=[]
    for k,g in df.groupby(key):
        if len(g)<min_n: continue
        m=grp_metrics(g); m['key']=k; rows.append(m)
    rows.sort(key=lambda x:x['exp'], reverse=sort_desc)
    out.append("="*100); out.append(title); out.append("="*100)
    hdr=f"{key:<16}{'n':>6}{'WR%':>7}{'Exp_net$':>11}{'PF':>7}{'avgRet_n%':>11}{'totPnL$':>11}"
    out.append(hdr); out.append("-"*len(hdr))
    show=rows if top is None else rows[:top]
    for m in show:
        pf='inf' if m['pf']==np.inf else f"{m['pf']:.2f}"
        out.append(f"{str(m['key']):<16}{m['n']:>6}{m['wr']:>7.1f}{m['exp']:>11.4f}{pf:>7}{m['avg_ret']:>11.3f}{m['total']:>11.2f}")
    return rows

async def main():
    rows=await Database.fetch("""
        SELECT tr.result, tr.profit_percent, tr.profit_usdt, s.symbol, s.timeframe,
               s.market_condition
        FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
    """)
    df=pd.DataFrame([dict(result=r['result'],
        profit_percent=float(r['profit_percent']),
        profit_usdt=float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POS,
        symbol=r['symbol'], timeframe=r['timeframe'] or 'NA',
        market_condition=r['market_condition'] or 'NA') for r in rows])
    out=[]
    tot=(df.profit_usdt-FEE_U).sum()
    out.append(f"N={len(df)}  symbols={df.symbol.nunique()}  total net PnL={tot:+.2f}$  overall WR={(df.result=='WIN').mean()*100:.1f}%")
    out.append("")

    # حالة السوق
    table(df,'market_condition',out,"BY MARKET CONDITION (sorted by Exp desc)")
    out.append("")
    # الفريم
    table(df,'timeframe',out,"BY TIMEFRAME (sorted by Exp desc)")
    out.append("")

    # الرمز: top20 / bottom20 (كل الرموز) + نسخة n>=10
    sym=[]
    for k,g in df.groupby('symbol'):
        m=grp_metrics(g); m['key']=k; sym.append(m)
    sym.sort(key=lambda x:x['exp'], reverse=True)
    def dump(title, lst):
        out.append("="*100); out.append(title); out.append("="*100)
        hdr=f"{'symbol':<16}{'n':>6}{'WR%':>7}{'Exp_net$':>11}{'PF':>7}{'avgRet_n%':>11}{'totPnL$':>11}"
        out.append(hdr); out.append("-"*len(hdr))
        for m in lst:
            pf='inf' if m['pf']==np.inf else f"{m['pf']:.2f}"
            out.append(f"{str(m['key']):<16}{m['n']:>6}{m['wr']:>7.1f}{m['exp']:>11.4f}{pf:>7}{m['avg_ret']:>11.3f}{m['total']:>11.2f}")
    dump("TOP 20 SYMBOLS by Exp (all n)", sym[:20])
    out.append("")
    dump("BOTTOM 20 SYMBOLS by Exp (all n)", sym[-20:][::-1])
    out.append("")
    sym_big=[m for m in sym if m['n']>=10]
    dump(f"TOP 20 SYMBOLS by Exp — n>=10 only ({len(sym_big)} symbols qualify)", sym_big[:20])
    out.append("")
    dump("BOTTOM 20 SYMBOLS by Exp — n>=10 only", sym_big[-20:][::-1])
    out.append("")

    # ===== تركّز الخسارة (Pareto) =====
    out.append("="*100); out.append("LOSS CONCENTRATION (Pareto)"); out.append("="*100)
    npos=sum(1 for m in sym if m['total']>0); nneg=sum(1 for m in sym if m['total']<0)
    out.append(f"symbols net-positive: {npos} | net-negative: {nneg} | total symbols: {len(sym)}")
    losers=sorted([m for m in sym if m['total']<0], key=lambda x:x['total'])  # most negative first
    total_loss=sum(m['total'] for m in losers)
    out.append(f"sum of all symbol net losses = {total_loss:+.2f}$")
    cum=0
    for thr in [5,10,20,30]:
        cum=sum(m['total'] for m in losers[:thr])
        out.append(f"  worst {thr} symbols account for {cum:+.2f}$ = {cum/total_loss*100:.1f}% of total loss")
    out.append("worst 10 loss symbols (symbol: net$ , n):")
    for m in losers[:10]:
        out.append(f"   {m['key']:<14} {m['total']:>9.2f}$  n={m['n']}")
    # تركّز حسب الفريم/الحالة
    out.append("")
    out.append("net PnL by timeframe:")
    for k,g in df.groupby('timeframe'):
        out.append(f"   {k:<6} net={ (g.profit_usdt-FEE_U).sum():+.2f}$  n={len(g)}")
    out.append("net PnL by market condition:")
    for k,g in df.groupby('market_condition'):
        out.append(f"   {k:<10} net={ (g.profit_usdt-FEE_U).sum():+.2f}$  n={len(g)}")

    text="\n".join(out); print(text)
    with open('/app/logs/source_analysis_report.txt','w') as f: f.write(text)

asyncio.run(main())
