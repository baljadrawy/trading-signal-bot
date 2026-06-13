#!/usr/bin/env python3
"""اختبار 'الأمل': مجموعة bearish+sideways — breakeven WR, gross/net PF, التوزيع الزمني."""
import sys, asyncio, json
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from shared.database import Database
POS=50.0
def fu(p): return p/100*POS

def stats(g, fee):
    n=len(g)
    if n==0: return None
    net=g.profit_usdt.values - fu(fee)
    wins=int((g.result=='WIN').sum())
    aw=net[net>0].mean() if (net>0).any() else 0.0
    al=-net[net<0].mean() if (net<0).any() else 0.0
    pos=net[net>0].sum(); neg=-net[net<0].sum()
    pf=(pos/neg) if neg>0 else float('inf')
    be=al/(aw+al)*100 if (aw+al)>0 else float('nan')
    return dict(n=n, wr=wins/n*100, exp=net.mean(), pf=pf, aw=aw, al=al, be=be, tot=net.sum())

async def main():
    rows=await Database.fetch("""
        SELECT tr.result, tr.profit_percent, tr.profit_usdt, tr.exit_time, s.market_condition, s.timeframe
        FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
          AND s.market_condition IN ('bearish','sideways')
    """)
    df=pd.DataFrame([dict(result=r['result'],
        profit_usdt=float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POS,
        ym=r['exit_time'].strftime('%Y-%m'), tf=r['timeframe'] or 'NA',
        cond=r['market_condition']) for r in rows])
    out=[]
    out.append(f"GROUP = bearish + sideways | N={len(df)}")
    out.append("")
    g=stats(df,0.0); g3=stats(df,0.3); g6=stats(df,0.6); g8=stats(df,0.8)
    out.append("OVERALL:")
    out.append(f"  GROSS (0%):  WR={g['wr']:.1f}%  Exp={g['exp']:+.4f}$  PF={g['pf']:.3f}  avgWin={g['aw']:.3f}  avgLoss={g['al']:.3f}  breakeven_WR={g['be']:.1f}%  gap={g['be']-g['wr']:+.1f}pp")
    out.append(f"  NET 0.3%:    WR={g3['wr']:.1f}%  Exp={g3['exp']:+.4f}$  PF={g3['pf']:.3f}  breakeven_WR={g3['be']:.1f}%  gap={g3['be']-g3['wr']:+.1f}pp")
    out.append(f"  NET 0.6%:    Exp={g6['exp']:+.4f}$  PF={g6['pf']:.3f}  breakeven_WR={g6['be']:.1f}%")
    out.append(f"  NET 0.8%:    Exp={g8['exp']:+.4f}$  PF={g8['pf']:.3f}  breakeven_WR={g8['be']:.1f}%")
    out.append("")
    out.append("TEMPORAL (gross & net@0.3 per month):")
    out.append(f"  {'month':<9}{'n':>6}{'WR%':>7}{'grossExp':>10}{'grossPF':>9}{'netExp@0.3':>12}{'netPF':>8}")
    for m in sorted(df.ym.unique()):
        sm=df[df.ym==m]; a=stats(sm,0.0); b=stats(sm,0.3)
        out.append(f"  {m:<9}{a['n']:>6}{a['wr']:>7.1f}{a['exp']:>10.4f}{a['pf']:>9.3f}{b['exp']:>12.4f}{b['pf']:>8.3f}")
    out.append("")
    ins=df[df.ym=='2026-04']; oos=df[df.ym!='2026-04']
    ai=stats(ins,0.0); ao=stats(oos,0.0) if len(oos)>0 else None
    out.append("IN-SAMPLE (Apr) vs OOS (May+Jun), GROSS:")
    out.append(f"  in-sample: n={ai['n']} WR={ai['wr']:.1f}% Exp={ai['exp']:+.4f}$ PF={ai['pf']:.3f}")
    if ao: out.append(f"  OOS:       n={ao['n']} WR={ao['wr']:.1f}% Exp={ao['exp']:+.4f}$ PF={ao['pf']:.3f}")
    else:  out.append("  OOS: n=0")
    out.append("")
    out.append("by timeframe within bearish+sideways (gross):")
    for tf,sm in df.groupby('tf'):
        a=stats(sm,0.0)
        out.append(f"  {tf:<5} n={a['n']:>4} WR={a['wr']:.1f}% grossExp={a['exp']:+.4f}$ grossPF={a['pf']:.3f}")
    text="\n".join(out); print(text)
    with open('/app/logs/bear_side_hope_report.txt','w') as f: f.write(text)
asyncio.run(main())
