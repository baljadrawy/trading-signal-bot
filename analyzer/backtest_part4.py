"""
Backtester part 4: Bootstrap Statistical Significance
=======================================================
Input:  backtest_results_part2.jsonl
Output: backtest_results_part4.jsonl

Computes:
1. Bootstrap 95% CI for WR and expectancy
2. Permutation p-value: observed WR vs null (33%)
3. Power analysis: min-n to detect WR improvement
4. Breakdown by score tier and market_condition
"""

import json
import sys
import random
import math
import os
from datetime import datetime
from typing import Dict, List, Tuple

INPUT_FILE  = '/app/backtest_results_part2.jsonl'
OUTPUT_FILE = '/app/backtest_results_part4.jsonl'

N_BOOTSTRAP  = 1000    # max imposed by server constraints
ALPHA        = 0.05
WR_NULL      = 0.33    # historical baseline
WR_TARGET    = 0.45    # minimum WR worth planning for
MIN_SAMPLE   = 5


# ── helpers ────────────────────────────────────────────────────────────────

def expectancy_stats(profits: List[float]) -> Tuple[float, float, float, float]:
    """Return (wr, avg_win, avg_loss, expectancy)"""
    if not profits:
        return 0.0, 0.0, 0.0, 0.0
    wins   = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    wr     = len(wins) / len(profits)
    avg_w  = sum(wins)   / len(wins)   if wins   else 0.0
    avg_l  = sum(losses) / len(losses) if losses else 0.0
    exp    = wr * avg_w + (1 - wr) * avg_l
    return wr, avg_w, avg_l, exp


def stat_wr(data: List[float]) -> float:
    return sum(1 for x in data if x > 0) / len(data) if data else 0.0


def stat_exp(data: List[float]) -> float:
    if not data:
        return 0.0
    wins   = [x for x in data if x > 0]
    losses = [x for x in data if x <= 0]
    wr     = len(wins) / len(data)
    avg_w  = sum(wins)   / len(wins)   if wins   else 0.0
    avg_l  = sum(losses) / len(losses) if losses else 0.0
    return wr * avg_w + (1 - wr) * avg_l


def bootstrap_ci(data: List[float], fn, n_boot: int = N_BOOTSTRAP,
                 alpha: float = ALPHA) -> Tuple[float, float, float]:
    """Return (lower, point_estimate, upper)"""
    n = len(data)
    if n < 2:
        pe = fn(data)
        return pe, pe, pe
    boot = []
    for _ in range(n_boot):
        s = [data[random.randint(0, n - 1)] for _ in range(n)]
        try:
            boot.append(fn(s))
        except Exception:
            pass
    if not boot:
        pe = fn(data)
        return pe, pe, pe
    boot.sort()
    lo_idx = max(0, int(math.floor(alpha / 2 * len(boot))))
    hi_idx = min(len(boot) - 1, int(math.ceil((1 - alpha / 2) * len(boot))) - 1)
    return boot[lo_idx], fn(data), boot[hi_idx]


def perm_pvalue(data: List[float], null_wr: float, n_boot: int = N_BOOTSTRAP) -> float:
    """Permutation p-value: is observed WR different from null_wr?"""
    n = len(data)
    if n < MIN_SAMPLE:
        return 1.0
    obs = stat_wr(data)
    delta = abs(obs - null_wr)
    extremes = 0
    for _ in range(n_boot):
        sim_wins = sum(1 for _ in range(n) if random.random() < null_wr)
        if abs(sim_wins / n - null_wr) >= delta:
            extremes += 1
    return extremes / n_boot


def min_n_power(null_wr: float, alt_wr: float,
                alpha: float = 0.05, power: float = 0.80) -> int:
    """Approximate sample size for z-test between two proportions."""
    diff = abs(alt_wr - null_wr)
    if diff < 0.001:
        return 99999
    z_a = 1.645
    z_p = 0.842
    n = ((z_a * math.sqrt(null_wr * (1 - null_wr)) +
          z_p  * math.sqrt(alt_wr  * (1 - alt_wr))) / diff) ** 2
    return max(1, int(math.ceil(n)))


