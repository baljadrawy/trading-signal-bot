"""
الباكتيستر — الجزء 12: تحقق من سقف score لإشارات 1d (overbought filter)
=========================================================================
الفرضية: في إطار 1d+bearish/sideways، كلما ارتفع score كلما انخفض WR.
- score=3 (raw<4): WR=58%(bearish), 50%(sideways) — ربح واضح
- score=4 (raw∈[4,5)): WR=42.9%, 36.8% — خسارة
- score=5+: WR=22%, 20% — خسارة حادة
السؤال: هل رفض raw_score>=4.0 في 1d يُحسّن E بعد الرسوم؟
الحل: مقارنة portfolio (كل الصفقات) مع portfolio (1d bearish/sideways raw<4 فقط).
"""

import sys
import asyncio
import json

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')
from shared.database import Database

FEE_PCT = 0.003  # 0.3% لكل صفقة (0.2% رسوم + 0.1% انزلاق)

def adj(pct, fee=FEE_PCT):
    """profit_percent من DB هو نسبة، نحسم منه الرسوم بشكل مباشر."""
    return pct - fee * 100  # تحويل 0.003 -> 0.3%

async def main():
    await Database.connect()
    
    # جلب كل الصفقات المغلقة مع تفاصيل الإشارة
    rows = await Database.fetch("""
        SELECT 
            tr.result,
            tr.profit_percent,
            tr.profit_usdt,
            tr.stop_hit,
            tr.target_reached,
            s.score,
            s.timeframe,
            s.market_condition,
            s.score_details
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.result IN ('WIN', 'LOSS')
        ORDER BY tr.exit_time
    """)
    
    if not rows:
        print("لا توجد بيانات")
        return
    
    print(f"\n{'='*65}")
    print(f"الباكتيستر الجزء 12 — سقف score لإشارات 1d")
    print(f"{'='*65}")
    print(f"إجمالي الصفقات: {len(rows)}")
    
    # تصنيف الصفقات
    all_trades = []
    excluded_1d = []  # الصفقات التي ستُرفض بالفلتر الجديد
    included_1d = []  # الصفقات 1d التي تبقى
    
    for r in rows:
        p = float(r['profit_percent'] or 0)
        p_adj = adj(p)
        p_usdt = float(r['profit_usdt'] or 0)
        win = r['result'] == 'WIN'
        tf = r['timeframe']
        mc = r['market_condition']
        score = r['score']
        
        trade = {
            'win': win,
            'pct_raw': p,
            'pct_adj': p_adj,
            'usdt': p_usdt,
            'tf': tf,
            'mc': mc,
            'score': score,
        }
        
        all_trades.append(trade)
        
        # فلتر السقف: رفض 1d+bearish/sideways بـ score>=4
        if tf == '1d' and mc in ('bearish', 'sideways') and score >= 4:
            excluded_1d.append(trade)
        else:
            included_1d.append(trade)
    
    def metrics(trades, label):
        if not trades:
            print(f"\n{label}: لا صفقات")
            return
        n = len(trades)
        wins = sum(1 for t in trades if t['win'])
        wr = wins / n * 100
        avg_win_raw = sum(t['pct_raw'] for t in trades if t['win']) / max(wins, 1)
        avg_loss_raw = sum(t['pct_raw'] for t in trades if not t['win']) / max(n-wins, 1)
        avg_win_adj = sum(t['pct_adj'] for t in trades if t['win']) / max(wins, 1)
        avg_loss_adj = sum(t['pct_adj'] for t in trades if not t['win']) / max(n-wins, 1)
        e_raw = wr/100 * avg_win_raw + (1-wr/100) * avg_loss_raw
        e_adj = wr/100 * avg_win_adj + (1-wr/100) * avg_loss_adj
        pnl = sum(t['usdt'] for t in trades)
        
        print(f"\n{label} (n={n})")
        print(f"  WR: {wr:.1f}% | صافي PnL: ${pnl:.2f}")
        print(f"  avg_win: {avg_win_raw:+.2f}% | avg_loss: {avg_loss_raw:+.2f}%")
        print(f"  E_raw: {e_raw:+.3f}% | E_adj: {e_adj:+.3f}%")
        if wins > 0:
            pf = abs(avg_win_raw * wins) / abs(avg_loss_raw * (n-wins)) if n > wins else float('inf')
            print(f"  Profit Factor: {pf:.2f}")
        return e_adj
    
    print(f"\n--- المقارنة ---")
    
    e_all = metrics(all_trades, "الكل (baseline)")
    e_filtered = metrics(included_1d, "بعد رفض 1d+bearish/sideways+score>=4")
    e_excluded = metrics(excluded_1d, "الصفقات المُرفوضة (1d+b/sw+score>=4)")
    
    print(f"\n--- تأثير الفلتر ---")
    print(f"صفقات ستُحذف: {len(excluded_1d)} ({len(excluded_1d)/len(all_trades)*100:.1f}%)")
    if e_all is not None and e_filtered is not None:
        delta = e_filtered - e_all
        print(f"تحسن E_adj: {e_all:+.3f}% → {e_filtered:+.3f}% (Δ={delta:+.3f}%)")
    
    # تفصيل الصفقات المُرفوضة
    print(f"\n--- تفصيل المُرفوضة بالـ score ---")
    for sc in [4, 5, 6]:
        sub = [t for t in excluded_1d if t['score'] == sc]
        if not sub:
            continue
        n = len(sub)
        wins = sum(1 for t in sub if t['win'])
        wr = wins/n*100
        pnl = sum(t['usdt'] for t in sub)
        print(f"  score={sc}: n={n}, WR={wr:.1f}%, PnL=${pnl:.2f}")
    
    # تحقق: هل الفلتر يُجفّف إشارات 1d بالكامل؟
    total_1d = [t for t in all_trades if t['tf'] == '1d']
    remaining_1d = [t for t in included_1d if t['tf'] == '1d']
    print(f"\n--- تأثير على إشارات 1d ---")
    print(f"إجمالي 1d: {len(total_1d)}")
    print(f"يبقى بعد الفلتر: {len(remaining_1d)} ({len(remaining_1d)/max(len(total_1d),1)*100:.1f}%)")
    print(f"يُرفض: {len(excluded_1d)}")
    
    # أهم توليفة باقية
    print(f"\n--- أفضل توليفات 1d الباقية ---")
    groups = {}
    for t in remaining_1d:
        key = (t['tf'], t['mc'], t['score'])
        if key not in groups:
            groups[key] = []
        groups[key].append(t)
    
    sorted_groups = sorted(groups.items(), 
                           key=lambda x: sum(t['usdt'] for t in x[1]), 
                           reverse=True)
    for (tf, mc, sc), trades in sorted_groups[:8]:
        n = len(trades)
        wins = sum(1 for t in trades if t['win'])
        wr = wins/n*100
        pnl = sum(t['usdt'] for t in trades)
        e = sum(t['pct_adj'] for t in trades) / n
        print(f"  {tf}+{mc}+score{sc}: n={n}, WR={wr:.1f}%, PnL=${pnl:.2f}, E_adj={e:+.3f}%")
    
    print(f"\n{'='*65}")
    print("القرار: الفلتر مُطبَّق في signal_logic.py (raw_score>=4.0 يُرفض في 1d+b/sw)")
    print("الاختبار الحقيقي: أول 20 إشارة 1d post-تطبيق")

asyncio.run(main())
