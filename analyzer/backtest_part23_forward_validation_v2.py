"""
الجزء 23 من الباكتيستر — Forward Validation التراكمي (نسخة محدّثة)
الهدف: تتبع تراكمي لأداء الصفقات بعد التجميد 2026-05-17
       مع تحليل مُعمَّق لأنماط rsi_divergence مقابل RSI+Bollinger فقط
المنهج:
  1. جلب كل الصفقات المغلقة بعد 2026-05-17 (الهدف: 50 صفقة)
  2. تحليل ثنائي: rsi_div>0 vs rsi_div=0
  3. تتبع تراكمي للـ WR كل 5 صفقات (هل يستقر أم يتذبذب؟)
  4. تقييم جودة الإشارات: أي مؤشرات في score_details ترتبط بالنجاح؟
  5. حساب p-value من permutation test للفرق بين المجموعتين
"""
import json
import sys
sys.path.insert(0, '/home/tradmin/trading-signal-bot')

import asyncio
import asyncpg
import random
from datetime import datetime

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
FEE_PCT = 0.003   # 0.3% رسوم + انزلاق
FREEZE_DATE = '2026-05-17 00:00:00'
N_PERMUTATIONS = 500  # bootstrap خفيف لتوفير RAM

async def main():
    conn = await asyncpg.connect(DB_URL)

    rows = await conn.fetch("""
        SELECT tr.id, s.symbol, s.timeframe, s.market_condition, s.score,
               s.score_details,
               tr.result, tr.profit_percent, tr.profit_usdt, tr.stop_hit,
               tr.target_reached, tr.duration_hours,
               s.signal_time, tr.exit_time
        FROM trade_results tr
        JOIN signals s ON s.id = tr.signal_id
        WHERE tr.exit_time > $1
          AND s.timeframe = '1d'
        ORDER BY tr.exit_time
    """, datetime.fromisoformat(FREEZE_DATE))

    await conn.close()

    print(f"\n{'='*70}")
    print(f"PART 23 — FORWARD VALIDATION CUMULATIVE (post-freeze {FREEZE_DATE})")
    print(f"{'='*70}")
    print(f"إجمالي الصفقات المغلقة بعد التجميد: {len(rows)}\n")

    if not rows:
        print("لا توجد صفقات مغلقة بعد التجميد بعد.")
        return

    trades = []
    for row in rows:
        details = row['score_details']
        if isinstance(details, str):
            details = json.loads(details)
        elif details is None:
            details = {}

        pnl_pct = float(row['profit_percent'])
        pnl_adj = pnl_pct - (FEE_PCT * 100)  # طرح الرسوم دائماً

        rsi_div = float(details.get('rsi_divergence', 0) or 0)
        rsi_val = float(details.get('rsi', 0) or 0)
        bb_val = float(details.get('bollinger', 0) or 0)
        fib_val = float(details.get('fibonacci', 0) or 0)
        stoch_val = float(details.get('stoch_rsi', 0) or 0)

        trades.append({
            'symbol': row['symbol'],
            'mc': row['market_condition'],
            'score': row['score'],
            'result': row['result'],
            'pnl_pct': pnl_pct,
            'pnl_usdt': float(row['profit_usdt']),
            'pnl_adj': pnl_adj,
            'stop_hit': row['stop_hit'],
            'target': row['target_reached'],
            'dur_h': float(row['duration_hours'] or 0),
            'rsi_div': rsi_div,
            'rsi': rsi_val,
            'bollinger': bb_val,
            'fibonacci': fib_val,
            'stoch': stoch_val,
            'exit_time': row['exit_time'],
        })

    n = len(trades)
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    wr = len(wins) / n * 100 if n > 0 else 0
    avg_win = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t['pnl_usdt'] for t in trades)
    total_pnl_adj = sum(t['pnl_adj'] for t in trades) * 0.5  # تقدير تقريبي

    # E_adj = WR * avg_win - (1-WR) * |avg_loss| - fee
    e_raw = (len(wins)/n * avg_win + len(losses)/n * avg_loss) if n > 0 else 0
    e_adj = e_raw - (FEE_PCT * 100)  # طرح 0.3% رسوم

    print(f"{'─'*50}")
    print(f"ملخص الأداء العام (n={n}):")
    print(f"  WR           = {wr:.1f}% ({len(wins)}/{n})")
    print(f"  avg_win      = +{avg_win:.3f}%")
    print(f"  avg_loss     = {avg_loss:.3f}%")
    print(f"  E_raw        = {e_raw:.3f}%")
    print(f"  E_adj (-0.3%)= {e_adj:.3f}%")
    print(f"  صافي PnL     = ${total_pnl:.2f}")
    print(f"  SL hits      = {sum(1 for t in trades if t['stop_hit'])} ({sum(1 for t in trades if t['stop_hit'])/n*100:.0f}%)")
    print(f"  T3 reached   = {sum(1 for t in trades if t['target'] >= 3)} ({sum(1 for t in trades if t['target'] >= 3)/n*100:.0f}%)")
    print(f"  avg_duration = {sum(t['dur_h'] for t in trades)/n:.1f}h")

    # ═══ تحليل rsi_divergence ═══
    print(f"\n{'─'*50}")
    print("تحليل rsi_divergence:")

    div_trades = [t for t in trades if t['rsi_div'] > 0]
    nodiv_trades = [t for t in trades if t['rsi_div'] == 0]

    for group_name, group in [("rsi_div > 0", div_trades), ("rsi_div = 0 (RSI+BB)", nodiv_trades)]:
        if not group:
            print(f"  {group_name}: لا توجد صفقات")
            continue
        ng = len(group)
        wg = [t for t in group if t['result'] == 'WIN']
        lg = [t for t in group if t['result'] == 'LOSS']
        wrg = len(wg)/ng*100
        avg_wg = sum(t['pnl_pct'] for t in wg)/len(wg) if wg else 0
        avg_lg = sum(t['pnl_pct'] for t in lg)/len(lg) if lg else 0
        e_g = (len(wg)/ng * avg_wg + len(lg)/ng * avg_lg) - (FEE_PCT * 100)
        print(f"  {group_name}: n={ng} | WR={wrg:.1f}% | avg_win={avg_wg:+.2f}% | avg_loss={avg_lg:+.2f}% | E_adj={e_g:+.3f}%")
        for t in group:
            sign = "WIN" if t['result'] == 'WIN' else "LOSS"
            print(f"    [{sign}] {t['symbol']} pnl={t['pnl_pct']:+.2f}% T{t['target']} SL={t['stop_hit']}")

    # permutation test للفرق بين المجموعتين (E_adj)
    if div_trades and nodiv_trades and len(div_trades) + len(nodiv_trades) >= 5:
        print(f"\n  Permutation test (n_perm={N_PERMUTATIONS}):")
        div_pnls = [t['pnl_pct'] - (FEE_PCT * 100) for t in div_trades]
        nodiv_pnls = [t['pnl_pct'] - (FEE_PCT * 100) for t in nodiv_trades]
        obs_diff = (sum(div_pnls)/len(div_pnls)) - (sum(nodiv_pnls)/len(nodiv_pnls))

        all_pnls = div_pnls + nodiv_pnls
        n_div = len(div_pnls)
        random.seed(42)
        count_exceeds = 0
        for _ in range(N_PERMUTATIONS):
            shuffled = all_pnls[:]
            random.shuffle(shuffled)
            perm_div = shuffled[:n_div]
            perm_nodiv = shuffled[n_div:]
            perm_diff = sum(perm_div)/len(perm_div) - sum(perm_nodiv)/len(perm_nodiv)
            if perm_diff >= obs_diff:
                count_exceeds += 1

        p_val = count_exceeds / N_PERMUTATIONS
        print(f"  obs_diff E = {obs_diff:+.3f}% (rsi_div vs no_div)")
        print(f"  p-value = {p_val:.3f} ({'دال إحصائياً p<0.05' if p_val < 0.05 else 'غير دال p>0.05'})")
        print(f"  ملاحظة: n_div={len(div_trades)}, n_nodiv={len(nodiv_trades)} — عينة صغيرة")

    # ═══ تتبع WR التراكمي ═══
    print(f"\n{'─'*50}")
    print("WR التراكمي كل صفقة (اتجاه الأداء):")
    cumulative_wins = 0
    for i, t in enumerate(trades, 1):
        if t['result'] == 'WIN':
            cumulative_wins += 1
        cum_wr = cumulative_wins / i * 100
        bar = "█" * int(cum_wr/10)
        print(f"  [{i:2d}] {t['symbol']:<10} {t['result']:<4} rsi_div={t['rsi_div']:.1f} | CumWR={cum_wr:.0f}% {bar}")

    # ═══ تحليل market_condition ═══
    print(f"\n{'─'*50}")
    print("التوزيع حسب market_condition:")
    for mc in ['bearish', 'sideways']:
        mc_trades = [t for t in trades if t['mc'] == mc]
        if not mc_trades:
            continue
        nmc = len(mc_trades)
        wmc = sum(1 for t in mc_trades if t['result'] == 'WIN')
        e_mc = sum(t['pnl_pct'] - (FEE_PCT*100) for t in mc_trades) / nmc
        print(f"  {mc}: n={nmc} | WR={wmc/nmc*100:.0f}% | E_adj={e_mc:+.3f}%")

    # ═══ متى يصل للتجميد؟ ═══
    print(f"\n{'─'*50}")
    remaining = 50 - n
    if remaining > 0:
        print(f"تقدّم التجميد: {n}/50 صفقة مغلقة (متبقٍ {remaining})")
    else:
        print(f"*** تحذير: وصلنا إلى {n}/50 — يجب إشعار المستخدم لرفع التجميد ***")

    # ═══ توصيات ما بعد التجميد ═══
    if n >= 10:
        print(f"\n{'─'*50}")
        print("التقييم عند n=10+:")
        if wr >= 50:
            print(f"  WR={wr:.0f}% >= 50% — الحافة تصمد. توسّع بحذر بعد رفع التجميد.")
        elif wr >= 40 and e_adj > 0:
            print(f"  WR={wr:.0f}% مع E_adj={e_adj:+.3f}% — أداء معقول، استمر بالمراقبة.")
        else:
            print(f"  WR={wr:.0f}% مع E_adj={e_adj:+.3f}% — دون التوقعات. راجع الفرضية بعد 30 صفقة.")

    # ═══ ملخص JSON للذاكرة ═══
    print(f"\n{'='*70}")
    print(f"SUMMARY JSON:")
    summary = {
        "part": 23,
        "date": datetime.now().isoformat()[:10],
        "n_total": n,
        "wr_pct": round(wr, 1),
        "e_adj_pct": round(e_adj, 3),
        "total_pnl_usdt": round(total_pnl, 2),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "sl_hits": sum(1 for t in trades if t['stop_hit']),
        "t3_count": sum(1 for t in trades if t['target'] >= 3),
        "rsi_div_group": {
            "n": len(div_trades),
            "wr_pct": round(sum(1 for t in div_trades if t['result']=='WIN')/len(div_trades)*100, 1) if div_trades else 0,
        },
        "nodiv_group": {
            "n": len(nodiv_trades),
            "wr_pct": round(sum(1 for t in nodiv_trades if t['result']=='WIN')/len(nodiv_trades)*100, 1) if nodiv_trades else 0,
        },
        "freeze_counter": n,
        "freeze_remaining": max(0, 50 - n),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
