"""
الجزء 25 — تحليل stoch_rsi كفلتر على 1d+bearish/sideways
هدف: هل stoch_rsi>0 يُحسّن WR وExpectancy بشكل دال على n=281 (pre-freeze)?
وهل نمط post-freeze (n=7) يتسق مع pre-freeze؟
الفلسفة: بيانات pre-freeze أكبر → تحكم في صلاحية الفلتر.
"""
import sys
import os
import json
import math
sys.path.insert(0, '/home/tradmin/trading-signal-bot')

import asyncio
import asyncpg

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"

async def main():
    print(f"Connecting to DB...")
    conn = await asyncpg.connect(DB_URL)

    # ──────────────────────────────────────────────
    # 1. Pull all 1d+bearish/sideways closed trades with score_details
    # ──────────────────────────────────────────────
    rows = await conn.fetch("""
        SELECT
            s.id,
            s.symbol,
            s.timeframe,
            s.market_condition,
            s.score,
            s.score_details,
            s.signal_time,
            tr.result,
            tr.profit_percent,
            tr.profit_usdt,
            tr.stop_hit,
            tr.target_reached,
            tr.duration_hours,
            tr.exit_time
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
        ORDER BY tr.exit_time ASC
    """)

    print(f"\nTotal 1d+bearish/sideways closed trades: {len(rows)}")

    if len(rows) < 10:
        print("Insufficient data — aborting")
        await conn.close()
        return

    # ──────────────────────────────────────────────
    # 2. Split by period: pre-freeze (before 2026-05-17) vs post-freeze
    # ──────────────────────────────────────────────
    from datetime import datetime, timezone
    freeze_date = datetime(2026, 5, 17, 0, 0, 0)

    pre_freeze = []
    post_freeze = []

    for row in rows:
        sd = row['score_details']
        if isinstance(sd, str):
            sd = json.loads(sd)
        elif sd is None:
            sd = {}

        trade = {
            'symbol': row['symbol'],
            'timeframe': row['timeframe'],
            'market_condition': row['market_condition'],
            'score': row['score'],
            'result': row['result'],
            'profit_pct': float(row['profit_percent'] or 0),
            'profit_usdt': float(row['profit_usdt'] or 0),
            'stop_hit': row['stop_hit'],
            'target_reached': row['target_reached'],
            'duration_hours': float(row['duration_hours'] or 0),
            'stoch_rsi': float(sd.get('stoch_rsi', 0) or 0),
            'rsi_div': float(sd.get('rsi_divergence', 0) or 0),
            'fibonacci': float(sd.get('fibonacci', 0) or 0),
            'bollinger': float(sd.get('bollinger', 0) or 0),
            'rsi': float(sd.get('rsi', 0) or 0),
            'exit_time': row['exit_time'],
        }

        exit_time = row['exit_time']
        if exit_time is not None:
            # asyncpg returns datetime objects
            if hasattr(exit_time, 'replace'):
                et = exit_time.replace(tzinfo=None)
            else:
                et = exit_time
            if et < freeze_date:
                pre_freeze.append(trade)
            else:
                post_freeze.append(trade)
        else:
            pre_freeze.append(trade)

    print(f"Pre-freeze: {len(pre_freeze)} trades | Post-freeze: {len(post_freeze)} trades")

    # ──────────────────────────────────────────────
    # 3. Helper functions
    # ──────────────────────────────────────────────
    COST_PCT = 0.003  # 0.30% round-trip (taker)

    def expectancy(trades):
        """E_adj = avg(profit_pct - COST_PCT) per trade"""
        if not trades:
            return 0, 0, 0, 0
        wins = [t for t in trades if t['result'] == 'WIN']
        losses = [t for t in trades if t['result'] == 'LOSS']
        wr = len(wins) / len(trades)
        avg_win = sum(t['profit_pct'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['profit_pct'] for t in losses) / len(losses) if losses else 0
        e_adj = sum(t['profit_pct'] - COST_PCT for t in trades) / len(trades)
        return wr, avg_win, avg_loss, e_adj

    def permutation_test(group_a, group_b, n_perm=1000):
        """
        One-sided permutation test: H0 = group_a E_adj <= group_b E_adj
        H1 = group_a E_adj > group_b E_adj
        """
        if not group_a or not group_b:
            return 1.0
        all_trades = group_a + group_b
        na = len(group_a)
        obs_diff = (sum(t['profit_pct'] for t in group_a) / na) - \
                   (sum(t['profit_pct'] for t in group_b) / len(group_b))

        import random
        random.seed(42)
        count_ge = 0
        pcts = [t['profit_pct'] for t in all_trades]
        for _ in range(n_perm):
            random.shuffle(pcts)
            perm_diff = sum(pcts[:na]) / na - sum(pcts[na:]) / len(group_b)
            if perm_diff >= obs_diff:
                count_ge += 1
        return count_ge / n_perm

    def print_group_stats(label, trades):
        if not trades:
            print(f"  {label}: n=0")
            return
        wr, avg_win, avg_loss, e_adj = expectancy(trades)
        total_pnl = sum(t['profit_usdt'] for t in trades)
        sl_count = sum(1 for t in trades if t['stop_hit'])
        print(f"  {label}: n={len(trades)} | WR={wr*100:.1f}% | "
              f"avg_win={avg_win:.2f}% avg_loss={avg_loss:.2f}% | "
              f"E_adj={e_adj:.3f}% | PnL=${total_pnl:.2f} | SL={sl_count}")

    # ──────────────────────────────────────────────
    # 4. ANALYSIS A: stoch_rsi filter on pre-freeze data
    # ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("ANALYSIS A — stoch_rsi filter on PRE-FREEZE (1d+bear/side)")
    print("="*60)

    thresholds = [0.0, 0.3, 0.5, 0.7, 0.9]

    for thr in thresholds:
        group_yes = [t for t in pre_freeze if t['stoch_rsi'] > thr]
        group_no  = [t for t in pre_freeze if t['stoch_rsi'] <= thr]
        print(f"\n  stoch_rsi > {thr}:")
        print_group_stats(f"    YES (>{thr})", group_yes)
        print_group_stats(f"    NO  (<={thr})", group_no)
        if len(group_yes) >= 5 and len(group_no) >= 5:
            p = permutation_test(group_yes, group_no)
            print(f"    Permutation p-value (YES>NO): {p:.3f} {'*** SIGNIFICANT' if p<0.05 else '(not significant)'}")

    # ──────────────────────────────────────────────
    # 5. ANALYSIS B: rsi_divergence filter on pre-freeze
    # ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("ANALYSIS B — rsi_divergence filter on PRE-FREEZE")
    print("="*60)

    for thr in [0.0, 0.5, 1.0, 1.5]:
        group_yes = [t for t in pre_freeze if t['rsi_div'] > thr]
        group_no  = [t for t in pre_freeze if t['rsi_div'] <= thr]
        print(f"\n  rsi_div > {thr}:")
        print_group_stats(f"    YES", group_yes)
        print_group_stats(f"    NO ", group_no)
        if len(group_yes) >= 5 and len(group_no) >= 5:
            p = permutation_test(group_yes, group_no)
            print(f"    Permutation p-value: {p:.3f} {'*** SIGNIFICANT' if p<0.05 else '(not significant)'}")

    # ──────────────────────────────────────────────
    # 6. ANALYSIS C: Combined stoch_rsi + rsi_div filter
    # ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("ANALYSIS C — Combined (stoch_rsi>0 AND rsi_div>0) on PRE-FREEZE")
    print("="*60)

    combinations = [
        ("stoch>0 AND div>0", lambda t: t['stoch_rsi'] > 0 and t['rsi_div'] > 0),
        ("stoch>0 OR div>0",  lambda t: t['stoch_rsi'] > 0 or t['rsi_div'] > 0),
        ("stoch>0 only",      lambda t: t['stoch_rsi'] > 0),
        ("div>0 only",        lambda t: t['rsi_div'] > 0),
        ("stoch<=0 AND div=0",lambda t: t['stoch_rsi'] <= 0 and t['rsi_div'] == 0),
    ]

    for label, cond in combinations:
        grp = [t for t in pre_freeze if cond(t)]
        rest = [t for t in pre_freeze if not cond(t)]
        print(f"\n  {label}:")
        print_group_stats(f"    Pass", grp)
        print_group_stats(f"    Fail", rest)

    # ──────────────────────────────────────────────
    # 7. ANALYSIS D: Score distribution in pre-freeze
    # ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("ANALYSIS D — Score breakdown on PRE-FREEZE (raw scores 3-5)")
    print("="*60)

    score_thresholds = [
        ("score=3 (2.5-3.49)",  lambda t: 2.5 <= t['score'] < 3.5),
        ("score=4 (3.5-4.49)",  lambda t: 3.5 <= t['score'] < 4.5),
        ("score=5 (4.5+)",      lambda t: t['score'] >= 4.5),
    ]
    for label, cond in score_thresholds:
        grp = [t for t in pre_freeze if cond(t)]
        print(f"\n  {label}:")
        print_group_stats(f"    All", grp)
        if grp:
            stoch_yes = [t for t in grp if t['stoch_rsi'] > 0]
            stoch_no  = [t for t in grp if t['stoch_rsi'] <= 0]
            print_group_stats(f"    stoch>0", stoch_yes)
            print_group_stats(f"    stoch=0", stoch_no)

    # ──────────────────────────────────────────────
    # 8. ANALYSIS E: Post-freeze confirmation
    # ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("ANALYSIS E — POST-FREEZE confirmation (n=7)")
    print("="*60)
    print_group_stats("All post-freeze", post_freeze)
    if post_freeze:
        pf_stoch_yes = [t for t in post_freeze if t['stoch_rsi'] > 0]
        pf_stoch_no  = [t for t in post_freeze if t['stoch_rsi'] <= 0]
        pf_div_yes   = [t for t in post_freeze if t['rsi_div'] > 0]
        pf_div_no    = [t for t in post_freeze if t['rsi_div'] <= 0]
        pf_both_yes  = [t for t in post_freeze if t['stoch_rsi'] > 0 and t['rsi_div'] > 0]
        pf_both_no   = [t for t in post_freeze if t['stoch_rsi'] <= 0 and t['rsi_div'] == 0]
        print_group_stats("stoch>0", pf_stoch_yes)
        print_group_stats("stoch=0", pf_stoch_no)
        print_group_stats("div>0",   pf_div_yes)
        print_group_stats("div=0",   pf_div_no)
        print_group_stats("both>0",  pf_both_yes)
        print_group_stats("both=0",  pf_both_no)

    # ──────────────────────────────────────────────
    # 9. Summary Decision
    # ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("DECISION SUMMARY")
    print("="*60)

    # Compute the key numbers
    pre_stoch_yes = [t for t in pre_freeze if t['stoch_rsi'] > 0]
    pre_stoch_no  = [t for t in pre_freeze if t['stoch_rsi'] <= 0]
    pre_div_yes   = [t for t in pre_freeze if t['rsi_div'] > 0]
    pre_div_no    = [t for t in pre_freeze if t['rsi_div'] <= 0]
    pre_both      = [t for t in pre_freeze if t['stoch_rsi'] > 0 and t['rsi_div'] > 0]

    wr_yes, _, _, e_yes = expectancy(pre_stoch_yes)
    wr_no, _, _, e_no   = expectancy(pre_stoch_no)
    wr_div_y, _, _, e_div_y = expectancy(pre_div_yes)
    wr_div_n, _, _, e_div_n = expectancy(pre_div_no)
    wr_both, _, _, e_both = expectancy(pre_both)

    if len(pre_stoch_yes) >= 5 and len(pre_stoch_no) >= 5:
        p_stoch = permutation_test(pre_stoch_yes, pre_stoch_no)
    else:
        p_stoch = 1.0

    if len(pre_div_yes) >= 5 and len(pre_div_no) >= 5:
        p_div = permutation_test(pre_div_yes, pre_div_no)
    else:
        p_div = 1.0

    print(f"\nstoch_rsi>0 filter:")
    print(f"  YES: n={len(pre_stoch_yes)}, WR={wr_yes*100:.1f}%, E_adj={e_yes:.3f}%")
    print(f"  NO:  n={len(pre_stoch_no)},  WR={wr_no*100:.1f}%,  E_adj={e_no:.3f}%")
    print(f"  p-value: {p_stoch:.3f} | Verdict: {'SIGNIFICANT — filter IS predictive' if p_stoch<0.05 else 'NOT significant — filter not predictive on pre-freeze'}")

    print(f"\nrsi_divergence>0 filter:")
    print(f"  YES: n={len(pre_div_yes)}, WR={wr_div_y*100:.1f}%, E_adj={e_div_y:.3f}%")
    print(f"  NO:  n={len(pre_div_no)},  WR={wr_div_n*100:.1f}%,  E_adj={e_div_n:.3f}%")
    print(f"  p-value: {p_div:.3f} | Verdict: {'SIGNIFICANT' if p_div<0.05 else 'NOT significant'}")

    print(f"\nBoth (stoch>0 AND div>0):")
    print(f"  n={len(pre_both)}, WR={wr_both*100:.1f}%, E_adj={e_both:.3f}%")

    # Impact calculation if stoch filter applied
    if pre_stoch_no:
        filtered_out_pnl = sum(t['profit_usdt'] for t in pre_stoch_no)
        filtered_kept_pnl = sum(t['profit_usdt'] for t in pre_stoch_yes)
        print(f"\nImpact of applying stoch>0 filter (pre-freeze):")
        print(f"  Trades kept:    n={len(pre_stoch_yes)}, PnL=${filtered_kept_pnl:.2f}")
        print(f"  Trades removed: n={len(pre_stoch_no)},  PnL=${filtered_out_pnl:.2f}")
        print(f"  Net impact: ${filtered_kept_pnl - (filtered_kept_pnl + filtered_out_pnl):.2f} "
              f"(+${-filtered_out_pnl:.2f} avoided)")

    await conn.close()
    print("\n[Part 25 complete]")


if __name__ == '__main__':
    asyncio.run(main())
