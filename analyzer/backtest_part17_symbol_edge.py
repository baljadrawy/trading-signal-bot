"""
الباكتيستر — الجزء 17: Edge Positioning لكل عملة (Per-Symbol Edge Analysis)
============================================================================
يُحلّل expectancy تاريخياً لكل عملة على شريحة 1d+bearish/sideways
لتحديد الرموز ذات الحافة الحقيقية vs الرموز المُستنزِفة.

المنهجية:
1. تحميل صفقات 1d+bearish/sideways من DB مع تفاصيل الربح
2. حساب E_adj (0.3% رسوم) لكل رمز مع min 5 صفقات
3. تطبيق Bootstrap 200 معاينة لحساب CI 95% للـ E_adj
4. تصنيف الرموز: edge_positive / edge_negative / insufficient_data
5. مقارنة مع الكلي كخط أساس

القيود:
- n=2435 إجمالاً، لكن 1d فقط = 370، مع trade_results = 281
- العينات الصغيرة per-symbol = CI واسعة — نتائج استرشادية لا قطعية
- التجميد ساري: النتائج توصية فقط لما بعد التجميد

قيود الخادم: aarch64، نواتان، ~2GB RAM. Bootstrap ≤200 معاينة per-symbol.
المخرج: backtest_results_part17.jsonl + ملخص طباعي.
"""

import asyncio
import json
import random
import sys
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

from shared.database import Database

OUTPUT_FILE = '/app/backtest_results_part17.jsonl'

FEE_PCT        = 0.003    # 0.3% رسوم + انزلاق
N_BOOTSTRAP    = 200      # معاينات Bootstrap per-symbol
MIN_TRADES     = 5        # حد أدنى للتقييم الموثوق
TRADE_AMOUNT   = 50.0     # USDT افتراضي

random.seed(42)


# ══════════════════════════════════════════════════════════════════════════════
# 1. تحميل البيانات
# ══════════════════════════════════════════════════════════════════════════════

async def load_1d_trades() -> List[Dict]:
    """تحميل صفقات 1d+bearish/sideways مع نتائجها من DB."""
    rows = await Database.fetch("""
        SELECT
            s.symbol,
            s.market_condition,
            s.score,
            tr.result,
            CAST(tr.profit_percent AS FLOAT) AS profit_pct,
            CAST(tr.profit_usdt AS FLOAT)    AS profit_usdt,
            tr.stop_hit,
            tr.target_reached,
            CAST(tr.duration_hours AS FLOAT) AS duration_h,
            tr.exit_time
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.timeframe = '1d'
          AND s.market_condition IN ('bearish', 'sideways')
        ORDER BY tr.exit_time
    """)
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# 2. حسابات الأداء
# ══════════════════════════════════════════════════════════════════════════════

def adj_pct(profit_pct: float, fee_pct: float = FEE_PCT) -> float:
    """تعديل الربح بعد الرسوم والانزلاق."""
    return profit_pct - fee_pct * 100


def compute_metrics(trades: List[Dict]) -> Dict:
    """يحسب مقاييس الأداء الأساسية لمجموعة صفقات."""
    n = len(trades)
    if n == 0:
        return {'n': 0, 'wr': 0.0, 'e_raw': 0.0, 'e_adj': 0.0, 'pnl_adj': 0.0}

    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    wr = len(wins) / n

    raw_profits = [t['profit_pct'] for t in trades]
    adj_profits = [adj_pct(p) for p in raw_profits]

    e_raw = sum(raw_profits) / n
    e_adj = sum(adj_profits) / n
    pnl_adj = sum(adj_profits) * (TRADE_AMOUNT / 100)

    avg_win_raw  = sum(t['profit_pct'] for t in wins)  / len(wins)  if wins   else 0.0
    avg_loss_raw = sum(t['profit_pct'] for t in losses) / len(losses) if losses else 0.0
    avg_win_adj  = adj_pct(avg_win_raw)
    avg_loss_adj = adj_pct(avg_loss_raw)

    sl_hits = sum(1 for t in trades if t.get('stop_hit'))

    return {
        'n':            n,
        'wins':         len(wins),
        'losses':       len(losses),
        'wr':           round(wr * 100, 1),
        'e_raw':        round(e_raw, 3),
        'e_adj':        round(e_adj, 3),
        'pnl_adj_usdt': round(pnl_adj, 2),
        'avg_win_raw':  round(avg_win_raw, 2),
        'avg_loss_raw': round(avg_loss_raw, 2),
        'avg_win_adj':  round(avg_win_adj, 2),
        'avg_loss_adj': round(avg_loss_adj, 2),
        'sl_hit_rate':  round(sl_hits / n * 100, 1),
    }


def bootstrap_e_adj(trades: List[Dict], n_boot: int = N_BOOTSTRAP, seed: int = 42) -> Tuple[float, float]:
    """Bootstrap CI 95% للـ E_adj."""
    rng = random.Random(seed)
    n = len(trades)
    if n < 3:
        return float('nan'), float('nan')

    boot_means = []
    for _ in range(n_boot):
        sample = [rng.choice(trades) for _ in range(n)]
        boot_means.append(sum(adj_pct(t['profit_pct']) for t in sample) / n)

    boot_means.sort()
    lo = boot_means[int(0.025 * n_boot)]
    hi = boot_means[int(0.975 * n_boot)]
    return round(lo, 3), round(hi, 3)


