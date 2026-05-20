"""
الجزء 24 من الباكتيستر — تحليل أنماط المؤشرات في صفقات ما بعد التجميد
الهدف: مقارنة قيم score_details بين الفائزين والخاسرين post-2026-05-17
       وربطها بأنماط الحافة المكتشفة في الأجزاء السابقة:
       - rsi_divergence (Part 21): WIN E_adj=+2.92% vs LOSS E_adj=-2.86%
       - RSI+Bollinger (Part 18): أفضل توليفة للحافة التاريخية
       - stoch_rsi (Part 19): WIN avg=0.94 vs LOSS avg=0.31
المنهج:
  1. حساب المتوسط لكل مؤشر في الفائزين مقابل الخاسرين
  2. حساب نسبة "القوة التنبؤية" (Delta/StdDev) لكل مؤشر
  3. اقتراح فلتر بسيط بناء على البيانات المتاحة (توصية فقط)
قيود: n=6 صغير جداً — نتائج إشارية لا حاسمة
"""
import json
import sys
sys.path.insert(0, '/home/tradmin/trading-signal-bot')

import asyncio
import asyncpg
from datetime import datetime

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
FEE_PCT = 0.003
FREEZE_DATE = '2026-05-17 00:00:00'

ALL_INDICATORS = [
    'rsi', 'bollinger', 'rsi_divergence', 'stoch_rsi',
    'fibonacci', 'order_book', 'macd', 'obv', 'volume', 'ema_cross'
]

