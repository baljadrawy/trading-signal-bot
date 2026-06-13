"""
backtest_fixed_template.py — القالب الثابت (Professional Scalp Template)
=======================================================================
يقارن بين القالب الحالي المحسوب ديناميكياً والقالب الثابت المستخرج من 13 توصية احترافية:
    SL = Entry × 0.96  (−4%)
    T1 = Entry × 1.04  (+4% = 1R)
    T2 = Entry × 1.07  (+7% = 1.75R)
    T3 = Entry × 1.09  (+9% = 2.25R)
    شرط الستوب: إغلاق شمعة 4h أقل من SL

البيانات: 271 صفقة مغلقة post-2026-04-22
المنهج:
    1. نعيد محاكاة كل صفقة بالقالب الثابت باستخدام exit_price/profit_percent الأصلي
       كبروكسي لمسار السعر (نظراً لعدم توفر OHLC كامل للشمعة)
    2. نستخدم exit_price الفعلي للحكم على نتيجة القالب الثابت
    3. Walk-forward 60/40 زمني
    4. شريحة الحافة 1d+bearish/sideways
    5. تحليل قلب النتيجة

قواعد البحث فقط (التجميد ساري):
    - لا تعديل على signal_logic.py أو technical_analyzer.py
    - لا تعديل على PAPER_TRADING
    - لا إضافة عملات للقوائم البيضاء/السوداء
"""

import asyncio
import asyncpg
import json
import sys
from dataclasses import dataclass
from typing import Optional

# ── إعدادات القالب الثابت ────────────────────────────────────────────────
FIXED_SL_PCT  = 4.0    # −4% من الدخول
FIXED_T1_PCT  = 4.0    # +4%
FIXED_T2_PCT  = 7.0    # +7%
FIXED_T3_PCT  = 9.0    # +9%

FEE_PCT       = 0.3    # رسوم ذهاباً وإياباً (0.3%)
TRADE_AMOUNT  = 50.0   # USDT
TRAIL_PCT     = 2.5    # trailing stop% بعد T2
EXPIRY_H      = 48.0   # ساعة انتهاء صلاحية

DB_URL = "postgresql://trading_signal_bot:6psgaD1GV2ClGtopvSe5Lm8za@postgres:5432/trading_signals"


# ── بنية نتيجة الصفقة ───────────────────────────────────────────────────
@dataclass
class TradeResult:
    symbol: str
    signal_time: object
    timeframe: str
    market_condition: str
    score: int
    entry: float

    # النتيجة الفعلية (القالب الحالي)
    actual_result: str        # WIN/LOSS
    actual_profit_pct: float
    actual_profit_usdt: float
    actual_target_reached: int
    actual_stop_hit: bool
    actual_duration_h: float

    # أهداف القالب الثابت
    fixed_sl: float
    fixed_t1: float
    fixed_t2: float
    fixed_t3: float

    # نتيجة القالب الثابت (محاكاة)
    fixed_result: str
    fixed_profit_pct: float
    fixed_profit_usdt: float
    fixed_exit_reason: str    # T1/T2/T3/SL/expiry
    fixed_target_reached: int
    fixed_stop_hit: bool

    # قلب النتيجة
    flipped: str    # 'win_to_loss' | 'loss_to_win' | 'same_win' | 'same_loss'


