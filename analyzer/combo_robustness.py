#!/usr/bin/env python3
"""
إعادة اختبار أفضل 10 توليفات: استقرار زمني، إجهاد رسوم، شروط score، أفضل combo n>=100.
قيد فادح معروف: 95% من الصفقات في أبريل 2026 → التحقّق الزمني محدود جداً (نُظهره بالأرقام).
كل القيم net بعد الرسوم. profit_usdt إجمالي (gross) ومركز 50$.
"""
import sys, asyncio, json
import numpy as np, pandas as pd
sys.path.insert(0, '/app')
from shared.database import Database

POSITION = 50.0
INDICATORS = ['rsi','macd','ema_cross','bollinger','volume','stoch_rsi',
              'obv','rsi_divergence','fibonacci','order_book','btc_trend']
def fee_usdt(pct): return pct/100.0*POSITION   # 0.3->0.15, 0.6->0.30, 0.8->0.40

def metrics(g, fee=0.3):
    n=len(g)
    if n==0: return dict(n=0)
    wins=int((g.result=='WIN').sum())
    net=g.profit_usdt.values - fee_usdt(fee)
    pos=net[net>0].sum(); neg=-net[net<0].sum()
    pf=(pos/neg) if neg>0 else (np.inf if pos>0 else 0.0)
    return dict(n=n, wr=wins/n*100, exp=float(net.mean()), pf=pf)