async def main():
    conn = await asyncpg.connect(DB_URL)

    rows = await conn.fetch("""
        SELECT tr.id, s.symbol, s.timeframe, s.market_condition, s.score,
               s.score_details,
               tr.result, tr.profit_percent, tr.profit_usdt, tr.stop_hit,
               tr.target_reached, tr.duration_hours
        FROM trade_results tr
        JOIN signals s ON s.id = tr.signal_id
        WHERE tr.exit_time > $1
          AND s.timeframe = '1d'
        ORDER BY tr.exit_time
    """, datetime.fromisoformat(FREEZE_DATE))

    await conn.close()

    print(f"\n{'='*70}")
    print(f"PART 24 — INDICATOR PATTERN ANALYSIS (post-freeze)")
    print(f"{'='*70}")
    print(f"إجمالي الصفقات: {len(rows)}\n")

    if len(rows) < 4:
        print("n أصغر من 4 — التحليل غير موثوق. يُعاد تشغيله عند n>=10.")
        return

    trades = []
    for row in rows:
        details = row['score_details']
        if isinstance(details, str):
            details = json.loads(details)
        elif details is None:
            details = {}
        pnl_adj = float(row['profit_percent'] or 0) - (FEE_PCT * 100 if row['result'] == 'WIN' else -FEE_PCT * 100)
        trades.append({
            'symbol': row['symbol'],
            'result': row['result'],
            'pnl_pct': float(row['profit_percent'] or 0),
            'pnl_adj': pnl_adj,
            'stop_hit': row['stop_hit'],
            'target': row['target_reached'],
            'duration': float(row['duration_hours'] or 0),
            'details': details,
            'is_win': row['result'] == 'WIN',
        })

    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]
    n_wins = len(wins)
    n_losses = len(losses)

    print(f"{'─'*50}")
    print(f"ملخص: WIN={n_wins} ({100*n_wins//len(trades)}%) | LOSS={n_losses} ({100*n_losses//len(trades)}%)")
    print(f"avg_win = {sum(t['pnl_pct'] for t in wins)/max(n_wins,1):.2f}% | avg_loss = {sum(t['pnl_pct'] for t in losses)/max(n_losses,1):.2f}%")
    e_raw = sum(t['pnl_pct'] for t in trades) / len(trades)
    e_adj = e_raw - FEE_PCT * 100
    print(f"E_raw = {e_raw:.3f}% | E_adj = {e_adj:.3f}%")
    print(f"صافي PnL = ${sum(t['pnl_adj'] for t in trades):.2f}\n")

    print(f"{'─'*50}")
    print(f"تحليل المؤشرات — متوسط قيم score_details:")
    print(f"{'المؤشر':20} {'WIN_avg':>10} {'LOSS_avg':>10} {'Delta':>10} {'إشارة':>10}")
    print(f"{'─'*60}")

    indicator_deltas = []
    for ind in ALL_INDICATORS:
        win_vals = [t['details'].get(ind, 0) or 0 for t in wins]
        loss_vals = [t['details'].get(ind, 0) or 0 for t in losses]
        win_avg = sum(win_vals) / max(n_wins, 1)
        loss_avg = sum(loss_vals) / max(n_losses, 1)
        delta = win_avg - loss_avg
        all_vals = win_vals + loss_vals
        std = (sum((v - (sum(all_vals)/len(all_vals)))**2 for v in all_vals) / max(len(all_vals)-1, 1)) ** 0.5
        signal_str = ""
        if abs(delta) > 0.3:
            signal_str = "*** قوي" if delta > 0 else "*** عكسي"
        elif abs(delta) > 0.1:
            signal_str = "* واعد" if delta > 0 else "* عكسي خفيف"
        print(f"  {ind:20} {win_avg:>10.3f} {loss_avg:>10.3f} {delta:>+10.3f}  {signal_str}")
        indicator_deltas.append((ind, delta, win_avg, loss_avg))

    # ترتيب حسب أهمية الـ Delta
    indicator_deltas.sort(key=lambda x: abs(x[1]), reverse=True)
    print(f"\n{'─'*50}")
    print("ترتيب المؤشرات حسب قوة التأثير (abs Delta):")
    for rank, (ind, delta, wa, la) in enumerate(indicator_deltas, 1):
        direction = "ايجابي" if delta > 0 else "سلبي/عكسي"
        print(f"  {rank}. {ind:20} | Delta={delta:+.3f} | {direction}")

    print(f"\n{'─'*50}")
    print("فحص فرضية RSI+Bollinger للحافة (من Part 18):")
    for t in trades:
        has_rsi = (t['details'].get('rsi', 0) or 0) > 0
        has_boll = (t['details'].get('bollinger', 0) or 0) > 0
        pattern = "RSI+BB" if (has_rsi and has_boll) else ("RSI" if has_rsi else ("BB" if has_boll else "NONE"))
        rsi_div = t['details'].get('rsi_divergence', 0) or 0
        print(f"  [{t['result']}] {t['symbol']:12} pattern={pattern:8} rsi_div={rsi_div:.1f} stoch={t['details'].get('stoch_rsi',0):.2f}")

    # تحليل stoch_rsi كفلتر (Part 19 وجد: WIN avg=0.94 vs LOSS avg=0.31)
    print(f"\n{'─'*50}")
    print("فحص فرضية stoch_rsi كفلتر (threshold=0.7):")
    stoch_threshold = 0.7
    high_stoch = [t for t in trades if (t['details'].get('stoch_rsi', 0) or 0) >= stoch_threshold]
    low_stoch = [t for t in trades if (t['details'].get('stoch_rsi', 0) or 0) < stoch_threshold]
    if high_stoch:
        hs_wr = sum(1 for t in high_stoch if t['is_win']) / len(high_stoch)
        print(f"  stoch >= {stoch_threshold}: n={len(high_stoch)} | WR={100*hs_wr:.0f}%")
    if low_stoch:
        ls_wr = sum(1 for t in low_stoch if t['is_win']) / len(low_stoch)
        print(f"  stoch <  {stoch_threshold}: n={len(low_stoch)} | WR={100*ls_wr:.0f}%")

    # نمط الخروج (T3 vs SL)
    print(f"\n{'─'*50}")
    print("نمط الخروج:")
    t3 = [t for t in trades if t['target'] >= 3]
    sl = [t for t in trades if t['stop_hit']]
    print(f"  T3 reached: {len(t3)} صفقة | avg_duration = {sum(t['duration'] for t in t3)/max(len(t3),1):.1f}h")
    print(f"  SL hit:     {len(sl)} صفقة | avg_duration = {sum(t['duration'] for t in sl)/max(len(sl),1):.1f}h")
    print(f"  avg SL loss = {sum(t['pnl_pct'] for t in sl)/max(len(sl),1):.2f}%")
    print(f"  avg T3 win  = {sum(t['pnl_pct'] for t in t3)/max(len(t3),1):.2f}%")
    if t3 and sl:
        rr_realized = abs(sum(t['pnl_pct'] for t in t3)/len(t3)) / abs(sum(t['pnl_pct'] for t in sl)/len(sl))
        print(f"  R:R المتحقق = {rr_realized:.2f}:1 (المطلوب: 1.5:1+)")

    print(f"\n{'─'*50}")
    print("توصيات للمراقبة (تُطبَّق بعد رفع التجميد عند n>=20):")
    top_pos = [x for x in indicator_deltas if x[1] > 0.2]
    top_neg = [x for x in indicator_deltas if x[1] < -0.2]
    if top_pos:
        print(f"  مرشحون للتعزيز: {', '.join(x[0] for x in top_pos)}")
    if top_neg:
        print(f"  مرشحون للتخفيض: {', '.join(x[0] for x in top_neg)}")
    if not top_pos and not top_neg:
        print("  لا إشارة واضحة بعد (n=6 صغيرة جداً)")

    print(f"\n{'='*70}")
    print(f"تقدّم التجميد: {len(trades)}/50 صفقة (متبقٍ {50-len(trades)})")
    print(f"{'='*70}")

    # ملخص JSON
    import json as jsonmod
    summary = {
        "part": 24,
        "date": "2026-05-20",
        "n_total": len(trades),
        "wr_pct": round(100*n_wins/len(trades), 1),
        "e_adj_pct": round(e_adj, 3),
        "freeze_counter": len(trades),
        "freeze_remaining": 50 - len(trades),
        "top_indicators": [
            {"indicator": x[0], "delta": round(x[1], 3), "direction": "positive" if x[1] > 0 else "negative"}
            for x in indicator_deltas[:5]
        ]
    }
    print(f"\nSUMMARY JSON:\n{jsonmod.dumps(summary, ensure_ascii=False, indent=2)}")

asyncio.run(main())
