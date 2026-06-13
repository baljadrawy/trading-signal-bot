#!/usr/bin/env python3
"""فحص تغطية بيانات الآجلة (klines + funding) لكل رموز البوت — يشكّل تصميم الاختبار.
لا ينزّل كل شيء؛ يفحص أول شهر متاح لكل رمز بمسبار خفيف (HEAD-like عبر GET صغير مع تخطّي 404)."""
import sys, urllib.request, urllib.error, concurrent.futures as cf
syms=[s.strip() for s in open('/app/bt_symbols.txt') if s.strip()]
BASE="https://data.binance.vision/data/futures/um/monthly"
MONTHS=[f"{y}-{m:02d}" for y in (2023,2024,2025) for m in range(1,13)]

def exists(url):
    try:
        req=urllib.request.Request(url,method='HEAD')
        urllib.request.urlopen(req,timeout=15); return True
    except urllib.error.HTTPError as e:
        return e.code!=404
    except Exception:
        return False

def first_month(sym,kind):
    # kind: 'klines/SYM/1d' or 'fundingRate/SYM'
    for ym in MONTHS:
        if kind=='k':
            url=f"{BASE}/klines/{sym}/1d/{sym}-1d-{ym}.zip"
        else:
            url=f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"
        if exists(url): return ym
    return None

def probe(sym):
    fk=first_month(sym,'k'); ff=first_month(sym,'f')
    return sym,fk,ff

res=[]
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    for i,r in enumerate(ex.map(probe,syms),1):
        res.append(r)
        if i%50==0: print(f"  probed {i}/{len(syms)}",flush=True)

has_fut=[r for r in res if r[1] is not None]
has_fund=[r for r in res if r[2] is not None]
from_2023=[r for r in has_fund if r[2]<='2023-12']
from_2024=[r for r in has_fund if r[2] and r[2]<='2024-12']
print("="*70)
print(f"total bot symbols          : {len(syms)}")
print(f"have futures klines        : {len(has_fut)}")
print(f"have funding history       : {len(has_fund)}")
print(f"  funding reaching 2023    : {len(from_2023)}")
print(f"  funding reaching 2024    : {len(from_2024)}")
# توزّع أول شهر funding
from collections import Counter
yrs=Counter((r[2][:4] if r[2] else 'none') for r in res)
print("funding first-year dist    :", dict(sorted(yrs.items())))
# اكتب قائمة الرموز ذات التغطية الكاملة من 2024
cov=[r[0] for r in has_fund if r[2] and r[2]<='2024-01']
open('/app/logs/futures_covered_syms.txt','w').write("\n".join(cov))
print(f"\nsymbols with funding from <=2024-01 (saved): {len(cov)}")
print("sample:", cov[:15])
