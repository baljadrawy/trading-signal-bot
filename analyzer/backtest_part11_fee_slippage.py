"""
الباكتيستر — الجزء 11: نمذجة رسوم Binance والانزلاق (freqtrade-inspired)
=========================================================================
المشكلة: الباكتيستر الحالي يفترض صفقات بدون رسوم — يجعل النتائج متفائلة.
رسوم Binance Spot: 0.1% maker + 0.1% taker = 0.2% لكل رحلة كاملة (دخول+خروج).
مع انزلاق واقعي 0.05% لكل جهة = 0.1% إجمالي.
إجمالي التكلفة الواقعية: ~0.3% من رأس المال لكل صفقة.

السؤال: هل expectancy تنهار أم تبقى إيجابية بعد حسم التكاليف؟
    - avg_win حالياً: +3.17% → بعد الرسوم: +2.87%
    - avg_loss حالياً: -2.60% → بعد الرسوم: -2.90%
    - WR 37.6%: E = 0.376×2.87 + 0.624×(-2.90) = 1.079 - 1.810 = -0.731%
    - مقابل الحالي (بدون رسوم): 0.376×3.17 + 0.624×(-2.60) = 1.192 - 1.622 = -0.430%

الهدف: قياس الانهيار الفعلي في expectancy مع محاكاة كاملة على 2433 صفقة.
المخرج: مقارنة WR/PF/expectancy مع/بدون رسوم، مجزّأة بـ (timeframe, market_condition, score).

قيود الخادم: معالجة متزامنة، بلا حزم خارجية، batch صغيرة.
"""

import json
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

from shared.database import Database

# رسوم Binance Spot الواقعية
MAKER_FEE = 0.001       # 0.1% دخول (limit order)
TAKER_FEE = 0.001       # 0.1% خروج (market order)
SLIPPAGE_ENTRY = 0.0005  # 0.05% انزلاق عند الدخول
SLIPPAGE_EXIT = 0.0005   # 0.05% انزلاق عند الخروج
TOTAL_COST_PCT = MAKER_FEE + TAKER_FEE + SLIPPAGE_ENTRY + SLIPPAGE_EXIT  # ~0.3%

OUTPUT_FILE = '/app/backtest_results_part11.jsonl'


def apply_fees(raw_pct) -> float:
    """حسم الرسوم والانزلاق من نسبة الربح/الخسارة الخام"""
    return float(raw_pct) - (TOTAL_COST_PCT * 100)


def calc_metrics(trades: list, label: str) -> dict:
    """حساب مقاييس الأداء لمجموعة صفقات"""
    if not trades:
        return {}
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    n = len(trades)
    wr = len(wins) / n if n > 0 else 0

    avg_win_raw = sum(float(t['profit_percent']) for t in wins) / len(wins) if wins else 0
    avg_loss_raw = sum(float(t['profit_percent']) for t in losses) / len(losses) if losses else 0
    avg_win_adj = sum(apply_fees(t['profit_percent']) for t in wins) / len(wins) if wins else 0
    avg_loss_adj = sum(apply_fees(t['profit_percent']) for t in losses) / len(losses) if losses else 0

    exp_raw = wr * avg_win_raw + (1 - wr) * avg_loss_raw
    exp_adj = wr * avg_win_adj + (1 - wr) * avg_loss_adj

    total_pnl_raw = sum(float(t['profit_usdt']) for t in trades)
    total_pnl_adj = total_pnl_raw - (n * TOTAL_COST_PCT * 50)  # 50 USDT position size

    pf_raw = abs(sum(t['profit_percent'] for t in wins)) / abs(sum(t['profit_percent'] for t in losses)) if losses and sum(t['profit_percent'] for t in losses) != 0 else float('inf')
    pf_adj = abs(sum(apply_fees(t['profit_percent']) for t in wins)) / abs(sum(apply_fees(t['profit_percent']) for t in losses)) if losses and losses else float('inf')

    return {
        'label': label,
        'n': n,
        'wins': len(wins),
        'losses': len(losses),
        'wr_pct': round(wr * 100, 1),
        'avg_win_raw': round(avg_win_raw, 2),
        'avg_loss_raw': round(avg_loss_raw, 2),
        'avg_win_adj': round(avg_win_adj, 2),
        'avg_loss_adj': round(avg_loss_adj, 2),
        'expectancy_raw': round(exp_raw, 3),
        'expectancy_adj': round(exp_adj, 3),
        'expectancy_delta': round(exp_adj - exp_raw, 3),
        'total_pnl_raw': round(total_pnl_raw, 2),
        'total_pnl_adj': round(total_pnl_adj, 2),
        'pnl_delta': round(total_pnl_adj - total_pnl_raw, 2),
        'pf_raw': round(pf_raw, 2) if pf_raw != float('inf') else 99.0,
        'pf_adj': round(pf_adj, 2) if pf_adj != float('inf') else 99.0,
    }


