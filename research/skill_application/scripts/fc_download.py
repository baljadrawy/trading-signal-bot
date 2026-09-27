#!/usr/bin/env python3
"""FC (funding-carry) data download — PERSISTENT.
Downloads to data/funding/ and data/perp/ (NOT /tmp):
  - Binance USD-M funding rate monthly: futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-<YYYY-MM>.zip
  - Binance USD-M perp 1h klines monthly: futures/um/monthly/klines/<SYM>/1h/<SYM>-1h-<YYYY-MM>.zip
Universe = 20 liquid perps, 2021-01..2026-06. Reports coverage; no silent truncation."""
import os, urllib.request, urllib.error, zipfile, io, concurrent.futures as cf

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
FUND_DEST = f"{ROOT}/data/funding"
PERP_DEST = f"{ROOT}/data/perp"
os.makedirs(FUND_DEST, exist_ok=True)
os.makedirs(PERP_DEST, exist_ok=True)

BASE = "https://data.binance.vision/data/futures/um/monthly"
SYMS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
        "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","ATOMUSDT","NEARUSDT","MATICUSDT",
        "ARBUSDT","OPUSDT","APTUSDT","INJUSDT","SUIUSDT","FILUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in range(2021,2027) for m in range(1,7 if y==2026 else 13)]


def fetch(url, out_csv, mk):
    if os.path.exists(out_csv) or os.path.exists(mk):
        return "skip"
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            data = r.read()
        z = zipfile.ZipFile(io.BytesIO(data))
        n = z.namelist()[0]
        with open(out_csv, "wb") as f:
            f.write(z.read(n))
        return "ok"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            open(mk, "w").close(); return "404"
        return "err"
    except Exception:
        return "err"


def dl_fund(a):
    sym, ym = a
    url = f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"
    out = f"{FUND_DEST}/{sym}__{ym}.csv"
    return ("fund", sym, ym, fetch(url, out, out + ".404"))


def dl_perp(a):
    sym, ym = a
    os.makedirs(f"{PERP_DEST}/{sym}", exist_ok=True)
    url = f"{BASE}/klines/{sym}/1h/{sym}-1h-{ym}.zip"
    out = f"{PERP_DEST}/{sym}/{sym}-1h-{ym}.csv"
    return ("perp", sym, ym, fetch(url, out, out + ".404"))


if __name__ == "__main__":
    jobs_f = [(s, ym) for s in SYMS for ym in MONTHS]
    jobs_p = [(s, ym) for s in SYMS for ym in MONTHS]
    stats = {"fund": {"ok":0,"404":0,"skip":0,"err":0}, "perp": {"ok":0,"404":0,"skip":0,"err":0}}
    errs = []
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        futs = [ex.submit(dl_fund, a) for a in jobs_f] + [ex.submit(dl_perp, a) for a in jobs_p]
        done = 0
        for fu in cf.as_completed(futs):
            kind, sym, ym, res = fu.result()
            stats[kind][res] += 1
            if res == "err":
                errs.append((kind, sym, ym))
            done += 1
            if done % 400 == 0:
                print(f"  ...{done}/{len(futs)}", flush=True)
    print("FUNDING:", stats["fund"], flush=True)
    print("PERP   :", stats["perp"], flush=True)
    if errs:
        print(f"ERRORS ({len(errs)}):", errs[:20], flush=True)

    # coverage report per symbol
    print("\n=== COVERAGE (months present) ===", flush=True)
    for s in SYMS:
        nf = len([m for m in MONTHS if os.path.exists(f"{FUND_DEST}/{s}__{m}.csv")])
        np_ = len([m for m in MONTHS if os.path.exists(f"{PERP_DEST}/{s}/{s}-1h-{m}.csv")])
        fm = [m for m in MONTHS if os.path.exists(f"{FUND_DEST}/{s}__{m}.csv")]
        span = f"[{fm[0]}..{fm[-1]}]" if fm else "[none]"
        print(f"  {s:<10} fund={nf:>2}/{len(MONTHS)}  perp1h={np_:>2}/{len(MONTHS)}  {span}", flush=True)
    print("DONE", flush=True)
