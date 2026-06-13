#!/usr/bin/env python3
"""تنزيل klines التاريخية من data.binance.vision (stdlib فقط، threaded).
الوجهة: /app/logs/bt_data/{symbol}/{tf}/{file}.zip  | يتخطّى الموجود و404."""
import os, urllib.request, urllib.error, concurrent.futures as cf
BASE="https://data.binance.vision/data/spot/monthly/klines"
DEST="/app/logs/bt_data"
TFS=["1h","4h","1d"]
MONTHS=[f"{y}-{m:02d}" for y in (2023,2024,2025) for m in range(1,13)]
syms=[s.strip() for s in open("/app/bt_symbols.txt") if s.strip()]

def task(args):
    sym,tf,ym=args
    d=f"{DEST}/{sym}/{tf}"; os.makedirs(d,exist_ok=True)
    zp=f"{d}/{sym}-{tf}-{ym}.zip"; mk=f"{d}/{sym}-{tf}-{ym}.404"
    if os.path.exists(zp) or os.path.exists(mk): return ("skip",)
    url=f"{BASE}/{sym}/{tf}/{sym}-{tf}-{ym}.zip"
    try:
        with urllib.request.urlopen(url,timeout=30) as r:
            data=r.read()
        with open(zp,"wb") as f: f.write(data)
        return ("ok",len(data))
    except urllib.error.HTTPError as e:
        if e.code==404:
            open(mk,"w").close(); return ("404",)
        return ("err",str(e))
    except Exception as e:
        return ("err",str(e))

jobs=[(s,tf,ym) for s in syms for tf in TFS for ym in MONTHS]
print(f"total jobs={len(jobs)} (symbols={len(syms)} x tfs={len(TFS)} x months={len(MONTHS)})",flush=True)
cok=c404=cerr=cskip=0; cbytes=0
with cf.ThreadPoolExecutor(max_workers=16) as ex:
    for i,res in enumerate(ex.map(task,jobs),1):
        t=res[0]
        if t=="ok": cok+=1; cbytes+=res[1]
        elif t=="404": c404+=1
        elif t=="skip": cskip+=1
        else: cerr+=1
        if i%2000==0:
            print(f"  {i}/{len(jobs)}  ok={cok} 404={c404} skip={cskip} err={cerr} MB={cbytes/1e6:.0f}",flush=True)
print(f"DONE ok={cok} 404={c404} skip={cskip} err={cerr} totalMB={cbytes/1e6:.1f}",flush=True)