async def run_analysis():
    await Database.connect()

    print("=" * 70)
    print("الجزء 11: نمذجة رسوم Binance والانزلاق")
    print("تاريخ التشغيل:", datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))
    print(f"إجمالي التكلفة لكل صفقة: {TOTAL_COST_PCT*100:.2f}% (~0.3% = رسوم 0.2% + انزلاق 0.1%)")
    print("=" * 70)

    # تحميل جميع صفقات trade_results مع بيانات الإشارة
    rows = await Database.fetch("""
        SELECT
            tr.id, tr.symbol, tr.result, tr.profit_percent, tr.profit_usdt,
            tr.target_reached, tr.stop_hit, tr.duration_hours,
            s.timeframe, s.market_condition, s.score
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.profit_percent IS NOT NULL
        ORDER BY tr.id ASC
    """)

    all_trades = [dict(r) for r in rows]
    n_total = len(all_trades)
    print(f"\nإجمالي الصفقات المحللة: {n_total}")

    results = []

    # 1. المقارنة الكلية
    print("\n--- 1. المقارنة الكلية (قبل/بعد الرسوم) ---")
    m = calc_metrics(all_trades, 'ALL')
    results.append(m)
    print(f"N={m['n']} | WR={m['wr_pct']}%")
    print(f"Expectancy الخام:      {m['expectancy_raw']:+.3f}%")
    print(f"Expectancy بعد رسوم:   {m['expectancy_adj']:+.3f}%  (delta: {m['expectancy_delta']:+.3f}%)")
    print(f"PnL الخام:    ${m['total_pnl_raw']:+.2f}")
    print(f"PnL بعد رسوم: ${m['total_pnl_adj']:+.2f}  (خصم: ${m['pnl_delta']:.2f})")
    print(f"Profit Factor (خام/بعد رسوم): {m['pf_raw']:.2f} / {m['pf_adj']:.2f}")

    # 2. تجزئة بالـ timeframe
    print("\n--- 2. حسب الإطار الزمني ---")
    tfs = ['1d', '1h', '4h', '15m']
    print(f"{'TF':<5} {'N':>5} {'WR%':>6} {'E_raw':>8} {'E_adj':>8} {'PnL_adj':>10}")
    for tf in tfs:
        subset = [t for t in all_trades if t['timeframe'] == tf]
        if not subset:
            continue
        m = calc_metrics(subset, f'TF={tf}')
        results.append(m)
        print(f"{tf:<5} {m['n']:>5} {m['wr_pct']:>6.1f} {m['expectancy_raw']:>+8.3f} {m['expectancy_adj']:>+8.3f} {m['total_pnl_adj']:>+10.2f}")

    # 3. تجزئة بالإطار + السوق
    print("\n--- 3. حسب الإطار + السوق (أبرز توليفات) ---")
    print(f"{'TF+MC':<20} {'N':>5} {'WR%':>6} {'E_raw':>8} {'E_adj':>8} {'PnL_adj':>10}")
    seen_combos = []
    for tf in ['1d', '1h']:
        for mc in ['bearish', 'sideways', 'bullish', 'volatile']:
            subset = [t for t in all_trades if t['timeframe'] == tf and t['market_condition'] == mc]
            if len(subset) < 5:
                continue
            m = calc_metrics(subset, f'{tf}+{mc}')
            results.append(m)
            seen_combos.append((len(subset), m))
            print(f"{tf}+{mc:<15} {m['n']:>5} {m['wr_pct']:>6.1f} {m['expectancy_raw']:>+8.3f} {m['expectancy_adj']:>+8.3f} {m['total_pnl_adj']:>+10.2f}")

    # 4. الحافة الوحيدة الإيجابية: score=3+1d
    print("\n--- 4. الحافة المُثبَتة: 1d+bearish+score3 ---")
    for score_val in [3, 4, 5]:
        for mc in ['bearish', 'sideways']:
            subset = [t for t in all_trades if t['timeframe'] == '1d'
                     and t['market_condition'] == mc and t['score'] == score_val]
            if len(subset) < 5:
                continue
            m = calc_metrics(subset, f'1d+{mc}+score{score_val}')
            results.append(m)
            print(f"1d+{mc}+score{score_val}: N={m['n']}, WR={m['wr_pct']}%, "
                  f"E_raw={m['expectancy_raw']:+.3f}%, E_adj={m['expectancy_adj']:+.3f}%, "
                  f"PnL_adj=${m['total_pnl_adj']:+.2f}")

    # 5. تحليل الصفقات الرابحة vs الخاسرة بعد الرسوم (هل صفقات صغيرة الربح تصبح خاسرة؟)
    print("\n--- 5. صفقات 'رابحة' تصبح خاسرة بعد الرسوم ---")
    flipped = [t for t in all_trades
               if t['result'] == 'WIN'
               and apply_fees(float(t['profit_percent'])) < 0]
    print(f"صفقات WIN تصبح LOSS بعد الرسوم: {len(flipped)}/{len([t for t in all_trades if t['result']=='WIN'])} "
          f"({len(flipped)/max(1, len([t for t in all_trades if t['result']=='WIN']))*100:.1f}%)")
    if flipped:
        avg_flip = sum(float(t['profit_percent']) for t in flipped) / len(flipped)
        print(f"  متوسط ربحها الخام: {avg_flip:.2f}% (ضمن هامش الرسوم 0.3%)")

    # 6. تأثير رفع WR على كسر التعادل مع الرسوم
    print("\n--- 6. WR المطلوب لكسر التعادل بعد الرسوم ---")
    avg_win_adj = m['avg_win_adj'] if m else 2.87
    avg_loss_adj = m['avg_loss_adj'] if m else -2.90
    # E = WR * avg_win_adj - (1-WR) * |avg_loss_adj| = 0
    # WR = |avg_loss_adj| / (avg_win_adj + |avg_loss_adj|)
    all_m = calc_metrics(all_trades, 'ALL_final')
    aw = abs(all_m['avg_win_adj'])
    al = abs(all_m['avg_loss_adj'])
    be_wr = al / (aw + al) if (aw + al) > 0 else 0.5
    print(f"avg_win بعد رسوم:  {all_m['avg_win_adj']:+.2f}%")
    print(f"avg_loss بعد رسوم: {all_m['avg_loss_adj']:+.2f}%")
    print(f"WR للتعادل بعد رسوم: {be_wr*100:.1f}% (حالياً: {all_m['wr_pct']}%)")
    gap = be_wr * 100 - all_m['wr_pct']
    print(f"الفجوة المطلوبة: +{gap:.1f}% في WR لبلوغ التعادل")

    # 7. توصيات
    print("\n--- 7. التوصيات ---")
    print("1. الباكتيستر يجب أن يحسم 0.3% من كل صفقة لتمثيل دقيق")
    print("2. الهدف الجديد: E_adj >= 0 (ليس E_raw >= 0)")
    print(f"3. WR المطلوب: {be_wr*100:.0f}% (الحالي {all_m['wr_pct']}%) — نقص {gap:.0f}%")
    print("4. الحافة 1d+bearish+score3 هي الوحيدة ذات E_adj إيجابية محتملة")
    print("5. كل إشارة تكلف فعلياً ~0.15 USDT رسوم (على position 50 USDT)")

    # حفظ النتائج
    results.append({'break_even_wr': round(be_wr * 100, 1), 'gap_pct': round(gap, 1),
                    'total_cost_pct': TOTAL_COST_PCT * 100})

    def safe_json(obj):
        """تحويل Decimal لـ float قبل JSON"""
        import decimal
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')

    with open(OUTPUT_FILE, 'w') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, default=safe_json) + '\n')
    print(f"\nالنتائج محفوظة في: {OUTPUT_FILE}")

    await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(run_analysis())
