"""
الباكتيستر — الجزء 16: قياس رافعة التكلفة (Cost Leverage Analysis)
====================================================================
يُقيِّم حساسية الاستراتيجية لتكلفة التنفيذ بسيناريوهات ثلاثة:

  السيناريو A — 0.30%: taker + انزلاق عادي (الافتراضي الحالي)
  السيناريو B — 0.15%: maker + انزلاق منخفض
  السيناريو C — 0.10%: maker + خصم BNB + انزلاق منخفض

لكل سيناريو (كلي + شرائح TF+MC):
  1. expectancy بعد التكلفة
  2. WR لنقطة التعادل
  3. عدد صفقات WIN تنقلب LOSS (وبالعكس)
  4. نسبة الصفقات المتأثرة

ملاحظة: تحليل جدوى فقط. لا تغيير على نوع الأوامر في الكود الحي.

المخرج: backtest_results_part16.jsonl + جدول مقارنة واضح.
"""

import asyncio
import json
import sys
from datetime import datetime
import decimal

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

from shared.database import Database

OUTPUT_FILE = '/app/backtest_results_part16.jsonl'

# ─── سيناريوهات التكلفة ───────────────────────────────────────────────────
SCENARIOS = [
    {
        'name': 'A_taker_normal',
        'label': '0.30% (taker + انزلاق عادي)',
        'cost_pct': 0.0030,
        'description': 'taker 0.2% + انزلاق 0.1% — الافتراضي الحالي',
    },
    {
        'name': 'B_maker_low_slip',
        'label': '0.15% (maker + انزلاق منخفض)',
        'cost_pct': 0.0015,
        'description': 'maker 0.1% + انزلاق 0.05% — limit orders دائماً',
    },
    {
        'name': 'C_maker_bnb_min_slip',
        'label': '0.10% (maker + BNB + انزلاق ضئيل)',
        'cost_pct': 0.0010,
        'description': 'maker مع خصم BNB (~0.075%) + انزلاق 0.025% — أفضل حالة',
    },
]


def safe_float(v) -> float:
    if isinstance(v, decimal.Decimal):
        return float(v)
    return float(v)


