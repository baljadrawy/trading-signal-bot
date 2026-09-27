#!/usr/bin/env python3
"""FC backtest — DELTA-NEUTRAL FUNDING CARRY, proper model (fees, basis MtM, margin/liquidation).
Falsify-first. Read-only research. Produces per-period records CSV for the robustness step.

MODEL (no look-ahead):
  Periods = 8h buckets aligned to funding settlements (00:00/08:00/16:00 UTC).
  Position when gate says HOLD: long N spot + short N perp (delta~0).
  GATE (strictly conservative, no peek): hold period k iff PRIOR settled funding f_{k-1} > 0.
  Per-period P&L (per unit notional N=1):
     funding_pnl = f_k              (this period's settled rate; +receive if>0, -pay if<0)
     spot_pnl    = S_k/S_{k-1} - 1
     perp_pnl    = -(P_k/P_{k-1} - 1)   (short)
     basis_pnl   = spot_pnl + perp_pnl   (basis mark-to-market; kept, not zeroed)
     gross       = funding_pnl + basis_pnl
  Prices S,P = 1h CLOSE at period boundary. Intra-period perp HIGH from 1h highs in bucket.
  Fees: roundtrip taker on BOTH legs charged once per holding SPELL (+ once per liquidation re-hedge).
  Capital deployed per unit notional = 1 (spot) + 1/L (short margin). Returns reported on capital.
  Liquidation: short leg isolated margin at leverage L. thr(L)=1/L - maint(0.005).
     Model R (rebalanced): reference reset each period -> perp_rise=P_high_k/P_{k-1}-1 >= thr.
     Model P (passive):    reference = spell-entry perp price -> cumulative rise >= thr (worse tail).
     On liq: short loss capped at margin (N*thr); spot offsets by spot value AT the perp-high bar
             (partial: spot may lag perp -> net negative). Funding not collected that period.
Outputs: fc_periods.csv (one row per held-eligible period, per symbol) + console summary.
"""
import os, glob, zipfile
import numpy as np, pandas as pd

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
SPOT = f"{ROOT}/data/bt_data"
PERP = f"{ROOT}/data/perp"
FUND = f"{ROOT}/data/funding"
OUT  = f"{ROOT}/scripts/fc_periods.csv"

SYMS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT",
        "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","ATOMUSDT","NEARUSDT","MATICUSDT",
        "ARBUSDT","OPUSDT","APTUSDT","INJUSDT","SUIUSDT","FILUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in range(2021,2027) for m in range(1,7 if y==2026 else 13)]
H8 = 8*3600*1000  # 8h in ms
MAINT = 0.005     # maintenance margin buffer (conservative -> earlier liq)


def _parse_klines(lines):
    rows = []
    for ln in lines:
        p = ln.split(',')
        if not p or not p[0] or p[0][:1].isalpha():
            continue
        try:
            rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])))
        except Exception:
            pass
    return rows


