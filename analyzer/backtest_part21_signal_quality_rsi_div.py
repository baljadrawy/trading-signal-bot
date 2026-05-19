"""
الجزء 21 من الباكتيستر — تحليل جودة الإشارة: rsi_divergence vs RSI+Bollinger فقط
الهدف: هل الإشارات ذات rsi_divergence>0 تُحقق WR أفضل من تلك التي تعتمد RSI+Bollinger+Fibonacci فقط؟
       وهل ينبغي استخدام rsi_divergence كفلتر ثانوي للإشارات؟
المنهج:
  - تقسيم 1d+bearish/sideways إلى: has_rsi_div (rsi_div>0) vs no_rsi_div
  - مقارنة WR, E_adj, avg_win, avg_loss
  - Permutation test لاستبعاد الصدفة
  - تحليل مجموعات الإشارة (RSI+BB, RSI+DIV, DIV+STOCH, إلخ)
قيود الخادم: معالجة تدريجية، bootstrap ≤500، لا حزم جديدة
"""
import json
import sys
import random
import asyncio
import asyncpg
from datetime import datetime, timezone

sys.path.insert(0, '/home/tradmin/trading-signal-bot')

FEE_PCT = 0.003
DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
N_PERMUTATIONS = 500
REBUILD_DATE = '2026-04-22 00:00:00'


def e_adj(trades):
    if not trades:
        return 0.0
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    n = len(trades)
    wr = len(wins) / n
    avg_w = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_l = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
    return wr * (avg_w - FEE_PCT * 100) + (1 - wr) * (avg_l - FEE_PCT * 100)


def permutation_test(group_a, group_b, stat_fn, n_perm=500):
    """اختبار الإذن — هل الفرق في الإحصائية بين A وB حقيقي؟"""
    if not group_a or not group_b:
        return 1.0
    observed = stat_fn(group_a) - stat_fn(group_b)
    combined = group_a + group_b
    n_a = len(group_a)
    count = 0
    for _ in range(n_perm):
        random.shuffle(combined)
        perm_a = combined[:n_a]
        perm_b = combined[n_a:]
        perm_diff = stat_fn(perm_a) - stat_fn(perm_b)
        if abs(perm_diff) >= abs(observed):
            count += 1
    return count / n_perm


def wr_stat(trades):
    if not trades:
        return 0.0
    return sum(1 for t in trades if t['result'] == 'WIN') / len(trades)