def calc_scenario(trades: list, cost_pct: float, label: str) -> dict:
    """يحسب مقاييس الأداء لسيناريو تكلفة محدد."""
    cost_pct_100 = cost_pct * 100  # بنسبة مئوية

    def adj(raw_pct):
        return safe_float(raw_pct) - cost_pct_100

    n = len(trades)
    if n == 0:
        return {'label': label, 'n': 0}

    # تصنيف الصفقات بعد التكلفة
    wins_raw  = [t for t in trades if t['result'] == 'WIN']
    losses_raw= [t for t in trades if t['result'] == 'LOSS']
    wr_raw    = len(wins_raw) / n

    adj_profits = [adj(t['profit_percent']) for t in trades]
    adj_wins    = [p for p in adj_profits if p > 0]
    adj_losses  = [p for p in adj_profits if p <= 0]
    wr_adj      = len(adj_wins) / n

    avg_win_raw  = sum(safe_float(t['profit_percent']) for t in wins_raw) / len(wins_raw)  if wins_raw   else 0.0
    avg_loss_raw = sum(safe_float(t['profit_percent']) for t in losses_raw)/ len(losses_raw) if losses_raw else 0.0
    avg_win_adj  = sum(adj_wins)   / len(adj_wins)   if adj_wins   else 0.0
    avg_loss_adj = sum(adj_losses) / len(adj_losses) if adj_losses else 0.0

    exp_raw = wr_raw * avg_win_raw + (1 - wr_raw) * avg_loss_raw
    exp_adj = wr_adj * avg_win_adj + (1 - wr_adj) * avg_loss_adj

    # WR لنقطة التعادل بعد التكلفة
    # E_adj = WR * avg_win_adj - (1-WR) * |avg_loss_adj| = 0
    # WR_be = |avg_loss_adj| / (avg_win_adj + |avg_loss_adj|)
    aw_a = abs(avg_win_adj)
    al_a = abs(avg_loss_adj)
    be_wr_adj = al_a / (aw_a + al_a) if (aw_a + al_a) > 0 else 0.5

    # عدد WIN تنقلب LOSS بعد التكلفة
    flipped_win_to_loss = sum(
        1 for t in wins_raw
        if adj(t['profit_percent']) < 0
    )
    # عدد LOSS تنقلب WIN بعد خفض التكلفة (مقارنة بسيناريو أغلى)
    # — لا ينطبق هنا مباشرة، نحسب من زاوية مختلفة

    # PnL إجمالي (افتراض position=50 USDT)
    pos = 50.0
    pnl_raw = sum(safe_float(t['profit_percent']) * pos / 100 for t in trades)
    pnl_adj = sum(adj(t['profit_percent']) * pos / 100 for t in trades)
    total_cost = n * cost_pct * pos

    return {
        'label':             label,
        'cost_pct_str':      f"{cost_pct*100:.2f}%",
        'n':                 n,
        'wr_raw_pct':        round(wr_raw * 100, 1),
        'wr_adj_pct':        round(wr_adj * 100, 1),
        'avg_win_raw':       round(avg_win_raw, 3),
        'avg_loss_raw':      round(avg_loss_raw, 3),
        'avg_win_adj':       round(avg_win_adj, 3),
        'avg_loss_adj':      round(avg_loss_adj, 3),
        'exp_raw':           round(exp_raw, 4),
        'exp_adj':           round(exp_adj, 4),
        'exp_delta':         round(exp_adj - exp_raw, 4),
        'be_wr_pct':         round(be_wr_adj * 100, 1),
        'be_wr_gap_pct':     round(be_wr_adj * 100 - wr_adj * 100, 1),
        'flipped_win_loss':  flipped_win_to_loss,
        'flipped_pct':       round(flipped_win_to_loss / max(1, len(wins_raw)) * 100, 1),
        'pnl_raw_usdt':      round(pnl_raw, 2),
        'pnl_adj_usdt':      round(pnl_adj, 2),
        'total_cost_usdt':   round(total_cost, 2),
        'pnl_delta_usdt':    round(pnl_adj - pnl_raw, 2),
    }


