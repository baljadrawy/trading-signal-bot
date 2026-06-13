import sys, glob
import numpy as np, pandas as pd
sys.path.insert(0,'/app')
import importlib.util
spec=importlib.util.spec_from_file_location("fa","/app/factor_attribution.py")
# نعيد استخدام strat من الملف
exec(open('/app/factor_attribution.py').read().split('out=[]')[0])
full=strat(True,True,30)
vals=[x for d,x in full]
active=[x for x in vals if abs(x)>1e-9]
pos_active=sum(1 for x in active if x>0)
print("Active (non-cash) periods: %d of %d total"%(len(active),len(vals)))
print("  win-rate on ACTIVE periods: %d/%d = %.0f%%"%(pos_active,len(active),pos_active/len(active)*100))
print("  (vs naive 21/52=40%% that counted cash periods as non-wins)")
# أي عملات تدخل عند ADV-rank 26-30 (سبب قفزة 25->30)؟
syms=[s for s in open('/app/bt_symbols.txt').read().split() if glob.glob(f"{DATA}/{s}/1d/*.zip")]
from collections import Counter
rank2630=Counter(); i=LOOK
while i+HOLD<len(idx):
    date=idx[i]
    if date.year>=2024 and ro(date):
        liq=dv.iloc[max(0,i-30):i].mean().dropna()
        ranked=liq.sort_values(ascending=False)
        for s in ranked.index[25:30]:  # المراكز 26-30
            rank2630[s]+=1
    i+=HOLD
print("\nCoins most often occupying ADV-rank 26-30 (the 25->30 jump zone):")
for s,c in rank2630.most_common(10):
    print("  %-14s appears %d times"%(s,c))