def simulate_fixed_template(entry: float, exit_price: float,
                             actual_result: str, actual_profit_pct: float,
                             actual_target_reached: int, duration_h: float) -> dict:
    """
    يحاكي نتيجة القالب الثابت بناءً على:
    - سعر الدخول
    - سعر الخروج الفعلي (بروكسي لمسار السعر)
    - actual_profit_pct لتحديد ما إذا كان السوق ارتفع أم انخفض

    المنطق:
    - إذا بلغ السعر T3_fixed أو أعلى (ارتفع ≥9%) → WIN عند T3
    - إذا بلغ T2_fixed (ارتفع ≥7%) لكن لم يبلغ T3 → نُقدّر خروج trailing بعد T2
    - إذا بلغ T1_fixed (ارتفع ≥4%) لكن لم يبلغ T2 → WIN بعد انتهاء الوقت أو break-even
    - إذا انخفض السعر إلى SL_fixed (−4%) → LOSS
    - إذا خرج بنتيجة سلبية بين (0, −4%) → LOSS (لكن أقل من القالب الحالي)
    """
    fixed_sl = entry * (1 - FIXED_SL_PCT / 100)
    fixed_t1 = entry * (1 + FIXED_T1_PCT / 100)
    fixed_t2 = entry * (1 + FIXED_T2_PCT / 100)
    fixed_t3 = entry * (1 + FIXED_T3_PCT / 100)

    # نحسب أعلى نقطة بلغها السوق استناداً إلى actual_profit_pct
    # إذا كان الخروج بـ WIN فأعلى نقطة = exit_price على الأقل
    # إذا كان LOSS فأعلى نقطة = entry * (1 + max_gain_before_loss)
    # نستخدم actual_target_reached كمؤشر
    if actual_result == 'WIN':
        max_price_proxy = exit_price  # الخروج بالربح = بلغ على الأقل هذا السعر
        # إذا وصل T1 أو T2 أو T3
        if actual_target_reached >= 3:
            max_gain_pct = actual_profit_pct  # قد يكون 6%+ في 1d
        elif actual_target_reached >= 2:
            max_gain_pct = actual_profit_pct
        elif actual_target_reached >= 1:
            max_gain_pct = actual_profit_pct
        else:
            max_gain_pct = actual_profit_pct  # break-even أو trailing
    else:
        # LOSS: exit_price < entry
        # لكن ربما ارتفع قليلاً أولاً (break-even بعد T1 الحالي)
        # نستخدم actual_target_reached لتقدير أعلى ارتفاع
        if actual_target_reached >= 2:
            # وصل T2 الحالي ثم trailing أغلقه
            # T2_current ≈ actual exit price (trailing)
            max_gain_pct = float(entry * (1 + 0.06) / entry - 1) * 100  # تقدير محافظ
        elif actual_target_reached >= 1:
            # وصل T1 الحالي ثم break-even
            max_gain_pct = 3.0  # تقدير: ارتفع للـT1 الحالي ≈3% عند إطارات صغيرة
        else:
            max_gain_pct = 0.0  # لم يرتفع قبل السقوط

    # نقدّر أدنى نقطة بلغها السوق
    if actual_result == 'LOSS':
        min_price_proxy = exit_price  # سقط إلى هذا السعر
        min_loss_pct = actual_profit_pct  # سالب
    else:
        # WIN: نقدّر أن السوق ربما انخفض أقل من entry قبل الارتفاع أو لا
        min_loss_pct = 0.0  # لم يعبر SL (وإلا كان LOSS)

    # حساب نتيجة القالب الثابت
    high_price = entry * (1 + max_gain_pct / 100)
    low_price  = entry * (1 + min_loss_pct / 100)

    target_reached = 0
    if high_price >= fixed_t3:
        target_reached = 3
    elif high_price >= fixed_t2:
        target_reached = 2
    elif high_price >= fixed_t1:
        target_reached = 1

    # هل ضرب SL الثابت؟
    hit_fixed_sl = (low_price <= fixed_sl)

    # منطق الخروج (مبسّط بدون شموع لساعية كاملة)
    if target_reached == 3:
        # وصل T3
        exit_price_fixed = fixed_t3
        profit_pct_fixed = FIXED_T3_PCT
        exit_reason = 'T3'
        result_fixed = 'WIN'
        stop_hit_fixed = False

    elif target_reached == 2:
        # وصل T2 → trailing stop بعد ذلك
        # نُقدّر خروج trailing بنسبة (T2 + T3)/2 أو trailing 2.5% تحت القمة
        # القمة المحتملة = high_price (أعلى ما وصله)
        trail_stop = high_price * (1 - TRAIL_PCT / 100)
        trail_stop = max(trail_stop, fixed_t1)  # أرضية T1

        if low_price <= trail_stop:
            # ضرب trailing
            exit_price_fixed = trail_stop
            profit_pct_fixed = ((trail_stop - entry) / entry) * 100
            exit_reason = 'trailing_stop'
            result_fixed = 'WIN' if trail_stop > entry else 'LOSS'
        else:
            # انتهت بـ T2 أو أعلى بدون trailing
            exit_price_fixed = high_price
            profit_pct_fixed = ((high_price - entry) / entry) * 100
            exit_reason = 'T2'
            result_fixed = 'WIN'

        stop_hit_fixed = False

    elif target_reached == 1:
        # وصل T1 → break-even بعد ذلك
        if low_price <= entry:
            # ضرب break-even
            exit_price_fixed = entry
            profit_pct_fixed = 0.0
            exit_reason = 'break_even'
            result_fixed = 'WIN'  # تعادل = لا خسارة
        else:
            # لم يصل break-even، خرج بمكسب صغير
            exit_price_fixed = exit_price
            profit_pct_fixed = actual_profit_pct
            exit_reason = 'T1'
            result_fixed = 'WIN'
        stop_hit_fixed = False

    elif hit_fixed_sl:
        # ضرب SL الثابت −4%
        exit_price_fixed = fixed_sl
        profit_pct_fixed = -FIXED_SL_PCT
        exit_reason = 'stop_loss'
        result_fixed = 'LOSS'
        stop_hit_fixed = True

    else:
        # لم يبلغ T1 ولم يضرب SL الثابت
        # خرج بين (−4%, +4%) → نستخدم actual_profit_pct
        exit_price_fixed = exit_price
        profit_pct_fixed = actual_profit_pct
        exit_reason = 'expiry' if duration_h >= EXPIRY_H else 'other'
        result_fixed = 'WIN' if profit_pct_fixed > 0 else 'LOSS'
        stop_hit_fixed = False

    profit_usdt_fixed = (profit_pct_fixed / 100) * TRADE_AMOUNT

    return {
        'fixed_sl': fixed_sl,
        'fixed_t1': fixed_t1,
        'fixed_t2': fixed_t2,
        'fixed_t3': fixed_t3,
        'fixed_result': result_fixed,
        'fixed_profit_pct': round(profit_pct_fixed, 4),
        'fixed_profit_usdt': round(profit_usdt_fixed, 4),
        'fixed_exit_reason': exit_reason,
        'fixed_target_reached': target_reached,
        'fixed_stop_hit': stop_hit_fixed,
    }


