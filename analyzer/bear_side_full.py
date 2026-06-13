#!/usr/bin/env python3
"""bearish+sideways فقط: مقاييس كاملة + تقسيم شهري + تقسيم score (3/4/5+). gross بلا رسوم."""
import sys, asyncio
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from shared.database import Database
POS=50.0

def stats(g):
    n=len(g)
    if n==0: return dict(n=0)
    p=g.profit_usdt.values; wins=int((g.result=='WIN').sum())
    aw=p[p>0].mean() if (p>0).any() else 0.0
    al=-p[p<0].mean() if (p<0).any() else 0.0
    pos=p[p>0].sum(); neg=-p[p<0].sum()
    pf=(pos/neg) if neg>0 else (float('inf') if pos>0 else 0.0)
    be=al/(aw+al)*100 if (aw+al)>0 else float('nan')
    return dict(n=n, wr=wins/n*100, exp=float(p.mean()), pf=pf, aw=aw, al=al, be=be)

def line(label, m):
    if m.get('n',0)==0: return f"{label:<14} n=0"
    pf='inf' if m['pf']==float('inf') else f"{m['pf']:.3f}"
    return (f"{label:<14} n={m['n']:>5}  WR={m['wr']:>5.1f}%  grossExp={m['exp']:>+8.4f}$  "
            f"grossPF={pf:>6}  avgWin={m['aw']:>6.3f}  avgLoss={m['al']:>6.3f}  breakevenWR={m['be']:>5.1f}%  gap={m['be']-m['wr']:>+5.1f}pp")

async def main():
    rows=await Database.fetch("""
        SELECT tr.result, tr.profit_percent, tr.profit_usdt, tr.exit_time, s.score
        FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
          AND s.market_condition IN ('bearish','sideways')
    """)
    df=pd.DataFrame([dict(result=r['result'],
        profit_usdt=float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POS,
        ym=r['exit_time'].strftime('%Y-%m'),
        score=float(r['score']) if r['score'] is not None else 0.0) for r in rows])
    out=[]
    out.append("="*130)
    out.append(f"bearish + sideways ONLY  —  N={len(df)}   (gross = before fees & slippage)")
    out.append("="*130)
    out.append(line("OVERALL", stats(df)))
    out.append("")
    out.append("── TEMPORAL split ──")
    for m in sorted(df.ym.unique()):
        out.append(line(m, stats(df[df.ym==m])))
    out.append("")
    out.append("── SCORE split ──")
    buckets=[('score=3', df[df.score==3]),
             ('score=4', df[df.score==4]),
             ('score=5+', df[df.score>=5])]
    for lbl,g in buckets:
        out.append(line(lbl, stats(g)))
    out.append("")
    out.append("── SCORE × MONTH (gross PF) — to see if any score bucket is stable across months ──")
    out.append(f"  {'bucket':<10}" + "".join(f"{m:>22}" for m in sorted(df.ym.unique())))
    for lbl,g in buckets:
        cells=""
        for m in sorted(df.ym.unique()):
            sm=g[g.ym==m]; s=stats(sm)
            if s.get('n',0)==0:
                cells+=f"{'n=0':>22}"
            else:
                pf='inf' if s['pf']==float('inf') else f"{s['pf']:.2f}"
                cell=f"n={s['n']}/WR{s['wr']:.0f}/PF{pf}"
                cells+=f"{cell:>22}"
        out.append(f"  {lbl:<10}{cells}")
    text="\n".join(out); print(text)
    with open('/app/logs/bear_side_full_report.txt','w') as f: f.write(text)
asyncio.run(main())
