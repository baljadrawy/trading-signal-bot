"""
الجزء 22 من الباكتيستر — Stop Loss Distance vs ATR Analysis
الهدف: تقييم ما إذا كان الـ SL cap (3% في 1d) مناسباً لكل عملة
       بناءً على ATR الفعلي — هل يضرب قبل الأوان؟
المنهج:
  1. لكل صفقة مغلقة post-rebuild (1d+bearish/sideways):
     - احسب ATR% = ATR/entry_price * 100
     - احسب SL_dist% = |entry_price - stop_loss| / entry_price * 100
     - احسب ATR_ratio = SL_dist / ATR% (كم ATR بين الدخول والـ SL)
  2. قارن ATR_ratio للفائزين vs الخاسرين
  3. ابحث عن عتبة ATR_ratio مثلى (1.0, 1.5, 2.0 ATR)
  4. قيّم هل صفقات الـ SL hit كان ATR_ratio < 1.0 (SL ضيّق جداً)
السياق: SL_cap=3% مطبّق على analyzer منذ commit ba2345b (2026-05-17)
         الهدف الأول T1=3% ← نفس المسافة للـ SL = R:R = 1:1
"""
import json
import os
import sys
sys.path.insert(0, '/home/tradmin/trading-signal-bot')

import asyncio
import asyncpg
from datetime import datetime, timezone

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"
FEE_PCT = 0.003
REBUILD_DATE = '2026-04-22 00:00:00'

