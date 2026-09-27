#!/usr/bin/env python3
"""تنزيل klines التاريخية الكاملة من data.binance.vision (2017-08 -> 2026-06).
الوجهة (مضيف): research/skill_application/data/bt_data/{symbol}/{tf}/{file}.zip
يتخطّى الموجود ويضع علامة .404 للأشهر غير المتاحة (قبل إدراج العملة). stdlib فقط، threaded."""
import os, sys, urllib.request, urllib.error, concurrent.futures as cf

BASE = "https://data.binance.vision/data/spot/monthly/klines"
ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
DEST = f"{ROOT}/data/bt_data"
TFS  = ["1h", "4h", "1d"]
MONTHS = [f"{y}-{m:02d}" for y in range(2017, 2027) for m in range(1, 13)
          if not (y == 2017 and m < 8) and not (y == 2026 and m > 6)]
syms = [s.strip() for s in open(f"{ROOT}/data/bt_symbols.txt") if s.strip()]

def task(args):
    sym, tf, ym = args
    d = f"{DEST}/{sym}/{tf}"; os.makedirs(d, exist_ok=True)
    zp = f"{d}/{sym}-{tf}-{ym}.zip"; mk = f"{d}/{sym}-{tf}-{ym}.404"
    if os.path.exists(zp) or os.path.exists(mk): return ("skip",)
    url = f"{BASE}/{sym}/{tf}/{sym}-{tf}-{ym}.zip"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
        with open(zp, "wb") as f: f.write(data)
        return ("ok", len(data))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            open(mk, "w").close(); return ("404",)
        return ("err", str(e))
    except Exception as e:
        return ("err", str(e))

jobs = [(s, tf, ym) for s in syms for tf in TFS for ym in MONTHS]
print(f"total jobs={len(jobs)} (symbols={len(syms)} x tfs={len(TFS)} x months={len(MONTHS)}) "
      f"range={MONTHS[0]}..{MONTHS[-1]}", flush=True)
cok = c404 = cerr = cskip = 0; cbytes = 0
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    for i, res in enumerate(ex.map(task, jobs), 1):
        t = res[0]
        if t == "ok": cok += 1; cbytes += res[1]
        elif t == "404": c404 += 1
        elif t == "skip": cskip += 1
        else: cerr += 1
        if i % 5000 == 0:
            print(f"  {i}/{len(jobs)}  ok={cok} 404={c404} skip={cskip} err={cerr} GB={cbytes/1e9:.2f}", flush=True)
print(f"DONE ok={cok} 404={c404} skip={cskip} err={cerr} totalGB={cbytes/1e9:.2f}", flush=True)
with open(f"{ROOT}/data/dl_history.done", "w") as f:
    f.write(f"ok={cok} 404={c404} err={cerr} GB={cbytes/1e9:.2f}\n")
