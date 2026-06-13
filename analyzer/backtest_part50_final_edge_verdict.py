#!/usr/bin/env python3
"""
Part 50: Final Edge Verdict
─────────────────────────────
After exhaustive search (Parts 33-49 spanning SMC, Wide R:R, COMBO, Volume, RSI Divergence):
- All paths yielded 0 edges after 0.3% fees
- COMBO (stoch+div) = marginal (+2.3% E_adj) but CI crosses zero at n=6 (underpowered)
- Current live WR (42/50 since freeze lift) = 23.8% vs historical baseline 37.3%

This script consolidates evidence and renders a final verdict for reporting.
"""

import asyncio
import json
from datetime import datetime, timezone
import sys
sys.path.append('/app')

from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('part50_verdict')

async def get_recent_trades(days=25):
    """Get all trades since freeze lift 2026-05-17"""
    return await Database.fetch("""
        SELECT
            id, symbol, entry_price, exit_price, result, profit_usdt,
            stop_hit, target_reached, exit_time
        FROM trade_results
        WHERE DATE(exit_time) >= '2026-05-17'
        ORDER BY exit_time ASC
    """)

async def analyze_cohorts(trades):
    """Analyze performance by timeframe, market condition, score ranges"""
    cohorts = {
        'total': {'n': 0, 'w': 0, 'e': 0.0, 'pnl': 0.0},
        'by_target_reached': {},
        'by_stop_hit': {},
    }

    for trade in trades:
        cohorts['total']['n'] += 1
        if trade['result'] == 'WIN':
            cohorts['total']['w'] += 1
        pnl = float(trade['profit_usdt'] or 0.0)
        cohorts['total']['pnl'] += pnl
        cohorts['total']['e'] += (pnl / 50)  # assume $50 trade size

        target_key = f"t{trade['target_reached']}"
        if target_key not in cohorts['by_target_reached']:
            cohorts['by_target_reached'][target_key] = {'n': 0, 'w': 0, 'e': 0.0, 'pnl': 0.0}
        cohorts['by_target_reached'][target_key]['n'] += 1
        if trade['result'] == 'WIN':
            cohorts['by_target_reached'][target_key]['w'] += 1
        cohorts['by_target_reached'][target_key]['pnl'] += float(pnl)
        cohorts['by_target_reached'][target_key]['e'] += (float(pnl) / 50)

        sl_key = 'sl_hit' if trade['stop_hit'] else 'no_sl'
        if sl_key not in cohorts['by_stop_hit']:
            cohorts['by_stop_hit'][sl_key] = {'n': 0, 'w': 0, 'e': 0.0, 'pnl': 0.0}
        cohorts['by_stop_hit'][sl_key]['n'] += 1
        if trade['result'] == 'WIN':
            cohorts['by_stop_hit'][sl_key]['w'] += 1
        cohorts['by_stop_hit'][sl_key]['pnl'] += float(pnl)
        cohorts['by_stop_hit'][sl_key]['e'] += (float(pnl) / 50)

    # Calculate win rates
    for key in cohorts:
        if key == 'total':
            cohorts[key]['wr'] = (100.0 * cohorts[key]['w'] / cohorts[key]['n']) if cohorts[key]['n'] > 0 else 0.0
        else:
            for sub_key in cohorts[key]:
                cohorts[key][sub_key]['wr'] = (100.0 * cohorts[key][sub_key]['w'] / cohorts[key][sub_key]['n']) if cohorts[key][sub_key]['n'] > 0 else 0.0

    return cohorts

async def main():
    await Database.connect()

    trades = await get_recent_trades(25)
    cohorts = await analyze_cohorts(trades)

    logger.info(f"\n═══ FINAL EDGE VERDICT (Cycle 19) ═══\n")

    logger.info(f"Total Closed Since Freeze Lift (2026-05-17): {cohorts['total']['n']}/50")
    logger.info(f"  W/L: {cohorts['total']['w']}/{cohorts['total']['n']-cohorts['total']['w']}")
    logger.info(f"  WR: {cohorts['total']['wr']:.1f}%")
    logger.info(f"  E_adj: ${cohorts['total']['e']:.4f}/trade")
    logger.info(f"  Net PnL: ${cohorts['total']['pnl']:.2f}")

    logger.info(f"\nBy Target Hit:")
    for target_key in sorted(cohorts['by_target_reached'].keys()):
        c = cohorts['by_target_reached'][target_key]
        logger.info(f"  {target_key}: n={c['n']}, WR={c['wr']:.1f}%, E=${c['e']:.4f}, PnL=${c['pnl']:.2f}")

    logger.info(f"\nBy Stop Hit:")
    for sl_key in sorted(cohorts['by_stop_hit'].keys()):
        c = cohorts['by_stop_hit'][sl_key]
        logger.info(f"  {sl_key}: n={c['n']}, WR={c['wr']:.1f}%, E=${c['e']:.4f}, PnL=${c['pnl']:.2f}")

    # Historical baseline for comparison
    hist_trades = await Database.fetch("SELECT COUNT(*) as n FROM trade_results WHERE result='WIN'")
    total_hist = await Database.fetchval("SELECT COUNT(*) FROM trade_results")
    hist_wr = (100.0 * (hist_trades[0]['n'] if hist_trades and hist_trades[0]['n'] else 0) / total_hist) if total_hist > 0 else 0.0

    logger.info(f"\nHistorical Baseline (all {total_hist} trades): WR={hist_wr:.1f}%")
    logger.info(f"Recent vs Baseline: {cohorts['total']['wr']:.1f}% vs {hist_wr:.1f}% → "
                f"{'DEGRADED' if cohorts['total']['wr'] < hist_wr else 'IMPROVED'}")

    # Final verdict
    logger.info(f"\n═══ EVIDENCE SUMMARY ═══")
    logger.info(f"1. SMC Research (Part 33-39): All features q>0.05 or E_adj negative → NO EDGE")
    logger.info(f"2. Wide R:R (Part 34, 38): E_adj=-36.5% vs baseline -0.4% → TOXIC")
    logger.info(f"3. COMBO (Part 45-46): E_adj=+2.3% at n=6 but CI crosses zero → UNDERPOWERED")
    logger.info(f"4. Live Performance (42/50): WR=23.8% vs historical 37.3% → DEGRADATION")
    logger.info(f"\n═══ FINAL VERDICT ═══")
    logger.info(f"Current market regime contains NO statistically significant edge after 0.3% fees.")
    logger.info(f"Recommendation: Either (a) freeze until market mean-reverting regime returns,")
    logger.info(f"  or (b) pivot to explicit edge discovery framework (ML classifier on 2k+ historical trades).")
    logger.info(f"No further parameter tuning will improve WR—the hypothesis is exhausted.")

    # Save to leaderboard
    verdict = {
        'cycle': 19,
        'status': 'FINAL VERDICT',
        'trades_closed': cohorts['total']['n'],
        'wr_pct': cohorts['total']['wr'],
        'e_adj': cohorts['total']['e'],
        'pnl_usdt': cohorts['total']['pnl'],
        'vs_baseline': f"{cohorts['total']['wr']:.1f}% vs {hist_wr:.1f}%",
        'edge_found': False,
        'evidence': [
            'SMC: all features q>0.05',
            'Wide RR: E=-36.5%',
            'COMBO: n=6 underpowered',
            'Live WR: 23.8%'
        ],
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    with open('/app/edge_leaderboard.jsonl', 'a') as f:
        f.write(json.dumps(verdict) + '\n')

    logger.info(f"\nVERDICT saved to edge_leaderboard.jsonl")

    await Database.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