async def main():
    conn = await asyncpg.connect(DB_URL)

    # جلب كل صفقات 1d+bearish/sideways post-rebuild
    rows = await conn.fetch("""
        SELECT tr.id, s.symbol, s.timeframe, s.market_condition, s.score,
               s.score_details,
               tr.result, tr.profit_percent, tr.profit_usdt, tr.stop_hit,
               tr.target_reached, tr.duration_hours,
               s.signal_time, tr.exit_time
        FROM trade_results tr
        JOIN signals s ON s.id = tr.signal_id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
          AND s.signal_time > $1
        ORDER BY tr.exit_time
    """, datetime.fromisoformat(REBUILD_DATE))

    await conn.close()

    print(f"\n{'='*70}")
    print(f"PART 21 — تحليل جودة الإشارة: rsi_divergence vs RSI+Bollinger")
    print(f"{'='*70}")
    print(f"إجمالي الصفقات 1d+bearish/sideways post-rebuild: {len(rows)}\n")

    if not rows:
        print("لا توجد بيانات كافية.")
        return

    # بناء قاموس البيانات
    trades = []
    for row in rows:
        details = row['score_details']
        if isinstance(details, str):
            details = json.loads(details)
        elif details is None:
            details = {}

        rsi_div = float(details.get('rsi_divergence', 0) or 0)
        stoch = float(details.get('stoch_rsi', 0) or 0)
        rsi = float(details.get('rsi', 0) or 0)
        boll = float(details.get('bollinger', 0) or 0)
        fib = float(details.get('fibonacci', 0) or 0)

        trades.append({
            'symbol': row['symbol'],
            'mc': row['market_condition'],
            'score': row['score'],
            'result': row['result'],
            'pnl_pct': float(row['profit_percent']),
            'pnl_usdt': float(row['profit_usdt']),
            'stop_hit': row['stop_hit'],
            'dur_h': float(row['duration_hours'] or 0),
            'rsi_div': rsi_div,
            'stoch': stoch,
            'rsi': rsi,
            'bollinger': boll,
            'fibonacci': fib,
            'exit_time': row['exit_time'],
        })

    n_total = len(trades)

    # التقسيم الرئيسي: has_rsi_div vs no_rsi_div
    with_div = [t for t in trades if t['rsi_div'] > 0]
    without_div = [t for t in trades if t['rsi_div'] == 0]

    print(f"{'─'*50}")
    print(f"1. تقسيم حسب rsi_divergence:")

    def print_group_stats(label, group):
        if not group:
            print(f"  {label}: n=0")
            return
        wins = [t for t in group if t['result'] == 'WIN']
        losses = [t for t in group if t['result'] == 'LOSS']
        wr = len(wins) / len(group) * 100
        avg_w = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
        avg_l = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
        ea = e_adj(group)
        sl = sum(1 for t in group if t['stop_hit'])
        print(f"  {label:35s}: n={len(group):3d}, WR={wr:.1f}%, "
              f"E_adj={ea:+.3f}%, avg_win={avg_w:+.2f}%, avg_loss={avg_l:+.2f}%, SL={sl}")

    print_group_stats("has_rsi_div (rsi_div>0)", with_div)
    print_group_stats("no_rsi_div (rsi_div==0)", without_div)

    # Permutation test للفرق
    if len(with_div) >= 5 and len(without_div) >= 5:
        p_wr = permutation_test(with_div, without_div, wr_stat, N_PERMUTATIONS)
        p_ea = permutation_test(with_div, without_div, e_adj, N_PERMUTATIONS)
        obs_wr_diff = wr_stat(with_div) - wr_stat(without_div)
        obs_ea_diff = e_adj(with_div) - e_adj(without_div)
        print(f"\n  فرق WR المرصود    : {obs_wr_diff*100:+.1f}%  (p={p_wr:.3f})")
        print(f"  فرق E_adj المرصود  : {obs_ea_diff:+.3f}%  (p={p_ea:.3f})")
        if p_wr < 0.05:
            print(f"  *** الفرق في WR دال إحصائياً (p<0.05) ***")
        elif p_wr < 0.10:
            print(f"  ** الفرق في WR حدّي (0.05<p<0.10) **")
        else:
            print(f"  الفرق في WR غير دال (p>0.10)")
    else:
        print(f"  (إحدى المجموعتين n<5 — تخطي permutation test)")

    # تحليل مجموعات المؤشرات
    print(f"\n{'─'*50}")
    print(f"2. تحليل مجموعات المؤشرات (4 أنماط رئيسية):")

    # نمط 1: RSI+Bollinger dominant (no div, rsi>0 or boll>0)
    rsi_boll = [t for t in trades if t['rsi_div'] == 0 and (t['rsi'] > 0 or t['bollinger'] > 0)]
    # نمط 2: Fibonacci dominant (no div, fib>0.5, rsi=0, boll=0)
    fib_only = [t for t in trades if t['rsi_div'] == 0 and t['fibonacci'] > 0.5 and t['rsi'] == 0 and t['bollinger'] == 0]
    # نمط 3: RSI_DIV + Stoch (يدل على momentum divergence)
    div_stoch = [t for t in trades if t['rsi_div'] > 0 and t['stoch'] > 0]
    # نمط 4: RSI_DIV فقط (بدون stoch)
    div_only = [t for t in trades if t['rsi_div'] > 0 and t['stoch'] == 0]

    print_group_stats("RSI+Bollinger (no_div)", rsi_boll)
    print_group_stats("Fibonacci dominant (no_div)", fib_only)
    print_group_stats("RSI_DIV + Stoch", div_stoch)
    print_group_stats("RSI_DIV solo (no stoch)", div_only)

    # تحليل post-freeze فقط (أحدث 10 إشارات)
    print(f"\n{'─'*50}")
    print(f"3. إشارات post-freeze (2026-05-17) — n={len([t for t in trades if t['exit_time'].replace(tzinfo=timezone.utc) >= datetime(2026,5,17,tzinfo=timezone.utc)])}:")
    post_freeze = [t for t in trades
                   if t['exit_time'].replace(tzinfo=timezone.utc) >= datetime(2026, 5, 17, tzinfo=timezone.utc)]

    if post_freeze:
        for t in post_freeze:
            pattern = "RSI_DIV" if t['rsi_div'] > 0 else ("RSI+BB" if t['rsi'] > 0 or t['bollinger'] > 0 else "FIB")
            print(f"  {t['symbol']:10s} {t['mc']:8s} "
                  f"{'WIN' if t['result']=='WIN' else 'LOSS':4s} "
                  f"{t['pnl_pct']:+.2f}% pattern={pattern:8s} "
                  f"rsi_div={t['rsi_div']:.1f} stoch={t['stoch']:.2f}")

    # توصية نهائية
    print(f"\n{'─'*50}")
    print(f"4. خلاصة وتوصية:")
    ea_div = e_adj(with_div)
    ea_nodiv = e_adj(without_div)
    wr_div = wr_stat(with_div) * 100 if with_div else 0
    wr_nodiv = wr_stat(without_div) * 100 if without_div else 0

    print(f"  has_rsi_div: WR={wr_div:.1f}%, E_adj={ea_div:+.3f}% (n={len(with_div)})")
    print(f"  no_rsi_div : WR={wr_nodiv:.1f}%, E_adj={ea_nodiv:+.3f}% (n={len(without_div)})")

    if len(with_div) >= 10 and ea_div > ea_nodiv and wr_div > wr_nodiv:
        print(f"\n  FINDING: rsi_divergence>0 يُحسّن E_adj بـ {ea_div-ea_nodiv:+.3f}%")
        print(f"  توصية بعد رفع التجميد: فلتر rsi_div>0 كشرط إضافي (يحجب {len(without_div)/n_total*100:.0f}% من الإشارات)")
    elif len(with_div) >= 5 and ea_div > ea_nodiv:
        print(f"\n  FINDING (مبدئي n<10): rsi_divergence>0 يبدو أفضل لكن العينة صغيرة")
        print(f"  توصية: راقب الأنماط حتى n_div≥20 قبل اتخاذ قرار")
    else:
        print(f"\n  FINDING: الفرق غير حاسم حالياً — يحتاج المزيد من البيانات")

    print(f"\n{'='*70}")
    print("الجزء 21 مكتمل.")


if __name__ == '__main__':
    asyncio.run(main())
