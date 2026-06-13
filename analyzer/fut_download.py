#!/usr/bin/env python3
"""تنزيل futures klines(1d) + fundingRate للكون المُغطّى (131 رمز)، 2024-2025. stdlib threaded."""
import os, urllib.request, urllib.error, concurrent.futures as cf
BASE="https://data.binance.vision/data/futures/um/monthly"
DEST="/app/logs/fut_data"
MONTHS=[f"{y}-{m:02d}" for y in (2023,2024,2025) for m in range(1,13)]
syms=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
print(f"symbols={len(syms)} months={len(MONTHS)}",flush=True)

def task(a):
    sym,kind,ym=a
    if kind=='k':
        sub=f"klines/{sym}/1d"; fn=f"{sym}-1d-{ym}.zip"
    else:
        sub=f"fundingRate/{sym}"; fn=f"{sym}-fundingRate-{ym}.zip"
    d=f"{DEST}/{sub}"; os.makedirs(d,exist_ok=True)
    zp=f"{d}/{fn}"; mk=zp+".404"
    if os.path.exists(zp) or os.path.exists(mk): return ("skip",)
    url=f"{BASE}/{sub}/{fn}"
    try:
        with urllib.request.urlopen(url,timeout=30) as r: data=r.read()
        open(zp,"wb").write(data); return ("ok",len(data))
    except urllib.error.HTTPError as e:
        if e.code==404: open(mk,"w").close(); return ("404",)
        return ("err",)
    except Exception: return ("err",)

jobs=[(s,k,ym) for s in syms for k in ('k','f') for ym in MONTHS]
print(f"jobs={len(jobs)}",flush=True)
ok=c4=ce=ck=0; mb=0
with cf.ThreadPoolExecutor(max_workers=16) as ex:
    for i,r in enumerate(ex.map(task,jobs),1):
        t=r[0]
        if t=="ok": ok+=1; mb+=r[1]
        elif t=="404": c4+=1
        elif t=="skip": ck+=1
        else: ce+=1
        if i%1500==0: print(f"  {i}/{len(jobs)} ok={ok} 404={c4} skip={ck} err={ce} MB={mb/1e6:.0f}",flush=True)
print(f"DONE ok={ok} 404={c4} skip={ck} err={ce} MB={mb/1e6:.1f}",flush=True)
