"""
الجزء 19 من الباكتيستر — Forward Validation (صفقات ما بعد التجميد 2026-05-17)
الهدف: تتبع أداء أول 50 صفقة 1d+bearish/sideways على الإعداد المثبَّت (التجميد)
المنهج: قياس WR, E_adj, بنية score_details لكل صفقة مغلقة
"""
import json
import os
import sys
sys.path.insert(0, '/home/tradmin/trading-signal-bot')

import asyncio
import asyncpg
from datetime import datetime, timezone

FEE_PCT = 0.003   # 0.3% لكل صفقة (رسوم + انزلاق)
FREEZE_DATE = '2026-05-17 00:00:00'

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"

async def main():
    conn = await asyncpg.connect(DB_URL)

    # جلب كل الصفقات المغلقة بعد التجميد
    rows = await conn.fetch("""
        SELECT tr.id, s.symbol, s.timeframe, s.market_condition, s.score,
               s.score_details,
               tr.result, tr.profit_percent, tr.profit_usdt, tr.stop_hit,
               tr.target_reached, tr.duration_hours,
               s.signal_time, tr.exit_time
        FROM trade_results tr
        JOIN signals s ON s.id = tr.signal_id
        WHERE tr.exit_time > $1
        ORDER BY tr.exit_time
    """, datetime.fromisoformat(FREEZE_DATE))

    print(f"\n{'='*70}")
    print(f"PART 19 — FORWARD VALIDATION (بعد التجميد {FREEZE_DATE})")
    print(f"{'='*70}")
    print(f"عدد الصفقات المغلقة بعد التجميد: {len(rows)}\n")

    trades = []
    for row in rows:
        details = row['score_details']
        if isinstance(details, str):
            details = json.loads(details)

        pnl_pct = float(row['profit_percent'])
        pnl_adj = pnl_pct - (FEE_PCT * 100) if pnl_pct > 0 else pnl_pct - (FEE_PCT * 100)

        trades.append({
            'symbol': row['symbol'],
            'timeframe': row['timeframe'],
            'mc': row['market_condition'],
            'score': row['score'],
            'result': row['result'],
            'pnl_pct': pnl_pct,
            'pnl_usdt': float(row['profit_usdt']),
            'pnl_adj': pnl_adj,
            'stop_hit': row['stop_hit'],
            'target': row['target_reached'],
            'dur_h': float(row['duration_hours'] or 0),
            'details': details,
            'exit_time': row['exit_time'],
        })

    if not trades:
        print("لا توجد صفقات مغلقة بعد التجميد بعد.")
        await conn.close()
        return

    # إحصاءات عامة
    n = len(trades)
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    wr = len(wins) / n * 100
    avg_win = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t['pnl_usdt'] for t in trades)

    # E_adj (بعد الرسوم — نطرح 0.3% من الفائزين فقط لأن الخسائر محسوبة بالفعل)
    avg_win_adj = avg_win - (FEE_PCT * 100) if wins else 0
    avg_loss_adj = avg_loss - (FEE_PCT * 100) if losses else 0
    e_adj = (wr/100 * avg_win_adj) + ((1 - wr/100) * avg_loss_adj) if n > 0 else 0

    print(f"{'─'*50}")
    print(f"الإحصاءات الكاملة (n={n}):")
    print(f"  WR          : {wr:.1f}% ({len(wins)}/{n})")
    print(f"  avg_win     : {avg_win:.3f}%")
    print(f"  avg_loss    : {avg_loss:.3f}%")
    print(f"  E_adj       : {e_adj:.3f}% (بعد رسوم 0.3%)")
    print(f"  total_pnl   : ${total_pnl:.2f}")
    print(f"  SL_hits     : {sum(1 for t in trades if t['stop_hit'])}/{n}")
    print(f"  T3_hits     : {sum(1 for t in trades if t['target'] == 3)}/{n}")
    print(f"  avg_dur_h   : {sum(t['dur_h'] for t in trades)/n:.1f}h")

    # مقارنة مع الخط الأساسي التاريخي
    print(f"\n{'─'*50}")
    print(f"المقارنة مع الخط الأساسي (pre-freeze 1d+score3):")
    print(f"  1d+bearish+score3 (pre): WR=58.3%, E_adj=+1.41% (n=36)")
    print(f"  1d+sideways+score3 (pre): WR=50.0%, E_adj=+0.64% (n=34)")
    print(f"  Post-freeze (حالي)    : WR={wr:.1f}%, E_adj={e_adj:.3f}% (n={n})")

    # تفاصيل كل صفقة
    print(f"\n{'─'*50}")
    print(f"تفاصيل الصفقات:")
    for t in trades:
        print(f"  [{t['exit_time'].strftime('%m-%d %H:%M')}] {t['symbol']:10s} "
              f"{t['mc']:8s} score={t['score']} "
              f"{'WIN' if t['result']=='WIN' else 'LOSS':4s} "
              f"{t['pnl_pct']:+.2f}% T{t['target']} "
              f"{'SL' if t['stop_hit'] else '  '} dur={t['dur_h']:.1f}h")

    # تحليل score_details لاكتشاف أنماط
    print(f"\n{'─'*50}")
    print("تحليل مكونات score_details:")
    indicators = ['rsi', 'bollinger', 'rsi_divergence', 'fibonacci',
                  'stoch_rsi', 'order_book', 'obv', 'macd', 'volume']

    for ind in indicators:
        win_vals = [t['details'].get(ind, 0) for t in wins]
        loss_vals = [t['details'].get(ind, 0) for t in losses]
        win_avg = sum(win_vals) / len(win_vals) if win_vals else 0
        loss_avg = sum(loss_vals) / len(loss_vals) if loss_vals else 0
        delta = win_avg - loss_avg
        print(f"  {ind:15s}: WIN_avg={win_avg:.3f}  LOSS_avg={loss_avg:.3f}  Δ={delta:+.3f}")

    # فحص الفلتر overbought: هل score=4 في signals يؤثر؟
    print(f"\n{'─'*50}")
    print("توزيع النتائج حسب score integer:")
    for sc in sorted(set(t['score'] for t in trades)):
        sc_trades = [t for t in trades if t['score'] == sc]
        sc_wins = sum(1 for t in sc_trades if t['result'] == 'WIN')
        sc_wr = sc_wins / len(sc_trades) * 100 if sc_trades else 0
        sc_pnl = sum(t['pnl_usdt'] for t in sc_trades)
        print(f"  score={sc}: n={len(sc_trades):3d}, WR={sc_wr:.0f}%, PnL=${sc_pnl:.2f}")

    # حالة عداد التجميد
    print(f"\n{'─'*50}")
    print(f"عداد التجميد: {n}/50 صفقة مغلقة")
    remaining = max(0, 50 - n)
    print(f"  متبقٍ: {remaining} صفقة للوصول لقرار رفع التجميد")

    if n >= 50:
        print(f"\n*** تنبيه: وصلنا 50 صفقة! يجب إبلاغ المستخدم لاتخاذ قرار رفع التجميد ***")
        if wr >= 50 and e_adj > 0:
            print(f"    الحافة صمدت (WR={wr:.1f}% >= 50%, E_adj={e_adj:.3f}% > 0)")
            print(f"    توصية: وسّع بحذر — ابدأ بتجربة RSI+Bollinger فقط")
        else:
            print(f"    الحافة لم تصمد (WR={wr:.1f}% < 50% أو E_adj={e_adj:.3f}% <= 0)")
            print(f"    توصية: راجع الفرضية قبل التوسع")

    # حاوية مؤقتة للصفقات المفتوحة
    open_trades = await conn.fetch("""
        SELECT at.symbol, at.timeframe, at.entry_price, at.peak_price,
               at.highest_target_hit, at.stop_loss, at.opened_at,
               s.market_condition, s.score
        FROM active_trades at
        JOIN signals s ON s.id = at.signal_id
        WHERE at.status = 'open'
        ORDER BY at.opened_at
    """)

    if open_trades:
        print(f"\n{'─'*50}")
        print(f"الصفقات المفتوحة حالياً ({len(open_trades)}):")
        for ot in open_trades:
            peak_pct = ((float(ot['peak_price'] or ot['entry_price']) - float(ot['entry_price']))
                       / float(ot['entry_price']) * 100) if ot['entry_price'] else 0
            age_h = (datetime.now(timezone.utc) - ot['opened_at'].replace(tzinfo=timezone.utc)).total_seconds() / 3600
            print(f"  {ot['symbol']:10s} {ot['market_condition']:8s} score={ot['score']} "
                  f"T{ot['highest_target_hit']} peak={peak_pct:+.2f}% age={age_h:.1f}h")

    await conn.close()
    print(f"\n{'='*70}")
    print("الجزء 19 مكتمل.")

if __name__ == '__main__':
    asyncio.run(main())