async def main():
    conn = await asyncpg.connect(DB_URL)

    print(f"\n{'='*70}")
    print(f"PART 22 — STOP LOSS DISTANCE vs ATR ANALYSIS")
    print(f"{'='*70}")

    # جلب صفقات post-rebuild مع ATR من analysis_results
    rows = await conn.fetch("""
        SELECT
            tr.id, s.symbol, s.timeframe, s.market_condition, s.score,
            tr.result, tr.profit_percent, tr.profit_usdt, tr.stop_hit,
            tr.target_reached, tr.duration_hours,
            s.entry_price as sig_entry, s.stop_loss as sig_sl,
            s.signal_time, tr.exit_time,
            ar.analysis_data
        FROM trade_results tr
        JOIN signals s ON s.id = tr.signal_id
        LEFT JOIN analysis_results ar ON (
            ar.symbol = s.symbol AND ar.timeframe = s.timeframe
            AND ar.analyzed_at <= s.signal_time + INTERVAL '30 minutes'
            AND ar.analyzed_at >= s.signal_time - INTERVAL '2 hours'
        )
        WHERE tr.exit_time > $1
        AND s.timeframe = '1d'
        AND s.market_condition IN ('bearish', 'sideways')
        ORDER BY tr.exit_time
    """, datetime.fromisoformat(REBUILD_DATE))

    print(f"إجمالي الصفقات post-rebuild (1d+bearish/sideways): {len(rows)}\n")

    # معالجة الصفقات
    trades = []
    no_atr = 0
    for row in rows:
        ad = row['analysis_data']
        if isinstance(ad, str):
            try:
                ad = json.loads(ad)
            except:
                ad = {}
        elif ad is None:
            ad = {}

        entry = float(row['sig_entry'])
        sl = float(row['sig_sl'])
        sl_dist_pct = abs(entry - sl) / entry * 100 if entry > 0 else 0

        atr_raw = ad.get('atr', None) if ad else None
        if atr_raw is None:
            no_atr += 1
            atr_pct = None
            atr_ratio = None
        else:
            atr_pct = float(atr_raw) / entry * 100 if entry > 0 else None
            atr_ratio = sl_dist_pct / atr_pct if atr_pct and atr_pct > 0 else None

        trades.append({
            'symbol': row['symbol'],
            'mc': row['market_condition'],
            'score': row['score'],
            'result': row['result'],
            'pnl_pct': float(row['profit_percent']),
            'pnl_usdt': float(row['profit_usdt']),
            'stop_hit': row['stop_hit'],
            'target': row['target_reached'],
            'dur_h': float(row['duration_hours'] or 0),
            'sl_dist_pct': sl_dist_pct,
            'atr_pct': atr_pct,
            'atr_ratio': atr_ratio,
            'exit_time': row['exit_time'],
        })

    # فلتر الصفقات ذات ATR
    with_atr = [t for t in trades if t['atr_ratio'] is not None]
    n_all = len(trades)
    n_atr = len(with_atr)

    print(f"{'─'*50}")
    print(f"بيانات ATR متاحة: {n_atr}/{n_all} صفقة ({n_atr/n_all*100:.0f}%)")
    print(f"بدون ATR (لا يوجد analysis_results مطابق): {no_atr}")

    if n_atr < 5:
        print(f"\nعينة غير كافية لتحليل ATR (n={n_atr} < 5)")
        print("سبب: analysis_results يُحدَّث كل دورة فيُستبدل — لا تاريخي يتراكم")
        print("البديل: تحليل SL_dist% من signals مباشرة (بدون ATR)")

        # تحليل SL_dist% فقط (من signals)
        wins_all = [t for t in trades if t['result'] == 'WIN']
        losses_all = [t for t in trades if t['result'] == 'LOSS']
        n = len(trades)

        print(f"\n{'─'*50}")
        print(f"تحليل SL Distance % (n={n}):")
        print(f"  WR الكلي: {len(wins_all)/n*100:.1f}%")
        print(f"  avg_sl_dist (WIN): {sum(t['sl_dist_pct'] for t in wins_all)/len(wins_all):.2f}%"
              if wins_all else "  avg_sl_dist (WIN): N/A")
        print(f"  avg_sl_dist (LOSS): {sum(t['sl_dist_pct'] for t in losses_all)/len(losses_all):.2f}%"
              if losses_all else "  avg_sl_dist (LOSS): N/A")

        # توزيع sl_dist
        buckets = {'<=1.5%': 0, '1.5-2.5%': 0, '2.5-3.5%': 0, '>3.5%': 0}
        buckets_win = {'<=1.5%': 0, '1.5-2.5%': 0, '2.5-3.5%': 0, '>3.5%': 0}
        for t in trades:
            d = t['sl_dist_pct']
            if d <= 1.5:
                k = '<=1.5%'
            elif d <= 2.5:
                k = '1.5-2.5%'
            elif d <= 3.5:
                k = '2.5-3.5%'
            else:
                k = '>3.5%'
            buckets[k] += 1
            if t['result'] == 'WIN':
                buckets_win[k] += 1

        print(f"\n  توزيع SL_dist:")
        for k in buckets:
            n_b = buckets[k]
            w_b = buckets_win[k]
            wr_b = w_b/n_b*100 if n_b > 0 else 0
            print(f"    {k:10s}: n={n_b:3d}, WR={wr_b:.0f}%, wins={w_b}")

        await conn.close()
        return

    # تحليل كامل مع ATR
    wins = [t for t in with_atr if t['result'] == 'WIN']
    losses = [t for t in with_atr if t['result'] == 'LOSS']
    n = len(with_atr)
    wr = len(wins) / n * 100

    print(f"\n{'─'*50}")
    print(f"تحليل ATR_ratio = SL_dist / ATR (n={n}):")
    print(f"  WR الكلي: {wr:.1f}%")

    avg_atr_win = sum(t['atr_pct'] for t in wins) / len(wins) if wins else 0
    avg_atr_loss = sum(t['atr_pct'] for t in losses) / len(losses) if losses else 0
    avg_ratio_win = sum(t['atr_ratio'] for t in wins) / len(wins) if wins else 0
    avg_ratio_loss = sum(t['atr_ratio'] for t in losses) / len(losses) if losses else 0
    avg_sl_dist_win = sum(t['sl_dist_pct'] for t in wins) / len(wins) if wins else 0
    avg_sl_dist_loss = sum(t['sl_dist_pct'] for t in losses) / len(losses) if losses else 0

    print(f"\n  مقارنة WIN vs LOSS:")
    print(f"  {'':15s} {'WIN':>10s} {'LOSS':>10s} {'Δ':>8s}")
    print(f"  {'ATR%':15s} {avg_atr_win:>10.3f} {avg_atr_loss:>10.3f} {avg_atr_win-avg_atr_loss:>+8.3f}")
    print(f"  {'SL_dist%':15s} {avg_sl_dist_win:>10.3f} {avg_sl_dist_loss:>10.3f} {avg_sl_dist_win-avg_sl_dist_loss:>+8.3f}")
    print(f"  {'ATR_ratio':15s} {avg_ratio_win:>10.3f} {avg_ratio_loss:>10.3f} {avg_ratio_win-avg_ratio_loss:>+8.3f}")

    # الصفقات ذات ATR_ratio < 1.0 (SL ضيق جداً)
    tight_sl = [t for t in with_atr if t['atr_ratio'] < 1.0]
    tight_wins = sum(1 for t in tight_sl if t['result'] == 'WIN')
    normal_sl = [t for t in with_atr if t['atr_ratio'] >= 1.0]
    normal_wins = sum(1 for t in normal_sl if t['result'] == 'WIN')

    print(f"\n  فلتر ATR_ratio < 1.0 (SL ضيق = أقل من ATR واحد):")
    print(f"    ATR_ratio < 1.0: n={len(tight_sl)}, WR={tight_wins/len(tight_sl)*100:.0f}%"
          if tight_sl else "    ATR_ratio < 1.0: لا صفقات")
    print(f"    ATR_ratio >= 1.0: n={len(normal_sl)}, WR={normal_wins/len(normal_sl)*100:.0f}%"
          if normal_sl else "    ATR_ratio >= 1.0: لا صفقات")

    # بحث عن عتبة مثلى
    print(f"\n  تأثير عتبة ATR_ratio على WR:")
    thresholds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    for thr in thresholds:
        above = [t for t in with_atr if t['atr_ratio'] >= thr]
        below = [t for t in with_atr if t['atr_ratio'] < thr]
        wr_a = sum(1 for t in above if t['result']=='WIN') / len(above) * 100 if above else 0
        wr_b = sum(1 for t in below if t['result']=='WIN') / len(below) * 100 if below else 0
        pnl_a = sum(t['pnl_usdt'] for t in above)
        print(f"    >= {thr:.2f} ATR: n={len(above):3d}, WR={wr_a:.0f}%, PnL=${pnl_a:.2f} | "
              f"rejected={len(below)}, WR_rej={wr_b:.0f}%")

    # تفاصيل كل صفقة
    print(f"\n{'─'*50}")
    print("تفاصيل الصفقات (مع ATR):")
    for t in sorted(with_atr, key=lambda x: x['exit_time']):
        print(f"  [{t['exit_time'].strftime('%m-%d %H:%M')}] {t['symbol']:10s} "
              f"{t['mc']:8s} {t['result']:4s} {t['pnl_pct']:+.2f}% "
              f"SL={t['sl_dist_pct']:.2f}% ATR={t['atr_pct']:.2f}% ratio={t['atr_ratio']:.2f} "
              f"{'SL_HIT' if t['stop_hit'] else '      '}")

    # خلاصة وتوصيات
    print(f"\n{'─'*50}")
    print("الخلاصة والتوصيات:")
    if n < 15:
        print(f"  تحذير: n={n} صغير — الأرقام إشارية فقط، تحتاج n>=30 للدلالة")

    if avg_ratio_win > avg_ratio_loss:
        delta_ratio = avg_ratio_win - avg_ratio_loss
        print(f"  ATR_ratio أعلى في الفائزين (Δ=+{delta_ratio:.3f}) — إشارة: SL أوسع = نتائج أفضل")
        if avg_ratio_loss < 1.0:
            print(f"  الخاسرون لديهم ATR_ratio={avg_ratio_loss:.2f} < 1.0 — SL ضيق جداً للسوق")
            print(f"  التوصية (للتطبيق بعد التجميد): رفع SL_cap من 3% إلى max(3%, 1.5*ATR)")
        else:
            print(f"  ATR_ratio للخاسرين={avg_ratio_loss:.2f} — الـ SL ليس المشكلة الرئيسية")
    else:
        print(f"  ATR_ratio مشابه للفائزين والخاسرين — الـ SL_cap ليس متغيراً محدداً")

    await conn.close()
    print(f"\n{'='*70}")
    print("الجزء 22 مكتمل.")

if __name__ == '__main__':
    asyncio.run(main())
