#!/usr/bin/env python3
"""
Falsify-first test of the "support zone strength" rule (3-candle reaction).

RULE UNDER TEST (user-specified, 2026-07-15):
  After price touches a support level:
    candle1 = the touch candle (a strong drop into support)
    candle2 = consolidation
    classify by candle3's CLOSE relative to candle1:
      Weak     : close <  50% of candle1 BODY      -> buyers not in control, break likely
      Standard : 50% of body <= close <= candle1 HIGH
      Strong   : close >  candle1 HIGH              -> buyers fully in control, best entry
  CLAIM: Strong is the best entry; Weak should underperform.

FALSIFICATION DESIGN (deliberately hostile to the claim):
- Support = swing-low pivot (PIV bars left AND right). A pivot at index p is only
  CONFIRMED at p+PIV, so a touch at t may only use pivots with p+PIV <= t. No look-ahead.
- Decision is taken at candle3 CLOSE (closed candle only). Forward return measured
  strictly AFTER that close.
- PRIMARY TEST = forward-return separation by class, with NO exit policy. This isolates
  whether the classification carries predictive information at all. A tuned stop/target
  would confound the test (2026-06-24 finding: target geometry is not the lever).
- PSEUDO-REPLICATION CONTROL (2026-07-14 audit lesson): at most ONE trigger per
  (symbol, pivot), and a cooldown so forward windows never overlap. Without this,
  the same setup re-counts and inflates n and significance.
- Fees: 0.6% round-trip, applied to the net column.

Outputs raw per-setup rows to CSV so the statistical audit (bootstrap CI, concentration,
per-year stability) runs separately without re-scanning.

Usage: support_strength_bt.py [TF] [SYMBOL_LIMIT]
"""
import os, sys, glob
import numpy as np, pandas as pd

sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E   # reuse load() + DATA

DATA = E.DATA
FEE_PCT = 0.6          # round-trip %
PIV = 5                # swing-low pivot: bars required left AND right
TOUCH_TOL = 0.005      # candle1 low within +0.5% of the pivot level counts as a touch
MAX_BREAK = 0.02       # if low is >2% BELOW the level it's a breakdown, not a touch
HORIZON = {'1d': 10, '4h': 30, '1h': 60}   # forward bars
OUT = '/home/tradmin/trading-signal-bot/research/skill_application/support_strength_rows.csv'


def pivot_lows(low, k):
    """Index array of swing lows: low[i] is the strict min of [i-k, i+k]."""
    n = len(low)
    out = np.zeros(n, dtype=bool)
    for i in range(k, n - k):
        w = low[i - k:i + k + 1]
        if low[i] == w.min() and (w.argmin() == k):
            out[i] = True
    return np.nonzero(out)[0]


def scan_symbol(df, tf, sym, require_support=True):
    """Yield one row per qualifying setup.

    require_support=False is the CONTROL arm: identical 3-candle classification but
    with NO support-touch condition (any down candle qualifies). If the strong-weak
    spread is the same in the control, the 'support' framing adds nothing and the
    signal is just a 2-bar reclaim / short-term momentum effect.
    """
    o = df['open'].to_numpy(); h = df['high'].to_numpy()
    l = df['low'].to_numpy();  c = df['close'].to_numpy()
    t = pd.to_datetime(df['t'], unit='ms', errors='coerce')
    years = t.dt.year.to_numpy()
    n = len(c)
    H = HORIZON[tf]

    piv = pivot_lows(l, PIV)
    if len(piv) == 0:
        return
    piv_conf = piv + PIV                      # index at which each pivot becomes known
    used_piv = set()                          # pseudo-replication control: 1 trigger/pivot
    next_ok = 0                               # cooldown: non-overlapping forward windows

    for i in range(PIV + 1, n - (2 + H) - 1):
        if i < next_ok:
            continue
        # candle1 must be a down candle (a drop INTO support)
        if not (c[i] < o[i]):
            continue
        p = None
        if require_support:
            # most recent pivot CONFIRMED strictly before i
            elig = np.nonzero((piv_conf <= i) & (piv < i))[0]
            if len(elig) == 0:
                continue
            p = piv[elig[-1]]
            if p in used_piv:
                continue
            level = l[p]
            if not np.isfinite(level) or level <= 0:
                continue
            # touch: reached the level (within tol) without decisively breaking it
            if not (l[i] <= level * (1 + TOUCH_TOL) and l[i] >= level * (1 - MAX_BREAK)):
                continue

        i3 = i + 2
        j = i3 + H
        if j >= n:
            continue
        body_mid = (o[i] + c[i]) / 2.0        # 50% of candle1's body (c<o here)
        c3 = c[i3]
        if c3 > h[i]:
            cls = 'strong'
        elif c3 < body_mid:
            cls = 'weak'
        else:
            cls = 'standard'

        if c[i3] <= 0:
            continue
        fwd = (c[j] - c[i3]) / c[i3] * 100.0
        if not np.isfinite(fwd):
            continue

        if p is not None:
            used_piv.add(p)
        next_ok = i3 + H                      # no overlapping forward windows
        yield (sym, tf, int(years[i3]) if np.isfinite(years[i3]) else 0,
               cls, round(fwd, 4))


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else '1d'
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    control = (len(sys.argv) > 3 and sys.argv[3] == 'nosupport')
    out_path = OUT.replace('.csv', '_control.csv') if control else OUT
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{DATA}/{s}/{tf}/*.zip")]
    if limit:
        syms = syms[:limit]
    print(f"support-strength scan | tf={tf} | {len(syms)} symbols | pivot={PIV} "
          f"| horizon={HORIZON[tf]} bars | fee={FEE_PCT}% "
          f"| MODE={'CONTROL (no support condition)' if control else 'support-touch'}", flush=True)

    rows = []
    for k, sym in enumerate(syms, 1):
        try:
            df = E.load(sym, tf)
        except Exception:
            continue
        if df is None or len(df) < 200:
            continue
        try:
            rows.extend(scan_symbol(df, tf, sym, require_support=not control))
        except Exception:
            continue
        if k % 100 == 0:
            print(f"  {k}/{len(syms)} symbols, {len(rows)} setups", flush=True)

    if not rows:
        print("NO SETUPS FOUND"); return
    out = pd.DataFrame(rows, columns=['symbol', 'tf', 'year', 'cls', 'fwd_gross_pct'])
    out['fwd_net_pct'] = out['fwd_gross_pct'] - FEE_PCT
    out.to_csv(out_path, index=False)
    print(f"\nwrote {len(out)} setups -> {out_path}\n")

    print(f"{'class':10s} {'n':>6s} {'WR%':>7s} {'mean_gross':>11s} {'mean_net':>10s} {'median_net':>11s}")
    for cls in ('strong', 'standard', 'weak'):
        g = out[out.cls == cls]
        if len(g) == 0:
            continue
        print(f"{cls:10s} {len(g):6d} {100*(g.fwd_gross_pct>0).mean():7.1f} "
              f"{g.fwd_gross_pct.mean():11.3f} {g.fwd_net_pct.mean():10.3f} "
              f"{g.fwd_net_pct.median():11.3f}")
    s = out[out.cls == 'strong'].fwd_net_pct
    w = out[out.cls == 'weak'].fwd_net_pct
    if len(s) and len(w):
        print(f"\nCLAIM CHECK  strong - weak = {s.mean()-w.mean():+.3f} pp "
              f"(claim predicts strongly POSITIVE)")


if __name__ == '__main__':
    main()
