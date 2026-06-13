import os, urllib.request, urllib.error, concurrent.futures as cf
from datetime import date, timedelta
BASE="https://data.binance.vision/data/futures/um/daily/metrics"
DEST="/app/logs/oi_data"
syms=[s.strip() for s in open("/app/logs/futures_covered_syms.txt") if s.strip()]
# نطاق التواريخ: 2024-01-01 .. 2025-12-31
d0=date(2024,1,1); d1=date(2025,12,31)
days=[]
d=d0
while d<=d1:
    days.append(d.isoformat()); d+=timedelta(days=1)
print(f"symbols={len(syms)} days={len(days)} jobs={len(syms)*len(days)}",flush=True)
def task(a):
    sym,day=a
    dd=f"{DEST}/{sym}"; os.makedirs(dd,exist_ok=True)
    zp=f"{dd}/{sym}-metrics-{day}.zip"; mk=zp+".404"
    if os.path.exists(zp) or os.path.exists(mk): return ("skip",)
    url=f"{BASE}/{sym}/{sym}-metrics-{day}.zip"
    try:
        with urllib.request.urlopen(url,timeout=25) as r: data=r.read()
        open(zp,"wb").write(data); return ("ok",len(data))
    except urllib.error.HTTPError as e:
        if e.code==404: open(mk,"w").close(); return ("404",)
        return ("err",)
    except Exception: return ("err",)
jobs=[(s,day) for s in syms for day in days]
ok=c4=ce=ck=0; mb=0
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    for i,r in enumerate(ex.map(task,jobs),1):
        t=r[0]
        if t=="ok": ok+=1; mb+=r[1]
        elif t=="404": c4+=1
        elif t=="skip": ck+=1
        else: ce+=1
        if i%10000==0: print(f"  {i}/{len(jobs)} ok={ok} 404={c4} skip={ck} err={ce} MB={mb/1e6:.0f}",flush=True)
print(f"DONE ok={ok} 404={c4} skip={ck} err={ce} MB={mb/1e6:.1f}",flush=True)