async def main():
    rows = await Database.fetch("""
        SELECT tr.result, tr.profit_percent, tr.profit_usdt, tr.exit_time,
               s.score, s.score_details, s.market_condition
        FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
        ORDER BY tr.exit_time ASC
    """)
    recs=[]
    for r in rows:
        d=r['score_details']; d=json.loads(d) if isinstance(d,str) else dict(d)
        rec=dict(result=r['result'],
                 profit_usdt=float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POSITION,
                 exit_time=r['exit_time'], ym=r['exit_time'].strftime('%Y-%m'),
                 score=float(r['score']) if r['score'] else 0.0)
        for ind in INDICATORS:
            try: rec[ind]=float(d.get(ind,0) or 0)
            except: rec[ind]=0.0
        recs.append(rec)
    df=pd.DataFrame(recs)
    df['combo']=df.apply(lambda r:'+'.join([i for i in INDICATORS if r[i]>0]) or '(none)', axis=1)
    months=sorted(df.ym.unique())
    out=[]
    out.append(f"Data span: {df.exit_time.min().date()} → {df.exit_time.max().date()} | N={len(df)}")
    out.append("Monthly totals: " + " | ".join(f"{m}:{int((df.ym==m).sum())}" for m in months))
    out.append("⚠ 95% in 2026-04 → temporal/walk-forward is structurally weak. OOS holdout = May+Jun only.")
    out.append("")

    # rank combos by net exp @0.3, n>=20  → top 10
    cand=[]
    for combo,g in df.groupby('combo'):
        if len(g)<20: continue
        m=metrics(g,0.3); m['combo']=combo; cand.append(m)
    cand.sort(key=lambda x:x['exp'], reverse=True)
    top10=cand[:10]

    out.append("="*135)
    out.append("TOP 10 COMBOS — robustness. Exp@X = net expectancy $/trade at X% round-trip cost.")
    out.append("="*135)
    hdr=f"{'#':>2} {'combo':<46}{'n':>5}{'WR%':>6}{'PF':>6}{'Exp@0.3':>9}{'Exp@0.6':>9}{'Exp@0.8':>9} {'still+@0.8':>10}"
    out.append(hdr); out.append("-"*len(hdr))
    for i,c in enumerate(top10,1):
        g=df[df.combo==c['combo']]
        e3=metrics(g,0.3)['exp']; e6=metrics(g,0.6)['exp']; e8=metrics(g,0.8)['exp']
        pf=c['pf']; pfs='inf' if pf==np.inf else f"{pf:.2f}"
        out.append(f"{i:>2} {c['combo']:<46}{c['n']:>5}{c['wr']:>6.1f}{pfs:>6}{e3:>9.4f}{e6:>9.4f}{e8:>9.4f}{('YES' if e8>0 else 'no'):>10}")
    out.append("")

    # per-combo monthly + OOS holdout + score thresholds
    out.append("="*135)
    out.append("PER-COMBO: monthly split (n/WR%/Exp@0.3$) + OOS(May+Jun) + score-threshold counts")
    out.append("="*135)
    for i,c in enumerate(top10,1):
        g=df[df.combo==c['combo']]
        out.append(f"#{i} {c['combo']}  (total n={len(g)})")
        # monthly
        mline="   monthly: "
        for m in months:
            sub=g[g.ym==m]
            if len(sub)==0: mline+=f"[{m}: 0] "
            else:
                mm=metrics(sub,0.3); mline+=f"[{m}: n={mm['n']} WR={mm['wr']:.0f}% E={mm['exp']:+.3f}] "
        out.append(mline)
        # OOS holdout
        ins=g[g.ym=='2026-04']; oos=g[g.ym!='2026-04']
        si=metrics(ins,0.3); so=metrics(oos,0.3)
        oos_str = (f"n={so['n']} WR={so['wr']:.0f}% E={so['exp']:+.3f}" if so.get('n',0)>0 else "n=0 (NO OOS DATA)")
        out.append(f"   in-sample(Apr): n={si.get('n',0)} E={si.get('exp',0):+.3f}   |   OOS(May+Jun): {oos_str}")
        # score thresholds
        c4=int((g.score>=4).sum()); c5=int((g.score>=5).sum()); c6=int((g.score>=6).sum())
        out.append(f"   score≥4: {c4}   score≥5: {c5}   score≥6: {c6}")
        # stability: share of total positive PnL from single biggest month
        net=g.profit_usdt - fee_usdt(0.3)
        tot=net.sum()
        by_m=(g.assign(net=net).groupby('ym').net.sum())
        if tot!=0:
            conc = by_m.max()/tot if tot>0 else float('nan')
        out.append(f"   total net PnL={tot:+.2f}$  by-month={ {m: round(float(by_m.get(m,0.0)),2) for m in months} }")
        out.append("")

    # Q5: best combo with n>=100
    out.append("="*135)
    out.append("BEST COMBO WITH n>=100 (ranked by Exp@0.3, with fee stress + OOS)")
    out.append("="*135)
    big=[c for c in cand if c['n']>=100]
    big.sort(key=lambda x:x['exp'], reverse=True)
    if not big:
        out.append("none with n>=100")
    else:
        for c in big:
            g=df[df.combo==c['combo']]
            e3=metrics(g,0.3)['exp']; e6=metrics(g,0.6)['exp']; e8=metrics(g,0.8)['exp']
            oos=g[g.ym!='2026-04']; so=metrics(oos,0.3)
            oos_str=(f"OOS n={so['n']} E={so['exp']:+.3f}" if so.get('n',0)>0 else "OOS n=0")
            pf=c['pf']; pfs='inf' if pf==np.inf else f"{pf:.2f}"
            out.append(f"{c['combo']:<46} n={c['n']} WR={c['wr']:.1f}% PF={pfs} "
                       f"E@0.3={e3:+.4f} E@0.6={e6:+.4f} E@0.8={e8:+.4f} | {oos_str}")
        out.append("")
        bestc=big[0]
        out.append(f">>> BEST n>=100: {bestc['combo']}  Exp@0.3={bestc['exp']:+.4f}$ "
                   f"({'PROFITABLE' if bestc['exp']>0 else 'still NEGATIVE'})")

    text="\n".join(out); print(text)
    with open('/app/logs/combo_robustness_report.txt','w') as f: f.write(text)

asyncio.run(main())
