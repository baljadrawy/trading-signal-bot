#!/usr/bin/env python3
"""
Part 45: MFE (Maximum Favorable Excursion) + Wide R:R Test
2026-06-19

Uses real OHLC from Binance API to compute per-trade MFE.
Tests whether wider TP targets (2R/4R/6R and 3R/5R/8R) would produce
positive expectancy — using actual intra-trade price data.

Method:
1. Fetch all post-freeze trades (entry_price, stop_loss, signal_time, exit_time, symbol)
2. Fetch 1h OHLC klines for each trade window from Binance API
3. Compute MFE as max(high) over the trade window, in % from entry
4. Convert MFE to R-multiple: MFE_R = MFE_pct / SL_pct
5. Simulate: if MFE_R >= threshold, count as WIN; else same result as original
6. Compute E_adj = E_gross - 0.3% fees for each variant
7. Compare vs baseline
"""

import asyncio
import asyncpg
import urllib.request
import json
import time
import sys
from datetime import datetime, timezone
sys.path.insert(0, '/app')
from shared.logger import setup_logger

logger = setup_logger('backtester.part45')

DB_CONFIG = {
    'host': '172.21.0.2',
    'user': 'trading_signal_bot',
    'password': '6psgaD1GV2ClGtopvSe5Lm8za',
    'database': 'trading_signals'
}

def fetch_klines(symbol, interval, start_ms, end_ms, max_retries=3):
    """Fetch OHLC klines from Binance REST API"""
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}"
        f"&startTime={int(start_ms)}&endTime={int(end_ms)}&limit=1000"
    )
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
                return data
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.warning(f"Failed to fetch {symbol}: {e}")
                return []

def compute_mfe(klines, entry_price):
    """Compute MFE as max high relative to entry price (%)"""
    if not klines:
        return None
    max_high = max(float(k[2]) for k in klines)
    mfe_pct = (max_high - entry_price) / entry_price * 100
    return mfe_pct

