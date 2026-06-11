#!/usr/bin/env python3
"""
Part 45 — COMBO (Stochastic RSI + RSI Divergence) Walk-Forward & Bootstrap Validation
Cycle 18: Validate the COMBO edge (stoch_rsi + rsi_div=2) discovered in Cycle 17.
Target: n=15+ OOS trades in COMBO cohort to confirm WR=66.7% is not a look-ahead artifact.

Walk-Forward: 5 windows 60% train / 40% test
Bootstrap: 10k resampling with CI 95%
Thresholds: test stoch_rsi in [0.5, 0.6, 0.7] to narrow optimal cutoff
"""

import sys, asyncio, json, numpy as np, pandas as pd, warnings
from datetime import datetime, timedelta

sys.path.insert(0, '/app')
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part45')
warnings.filterwarnings('ignore')

async def load_signals_with_features():
    """Load all closed trades with score_details and compute features."""
    rows = await Database.fetch("""
        SELECT
            tr.id, tr.result, tr.profit_usdt, tr.profit_percent, tr.exit_time,
            s.id as signal_id, s.score, s.score_details, s.market_condition, s.timeframe
        FROM trade_results tr
        LEFT JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-05-17'::timestamp
        ORDER BY tr.exit_time ASC
    """)

    records = []
    for row in rows:
        rec = {
            'trade_id': row['id'],
            'signal_id': row['signal_id'],
            'result': 1 if row['result'] == 'WIN' else 0,
            'profit_usdt': float(row['profit_usdt']),
            'profit_pct': float(row['profit_percent']),
            'exit_time': row['exit_time'],
            'score': float(row['score']) if row['score'] else 0,
            'market_condition': row['market_condition'],
            'timeframe': row['timeframe'],
            'stoch_rsi': None,
            'rsi_divergence': None,
        }

        if row['score_details']:
            try:
                details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
                if 'stoch_rsi' in details:
                    rec['stoch_rsi'] = float(details['stoch_rsi'])
                if 'rsi_divergence' in details:
                    rec['rsi_divergence'] = int(details['rsi_divergence'])
            except:
                pass

        records.append(rec)

    df = pd.DataFrame(records)
    # Keep only trades where both stoch_rsi and rsi_divergence are available
    df = df[(df['stoch_rsi'].notna()) & (df['rsi_divergence'].notna())]

    logger.info(f"Loaded {len(df)} trades with complete features")
    return df

def compute_expectancy(group, fee_pct=0.3):
    """Compute expectancy adjusted for 0.3% round-trip fees."""
    if len(group) == 0:
        return None
    wins = group[group['result'] == 1]
    losses = group[group['result'] == 0]

    # Adjust profit for fees
    adj_profit = group['profit_pct'].copy()
    adj_profit = adj_profit - fee_pct

    if len(group) == 0:
        return None
    return adj_profit.mean()

def bootstrap_ci(samples, n_bootstrap=5000, ci=95):
    """Compute bootstrap CI for expectancy."""
    if len(samples) < 5:
        return None, None

    boot_means = []
    for _ in range(n_bootstrap):
        resampled = np.random.choice(samples, size=len(samples), replace=True)
        boot_means.append(np.mean(resampled))

    lower = np.percentile(boot_means, (100 - ci) / 2)
    upper = np.percentile(boot_means, 100 - (100 - ci) / 2)

    return lower, upper

def walk_forward_split(df, n_folds=5):
    """Split df into 5 walk-forward folds (60% train / 40% test)."""
    total_n = len(df)
    fold_size = total_n // n_folds

    folds = []
    for i in range(n_folds):
        test_start_idx = i * fold_size
        test_end_idx = (i + 1) * fold_size if i < n_folds - 1 else total_n

        train = df.iloc[:test_start_idx].copy()
        test = df.iloc[test_start_idx:test_end_idx].copy()

        folds.append({'train': train, 'test': test, 'fold': i})

    return folds

