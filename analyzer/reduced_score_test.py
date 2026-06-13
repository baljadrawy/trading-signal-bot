#!/usr/bin/env python3
"""اختبار التقليل: هل حذف المؤشرات الضارة يحسّن الأداء؟ (live data, bear+side, gross)
نقارن: (1) الصفقات حيث لم يشتعل أي مؤشر ضار، (2) clean_score من الأربعة الجيدة فقط."""
import sys, asyncio, json
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
from shared.database import Database
POS=50.0; FEE_U=0.15
GOOD=['rsi','bollinger','macd','order_book']
BAD=['volume','stoch_rsi','ema_cross','fibonacci','obv']

def st(g, fee=0.0):
    n=len(g)
    if n==0: return "n=0"
    pu=g.pu.values - (fee/100*POS)
    pos=pu[pu>0].sum(); neg=-pu[pu<0].sum()
    pf=(pos/neg) if neg>0 else float('inf')
    pfs='inf' if pf==float('inf') else f"{pf:.3f}"
    return f"n={n:>4}  WR={(g.result=='WIN').mean()*100:>5.1f}%  grossExp={pu.mean():>+8.4f}$  PF={pfs}"

async def main():
    rows=await Database.fetch("""
        SELECT tr.result, tr.profit_usdt, tr.profit_percent, s.score_details
        FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
          AND s.market_condition IN ('bearish','sideways')
    """)
    recs=[]
    for r in rows:
        d=r['score_details']; d=json.loads(d) if isinstance(d,str) else dict(d)
        rec=dict(result=r['result'],
                 pu=float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POS)
        for k in GOOD+BAD:
            try: rec[k]=float(d.get(k,0) or 0)
            except: rec[k]=0.0
        recs.append(rec)
    df=pd.DataFrame(recs)
    df['clean']=df[GOOD].sum(axis=1)
    df['nbad']=(df[BAD]>0).sum(axis=1)
    out=[]
    out.append(f"bear+side N={len(df)}   GOOD={GOOD}   BAD={BAD}")
    out.append("="*100)
    out.append("(1) تأثير وجود مؤشرات ضارّة: تقسيم حسب عدد المؤشرات الضارة المشتعلة")
    out.append("="*100)
    for k in range(0,6):
        sub=df[df.nbad==k] if k<5 else df[df.nbad>=5]
        lbl=f"{k} bad fired" if k<5 else "5+ bad"
        out.append(f"  {lbl:<12}: {st(sub)}")
    out.append("  → لو الأرضية ترتفع كلما قلّت المؤشرات الضارة = دليل أن التقليل يساعد.")
    out.append("")
    out.append("="*100)
    out.append("(2) clean_score (مجموع مساهمة rsi+bollinger+macd+order_book فقط) — bucketed")
    out.append("="*100)
    for thr in [1.0,1.5,2.0,2.5,3.0]:
        sub=df[df.clean>=thr]
        out.append(f"  clean_score>={thr:<4}: {st(sub)}   | net@0.3: PF={_pf(sub,0.3)}")
    out.append("")
    out.append("="*100)
    out.append("(3) المقارنة الحاسمة: 'نظيف نقي' (good fired, NO bad) مقابل الباقي")
    out.append("="*100)
    pure=df[(df.clean>=2.0)&(df.nbad==0)]
    rest=df[~((df.clean>=2.0)&(df.nbad==0))]
    out.append(f"  PURE (clean>=2 & 0 bad): {st(pure)}   | net@0.3: PF={_pf(pure,0.3)} Exp={_exp(pure,0.3):+.4f}$")
    out.append(f"  REST                   : {st(rest)}")
    out.append(f"  baseline (all bear+side): {st(df)}")
    text="\n".join(out); print(text)
    with open('/app/logs/reduced_score_report.txt','w') as f: f.write(text)

def _pf(g,fee):
    if len(g)==0: return 'n=0'
    pu=g.pu.values-(fee/100*POS); pos=pu[pu>0].sum(); neg=-pu[pu<0].sum()
    return 'inf' if neg==0 else f"{pos/neg:.3f}"
def _exp(g,fee):
    return (g.pu.values-(fee/100*POS)).mean() if len(g)>0 else float('nan')
asyncio.run(main())