async def main():
    logger.info("=== Part 45: MFE Analysis + Wide R:R Test ===")

    conn = await asyncpg.connect(**DB_CONFIG)

    # Fetch all post-freeze closed trades with signal data
    trades = await conn.fetch("""
        SELECT
            tr.id, tr.symbol, tr.result, tr.profit_usdt, tr.profit_percent,
            tr.stop_hit, tr.target_reached, tr.entry_price, tr.exit_price,
            tr.duration_hours, tr.exit_time,
            s.signal_time, s.stop_loss, s.target_1, s.target_2, s.target_3,
            s.score, s.market_condition, s.score_details
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.exit_time >= '2026-05-17'
          AND tr.result IS NOT NULL
        ORDER BY tr.exit_time ASC
    """)

    await conn.close()

    logger.info(f"Loaded {len(trades)} trades from DB")

    results = []
    failed_mfe = 0

    for i, t in enumerate(trades):
        symbol = t['symbol']
        entry = float(t['entry_price'])
        sl = float(t['stop_loss'])
        sig_time = t['signal_time']
        exit_time = t['exit_time']

        # Compute SL distance in %
        sl_pct = abs((entry - sl) / entry * 100)
        if sl_pct < 0.01:
            failed_mfe += 1
            continue

        # Convert timestamps to milliseconds
        start_ms = sig_time.timestamp() * 1000
        end_ms = exit_time.timestamp() * 1000

        # Add buffer: 24h extra to capture MFE beyond exit
        end_ms_extended = end_ms + (24 * 3600 * 1000)

        # Fetch 1h klines for the trade window (extended)
        klines = fetch_klines(symbol, '1h', start_ms, end_ms_extended)

        if not klines:
            failed_mfe += 1
            mfe_pct = None
            mfe_r = None
        else:
            mfe_pct = compute_mfe(klines, entry)
            mfe_r = mfe_pct / sl_pct if sl_pct > 0 else None

        # Calculate R:R baseline targets
        r1_pct = sl_pct * 1.0   # 1R

        results.append({
            'id': t['id'],
            'symbol': symbol,
            'result': t['result'],
            'profit_usdt': float(t['profit_usdt']),
            'profit_pct': float(t['profit_percent']),
            'stop_hit': t['stop_hit'],
            'target_reached': t['target_reached'],
            'entry': entry,
            'sl': sl,
            'sl_pct': sl_pct,
            'mfe_pct': mfe_pct,
            'mfe_r': mfe_r,
            'duration_h': float(t['duration_hours'] or 0),
            'score': t['score'],
            'market': t['market_condition'],
            'score_details': t['score_details']
        })

        # Rate limit: small pause every 10 requests
        if (i + 1) % 10 == 0:
            time.sleep(0.5)
            logger.info(f"  Progress: {i+1}/{len(trades)} trades processed")

    logger.info(f"MFE computed: {len(results)-failed_mfe} success, {failed_mfe} failed")

    # Filter to trades with valid MFE
    valid = [r for r in results if r['mfe_r'] is not None]
    n_valid = len(valid)
    logger.info(f"Valid MFE trades: {n_valid}")

    if n_valid == 0:
        logger.error("No valid MFE data — aborting")
        return

    # Baseline stats
    baseline_wins = [r for r in valid if r['profit_usdt'] > 0]
    baseline_losses = [r for r in valid if r['profit_usdt'] <= 0]
    baseline_wr = len(baseline_wins) / n_valid
    baseline_avg_win = sum(r['profit_pct'] for r in baseline_wins) / len(baseline_wins) if baseline_wins else 0
    baseline_avg_loss = abs(sum(r['profit_pct'] for r in baseline_losses) / len(baseline_losses)) if baseline_losses else 0
    baseline_e = (baseline_wr * baseline_avg_win) - ((1 - baseline_wr) * baseline_avg_loss)
    baseline_e_adj = baseline_e - 0.3
    baseline_net = sum(r['profit_usdt'] for r in valid)

    logger.info(f"\n--- BASELINE (n={n_valid}) ---")
    logger.info(f"WR={baseline_wr*100:.1f}% | avg_win={baseline_avg_win:.3f}% | avg_loss={baseline_avg_loss:.3f}%")
    logger.info(f"E={baseline_e:.3f}% | E_adj={baseline_e_adj:.3f}% | Net=${baseline_net:.2f}")

    # MFE Distribution
    mfe_vals = [r['mfe_r'] for r in valid]
    mfe_vals_sorted = sorted(mfe_vals)

    # Percentiles
    def pct(vals, p):
        idx = int(len(vals) * p / 100)
        return vals[min(idx, len(vals)-1)]

    logger.info(f"\n--- MFE Distribution (n={n_valid}) ---")
    logger.info(f"MFE_R p10={pct(mfe_vals_sorted,10):.2f} | p25={pct(mfe_vals_sorted,25):.2f} | "
                f"p50={pct(mfe_vals_sorted,50):.2f} | p75={pct(mfe_vals_sorted,75):.2f} | "
                f"p90={pct(mfe_vals_sorted,90):.2f}")

    # Count how many trades have MFE >= X*R
    for threshold in [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]:
        count = sum(1 for r in valid if r['mfe_r'] >= threshold)
        logger.info(f"  MFE >= {threshold}R: {count}/{n_valid} = {count/n_valid*100:.1f}%")

    # Simulate Wide R:R Variants
    TRADE_AMOUNT = 50.0  # USDT

    def simulate_variant(trades, t1_r, t2_r, t3_r, name):
        """
        Simulate variant where:
        - T1 hit if MFE >= t1_r * SL_pct
        - T2 hit if MFE >= t2_r * SL_pct
        - T3 hit if MFE >= t3_r * SL_pct
        - SL hit if MFE < 1.0R (same as original SL)
        - Partial exits: 50% at T1, 30% at T2, 20% at T3
        """
        wins = 0
        losses = 0
        total_pnl_pct = 0

        for t in trades:
            mfe_r = t['mfe_r']
            sl_pct = t['sl_pct']

            if mfe_r is None:
                continue

            if mfe_r >= t3_r:
                # T3 hit: 50% at T1 + 30% at T2 + 20% at T3
                pnl = (0.5 * t1_r * sl_pct) + (0.3 * t2_r * sl_pct) + (0.2 * t3_r * sl_pct)
                wins += 1
            elif mfe_r >= t2_r:
                # T2 hit: 50% at T1 + 50% at T2 (T3 no)
                pnl = (0.5 * t1_r * sl_pct) + (0.5 * t2_r * sl_pct)
                wins += 1
            elif mfe_r >= t1_r:
                # T1 hit then break-even (same as current system)
                pnl = 0.1 * t1_r * sl_pct  # small positive from T1 partial
                wins += 1
            else:
                # SL hit
                pnl = -sl_pct
                losses += 1

            total_pnl_pct += pnl

        n = wins + losses
        if n == 0:
            return None

        wr = wins / n
        avg_win = total_pnl_pct / wins / 100 * TRADE_AMOUNT if wins > 0 else 0
        avg_loss_pct = sl_pct if losses > 0 else 0
        avg_loss = sum(t['sl_pct'] for t in trades if t['mfe_r'] is not None and t['mfe_r'] < t1_r) / losses if losses > 0 else 0

        e_pct = (wr * (total_pnl_pct / wins if wins > 0 else 0)) - ((1-wr) * avg_loss)
        e_adj = e_pct - 0.3  # fees
        net_usdt = total_pnl_pct / 100 * TRADE_AMOUNT

        logger.info(f"\n--- Variant {name} (T1={t1_r}R, T2={t2_r}R, T3={t3_r}R) ---")
        logger.info(f"WR={wr*100:.1f}% | wins={wins} | losses={losses}")
        logger.info(f"E={e_pct:.3f}% | E_adj={e_adj:.3f}% | Net=${net_usdt:.2f}")

        return {
            'name': name, 't1_r': t1_r, 't2_r': t2_r, 't3_r': t3_r,
            'wr': wr, 'wins': wins, 'losses': losses,
            'e_pct': e_pct, 'e_adj': e_adj, 'net_usdt': net_usdt
        }

    logger.info("\n=== Wide R:R Simulation (using real MFE from OHLC) ===")
    v1 = simulate_variant(valid, t1_r=2.0, t2_r=4.0, t3_r=6.0, name="Variant_A")
    v2 = simulate_variant(valid, t1_r=3.0, t2_r=5.0, t3_r=8.0, name="Variant_B")

    # Compare
    logger.info(f"\n=== COMPARISON ===")
    logger.info(f"Baseline E_adj: {baseline_e_adj:.3f}%")
    if v1:
        logger.info(f"Variant A E_adj: {v1['e_adj']:.3f}% | Delta: {v1['e_adj']-baseline_e_adj:+.3f}%")
    if v2:
        logger.info(f"Variant B E_adj: {v2['e_adj']:.3f}% | Delta: {v2['e_adj']-baseline_e_adj:+.3f}%")

    # STOCH filter impact on MFE
    logger.info(f"\n=== Stoch Filter Impact on MFE ===")
    stoch_pos = [r for r in valid if r['score_details'] and
                 isinstance(r['score_details'], dict) and
                 float(r['score_details'].get('stoch_rsi', 0) or 0) > 0]
    stoch_zero = [r for r in valid if r['score_details'] and
                  isinstance(r['score_details'], dict) and
                  float(r['score_details'].get('stoch_rsi', 0) or 0) == 0]

    if stoch_pos:
        mfe_pos = [r['mfe_r'] for r in stoch_pos if r['mfe_r'] is not None]
        wins_pos = [r for r in stoch_pos if r['profit_usdt'] > 0]
        logger.info(f"stoch>0 (n={len(stoch_pos)}): WR={len(wins_pos)/len(stoch_pos)*100:.1f}% | "
                    f"median_MFE_R={sorted(mfe_pos)[len(mfe_pos)//2]:.2f}")

    if stoch_zero:
        mfe_zero = [r['mfe_r'] for r in stoch_zero if r['mfe_r'] is not None]
        wins_zero = [r for r in stoch_zero if r['profit_usdt'] > 0]
        logger.info(f"stoch=0 (n={len(stoch_zero)}): WR={len(wins_zero)/len(stoch_zero)*100:.1f}% | "
                    f"median_MFE_R={sorted(mfe_zero)[len(mfe_zero)//2]:.2f}")

    logger.info("\n=== Part 45 Complete ===")

if __name__ == '__main__':
    asyncio.run(main())