def load_spot(sym):
    files = sorted(glob.glob(f"{SPOT}/{sym}/1h/{sym}-1h-*.zip"))
    rows = []
    for f in files:
        try:
            z = zipfile.ZipFile(f); n = z.namelist()[0]
            rows += _parse_klines(z.read(n).decode().splitlines())
        except Exception:
            pass
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=['t','o','h','l','c']).drop_duplicates('t').sort_values('t')
    df['t'] = df['t'].apply(lambda x: x//1000 if x > 1e14 else x)  # normalize to ms
    return df.reset_index(drop=True)


def load_perp(sym):
    files = sorted(glob.glob(f"{PERP}/{sym}/{sym}-1h-*.csv"))
    rows = []
    for f in files:
        try:
            with open(f) as fh:
                rows += _parse_klines(fh.read().splitlines())
        except Exception:
            pass
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=['t','o','h','l','c']).drop_duplicates('t').sort_values('t')
    df['t'] = df['t'].apply(lambda x: x//1000 if x > 1e14 else x)
    return df.reset_index(drop=True)


def load_funding(sym):
    recs = []
    for ym in MONTHS:
        p = f"{FUND}/{sym}__{ym}.csv"
        if not os.path.exists(p):
            continue
        for ln in open(p):
            if ln.startswith("calc_time"):
                continue
            q = ln.split(',')
            try:
                recs.append((int(q[0]), float(q[2])))
            except Exception:
                pass
    if not recs:
        return None
    df = pd.DataFrame(recs, columns=['T','rate']).drop_duplicates('T').sort_values('T')
    # funding settled at T earned over window [T-8h, T) -> price bucket index (T//8h - 1)
    df['period'] = (df['T'] // H8) - 1
    # sum any sub-8h settlements onto the same 8h period (rare: SOL 2h/4h)
    return df.groupby('period')['rate'].sum()


def build_periods(sym):
    s = load_spot(sym); p = load_perp(sym); f = load_funding(sym)
    if s is None or p is None or f is None:
        return None
    m = s.merge(p, on='t', suffixes=('_s','_p'), how='inner')
    if len(m) < 200:
        return None
    m['period'] = m['t'] // H8
    g = m.groupby('period')
    per = pd.DataFrame({
        'S_close': g['c_s'].last(),
        'P_close': g['c_p'].last(),
        'S_high' : g['h_s'].max(),
        'P_high' : g['h_p'].max(),
        'nbars'  : g.size(),
    })
    # spot close at the 1h bar where perp made its HIGH (basis at the spike moment)
    idx = g['h_p'].idxmax()
    per['S_at_ph'] = m.loc[idx.values, 'c_s'].values
    per = per.reset_index()
    per['sym'] = sym
    # attach funding of THIS period (settled at period end) and PRIOR (gate signal)
    per['rate'] = per['period'].map(f)
    per = per.sort_values('period').reset_index(drop=True)
    # prev-period closes and contiguity (period index must be consecutive)
    per['S_prev'] = per['S_close'].shift(1)
    per['P_prev'] = per['P_close'].shift(1)
    per['prev_period'] = per['period'].shift(1)
    per['contig'] = (per['period'] - per['prev_period']) == 1
    per['prior_rate'] = per['rate'].shift(1)   # f_{k-1}: known at period start (no look-ahead)
    per['dt'] = pd.to_datetime(per['period'] * H8, unit='ms')
    per['year'] = per['dt'].dt.year
    per['ym'] = per['dt'].dt.strftime('%Y-%m')
    # only rows where a hold decision is well-defined: contiguous, prev prices, both funding known
    per = per[per['contig'] & per['S_prev'].notna() & per['P_prev'].notna()
              & per['rate'].notna() & per['prior_rate'].notna()].copy()
    if len(per) < 100:
        return None
    # ---- per-period components (per unit notional N=1) ----
    per['spot_ret'] = per['S_close']/per['S_prev'] - 1
    per['perp_ret'] = per['P_close']/per['P_prev'] - 1
    per['funding_pnl'] = per['rate']
    per['basis_pnl'] = per['spot_ret'] - per['perp_ret']         # spot_pnl + short_perp_pnl
    per['gross_pnl'] = per['funding_pnl'] + per['basis_pnl']     # before fees/liq
    # intra-period perp up-move from period start (for rebalanced liq model)
    per['perp_rise_R'] = per['P_high']/per['P_prev'] - 1
    per['spot_conc'] = per['S_at_ph']/per['S_prev'] - 1          # spot ret at the perp-high bar
    # GATE: hold this period iff prior settled funding > 0
    per['hold'] = per['prior_rate'] > 0
    return per[['sym','period','dt','year','ym','rate','prior_rate','hold','nbars',
                'S_prev','S_close','P_prev','P_close','P_high','S_at_ph',
                'spot_ret','perp_ret','funding_pnl','basis_pnl','gross_pnl',
                'perp_rise_R','spot_conc']]


if __name__ == "__main__":
    frames = []
    cov = []
    for sym in SYMS:
        per = build_periods(sym)
        if per is None:
            cov.append((sym, 0, None, None)); print(f"  {sym:<10} NO DATA", flush=True); continue
        frames.append(per)
        cov.append((sym, len(per), per['dt'].min().date(), per['dt'].max().date()))
        print(f"  {sym:<10} periods={len(per):>6}  {per['dt'].min().date()}..{per['dt'].max().date()}  "
              f"held(gate)={per['hold'].mean()*100:4.1f}%  funding>0={ (per['rate']>0).mean()*100:4.1f}%", flush=True)
    allp = pd.concat(frames, ignore_index=True)
    allp.to_csv(OUT, index=False)
    print(f"\nUNIVERSE: {len(frames)}/{len(SYMS)} symbols  total periods={len(allp)}  "
          f"span={allp['dt'].min().date()}..{allp['dt'].max().date()}", flush=True)
    # funding distribution + gate sanity
    r = allp['rate']
    print(f"\nFUNDING 8h-rate dist: mean={r.mean()*100:.4f}%  median={r.median()*100:.4f}%  "
          f"min={r.min()*100:.3f}%  max={r.max()*100:.3f}%  pct>0={(r>0).mean()*100:.1f}%", flush=True)
    held = allp[allp['hold']]
    print(f"GATE sanity: when gate=HOLD, this-period funding>0 in {(held['rate']>0).mean()*100:.1f}% of cases "
          f"(gate should mostly avoid backwardation); mean funding while held={held['rate'].mean()*100:.4f}% vs "
          f"idle={allp[~allp['hold']]['rate'].mean()*100:.4f}%", flush=True)
    print(f"WROTE {OUT}", flush=True)