def compute_metrics(trades: list) -> dict:
    """يحسب المقاييس الرئيسية لمجموعة صفقات."""
    n = len(trades)
    if n == 0:
        return {'n': 0}

    wins  = [t for t in trades if t.actual_result == 'WIN']
    losses = [t for t in trades if t.actual_result == 'LOSS']
    wr = len(wins) / n * 100

    avg_win  = sum(t.actual_profit_pct for t in wins)  / max(len(wins), 1)
    avg_loss = sum(t.actual_profit_pct for t in losses) / max(len(losses), 1)
    total_pnl = sum(t.actual_profit_usdt for t in trades)

    # E_adj بعد رسوم 0.3%
    E_raw = sum(t.actual_profit_pct for t in trades) / n / 100
    E_adj = (E_raw - FEE_PCT / 100) * 100  # %

    # Profit Factor
    gross_win  = sum(t.actual_profit_usdt for t in wins)
    gross_loss = abs(sum(t.actual_profit_usdt for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

    t1_hits = sum(1 for t in trades if t.actual_target_reached >= 1)
    t2_hits = sum(1 for t in trades if t.actual_target_reached >= 2)
    t3_hits = sum(1 for t in trades if t.actual_target_reached >= 3)
    sl_hits = sum(1 for t in trades if t.actual_stop_hit)

    return {
        'n': n, 'wr_pct': round(wr, 1), 'E_adj_pct': round(E_adj, 4),
        'total_pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'avg_win_pct': round(avg_win, 3), 'avg_loss_pct': round(avg_loss, 3),
        'T1': t1_hits, 'T2': t2_hits, 'T3': t3_hits, 'SL': sl_hits,
    }


def compute_fixed_metrics(trades: list) -> dict:
    """يحسب المقاييس للقالب الثابت."""
    n = len(trades)
    if n == 0:
        return {'n': 0}

    wins  = [t for t in trades if t.fixed_result == 'WIN']
    losses = [t for t in trades if t.fixed_result == 'LOSS']
    wr = len(wins) / n * 100

    avg_win  = sum(t.fixed_profit_pct for t in wins)  / max(len(wins), 1)
    avg_loss = sum(t.fixed_profit_pct for t in losses) / max(len(losses), 1)
    total_pnl = sum(t.fixed_profit_usdt for t in trades)

    E_raw = sum(t.fixed_profit_pct for t in trades) / n / 100
    E_adj = (E_raw - FEE_PCT / 100) * 100

    gross_win  = sum(t.fixed_profit_usdt for t in wins)
    gross_loss = abs(sum(t.fixed_profit_usdt for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

    t1_hits = sum(1 for t in trades if t.fixed_target_reached >= 1)
    t2_hits = sum(1 for t in trades if t.fixed_target_reached >= 2)
    t3_hits = sum(1 for t in trades if t.fixed_target_reached >= 3)
    sl_hits = sum(1 for t in trades if t.fixed_stop_hit)

    return {
        'n': n, 'wr_pct': round(wr, 1), 'E_adj_pct': round(E_adj, 4),
        'total_pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'avg_win_pct': round(avg_win, 3), 'avg_loss_pct': round(avg_loss, 3),
        'T1': t1_hits, 'T2': t2_hits, 'T3': t3_hits, 'SL': sl_hits,
    }


async def main():
    print("=" * 60)
    print("backtest_fixed_template.py — القالب الثابت الاحترافي")
    print("=" * 60)

    conn = await asyncpg.connect(DB_URL)

    # جلب كل الصفقات المغلقة post-rebuild
    rows = await conn.fetch('''
        SELECT tr.id, tr.symbol, tr.entry_price, tr.exit_price, tr.result,
               tr.profit_percent, tr.profit_usdt, tr.target_reached, tr.stop_hit,
               tr.duration_hours, s.timeframe, s.market_condition, s.score,
               s.target_1, s.target_2, s.target_3, s.stop_loss, s.signal_time
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE s.signal_time >= '2026-04-22'
        ORDER BY s.signal_time
    ''')
    await conn.close()

    print(f"\nإجمالي الصفقات المغلقة post-rebuild: {len(rows)}")

    # بناء TradeResult لكل صفقة
    all_trades = []
    for row in rows:
        entry     = float(row['entry_price'])
        exit_p    = float(row['exit_price'])
        profit_p  = float(row['profit_percent'])
        target_r  = int(row['target_reached'] or 0)
        dur_h     = float(row['duration_hours'] or 0)
        result    = row['result']

        sim = simulate_fixed_template(entry, exit_p, result, profit_p, target_r, dur_h)

        # قلب النتيجة
        if result == 'WIN' and sim['fixed_result'] == 'LOSS':
            flipped = 'win_to_loss'
        elif result == 'LOSS' and sim['fixed_result'] == 'WIN':
            flipped = 'loss_to_win'
        elif result == 'WIN':
            flipped = 'same_win'
        else:
            flipped = 'same_loss'

        t = TradeResult(
            symbol=row['symbol'],
            signal_time=row['signal_time'],
            timeframe=row['timeframe'],
            market_condition=row['market_condition'],
            score=int(row['score'] or 0),
            entry=entry,
            actual_result=result,
            actual_profit_pct=profit_p,
            actual_profit_usdt=float(row['profit_usdt']),
            actual_target_reached=target_r,
            actual_stop_hit=bool(row['stop_hit']),
            actual_duration_h=dur_h,
            fixed_sl=sim['fixed_sl'],
            fixed_t1=sim['fixed_t1'],
            fixed_t2=sim['fixed_t2'],
            fixed_t3=sim['fixed_t3'],
            fixed_result=sim['fixed_result'],
            fixed_profit_pct=sim['fixed_profit_pct'],
            fixed_profit_usdt=sim['fixed_profit_usdt'],
            fixed_exit_reason=sim['fixed_exit_reason'],
            fixed_target_reached=sim['fixed_target_reached'],
            fixed_stop_hit=sim['fixed_stop_hit'],
            flipped=flipped,
        )
        all_trades.append(t)

    # ═══════════════════════════════════════════════════════
    # 1. الجدول الكلي: قبل / بعد
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("1. المقارنة الكلية: القالب الحالي vs القالب الثابت")
    print("=" * 60)

    curr = compute_metrics(all_trades)
    fixd = compute_fixed_metrics(all_trades)

    print(f"\n{'المقياس':<20} {'الحالي':>12} {'الثابت':>12} {'الفرق':>12}")
    print("-" * 56)
    metrics_to_show = [
        ('n', 'n', ''),
        ('WR%', 'wr_pct', '%'),
        ('E_adj%', 'E_adj_pct', '%'),
        ('PnL ($)', 'total_pnl', '$'),
        ('PF', 'pf', ''),
        ('avg_win%', 'avg_win_pct', '%'),
        ('avg_loss%', 'avg_loss_pct', '%'),
        ('T1 hits', 'T1', ''),
        ('T2 hits', 'T2', ''),
        ('T3 hits', 'T3', ''),
        ('SL hits', 'SL', ''),
    ]
    for label, key, unit in metrics_to_show:
        c_val = curr.get(key, 'N/A')
        f_val = fixd.get(key, 'N/A')
        if isinstance(c_val, (int, float)) and isinstance(f_val, (int, float)):
            diff = f_val - c_val
            print(f"{label:<20} {c_val:>12.3g} {f_val:>12.3g} {diff:>+12.3g}")
        else:
            print(f"{label:<20} {str(c_val):>12} {str(f_val):>12} {'N/A':>12}")

    # ═══════════════════════════════════════════════════════
    # 2. Walk-Forward 60/40
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("2. Walk-Forward 60/40 (زمني)")
    print("=" * 60)

    split = int(len(all_trades) * 0.6)
    is_trades  = all_trades[:split]
    oos_trades = all_trades[split:]

    print(f"\nIS (أول 60%): n={len(is_trades)}  |  OOS (آخر 40%): n={len(oos_trades)}")
    print(f"IS  يغطي: {all_trades[0].signal_time.date()} → {all_trades[split-1].signal_time.date()}")
    print(f"OOS يغطي: {all_trades[split].signal_time.date()} → {all_trades[-1].signal_time.date()}")

    for label, subset in [('IS', is_trades), ('OOS', oos_trades)]:
        c = compute_metrics(subset)
        f = compute_fixed_metrics(subset)
        print(f"\n  [{label}] الحالي:  WR={c['wr_pct']}%  E_adj={c['E_adj_pct']}%  PF={c['pf']}  SL={c['SL']}")
        print(f"  [{label}] الثابت:  WR={f['wr_pct']}%  E_adj={f['E_adj_pct']}%  PF={f['pf']}  SL={f['SL']}")
        if c['E_adj_pct'] != 0:
            ratio = f['E_adj_pct'] / c['E_adj_pct'] if c['E_adj_pct'] != 0 else float('nan')
            direction = "تحسّن" if f['E_adj_pct'] > c['E_adj_pct'] else "تراجع"
            print(f"  [{label}] الحكم: القالب الثابت {direction} بـ Δ={f['E_adj_pct']-c['E_adj_pct']:+.4f}%")

    # ═══════════════════════════════════════════════════════
    # 3. شريحة الحافة: 1d + bearish/sideways
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("3. شريحة الحافة: 1d + bearish/sideways")
    print("=" * 60)

    edge_slice = [t for t in all_trades if t.timeframe == '1d' and t.market_condition in ('bearish', 'sideways')]
    edge_score3 = [t for t in edge_slice if t.score == 3]

    print(f"\nكل 1d b/s: n={len(edge_slice)}")
    if edge_slice:
        c = compute_metrics(edge_slice)
        f = compute_fixed_metrics(edge_slice)
        print(f"  الحالي:  WR={c['wr_pct']}%  E_adj={c['E_adj_pct']}%  PF={c['pf']}  T1={c['T1']} T2={c['T2']} T3={c['T3']} SL={c['SL']}")
        print(f"  الثابت:  WR={f['wr_pct']}%  E_adj={f['E_adj_pct']}%  PF={f['pf']}  T1={f['T1']} T2={f['T2']} T3={f['T3']} SL={f['SL']}")
        print(f"  Δ E_adj = {f['E_adj_pct'] - c['E_adj_pct']:+.4f}%")

    print(f"\n1d b/s + score=3: n={len(edge_score3)}")
    if edge_score3:
        c3 = compute_metrics(edge_score3)
        f3 = compute_fixed_metrics(edge_score3)
        print(f"  الحالي:  WR={c3['wr_pct']}%  E_adj={c3['E_adj_pct']}%  PF={c3['pf']}  SL={c3['SL']}")
        print(f"  الثابت:  WR={f3['wr_pct']}%  E_adj={f3['E_adj_pct']}%  PF={f3['pf']}  SL={f3['SL']}")
        print(f"  Δ E_adj = {f3['E_adj_pct'] - c3['E_adj_pct']:+.4f}%")

    # ═══════════════════════════════════════════════════════
    # 4. تحليل قلب النتيجة
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("4. تحليل قلب النتيجة بسبب الستوب الثابت −4%")
    print("=" * 60)

    win_to_loss = [t for t in all_trades if t.flipped == 'win_to_loss']
    loss_to_win = [t for t in all_trades if t.flipped == 'loss_to_win']
    same_win    = [t for t in all_trades if t.flipped == 'same_win']
    same_loss   = [t for t in all_trades if t.flipped == 'same_loss']

    print(f"\n  win→loss (كانت تفوز بالحالي، تخسر بالثابت): {len(win_to_loss)}")
    print(f"  loss→win (كانت تخسر بالحالي، تفوز بالثابت): {len(loss_to_win)}")
    print(f"  نفس النتيجة (WIN→WIN): {len(same_win)}")
    print(f"  نفس النتيجة (LOSS→LOSS): {len(same_loss)}")

    if win_to_loss:
        print(f"\n  تفاصيل win→loss (أول 5):")
        for t in win_to_loss[:5]:
            print(f"    {t.symbol} {t.timeframe} {t.market_condition}: "
                  f"actual={t.actual_profit_pct:.2f}%  fixed_sl={t.fixed_sl:.6f}  "
                  f"entry={t.entry:.6f}  actual_sl_dist={(t.entry - float('nan')):.3f}%")

    if loss_to_win:
        print(f"\n  تفاصيل loss→win (أول 5):")
        for t in loss_to_win[:5]:
            print(f"    {t.symbol} {t.timeframe} {t.market_condition}: "
                  f"actual={t.actual_profit_pct:.2f}%  fixed_exit={t.fixed_exit_reason}")

    # ═══════════════════════════════════════════════════════
    # 5. توزيع الخروج بالقالب الثابت
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("5. توزيع أسباب الخروج — القالب الثابت")
    print("=" * 60)
    exit_reasons = {}
    for t in all_trades:
        exit_reasons[t.fixed_exit_reason] = exit_reasons.get(t.fixed_exit_reason, 0) + 1
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        pct = count / len(all_trades) * 100
        print(f"  {reason:<20}: {count:>4} ({pct:.1f}%)")

    # ═══════════════════════════════════════════════════════
    # 6. SL الحالي vs SL الثابت
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("6. مقارنة الستوب: الحالي vs الثابت −4%")
    print("=" * 60)

    sl_distances_current = []
    for t in all_trades:
        row_match = [r for r in rows if r['symbol'] == t.symbol and float(r['entry_price']) == t.entry]
        if row_match:
            row = row_match[0]
            sl_current = float(row['stop_loss'])
            sl_dist_current = (t.entry - sl_current) / t.entry * 100
            sl_distances_current.append(sl_dist_current)

    if sl_distances_current:
        avg_sl_curr = sum(sl_distances_current) / len(sl_distances_current)
        print(f"\n  متوسط الستوب الحالي: −{avg_sl_curr:.2f}%")
        print(f"  الستوب الثابت: −{FIXED_SL_PCT:.1f}%")
        print(f"  الفرق: {FIXED_SL_PCT - avg_sl_curr:+.2f}% (موجب = الثابت أضيق)")

        # كم صفقة الستوب الحالي أوسع من 4%?
        wider = sum(1 for d in sl_distances_current if d > FIXED_SL_PCT)
        narrower = sum(1 for d in sl_distances_current if d < FIXED_SL_PCT)
        exact = len(sl_distances_current) - wider - narrower
        print(f"  الستوب الحالي أوسع من 4%: {wider} ({wider/len(sl_distances_current)*100:.1f}%)")
        print(f"  الستوب الحالي أضيق من 4%: {narrower} ({narrower/len(sl_distances_current)*100:.1f}%)")

    # ═══════════════════════════════════════════════════════
    # الملخص والتوصية
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("الملخص النهائي والتوصية")
    print("=" * 60)

    delta_total = fixd['E_adj_pct'] - curr['E_adj_pct']
    is_c = compute_metrics(is_trades)
    is_f = compute_fixed_metrics(is_trades)
    oos_c = compute_metrics(oos_trades)
    oos_f = compute_fixed_metrics(oos_trades)

    delta_is  = is_f['E_adj_pct'] - is_c['E_adj_pct']
    delta_oos = oos_f['E_adj_pct'] - oos_c['E_adj_pct']

    wl = len(win_to_loss)
    lw = len(loss_to_win)

    print(f"\n  Δ E_adj الكلي:   {delta_total:+.4f}%")
    print(f"  Δ E_adj IS:      {delta_is:+.4f}%")
    print(f"  Δ E_adj OOS:     {delta_oos:+.4f}%")
    print(f"  قلب win→loss:   {wl}")
    print(f"  قلب loss→win:   {lw}")
    print(f"  صافي تحسّن القلب: {lw - wl:+d}")

    # حكم التوصية
    conditions = {
        'E_adj_improves_total': delta_total > 0,
        'E_adj_improves_OOS': delta_oos > 0,
        'edge_slice_improves': (compute_fixed_metrics(edge_slice).get('E_adj_pct', 0) >
                                 compute_metrics(edge_slice).get('E_adj_pct', 0)) if edge_slice else False,
        'net_flip_positive': lw > wl,
        'n_sufficient': len(all_trades) >= 100,
    }

    passed = sum(conditions.values())
    print(f"\n  شروط التوصية المستوفاة: {passed}/{len(conditions)}")
    for cond, val in conditions.items():
        print(f"    {'✓' if val else '✗'} {cond}")

    if passed >= 4:
        recommendation = "نعم — يستحق التطبيق post-freeze"
        note = "تحسّن واضح ومستقر OOS ويحمي شريحة الحافة"
    elif passed >= 3:
        recommendation = "مشروط — اختبار على 50 صفقة forward أولاً"
        note = "بعض الشروط مستوفاة، لكن يحتاج تأكيداً إضافياً"
    else:
        recommendation = "لا — القالب الحالي أفضل أو مساوٍ"
        note = "التحسين غير متسق أو يضرّ شريحة الحافة"

    print(f"\n  التوصية: {recommendation}")
    print(f"  الملاحظة: {note}")

    print("\n" + "=" * 60)
    print("انتهى الباكتيستر")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