async def run_cost_leverage():
    print("=" * 75)
    print("الجزء 16: قياس رافعة التكلفة — سيناريوهات 0.30% / 0.15% / 0.10%")
    print(f"تاريخ التشغيل: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 75)

    await Database.connect()
    rows = await Database.fetch("""
        SELECT
            tr.result,
            tr.profit_percent,
            tr.profit_usdt,
            s.timeframe,
            s.market_condition,
            s.score
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.profit_percent IS NOT NULL
        ORDER BY s.signal_time ASC
    """)
    await Database.disconnect()

    all_trades = [dict(r) for r in rows]
    n_total = len(all_trades)
    print(f"\nإجمالي الصفقات: {n_total}")
    print()

    all_results = []

    # ── 1. جدول مقارنة كلي ─────────────────────────────────────────────────
    print("=" * 75)
    print("الجدول 1: المقارنة الكلية (كل الصفقات)")
    print("=" * 75)
    print(f"\n{'السيناريو':<35} {'N':>5} {'WR%':>6} {'E_adj%':>8} {'BE_WR%':>8} {'Flipped':>8} {'PnL_adj$':>10} {'TotalCost$':>12}")
    print("-" * 100)

    global_rows = []
    for sc in SCENARIOS:
        m = calc_scenario(all_trades, sc['cost_pct'], sc['label'])
        m['scenario_name'] = sc['name']
        m['description']   = sc['description']
        m['scope'] = 'ALL'
        all_results.append(m)
        global_rows.append(m)
        print(
            f"{sc['label']:<35} "
            f"{m['n']:>5} "
            f"{m['wr_adj_pct']:>6.1f} "
            f"{m['exp_adj']:>+8.4f} "
            f"{m['be_wr_pct']:>8.1f} "
            f"{m['flipped_win_loss']:>8} "
            f"{m['pnl_adj_usdt']:>+10.2f} "
            f"{m['total_cost_usdt']:>12.2f}"
        )

    # تمييز الفارق بين السيناريوهات
    if len(global_rows) >= 3:
        e_a = global_rows[0]['exp_adj']
        e_b = global_rows[1]['exp_adj']
        e_c = global_rows[2]['exp_adj']
        print(f"\nتحسن E_adj عند الانتقال A→B: {e_b - e_a:+.4f}%")
        print(f"تحسن E_adj عند الانتقال A→C: {e_c - e_a:+.4f}%")
        print(f"تحسن E_adj عند الانتقال B→C: {e_c - e_b:+.4f}%")

    # ── 2. جدول لكل شريحة TF+MC ────────────────────────────────────────────
    print()
    print("=" * 75)
    print("الجدول 2: المقارنة حسب (TF + market_condition)")
    print("=" * 75)

    # الشرائح ذات الأهمية (n>=10)
    key_combos = []
    for tf in ['1d', '1h', '4h']:
        for mc in ['bearish', 'sideways', 'bullish', 'volatile']:
            subset = [t for t in all_trades if t['timeframe'] == tf and t['market_condition'] == mc]
            if len(subset) >= 10:
                key_combos.append((f"{tf}+{mc}", subset))

    key_combos.sort(key=lambda x: -len(x[1]))

    print(f"\n{'TF+MC':20s} {'N':>5}  ", end="")
    for sc in SCENARIOS:
        cost_str = sc['cost_pct'] * 100
        print(f"E_adj({cost_str:.2f}%){' ':>2}", end="")
    print()
    print("-" * 80)

    for combo_label, subset in key_combos:
        print(f"{combo_label:20s} {len(subset):>5}  ", end="")
        combo_results = []
        for sc in SCENARIOS:
            m = calc_scenario(subset, sc['cost_pct'], f"{combo_label}+{sc['name']}")
            m['scenario_name'] = sc['name']
            m['scope'] = combo_label
            all_results.append(m)
            combo_results.append(m)
            print(f"{m['exp_adj']:>+11.4f}  ", end="")
        print()

    # ── 3. الحافة المُثبَتة: 1d+bearish+score3 ──────────────────────────────
    print()
    print("=" * 75)
    print("الجدول 3: الحافة المُثبَتة (1d+bearish+score3 و 1d+sideways+score3)")
    print("=" * 75)

    edge_filters = [
        ('1d+bearish+score3', lambda t: t['timeframe']=='1d' and t['market_condition']=='bearish' and t['score']==3),
        ('1d+sideways+score3', lambda t: t['timeframe']=='1d' and t['market_condition']=='sideways' and t['score']==3),
        ('1d+bearish/sideways+score3', lambda t: t['timeframe']=='1d' and t['market_condition'] in ('bearish','sideways') and t['score']==3),
    ]

    print(f"\n{'الفلتر':30s} {'N':>4}  ", end="")
    for sc in SCENARIOS:
        cost_str = f"{sc['cost_pct']*100:.2f}%"
        print(f"E({cost_str}){' ':>2}", end="")
    print("  BE_WR(A)")
    print("-" * 85)

    for edge_label, edge_fn in edge_filters:
        subset = [t for t in all_trades if edge_fn(t)]
        n_sub = len(subset)
        if n_sub < 5:
            print(f"{edge_label:30s} {n_sub:>4}  (عينة صغيرة جداً)")
            continue
        print(f"{edge_label:30s} {n_sub:>4}  ", end="")
        edge_results = []
        for i, sc in enumerate(SCENARIOS):
            m = calc_scenario(subset, sc['cost_pct'], f"{edge_label}+{sc['name']}")
            m['scenario_name'] = sc['name']
            m['scope'] = edge_label
            all_results.append(m)
            edge_results.append(m)
            print(f"{m['exp_adj']:>+9.4f}  ", end="")
        # WR التعادل للسيناريو A
        print(f"  {edge_results[0]['be_wr_pct']:>5.1f}%")

    # ── 4. تحليل الصفقات التي تنقلب ─────────────────────────────────────────
    print()
    print("=" * 75)
    print("الجدول 4: كم صفقة تنقلب؟")
    print("(WIN→LOSS عند تطبيق التكلفة / LOSS→WIN عند خفضها من A إلى B/C)")
    print("=" * 75)

    wins_raw = [t for t in all_trades if t['result'] == 'WIN']
    losses_raw= [t for t in all_trades if t['result'] == 'LOSS']

    print(f"\nإجمالي WIN الخام: {len(wins_raw)} | إجمالي LOSS الخام: {len(losses_raw)}")
    print()
    print(f"{'السيناريو':<35} {'WIN→LOSS':>10} {'%من_WIN':>9}  {'توضيح'}")
    print("-" * 75)

    for sc in SCENARIOS:
        cost_pct_100 = sc['cost_pct'] * 100
        flipped = [t for t in wins_raw if safe_float(t['profit_percent']) - cost_pct_100 < 0]
        pct = len(flipped) / max(1, len(wins_raw)) * 100
        if flipped:
            avg_raw = sum(safe_float(t['profit_percent']) for t in flipped) / len(flipped)
        else:
            avg_raw = 0.0
        print(f"{sc['label']:<35} {len(flipped):>10} {pct:>9.1f}%  avg_raw={avg_raw:.3f}%")

    # كم LOSS يمكن أن تنقلب WIN عند الانتقال A→B (خفض 0.15%)
    print()
    print("LOSS قريبة من الصفر (ضمن 0-0.15%): قد تنقلب WIN مع سيناريو B")
    near_zero = [t for t in losses_raw
                 if -0.15 <= safe_float(t['profit_percent']) <= 0]
    print(f"  عدد هذه الصفقات: {len(near_zero)} ({len(near_zero)/max(1,len(losses_raw))*100:.1f}% من الخسائر)")

    print()
    print("LOSS قريبة من الصفر (ضمن 0-0.10%): قد تنقلب WIN مع سيناريو C")
    near_zero_c = [t for t in losses_raw
                   if -0.10 <= safe_float(t['profit_percent']) <= 0]
    print(f"  عدد هذه الصفقات: {len(near_zero_c)} ({len(near_zero_c)/max(1,len(losses_raw))*100:.1f}% من الخسائر)")

    # ── 5. توصيات ──────────────────────────────────────────────────────────
    print()
    print("=" * 75)
    print("التوصيات")
    print("=" * 75)

    m_a = global_rows[0] if len(global_rows) > 0 else {}
    m_b = global_rows[1] if len(global_rows) > 1 else {}
    m_c = global_rows[2] if len(global_rows) > 2 else {}

    print(f"""
السيناريو الحالي (A=0.30%):
  E_adj = {m_a.get('exp_adj', 0):+.4f}% | WR للتعادل = {m_a.get('be_wr_pct', 0):.1f}% | فجوة WR = {m_a.get('be_wr_gap_pct', 0):+.1f}%

السيناريو B (0.15% — maker + limit orders):
  E_adj = {m_b.get('exp_adj', 0):+.4f}% | تحسن = {m_b.get('exp_adj', 0) - m_a.get('exp_adj', 0):+.4f}%
  الشرط: استخدام limit orders دائماً لضمان maker fee.

السيناريو C (0.10% — maker + BNB):
  E_adj = {m_c.get('exp_adj', 0):+.4f}% | تحسن = {m_c.get('exp_adj', 0) - m_a.get('exp_adj', 0):+.4f}%
  الشرط: تفعيل خصم BNB + limit orders + سوق سائل.

الخلاصة:
  - الانتقال من taker إلى maker (A→B) يوفر {(m_b.get('exp_adj', 0) - m_a.get('exp_adj', 0)):+.4f}%/صفقة.
  - خصم BNB يُضيف {(m_c.get('exp_adj', 0) - m_b.get('exp_adj', 0)):+.4f}%/صفقة إضافية.
  - هذا تحليل جدوى فقط — لا تغيير على نوع الأوامر الحي.
""")

    # ── حفظ النتائج ──────────────────────────────────────────────────────
    def safe_json(obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        raise TypeError(f'Not serializable: {type(obj)}')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False, default=safe_json) + '\n')

    print(f"النتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 75)
    return all_results


if __name__ == '__main__':
    asyncio.run(run_cost_leverage())
