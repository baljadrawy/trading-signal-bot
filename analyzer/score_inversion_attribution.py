#!/usr/bin/env python3
"""انعكاس score: ما المؤشر الذي يضيف النقطة عند 3→4، وأثر كل مؤشر على Expectancy.
النطاق: bearish+sideways. gross بلا رسوم. مركز 50$.
تحذير: descriptive/marginal — مُربك بالتداخل (co-occurrence)، ليس سببياً."""
import sys, asyncio, json
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from shared.database import Database
POS=50.0
IND=['rsi','macd','ema_cross','bollinger','volume','stoch_rsi','obv','rsi_divergence','fibonacci','order_book','btc_trend']

async def main():
    rows=await Database.fetch("""
        SELECT tr.result, tr.profit_usdt, tr.profit_percent, s.score, s.score_details
        FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
          AND s.market_condition IN ('bearish','sideways')
    """)
    recs=[]
    for r in rows:
        d=r['score_details']; d=json.loads(d) if isinstance(d,str) else dict(d)
        rec=dict(result=r['result'], score=float(r['score']) if r['score'] else 0.0,
                 pu=float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POS)
        for i in IND:
            try: rec[i]=float(d.get(i,0) or 0)
            except: rec[i]=0.0
        recs.append(rec)
    df=pd.DataFrame(recs)
    out=[]
    out.append(f"bearish+sideways  N={len(df)}  (gross)")
    out.append("")

    # === A) ما الذي يضيف النقطة 3→4؟ ===
    out.append("="*112)
    out.append("(A) SCORE 3 → 4 : per-indicator presence & mean contribution. الأكبر فرقاً = 'مضيف النقطة'")
    out.append("="*112)
    s3=df[df.score==3]; s4=df[df.score==4]; s5=df[df.score>=5]
    out.append(f"n: score3={len(s3)}  score4={len(s4)}  score5+={len(s5)}")
    out.append(f"{'indicator':<15}{'fire%@3':>9}{'fire%@4':>9}{'Δfire':>8}{'mean@3':>9}{'mean@4':>9}{'Δmean':>9}")
    out.append("-"*68)
    rowsA=[]
    for i in IND:
        f3=(s3[i]>0).mean()*100; f4=(s4[i]>0).mean()*100
        m3=s3[i].mean(); m4=s4[i].mean()
        rowsA.append((i, f3, f4, f4-f3, m3, m4, m4-m3))
    for i,f3,f4,df_,m3,m4,dm in sorted(rowsA, key=lambda x:x[6], reverse=True):
        out.append(f"{i:<15}{f3:>9.1f}{f4:>9.1f}{df_:>+8.1f}{m3:>9.3f}{m4:>9.3f}{dm:>+9.3f}")
    out.append("→ المؤشر بأعلى Δmean/Δfire هو الذي يرفع السكور من 3 إلى 4 عادةً.")
    out.append("")

    # === B) أثر كل مؤشر على Expectancy (marginal lift) ===
    out.append("="*112)
    out.append("(B) MARGINAL EFFECT ON EXPECTANCY: E[gross exp | fired] vs E[ | not fired]  (within bear+side)")
    out.append("="*112)
    out.append(f"{'indicator':<15}{'n_fired':>8}{'E_fired$':>10}{'n_not':>7}{'E_not$':>9}{'LIFT$':>9}  verdict")
    out.append("-"*78)
    rowsB=[]
    for i in IND:
        fired=df[df[i]>0]; notf=df[df[i]==0]
        ef=fired.pu.mean() if len(fired)>0 else np.nan
        en=notf.pu.mean() if len(notf)>0 else np.nan
        lift=(ef-en) if (len(fired)>0 and len(notf)>0) else np.nan
        rowsB.append((i,len(fired),ef,len(notf),en,lift))
    for i,nf,ef,nn,en,lift in sorted(rowsB, key=lambda x: (-1e9 if np.isnan(x[5]) else x[5]), reverse=True):
        if nf==0:
            out.append(f"{i:<15}{0:>8}{'—':>10}{nn:>7}{en:>9.3f}{'—':>9}  never fired")
            continue
        v = 'HELPS' if (not np.isnan(lift) and lift>0.03) else ('HURTS' if (not np.isnan(lift) and lift<-0.03) else 'neutral')
        ls = '—' if np.isnan(lift) else f"{lift:+.3f}"
        es = '—' if np.isnan(en) else f"{en:.3f}"
        out.append(f"{i:<15}{nf:>8}{ef:>10.3f}{nn:>7}{es:>9}{ls:>9}  {v}")
    out.append("LIFT>0 = وجود المؤشر يرفع التوقّع. LIFT<0 = يفسد الصفقة. (تحذير: تداخل/مُربك.)")
    out.append("")

    # === C) per-score expectancy recap ===
    out.append("="*112)
    out.append("(C) RECAP — gross expectancy & PF by score")
    out.append("="*112)
    for lbl,g in [('score=3',s3),('score=4',s4),('score=5+',s5)]:
        pu=g.pu.values; pos=pu[pu>0].sum(); neg=-pu[pu<0].sum()
        pf=(pos/neg) if neg>0 else float('inf')
        out.append(f"{lbl:<10} n={len(g):>4}  WR={(g.result=='WIN').mean()*100:>5.1f}%  grossExp={pu.mean():>+8.4f}$  grossPF={pf:.3f}")

    text="\n".join(out); print(text)
    with open('/app/logs/score_inversion_report.txt','w') as f: f.write(text)
asyncio.run(main())