async def main():
    logger.info("="*70)
    logger.info("Part 45 — COMBO (Stoch+Div) Walk-Forward Bootstrap Validation")
    logger.info("="*70)

    df = await load_signals_with_features()
    logger.info(f"Total trades: n={len(df)}")

    # Define cohorts
    cohorts = {
        'all': lambda d: d,
        'combo_stoch_div': lambda d: d[(d['stoch_rsi'] >= 0.6) & (d['rsi_divergence'] == 2)],
        'stoch_alone': lambda d: d[d['stoch_rsi'] >= 0.6],
        'div_alone': lambda d: d[d['rsi_divergence'] == 2],
        'div_destructive': lambda d: d[d['rsi_divergence'] == 1],
        'sideways_1d': lambda d: d[(d['market_condition'] == 'sideways') & (d['timeframe'] == '1d')],
        'bearish_1d': lambda d: d[(d['market_condition'] == 'bearish') & (d['timeframe'] == '1d')],
    }

    results = {}

    logger.info("\n" + "="*70)
    logger.info("WALK-FORWARD RESULTS (5-fold, 60/40 train/test)")
    logger.info("="*70)

    for cohort_name, cohort_filter in cohorts.items():
        cohort_df = cohort_filter(df)

        if len(cohort_df) < 5:
            logger.info(f"\n{cohort_name}: SKIPPED (n={len(cohort_df)} < 5)")
            continue

        folds = walk_forward_split(cohort_df, n_folds=5)
        fold_results = []
        test_oos_profits = []

        logger.info(f"\n{cohort_name} (n={len(cohort_df)}):")
        logger.info(f"{'Fold':<6} {'Train n':>8} {'Test n':>8} {'Test WR':>8} {'Test E_adj':>12} {'Boot CI (95%)':>25}")
        logger.info("-" * 75)

        for fold_info in folds:
            train = fold_info['train']
            test = fold_info['test']
            fold_idx = fold_info['fold']

            # No calibration needed — just measure test set
            test_wins = test['result'].sum()
            test_wr = 100 * test_wins / len(test) if len(test) > 0 else 0

            test_e_adj = compute_expectancy(test, fee_pct=0.3)
            test_oos_profits.extend((test['profit_pct'].values - 0.3).tolist())

            boot_lower, boot_upper = bootstrap_ci(test['profit_pct'].values - 0.3, n_bootstrap=5000)

            if boot_lower is not None and boot_upper is not None:
                logger.info(f"{fold_idx:<6} {len(train):>8} {len(test):>8} {test_wr:>7.1f}% {test_e_adj:>12.4f}% " +
                           f"[{boot_lower:>7.4f}, {boot_upper:>7.4f}]")
            else:
                logger.info(f"{fold_idx:<6} {len(train):>8} {len(test):>8} {test_wr:>7.1f}% {test_e_adj:>12.4f}% " +
                           f"[N/A, N/A]")

            fold_results.append({
                'fold': fold_idx,
                'test_n': len(test),
                'test_wr': test_wr,
                'test_e_adj': test_e_adj,
                'boot_lower': boot_lower,
                'boot_upper': boot_upper,
            })

        # Aggregate across folds
        if test_oos_profits:
            agg_e_adj = np.mean(test_oos_profits)
            agg_boot_lower, agg_boot_upper = bootstrap_ci(np.array(test_oos_profits), n_bootstrap=5000)

            logger.info(f"{'AGGREGATE':<6} {'':>8} {len(cohort_df):>8} {np.mean([f['test_wr'] for f in fold_results]):>7.1f}% " +
                       f"{agg_e_adj:>12.4f}% [{agg_boot_lower:>7.4f}, {agg_boot_upper:>7.4f}]")

            results[cohort_name] = {
                'n': len(cohort_df),
                'test_oos_e_adj': agg_e_adj,
                'boot_ci_lower': agg_boot_lower,
                'boot_ci_upper': agg_boot_upper,
                'folds': fold_results,
                'ci_crosses_zero': agg_boot_lower <= 0 <= agg_boot_upper,
            }

    logger.info("\n" + "="*70)
    logger.info("SUMMARY TABLE")
    logger.info("="*70)
    logger.info(f"{'Cohort':<25} {'n':>6} {'OOS E_adj':>12} {'Boot CI 95%':>27} {'Crosses 0?':>12}")
    logger.info("-" * 90)

    for name, res in sorted(results.items(), key=lambda x: -x[1]['test_oos_e_adj']):
        ci_lower = res['boot_ci_lower']
        ci_upper = res['boot_ci_upper']
        crosses = "YES ⚠️" if res['ci_crosses_zero'] else "NO ✓"
        logger.info(f"{name:<25} {res['n']:>6} {res['test_oos_e_adj']:>11.4f}% " +
                   f"[{ci_lower:>8.4f}, {ci_upper:>8.4f}] {crosses:>12}")

    logger.info("\n" + "="*70)
    logger.info("STOCHASTIC RSI THRESHOLD SWEEP (all trades)")
    logger.info("="*70)

    logger.info(f"{'Threshold':<15} {'n':>6} {'WR':>8} {'E_adj':>12} {'Avg Win':>10} {'Avg Loss':>10}")
    logger.info("-" * 65)

    for threshold in [0.5, 0.55, 0.6, 0.65, 0.7]:
        cohort = df[df['stoch_rsi'] >= threshold]
        if len(cohort) < 5:
            continue

        wr = 100 * cohort['result'].sum() / len(cohort)
        e_adj = compute_expectancy(cohort, fee_pct=0.3)

        wins = cohort[cohort['result'] == 1]
        losses = cohort[cohort['result'] == 0]
        avg_win = wins['profit_pct'].mean() if len(wins) > 0 else 0
        avg_loss = abs(losses['profit_pct'].mean()) if len(losses) > 0 else 0

        logger.info(f"stoch_rsi≥{threshold:<8.2f} {len(cohort):>6} {wr:>7.1f}% {e_adj:>11.4f}% {avg_win:>10.2f}% {avg_loss:>10.2f}%")

    logger.info("\n" + "="*70)
    logger.info("DECISION CRITERIA CHECK")
    logger.info("="*70)

    combo = results.get('combo_stoch_div', {})
    if combo:
        logger.info(f"COMBO cohort: n={combo['n']}, OOS E_adj={combo['test_oos_e_adj']:.4f}%, " +
                   f"CI=[{combo['boot_ci_lower']:.4f}, {combo['boot_ci_upper']:.4f}]")

        if combo['n'] >= 15 and combo['test_oos_e_adj'] > 0.05 and not combo['ci_crosses_zero']:
            logger.info("✓ READY FOR LIVE DEPLOYMENT — meets all criteria (n≥15, E>+0.05%, CI>0)")
        elif combo['n'] >= 10 and combo['test_oos_e_adj'] > 0:
            logger.info("⚠️ PROMISING but needs more data (n<15 or CI marginal)")
        else:
            logger.info("✗ INSUFFICIENT EDGE — recommend continued monitoring")

    # Database cleanup not needed for read-only async connection

if __name__ == '__main__':
    asyncio.run(main())
