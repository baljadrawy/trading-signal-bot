"""
الباكتيستر — الجزء 44: مقارنة سياسات الستوب
==============================================
فرضية: هل الستوب الديناميكي (break-even بعد T1 + trailing بعد T2)
يحسّن الأداء مقارنة بالستوب الثابت القديم؟

السياسات الثلاث:
  A - Fixed SL: ستوب ثابت حتى T3 أو expire (السياسة القديمة)
  B - Break-even after T1 (السياسة الحالية):
      - بعد لمس T1 → نقل الستوب إلى entry_price
      - بعد لمس T2 → trailing 2.5% تحت القمة (أرضيته T1)
  C - Partial exit at T1 + runner:
      - عند T1 → إغلاق 50% بسعر T1، الـ 50% الباقية بستوب break-even
      - بعد T2 → trailing 2.5% على الـ 50% الباقية

المنهجية:
  - 396 صفقة 1d مُعلَّمة من DB (لها نتائج فعلية)
  - جلب OHLC 1d من Binance API: عملة واحدة مرة واحدة (154 طلب فقط)
  - لكل إشارة: نُعيد محاكاة السعر شمعة-شمعة بعد وقت الإشارة
  - نحسب PnL لكل سياسة على نفس المسار السعري
  - رسوم 0.3% مُحتسبة
  - Bootstrap 90% CI لكل مقارنة
  - Walk-Forward 5 نوافذ

القيود:
  - لا حزم جديدة: numpy, pandas فقط
  - لا look-ahead: الشموع بعد signal_time فقط
  - rate limit آمن: 0.15s بين الطلبات
"""

import asyncio
import asyncpg
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.append('/app')
from binance import AsyncClient
from shared.config import config

# ──────────────────────────────────────────────────────────────────────
# إعدادات
# ──────────────────────────────────────────────────────────────────────
DB_HOST  = 'postgres'
DB_PORT  = 5432
DB_NAME  = 'trading_signals'
DB_USER  = 'trading_signal_bot'
DB_PASS  = '6psgaD1GV2ClGtopvSe5Lm8za'

FEE_ROUND    = 0.003   # 0.3% round-trip
TRAIL_PCT    = 0.025   # 2.5% trailing stop distance
EXPIRE_BARS  = 30      # max bars to hold (~1 month for 1d)
API_DELAY_S  = 0.15    # rate limit safety
MIN_N_WF     = 10      # minimum n per WF window
CANDLES_BACK = 3       # days before signal to start fetching (for context)
CANDLES_FWRD = 35      # days forward to fetch


# ──────────────────────────────────────────────────────────────────────
# 1. تحميل الإشارات من DB
# ──────────────────────────────────────────────────────────────────────

async def load_signals() -> List[Dict]:
    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS
    )
    rows = await conn.fetch('''
        SELECT s.id, s.symbol, s.timeframe, s.market_condition, s.score,
               s.entry_price::float  AS entry_price,
               s.target_1::float     AS target_1,
               s.target_2::float     AS target_2,
               s.target_3::float     AS target_3,
               s.stop_loss::float    AS stop_loss,
               s.signal_time,
               tr.result, tr.profit_percent::float AS profit_pct,
               tr.target_reached, tr.stop_hit
        FROM signals s
        JOIN trade_results tr ON tr.signal_id = s.id
        WHERE s.timeframe = '1d'
        AND s.signal_time >= NOW() - INTERVAL '90 days'
        ORDER BY s.signal_time
    ''')
    await conn.close()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────
# 2. جلب OHLC من Binance (رمز واحد، السلسلة الكاملة)
# ──────────────────────────────────────────────────────────────────────

