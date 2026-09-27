#!/usr/bin/env python3
"""
Falsification audit of the support-strength scan — ROBUST version.

WHY ROBUST: raw means are meaningless here. Forward %-returns on micro-cap /
collapsing coins produce astronomic outliers (LUNAUSDT 2022 = +6,170,700% — a
near-zero denominator, not a tradeable gain). A single such row dominates a
class mean. So this audit reports median and winsorized/trimmed means, and
bootstraps by SYMBOL CLUSTER (crypto is cross-sectionally correlated, so naive
per-setup CIs overstate the effective sample size).

Bootstrap is vectorized via per-cluster (sum, count) so 5000 reps is instant.

Usage: support_strength_audit.py [rows.csv] [label]
"""
import sys
import numpy as np, pandas as pd

CSV = sys.argv[1] if len(sys.argv) > 1 else \
    '/home/tradmin/trading-signal-bot/research/skill_application/support_strength_rows.csv'
LABEL = sys.argv[2] if len(sys.argv) > 2 else 'support'
RNG = np.random.default_rng(12345)
B = 5000
WIN_LO, WIN_HI = 1.0, 99.0     # winsorization percentiles


def cluster_boot_mean_ci(vals, codes, k, n_boot=B):
    """Vectorized cluster bootstrap of a mean.
    vals: values; codes: integer cluster id per value; k: number of clusters."""
    sums = np.bincount(codes, weights=vals, minlength=k)
    cnts = np.bincount(codes, minlength=k).astype(float)
    idx = RNG.integers(0, k, size=(n_boot, k))
    tot = sums[idx].sum(1)
    num = cnts[idx].sum(1)
    with np.errstate(invalid='ignore', divide='ignore'):
        boot = np.where(num > 0, tot / np.maximum(num, 1e-9), np.nan)
    boot = boot[np.isfinite(boot)]
    return np.percentile(boot, [2.5, 97.5]), boot


def cluster_boot_diff_ci(v1, c1, v2, c2, k, n_boot=B):
    """Vectorized cluster bootstrap of (mean1 - mean2), resampling clusters jointly."""
    s1 = np.bincount(c1, weights=v1, minlength=k); n1 = np.bincount(c1, minlength=k).astype(float)
    s2 = np.bincount(c2, weights=v2, minlength=k); n2 = np.bincount(c2, minlength=k).astype(float)
    idx = RNG.integers(0, k, size=(n_boot, k))
    with np.errstate(invalid='ignore', divide='ignore'):
        m1 = s1[idx].sum(1) / np.maximum(n1[idx].sum(1), 1e-9)
        m2 = s2[idx].sum(1) / np.maximum(n2[idx].sum(1), 1e-9)
    d = m1 - m2
    d = d[np.isfinite(d)]
    return np.percentile(d, [2.5, 97.5]), d


def main():
    df = pd.read_csv(CSV)
    df = df[np.isfinite(df.fwd_gross_pct)]
    k_sym = df.symbol.nunique()
    print(f"\n{'='*78}\nARM: {LABEL}   |   {len(df)} setups | {k_sym} symbols | "
          f"years {df.year.min()}-{df.year.max()}\n{'='*78}")

    g = df.fwd_gross_pct
    lo_w, hi_w = np.percentile(g, [WIN_LO, WIN_HI])
    print(f"raw mean={g.mean():+.2f}  median={g.median():+.2f}  max={g.max():,.0f}%  "
          f"(winsorizing to [{lo_w:.1f}, {hi_w:.1f}])")
    df = df.copy()
    df['w_gross'] = g.clip(lo_w, hi_w)
    df['w_net'] = df.w_gross - 0.6

    codes, uniq = pd.factorize(df.symbol)
    df['ccode'] = codes
    k = len(uniq)

    print(f"\n{'class':10s} {'n':>6s} {'WR%':>6s} {'raw_mean':>9s} {'WINS_mean':>10s} "
          f"{'MEDIAN':>8s} {'trim10%':>8s}  {'clustered 95% CI (wins net)':>28s}")
    stats = {}
    for cls in ('strong', 'standard', 'weak'):
        s = df[df.cls == cls]
        if len(s) < 5:
            continue
        trim = s.w_net[(s.w_net >= s.w_net.quantile(0.05)) & (s.w_net <= s.w_net.quantile(0.95))].mean()
        (lo, hi), _ = cluster_boot_mean_ci(s.w_net.to_numpy(), s.ccode.to_numpy(), k)
        stats[cls] = dict(n=len(s), wmean=s.w_net.mean(), med=s.w_net.median(), lo=lo, hi=hi)
        print(f"{cls:10s} {len(s):6d} {100*(s.fwd_gross_pct>0).mean():6.1f} "
              f"{s.fwd_net_pct.mean():9.3f} {s.w_net.mean():10.3f} {s.w_net.median():8.3f} "
              f"{trim:8.3f}  {'['+f'{lo:+.3f}, {hi:+.3f}'+']':>28s}")

    if 'strong' in stats and 'weak' in stats:
        S = df[df.cls == 'strong']; W = df[df.cls == 'weak']
        print(f"\n--- THE CLAIM: strong should beat weak ---")
        for lab, col in (('winsorized mean', 'w_net'),):
            obs = S[col].mean() - W[col].mean()
            (lo, hi), d = cluster_boot_diff_ci(S[col].to_numpy(), S.ccode.to_numpy(),
                                               W[col].to_numpy(), W.ccode.to_numpy(), k)
            verdict = 'HOLDS (CI excludes 0)' if lo > 0 else 'NOT SIGNIFICANT (CI includes 0)'
            print(f"  {lab:16s}: {obs:+.3f} pp  CI [{lo:+.3f}, {hi:+.3f}]  "
                  f"P(>0)={(d>0).mean():.3f}  -> {verdict}")
        print(f"  {'median':16s}: {S.w_net.median()-W.w_net.median():+.3f} pp "
              f"(robust central tendency; compare with the mean above)")

        print(f"\n--- CONCENTRATION: remove top-N strong setups ---")
        ss = S.sort_values('w_net', ascending=False); wm = W.w_net.mean()
        for n in (0, 1, 5, 10, 25, 50):
            cut = ss.iloc[n:]
            print(f"  remove top-{n:3d}: strong={cut.w_net.mean():+.3f}  "
                  f"strong-weak={cut.w_net.mean()-wm:+.3f} pp")

        print(f"\n--- PER-YEAR STABILITY (winsorized net) ---")
        pos = tot = 0
        for y, gg in df.groupby('year'):
            a, b = gg[gg.cls == 'strong'], gg[gg.cls == 'weak']
            if len(a) < 15 or len(b) < 15:
                continue
            d = a.w_net.mean() - b.w_net.mean(); tot += 1; pos += d > 0
            print(f"  {y}: n_s={len(a):4d} n_w={len(b):5d}  strong={a.w_net.mean():+7.3f} "
                  f"weak={b.w_net.mean():+7.3f}  diff={d:+7.3f}")
        if tot:
            print(f"  -> strong beat weak in {pos}/{tot} years")

    print(f"\n--- FEE HURDLE (winsorized gross - fee) ---")
    for fee in (0.3, 0.6, 1.0):
        row = f"  fee {fee:.1f}%: "
        for cls in ('strong', 'standard', 'weak'):
            s = df[df.cls == cls]
            if len(s) < 5: continue
            row += f"{cls}={s.w_gross.mean()-fee:+.3f}  "
        print(row)


if __name__ == '__main__':
    main()