# ── main ───────────────────────────────────────────────────────────────────

def run():
    random.seed(42)
    print("=" * 65)
    print("Backtester Part 4: Bootstrap Statistical Significance")
    print("=" * 65)

    if not os.path.exists(INPUT_FILE):
        print("ERROR: part2 file not found: " + INPUT_FILE)
        sys.exit(1)

    records = []
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as e:
                print("WARNING bad line: " + str(e))

    if not records:
        print("ERROR: part2 file is empty")
        sys.exit(1)

    n_total = len(records)
    print("Total simulated trades: " + str(n_total))
    print("Bootstrap N=" + str(N_BOOTSTRAP) + " | alpha=" + str(ALPHA) +
          " | WR_null=" + str(WR_NULL))
    print()

    all_profits = [r.get('sim_profit_pct', 0.0) for r in records]

    # ── Section 1: All trades ──────────────────────────────────────────────
    print("--- 1. All Trades ---")
    wr_a, avg_w_a, avg_l_a, exp_a = expectancy_stats(all_profits)
    wr_lo,  wr_pe,  wr_hi  = bootstrap_ci(all_profits, stat_wr)
    exp_lo, exp_pe, exp_hi = bootstrap_ci(all_profits, stat_exp)
    p_a = perm_pvalue(all_profits, WR_NULL)
    n_need_target = min_n_power(WR_NULL, WR_TARGET)

    sig_a = "SIGNIFICANT" if p_a < ALPHA else "not significant"
    print("  n=" + str(n_total) +
          " | WR=" + str(round(wr_a * 100, 1)) + "%" +
          " [" + str(round(wr_lo * 100, 1)) + "%, " + str(round(wr_hi * 100, 1)) + "%] 95CI")
    print("  Expectancy=" + str(round(exp_a, 3)) + "%" +
          " [" + str(round(exp_lo, 3)) + "%, " + str(round(exp_hi, 3)) + "%] 95CI")
    print("  avg_win=" + str(round(avg_w_a, 3)) + "% | avg_loss=" + str(round(avg_l_a, 3)) + "%")
    print("  p-value vs WR_null=" + str(int(WR_NULL * 100)) + "%: " +
          str(round(p_a, 3)) + " (" + sig_a + ")")
    print("  n_needed to detect WR=" + str(int(WR_TARGET * 100)) + "%: " + str(n_need_target))
    print()

    # ── Section 2: score >= 3.4 ────────────────────────────────────────────
    print("--- 2. score >= 3.4 (walk-forward candidate) ---")
    hs = [r for r in records if r.get('total_score', 0) >= 3.4]
    hs_profits = [r.get('sim_profit_pct', 0.0) for r in hs]

    if len(hs_profits) >= MIN_SAMPLE:
        wr_hs, avg_w_hs, avg_l_hs, exp_hs = expectancy_stats(hs_profits)
        wr_lo2, _, wr_hi2   = bootstrap_ci(hs_profits, stat_wr)
        exp_lo2, _, exp_hi2 = bootstrap_ci(hs_profits, stat_exp)
        p_hs = perm_pvalue(hs_profits, WR_NULL)
        eff_alt = max(wr_hs, WR_TARGET)
        n_need_hs = min_n_power(WR_NULL, eff_alt)
        sig_hs = "SIGNIFICANT" if p_hs < ALPHA else "not significant"
        print("  n=" + str(len(hs_profits)) +
              " | WR=" + str(round(wr_hs * 100, 1)) + "%" +
              " [" + str(round(wr_lo2 * 100, 1)) + "%, " + str(round(wr_hi2 * 100, 1)) + "%] 95CI")
        print("  Expectancy=" + str(round(exp_hs, 3)) + "%" +
              " [" + str(round(exp_lo2, 3)) + "%, " + str(round(exp_hi2, 3)) + "%] 95CI")
        print("  p-value: " + str(round(p_hs, 3)) + " (" + sig_hs + ")")
        print("  n_needed: " + str(n_need_hs))
    else:
        wr_hs = 0.0
        exp_hs = 0.0
        p_hs = 1.0
        n_need_hs = 999
        wr_lo2 = wr_hi2 = exp_lo2 = exp_hi2 = 0.0
        print("  sample too small (" + str(len(hs)) + ") — skipped")
    print()

    # ── Section 3: Outcome distribution ───────────────────────────────────
    print("--- 3. Outcome Distribution ---")
    wins_    = [r for r in records if r.get('sim_result') == 'WIN']
    sl_hits  = [r for r in records if r.get('sim_result') == 'LOSS'
                                   and not r.get('hit_breakeven')]
    be_saved = [r for r in records if r.get('hit_breakeven')
                                   and r.get('sim_result') != 'WIN']
    print("  WIN:        " + str(len(wins_))   + " (" + str(round(len(wins_)   / n_total * 100, 1)) + "%)")
    print("  SL:         " + str(len(sl_hits)) + " (" + str(round(len(sl_hits) / n_total * 100, 1)) + "%)")
    print("  break-even: " + str(len(be_saved))+ " (" + str(round(len(be_saved)/ n_total * 100, 1)) + "%)")
    print()

    # ── Section 4: score < 3.4 vs >= 3.4 ──────────────────────────────────
    print("--- 4. score<3.4 vs score>=3.4 ---")
    ls = [r for r in records if r.get('total_score', 0) < 3.4]
    ls_profits = [r.get('sim_profit_pct', 0.0) for r in ls]
    if ls_profits:
        wr_ls, _, _, exp_ls = expectancy_stats(ls_profits)
        print("  score<3.4:  n=" + str(len(ls_profits)) +
              " WR=" + str(round(wr_ls * 100, 1)) + "%" +
              " E=" + str(round(exp_ls, 3)) + "%")
    else:
        exp_ls = 0.0
        wr_ls = 0.0
    if hs_profits:
        delta = round(exp_hs - exp_ls, 3)
        print("  score>=3.4: n=" + str(len(hs_profits)) +
              " WR=" + str(round(wr_hs * 100, 1)) + "%" +
              " E=" + str(round(exp_hs, 3)) + "%")
        verdict = "edge candidate" if delta > 0 else "no edge"
        print("  Delta-E: " + str(delta) + "% (" + verdict + ")")
    print()

    # ── Section 5: by market_condition ────────────────────────────────────
    print("--- 5. By market_condition ---")
    cond_map: Dict[str, List[float]] = {}
    for r in records:
        mc = r.get('market_condition', 'unknown')
        cond_map.setdefault(mc, []).append(r.get('sim_profit_pct', 0.0))

    cond_results: Dict = {}
    for mc in sorted(cond_map):
        profs = cond_map[mc]
        if len(profs) < MIN_SAMPLE:
            print("  " + mc + ": n=" + str(len(profs)) + " — too small")
            cond_results[mc] = {'n': len(profs)}
            continue
        wr_mc, _, _, exp_mc = expectancy_stats(profs)
        lo_mc, _, hi_mc = bootstrap_ci(profs, stat_wr)
        p_mc = perm_pvalue(profs, WR_NULL)
        sig_mc = "p<0.05" if p_mc < ALPHA else "p>0.05"
        print("  " + mc + ": n=" + str(len(profs)) +
              " WR=" + str(round(wr_mc * 100, 1)) + "%" +
              " [" + str(round(lo_mc * 100, 1)) + "%-" + str(round(hi_mc * 100, 1)) + "%]" +
              " E=" + str(round(exp_mc, 3)) + "%" +
              " (" + sig_mc + ")")
        cond_results[mc] = {
            'n': len(profs),
            'wr': round(wr_mc, 4),
            'exp': round(exp_mc, 4),
            'p_value': round(p_mc, 4),
            'wr_ci_lo': round(lo_mc, 4),
            'wr_ci_hi': round(hi_mc, 4),
        }
    print()

    # ── Section 6: Power analysis ──────────────────────────────────────────
    print("--- 6. Power Analysis (null=" + str(int(WR_NULL * 100)) + "%, power=80%) ---")
    n40 = min_n_power(WR_NULL, 0.40)
    n45 = min_n_power(WR_NULL, 0.45)
    n50 = min_n_power(WR_NULL, 0.50)
    nc  = n_total

    def status(nc, need):
        if nc >= need:
            return "OK"
        return "need " + str(need - nc) + " more"

    print("  detect WR=40%: need " + str(n40) + " trades (" + status(nc, n40) + ")")
    print("  detect WR=45%: need " + str(n45) + " trades (" + status(nc, n45) + ")")
    print("  detect WR=50%: need " + str(n50) + " trades (" + status(nc, n50) + ")")
    print()

    # ── Conclusions ────────────────────────────────────────────────────────
    conclusions = []
    if p_a < ALPHA:
        conclusions.append(
            "WR=" + str(round(wr_a * 100, 1)) + "% is statistically significant (p=" +
            str(round(p_a, 3)) + ") — strategy beats random")
    else:
        conclusions.append(
            "WR=" + str(round(wr_a * 100, 1)) + "% is NOT significant (p=" +
            str(round(p_a, 3)) + ") — need more data (n=" + str(n_total) + ")")
    if exp_a > 0:
        conclusions.append(
            "Expectancy positive (" + str(round(exp_a, 3)) + "%) — promising direction")
    else:
        conclusions.append(
            "Expectancy negative (" + str(round(exp_a, 3)) + "%) — strategy loses on average")
    if hs_profits and exp_hs > exp_a:
        conclusions.append(
            "score>=3.4 shows better E (" + str(round(exp_hs, 3)) + "% vs " +
            str(round(exp_a, 3)) + "%) — but n=" + str(len(hs_profits)) +
            " insufficient (need " + str(n_need_hs) + " for significance)")
    conclusions.append(
        "Need " + str(n45) + " trades to detect WR=45% reliably (currently " +
        str(n_total) + ")")

    # ── Save ───────────────────────────────────────────────────────────────
    summary = {
        'run_date': datetime.utcnow().isoformat(),
        'n_bootstrap': N_BOOTSTRAP,
        'alpha': ALPHA,
        'wr_null': WR_NULL,
        'wr_target': WR_TARGET,
        'all_trades': {
            'n': n_total,
            'wr': round(wr_a, 4),
            'wr_ci_lo': round(wr_lo, 4),
            'wr_ci_hi': round(wr_hi, 4),
            'expectancy_pct': round(exp_a, 4),
            'exp_ci_lo': round(exp_lo, 4),
            'exp_ci_hi': round(exp_hi, 4),
            'avg_win_pct': round(avg_w_a, 4),
            'avg_loss_pct': round(avg_l_a, 4),
            'p_value': round(p_a, 4),
            'significant': p_a < ALPHA,
            'n_needed_for_wr_target': n_need_target,
        },
        'high_score_trades': {
            'min_score': 3.4,
            'n': len(hs_profits),
            'wr': round(wr_hs, 4),
            'wr_ci_lo': round(wr_lo2, 4),
            'wr_ci_hi': round(wr_hi2, 4),
            'expectancy_pct': round(exp_hs, 4),
            'exp_ci_lo': round(exp_lo2, 4),
            'exp_ci_hi': round(exp_hi2, 4),
            'p_value': round(p_hs, 4),
            'significant': p_hs < ALPHA,
            'n_needed': n_need_hs,
        },
        'outcome_distribution': {
            'wins': len(wins_),
            'sl_hits': len(sl_hits),
            'breakeven_saved': len(be_saved),
            'total': n_total,
        },
        'by_market_condition': cond_results,
        'power_analysis': {
            'current_n': nc,
            'n_for_wr_40pct': n40,
            'n_for_wr_45pct': n45,
            'n_for_wr_50pct': n50,
        },
        'key_conclusions': conclusions,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
        json.dump(summary, fout, ensure_ascii=False, indent=2)

    print("=" * 65)
    print("Key Conclusions:")
    for i, c in enumerate(conclusions, 1):
        print("  " + str(i) + ". " + c)
    print()
    print("Results saved: " + OUTPUT_FILE)
    print("=" * 65)
    return summary


if __name__ == '__main__':
    run()