def classify_symbol(e_adj: float, ci_lo: float, ci_hi: float, n: int) -> str:
    """
    تصنيف الرمز:
    - edge_positive: CI_lo > 0 (مرجّح ربح حتى في أسوأ السيناريوهات)
    - edge_candidate: e_adj > 0 لكن CI يشمل الصفر
    - edge_negative: e_adj < 0 وCI_hi <= 0
    - edge_drag: e_adj < -0.5% (مُستنزِف واضح)
    - insufficient: n < MIN_TRADES
    """
    if n < MIN_TRADES:
        return 'insufficient'
    if math.isnan(ci_lo):
        return 'insufficient'
    if ci_lo > 0:
        return 'edge_positive'
    if e_adj > 0:
        return 'edge_candidate'
    if ci_hi <= 0:
        return 'edge_negative'
    if e_adj < -0.5:
        return 'edge_drag'
    return 'edge_weak_negative'


# ══════════════════════════════════════════════════════════════════════════════
# 3. التحليل الرئيسي
# ══════════════════════════════════════════════════════════════════════════════

async def run_part17():
    await Database.connect()
    try:
        print("=== الجزء 17: Per-Symbol Edge Analysis (1d+bearish/sideways) ===\n")

        trades = await load_1d_trades()
        print(f"إجمالي الصفقات المُحمَّلة: {len(trades)}")

        # الكلي كخط أساس
        baseline = compute_metrics(trades)
        bl_lo, bl_hi = bootstrap_e_adj(trades)
        print(f"\nخط الأساس الكلي (n={baseline['n']}):")
        print(f"  WR={baseline['wr']}%, E_adj={baseline['e_adj']}% [{bl_lo}, {bl_hi}] 95CI")
        print(f"  PnL_adj={baseline['pnl_adj_usdt']} USDT\n")

        # تجميع per-symbol
        symbol_trades: Dict[str, List] = {}
        for t in trades:
            sym = t['symbol']
            symbol_trades.setdefault(sym, []).append(t)

        symbol_results = []
        for symbol, sym_trades in sorted(symbol_trades.items()):
            metrics = compute_metrics(sym_trades)
            ci_lo, ci_hi = bootstrap_e_adj(sym_trades)
            category = classify_symbol(metrics['e_adj'], ci_lo, ci_hi, metrics['n'])
            symbol_results.append({
                'symbol':    symbol,
                'category':  category,
                'ci_lo':     ci_lo,
                'ci_hi':     ci_hi,
                **metrics,
            })

        # ترتيب بـ PnL_adj
        symbol_results.sort(key=lambda x: x['pnl_adj_usdt'], reverse=True)

        # طباعة جدول
        print(f"{'الرمز':<15} {'n':>4} {'WR':>6} {'E_adj':>7} {'CI_lo':>7} {'CI_hi':>7} {'PnL_adj':>8} {'تصنيف'}")
        print("-" * 80)
        for r in symbol_results:
            if r['n'] >= MIN_TRADES:
                print(f"{r['symbol']:<15} {r['n']:>4} {r['wr']:>5.1f}% {r['e_adj']:>7.3f}% "
                      f"{str(r['ci_lo']):>7} {str(r['ci_hi']):>7} "
                      f"{r['pnl_adj_usdt']:>7.2f}$ {r['category']}")

        # ملخص التصنيفات
        cats = {}
        for r in symbol_results:
            cats[r['category']] = cats.get(r['category'], 0) + 1
        print(f"\n=== ملخص التصنيفات ===")
        for cat, cnt in sorted(cats.items()):
            print(f"  {cat}: {cnt} رمز")

        # أفضل الرموز (edge_positive + edge_candidate)
        top = [r for r in symbol_results if r['category'] in ('edge_positive', 'edge_candidate') and r['n'] >= MIN_TRADES]
        print(f"\n=== الرموز الواعدة ({len(top)}) ===")
        for r in top[:10]:
            print(f"  {r['symbol']}: n={r['n']}, WR={r['wr']}%, E_adj={r['e_adj']}%, CI=[{r['ci_lo']},{r['ci_hi']}]")

        # أسوأ الرموز (drag)
        drag = [r for r in symbol_results if r['category'] in ('edge_negative', 'edge_drag') and r['n'] >= MIN_TRADES]
        print(f"\n=== الرموز المستنزِفة ({len(drag)}) ===")
        for r in sorted(drag, key=lambda x: x['pnl_adj_usdt'])[:10]:
            print(f"  {r['symbol']}: n={r['n']}, WR={r['wr']}%, E_adj={r['e_adj']}%, PnL={r['pnl_adj_usdt']}$")

        # حفظ النتائج
        output = {
            'run_date':     datetime.utcnow().isoformat(),
            'n_total':      len(trades),
            'fee_pct':      FEE_PCT,
            'n_bootstrap':  N_BOOTSTRAP,
            'min_trades':   MIN_TRADES,
            'baseline': {
                'n':      baseline['n'],
                'wr':     baseline['wr'],
                'e_adj':  baseline['e_adj'],
                'ci_lo':  bl_lo,
                'ci_hi':  bl_hi,
                'pnl_adj': baseline['pnl_adj_usdt'],
            },
            'category_summary': cats,
            'symbols': symbol_results,
        }

        with open(OUTPUT_FILE, 'w') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\nNتائج محفوظة: {OUTPUT_FILE}")
        print("=== اكتمل الجزء 17 ===")

    finally:
        await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(run_part17())