async def fetch_ohlc(client: AsyncClient, symbol: str,
                     start_time: datetime, end_time: datetime) -> pd.DataFrame:
    """يجلب شموع 1d من start_time حتى end_time."""
    start_ms = int(start_time.timestamp() * 1000)
    end_ms   = int(end_time.timestamp() * 1000)

    try:
        klines = await client.get_historical_klines(
            symbol, '1d',
            start_str=str(start_ms),
            end_str=str(end_ms),
            limit=CANDLES_FWRD + CANDLES_BACK + 5
        )
    except Exception as e:
        print(f"  خطأ API لـ {symbol}: {e}")
        return pd.DataFrame()

    if not klines:
        return pd.DataFrame()

    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df.set_index('open_time', inplace=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df


# ──────────────────────────────────────────────────────────────────────
# 3. محاكاة السياسات الثلاث
# ──────────────────────────────────────────────────────────────────────

def run_policy_a(future: pd.DataFrame, entry, t1, t2, t3, sl) -> float:
    """Fixed SL — ستوب ثابت حتى T3 أو expire."""
    for _, bar in future.iterrows():
        low  = float(bar['low'])
        high = float(bar['high'])

        if low <= sl:
            return (sl - entry) / entry - FEE_ROUND

        if high >= t3:
            return (t3 - entry) / entry - FEE_ROUND

    last_close = float(future.iloc[-1]['close'])
    return (last_close - entry) / entry - FEE_ROUND


def run_policy_b(future: pd.DataFrame, entry, t1, t2, t3, sl) -> float:
    """Break-even after T1, trailing 2.5% after T2 (السياسة الحالية)."""
    current_sl = sl
    hit_t1 = False
    hit_t2 = False
    peak   = entry

    for _, bar in future.iterrows():
        low  = float(bar['low'])
        high = float(bar['high'])

        if low <= current_sl:
            return (current_sl - entry) / entry - FEE_ROUND

        if high >= t3:
            return (t3 - entry) / entry - FEE_ROUND

        if not hit_t1 and high >= t1:
            hit_t1 = True
            current_sl = entry

        if not hit_t2 and high >= t2:
            hit_t2 = True

        if hit_t2:
            peak = max(peak, high)
            trail_sl = peak * (1.0 - TRAIL_PCT)
            trail_sl = max(trail_sl, t1)
            current_sl = max(current_sl, trail_sl)

    last_close = float(future.iloc[-1]['close'])
    if last_close < current_sl:
        return (current_sl - entry) / entry - FEE_ROUND
    return (last_close - entry) / entry - FEE_ROUND


def run_policy_c(future: pd.DataFrame, entry, t1, t2, t3, sl) -> float:
    """Partial exit 50% at T1 + runner with trailing."""
    current_sl = sl
    hit_t1   = False
    hit_t2   = False
    peak     = entry
    t1_pnl   = 0.0

    for _, bar in future.iterrows():
        low  = float(bar['low'])
        high = float(bar['high'])

        if low <= current_sl:
            runner_pnl = (current_sl - entry) / entry
            if not hit_t1:
                return runner_pnl - FEE_ROUND
            else:
                return (t1_pnl * 0.5 + runner_pnl * 0.5) - FEE_ROUND

        if high >= t3:
            full_pnl = (t3 - entry) / entry
            if not hit_t1:
                return full_pnl - FEE_ROUND
            else:
                return (t1_pnl * 0.5 + full_pnl * 0.5) - FEE_ROUND

        if not hit_t1 and high >= t1:
            hit_t1   = True
            t1_pnl   = (t1 - entry) / entry
            current_sl = entry

        if not hit_t2 and high >= t2:
            hit_t2 = True

        if hit_t2:
            peak = max(peak, high)
            trail_sl = peak * (1.0 - TRAIL_PCT)
            trail_sl = max(trail_sl, t1)
            current_sl = max(current_sl, trail_sl)

    last_close = float(future.iloc[-1]['close'])
    exit_px = last_close if last_close >= current_sl else current_sl
    runner_pnl = (exit_px - entry) / entry
    if not hit_t1:
        return runner_pnl - FEE_ROUND
    else:
        return (t1_pnl * 0.5 + runner_pnl * 0.5) - FEE_ROUND


def simulate_all_policies(sig: Dict, symbol_ohlc: pd.DataFrame) -> Optional[Dict]:
    """يُشغّل السياسات الثلاث على شموع الرمز بعد وقت الإشارة."""
    entry = sig['entry_price']
    t1    = sig['target_1']
    t2    = sig['target_2']
    t3    = sig['target_3']
    sl    = sig['stop_loss']

    if not all([entry, t1, t2, t3, sl]):
        return None
    if entry <= 0 or sl >= entry or t1 <= entry:
        return None
    if t1 / entry > 2.5 or sl / entry < 0.6:
        return None

    sig_time = sig['signal_time']
    if isinstance(sig_time, datetime) and sig_time.tzinfo is None:
        sig_time = sig_time.replace(tzinfo=timezone.utc)
    if not isinstance(sig_time, datetime):
        sig_time = datetime.fromtimestamp(sig_time.timestamp(), tz=timezone.utc)

    future = symbol_ohlc[symbol_ohlc.index > sig_time].head(EXPIRE_BARS)
    if len(future) < 3:
        return None

    return {
        'pnl_a': run_policy_a(future, entry, t1, t2, t3, sl),
        'pnl_b': run_policy_b(future, entry, t1, t2, t3, sl),
        'pnl_c': run_policy_c(future, entry, t1, t2, t3, sl),
        'signal_time': sig_time,
        'score': sig['score'],
        'market_condition': sig['market_condition'],
        'actual_result': sig['result'],
        'actual_pnl': sig['profit_pct'],
    }


# ──────────────────────────────────────────────────────────────────────
# 4. إحصائيات وBootstrap
# ──────────────────────────────────────────────────────────────────────

def compute_stats(pnl_list: List[float]) -> Dict:
    if not pnl_list:
        return {'n': 0, 'wr': 0, 'expectancy': 0, 'avg_win': 0, 'avg_loss': 0, 'total_pnl': 0}
    n   = len(pnl_list)
    wr  = sum(1 for p in pnl_list if p > 0) / n
    avg = sum(pnl_list) / n
    wins   = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    return {
        'n': n,
        'wr': round(wr, 4),
        'expectancy': round(avg, 4),
        'avg_win':  round(sum(wins) / len(wins)     if wins   else 0, 4),
        'avg_loss': round(sum(losses) / len(losses)  if losses else 0, 4),
        'total_pnl': round(sum(pnl_list), 4),
    }


def bootstrap_ci(pnl_ref: List[float], pnl_new: List[float],
                  n_boot=2000, seed=42) -> Dict:
    """Bootstrap CI للفرق (new - ref) في Expectancy."""
    rng   = np.random.default_rng(seed)
    n     = min(len(pnl_ref), len(pnl_new))
    arr_r = np.array(pnl_ref[:n])
    arr_n = np.array(pnl_new[:n])
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        diffs.append(arr_n[idx].mean() - arr_r[idx].mean())
    diffs = np.array(diffs)
    return {
        'mean_diff': round(float(diffs.mean()), 4),
        'ci_lo': round(float(np.percentile(diffs, 5)),  4),
        'ci_hi': round(float(np.percentile(diffs, 95)), 4),
        'p_new_worse': round(float((diffs <= 0).mean()), 4),
    }


def walk_forward(sim_results: List[Dict], n_windows=5) -> List[Dict]:
    n = len(sim_results)
    ws = n // n_windows
    out = []
    for w in range(n_windows):
        s = w * ws
        e = s + ws if w < n_windows - 1 else n
        chunk = sim_results[s:e]
        if len(chunk) < MIN_N_WF:
            continue
        out.append({
            'window': w + 1,
            'start': str(chunk[0]['signal_time'])[:10],
            'end':   str(chunk[-1]['signal_time'])[:10],
            'n': len(chunk),
            'A': compute_stats([r['pnl_a'] for r in chunk]),
            'B': compute_stats([r['pnl_b'] for r in chunk]),
            'C': compute_stats([r['pnl_c'] for r in chunk]),
        })
    return out


# ──────────────────────────────────────────────────────────────────────
# 5. الدالة الرئيسية
# ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 68)
    print("Part 44 — Stop Policy Backtest: Fixed (A) vs Dynamic (B) vs Partial (C)")
    print("=" * 68)

    # 1. تحميل الإشارات
    print("\n[1] تحميل الإشارات من DB...")
    signals = await load_signals()
    print(f"    {len(signals)} إشارة 1d مُعلَّمة")

    # 2. تجميع حدود التاريخ لكل رمز
    sym_ranges: Dict[str, Tuple[datetime, datetime]] = {}
    for sig in signals:
        sym = sig['symbol']
        t   = sig['signal_time']
        if isinstance(t, datetime) and t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if sym not in sym_ranges:
            sym_ranges[sym] = (t, t)
        lo, hi = sym_ranges[sym]
        sym_ranges[sym] = (min(lo, t), max(hi, t))

    # 3. جلب OHLC من Binance
    print(f"[2] جلب OHLC 1d من Binance لـ {len(sym_ranges)} رمز...")
    client = await AsyncClient.create(config.BINANCE_API_KEY, config.BINANCE_API_SECRET)
    sym_ohlc: Dict[str, pd.DataFrame] = {}

    for i, (sym, (lo, hi)) in enumerate(sym_ranges.items(), 1):
        start = lo - timedelta(days=CANDLES_BACK)
        end   = hi + timedelta(days=CANDLES_FWRD + 2)
        df = await fetch_ohlc(client, sym, start, end)
        if not df.empty:
            sym_ohlc[sym] = df
        if i % 20 == 0:
            print(f"    {i}/{len(sym_ranges)} رموز محملة...")
        await asyncio.sleep(API_DELAY_S)

    await client.close_connection()
    print(f"    {len(sym_ohlc)} رمز تم جلب بياناته بنجاح")

    # 4. محاكاة السياسات
    print("[3] محاكاة السياسات الثلاث...")
    sim_results = []
    no_ohlc = 0
    invalid = 0

    for sig in signals:
        sym = sig['symbol']
        if sym not in sym_ohlc:
            no_ohlc += 1
            continue
        result = simulate_all_policies(sig, sym_ohlc[sym])
        if result is None:
            invalid += 1
            continue
        sim_results.append(result)

    print(f"    ناجح: {len(sim_results)} | بدون OHLC: {no_ohlc} | بيانات غير صالحة: {invalid}")

    if len(sim_results) < 20:
        print("    خطأ: عينة صغيرة جداً — توقف.")
        return

    # 5. استخراج قوائم PnL
    pnl_a = [r['pnl_a'] for r in sim_results]
    pnl_b = [r['pnl_b'] for r in sim_results]
    pnl_c = [r['pnl_c'] for r in sim_results]

    sa = compute_stats(pnl_a)
    sb = compute_stats(pnl_b)
    sc = compute_stats(pnl_c)

    # ── إحصائيات كلية ──────────────────────────────────────────────
    print("\n" + "=" * 68)
    print(f"النتائج الكلية (n={len(sim_results)})")
    print("=" * 68)

    print(f"\n{'Policy':<8} {'n':>5} {'WR%':>7} {'E_adj%':>8} {'AvgWin%':>9} {'AvgLoss%':>10} {'TotalPnL%':>11}")
    print("-" * 65)
    for name, st in [('A-Fixed', sa), ('B-Dynamic', sb), ('C-Partial', sc)]:
        print(f"{name:<8} {st['n']:>5} {st['wr']*100:>6.1f}%  {st['expectancy']*100:>7.3f}%  "
              f"{st['avg_win']*100:>8.3f}%  {st['avg_loss']*100:>9.3f}%  {st['total_pnl']*100:>10.2f}%")

    # ── Bootstrap CI ────────────────────────────────────────────────
    print("\n── Bootstrap 90% CI ──────────────────────────────────────")
    ci_ba = bootstrap_ci(pnl_a, pnl_b)
    print(f"  B vs A: ΔE={ci_ba['mean_diff']*100:+.3f}%  CI=[{ci_ba['ci_lo']*100:+.3f}%, {ci_ba['ci_hi']*100:+.3f}%]")
    verdict_b = "B أفضل (90%)" if ci_ba['p_new_worse'] < 0.10 and ci_ba['mean_diff'] > 0 else \
                "A أفضل (90%)" if ci_ba['p_new_worse'] > 0.90 and ci_ba['mean_diff'] < 0 else \
                "غير معنوي"
    print(f"  P(B<=A)={ci_ba['p_new_worse']:.3f} → {verdict_b}")

    ci_ca = bootstrap_ci(pnl_a, pnl_c)
    print(f"  C vs A: ΔE={ci_ca['mean_diff']*100:+.3f}%  CI=[{ci_ca['ci_lo']*100:+.3f}%, {ci_ca['ci_hi']*100:+.3f}%]")
    verdict_c = "C أفضل (90%)" if ci_ca['p_new_worse'] < 0.10 and ci_ca['mean_diff'] > 0 else \
                "A أفضل (90%)" if ci_ca['p_new_worse'] > 0.90 and ci_ca['mean_diff'] < 0 else \
                "غير معنوي"
    print(f"  P(C<=A)={ci_ca['p_new_worse']:.3f} → {verdict_c}")

    # ── Walk-Forward ────────────────────────────────────────────────
    print("\n── Walk-Forward (5 نوافذ زمنية) ───────────────────────────")
    wf = walk_forward(sim_results, n_windows=5)
    print(f"{'Win':>3} {'من':>10} {'حتى':>10} {'n':>4}  "
          f"{'A_E%':>7}  {'B_E%':>7}  {'C_E%':>7}  "
          f"{'A_WR%':>6}  {'B_WR%':>6}  {'C_WR%':>6}")
    print("-" * 72)
    for w in wf:
        def e(s): return s['expectancy']*100
        def wr(s): return s['wr']*100
        print(f"{w['window']:>3} {w['start']:>10} {w['end']:>10} {w['n']:>4}  "
              f"{e(w['A']):>+7.3f}%  {e(w['B']):>+7.3f}%  {e(w['C']):>+7.3f}%  "
              f"{wr(w['A']):>5.1f}%  {wr(w['B']):>5.1f}%  {wr(w['C']):>5.1f}%")

    # ── تحليل break-even exits ─────────────────────────────────────
    be_exits_b = sum(1 for r in sim_results
                     if abs(r['pnl_b']) < FEE_ROUND * 1.5)
    b_better   = sum(1 for r in sim_results if r['pnl_b'] > r['pnl_a'])
    b_worse    = sum(1 for r in sim_results if r['pnl_b'] < r['pnl_a'])
    n = len(sim_results)
    print(f"\n── توزيع B vs A ─────────────────────────────────────────")
    print(f"  B أفضل من A:  {b_better}/{n} ({b_better/n*100:.1f}%)")
    print(f"  B أسوأ من A:  {b_worse}/{n} ({b_worse/n*100:.1f}%)")
    print(f"  مخرجات break-even في B: {be_exits_b}")

    # ── WR المقارن بالفعلي ─────────────────────────────────────────
    actual_wins = sum(1 for r in sim_results if r['actual_result'] == 'WIN')
    print(f"\n── مقارنة بالنتائج الفعلية ─────────────────────────────")
    print(f"  WR فعلي:     {actual_wins/n*100:.1f}%  ({actual_wins}/{n})")
    print(f"  WR محاكاة A: {sa['wr']*100:.1f}%  (fixed SL)")
    print(f"  WR محاكاة B: {sb['wr']*100:.1f}%  (dynamic)")
    print(f"  WR محاكاة C: {sc['wr']*100:.1f}%  (partial)")

    # ── الخلاصة ──────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print("الخلاصة والتوصية:")
    best = max([('A-Fixed', sa), ('B-Dynamic', sb), ('C-Partial', sc)],
               key=lambda x: x[1]['expectancy'])
    print(f"  أفضل Expectancy: {best[0]}  E={best[1]['expectancy']*100:+.3f}%/trade")

    b_delta = (sb['expectancy'] - sa['expectancy']) * 100
    c_delta = (sc['expectancy'] - sa['expectancy']) * 100
    print(f"  ΔE (B-A) = {b_delta:+.3f}%/trade  [{verdict_b}]")
    print(f"  ΔE (C-A) = {c_delta:+.3f}%/trade  [{verdict_c}]")

    print()
    if verdict_b == "B أفضل (90%)" and b_delta > 0:
        print("  VERDICT: الستوب الديناميكي (B) أفضل إحصائياً — أبقِه.")
    elif verdict_b == "A أفضل (90%)" and b_delta < 0:
        print("  VERDICT: الستوب الثابت (A) أفضل — يُوصى بالتحويل إليه.")
    else:
        print("  VERDICT: لا يوجد فرق معنوي — لا تغيير مبرر بهذه البيانات.")

    if verdict_c == "C أفضل (90%)" and c_delta > b_delta:
        print("  BONUS: الخروج الجزئي (C) يُضيف قيمة — يستحق التجربة.")

    print("=" * 68)


if __name__ == '__main__':
    asyncio.run(main())
