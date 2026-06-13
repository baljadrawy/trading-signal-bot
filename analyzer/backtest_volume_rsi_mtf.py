"""
الباكتيستر — استراتيجية الكميات + RSI متعددة الأطر (Volume/RSI EMA MTF)
========================================================================
طلب المستخدم (اختبار، الإنتاج مجمّد — لا يُطبَّق شيء):

  الشرط (1) بداية الإيجابية — 15m:
    إغلاق يخترق EMA-23 صعوداً + RSI(14) > 55 + كمية الشمعة > EMA-23(كمية)
    → نقطة الدخول (الدخول عند الشرط 1 فقط)

  الشرط (2) الاستمرارية — يومي:
    إغلاق فوق EMA-28 + RSI(14) يومي > 55 + كمية > EMA-28(كمية)
    → لا يُستخدم للدخول؛ يُرصد أثناء الصفقة لتقسيم النتائج (ادعاء: غالباً +5–8%)

  الخروج = عكس ما سبق (إشارة عكسية فقط، بلا ستوب ثابت):
    إغلاق 15m يكسر EMA-23 نزولاً + RSI < 55

النطاق: أكبر ~30 عملة USDT سيولةً × آخر 12 شهراً. رسوم 0.3% ذهاب وإياب.
صفقة واحدة لكل رمز في كل وقت. تنفيذ بسعر إغلاق شمعة الإشارة.

قيود: numpy/pandas فقط، معالجة متدفّقة، cache pickle لكل (رمز,إطار)، لا مساس بالإنتاج.
المخرج: backtest_results_volume_rsi_mtf.jsonl + ملخص طباعي عربي.
"""

import asyncio
import json
import os
import pickle
import sys
from datetime import datetime, timezone

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

import numpy as np
import pandas as pd
from binance import AsyncClient

# ─────────────────────────── إعدادات قابلة للضبط ───────────────────────────
TOP_N            = int(os.getenv('BT_TOP_N', '30'))
MONTHS           = int(os.getenv('BT_MONTHS', '12'))
EMA_FAST_15M     = int(os.getenv('BT_EMA_15M', '23'))
EMA_DAILY        = int(os.getenv('BT_EMA_1D', '28'))
RSI_PERIOD       = int(os.getenv('BT_RSI_PERIOD', '14'))
RSI_THRESH       = float(os.getenv('BT_RSI_THRESH', '55'))
FEE_PCT          = float(os.getenv('BT_FEE', '0.003'))   # ذهاب+إياب
# فلتر الكمية: 1=كمية>EMA(كمية) (الافتراضي، يكرّم "شمعة كميات") | 0=بلا فلتر كمية
USE_VOLUME_FILTER = os.getenv('BT_VOL_FILTER', '1') == '1'
# إطار الخروج: '15m'=انعكاس 15m (سريع) | '1d'=انعكاس يومي (يركب الترند، "تتابع سهمك")
EXIT_TF = os.getenv('BT_EXIT_TF', '15m')
N_BOOTSTRAP      = int(os.getenv('BT_BOOTSTRAP', '2000'))
API_DELAY_S      = 0.15

CACHE_DIR   = '/app/bt_cache_vrsi'
OUTPUT_FILE = '/app/backtest_results_volume_rsi_mtf.jsonl'
SUMMARY_FILE = '/app/backtest_summary_volume_rsi_mtf.json'

STABLE = {'USDC', 'FDUSD', 'TUSD', 'BUSD', 'DAI', 'USDP', 'EUR', 'GBP', 'AEUR', 'USD1'}


def log(msg):
    print(msg, flush=True)


# ─────────────────────────── اختيار الرموز ───────────────────────────
async def select_top_symbols(client, n):
    tickers = await client.get_ticker()
    rows = []
    for t in tickers:
        s = t['symbol']
        if not s.endswith('USDT'):
            continue
        base = s[:-4]
        if base in STABLE:
            continue
        if any(x in base for x in ('UP', 'DOWN', 'BULL', 'BEAR')):
            continue
        try:
            qv = float(t['quoteVolume'])
        except (KeyError, ValueError):
            continue
        rows.append((s, qv))
    rows.sort(key=lambda r: r[1], reverse=True)
    return [s for s, _ in rows[:n]]


# ─────────────────────────── جلب OHLC مع cache ───────────────────────────
async def fetch_klines(client, symbol, interval, start_str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{MONTHS}m.pkl")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass
    try:
        klines = await client.get_historical_klines(symbol, interval, start_str)
    except Exception as e:
        log(f"❌ جلب {symbol} {interval}: {e}")
        return None
    if not klines:
        return None
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'qav', 'trades', 'tbav', 'tbqv', 'ignore'])
    df = df[['open_time', 'open', 'high', 'low', 'close', 'volume']].copy()
    for c in ('open', 'high', 'low', 'close', 'volume'):
        df[c] = df[c].astype(float)
    df['dt'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    with open(cache_path, 'wb') as f:
        pickle.dump(df, f)
    await asyncio.sleep(API_DELAY_S)
    return df


# ─────────────────────────── المؤشرات ───────────────────────────
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100)  # لا خسائر = RSI مرتفع


def prepare(df, ema_span):
    df = df.reset_index(drop=True)
    df['ema_price'] = ema(df['close'], ema_span)
    df['ema_vol'] = ema(df['volume'], ema_span)
    df['rsi'] = rsi(df['close'], RSI_PERIOD)
    return df


def daily_condition_mask(d):
    cond = (d['close'] > d['ema_price']) & (d['rsi'] > RSI_THRESH)
    if USE_VOLUME_FILTER:
        cond = cond & (d['volume'] > d['ema_vol'])
    return cond


# ─────────────────────────── محاكاة رمز واحد ───────────────────────────
def simulate(symbol, df15, dfd):
    """يولّد الصفقات من 15m مع وسم تحقق الشرط اليومي أثناء كل صفقة."""
    df15 = prepare(df15, EMA_FAST_15M)
    dfd = prepare(dfd, EMA_DAILY)
    dfd['day_cond'] = daily_condition_mask(dfd)
    # انعكاس يومي: إغلاق يومي < EMA28 + RSI يومي < العتبة
    dfd['day_rev'] = (dfd['close'] < dfd['ema_price']) & (dfd['rsi'] < RSI_THRESH)

    c = df15['close'].values
    e = df15['ema_price'].values
    v = df15['volume'].values
    ve = df15['ema_vol'].values
    r = df15['rsi'].values
    dt = df15['dt'].values
    n = len(df15)

    # شروط الدخول/الخروج (متجهة)
    cross_up = np.zeros(n, dtype=bool)
    cross_dn = np.zeros(n, dtype=bool)
    cross_up[1:] = (c[1:] > e[1:]) & (c[:-1] <= e[:-1])
    cross_dn[1:] = (c[1:] < e[1:]) & (c[:-1] >= e[:-1])
    entry_sig = cross_up & (r > RSI_THRESH)
    if USE_VOLUME_FILTER:
        entry_sig = entry_sig & (v > ve)
    exit_sig = cross_dn & (r < RSI_THRESH)

    # خريطة يومية للبحث السريع
    d_times = dfd['dt'].values                       # open_time للشمعة اليومية
    d_cond = dfd['day_cond'].values
    d_rev = dfd['day_rev'].values
    one_day = np.timedelta64(1, 'D')
    d_close_times = d_times + one_day                # وقت إغلاق الشمعة اليومية
    # لكل شمعة 15m: فهرس آخر شمعة يومية *مغلقة*
    closed_didx = np.searchsorted(d_close_times, dt, side='right') - 1

    trades = []
    i = max(EMA_FAST_15M, RSI_PERIOD) + 1
    in_pos = False
    entry_px = entry_t = entry_idx = None
    while i < n:
        if not in_pos:
            if entry_sig[i]:
                in_pos = True
                entry_px = c[i]
                entry_t = dt[i]
                entry_idx = i
        else:
            # تحديد إشارة الخروج حسب الإطار المختار
            if EXIT_TF == '1d':
                cdi = closed_didx[i]
                hit_exit = (cdi >= 0 and d_rev[cdi]
                            and d_close_times[cdi] > entry_t)
            else:
                hit_exit = exit_sig[i]
            if hit_exit or i == n - 1:
                exit_px = c[i]
                exit_t = dt[i]
                gross = exit_px / entry_px - 1.0
                net = gross - FEE_PCT
                # (أ) قابل للتداول: الشرط اليومي على آخر شمعة يومية *مغلقة* قبل الدخول
                pos = np.searchsorted(d_times, entry_t - one_day, side='right') - 1
                day_at_entry = bool(d_cond[pos]) if pos >= 0 else False
                # (ب) وصفي فقط (ملوَّث بنظر مستقبلي): تحقق الشرط أثناء الاحتفاظ
                mask = (d_times >= entry_t) & (d_times <= exit_t)
                day_met = bool(d_cond[mask].any()) if mask.any() else False
                hold_bars = i - entry_idx
                trades.append({
                    'symbol': symbol,
                    'entry_time': pd.Timestamp(entry_t).isoformat(),
                    'exit_time': pd.Timestamp(exit_t).isoformat(),
                    'entry_px': round(float(entry_px), 8),
                    'exit_px': round(float(exit_px), 8),
                    'gross_pct': round(gross * 100, 4),
                    'net_pct': round(net * 100, 4),
                    'hold_bars_15m': int(hold_bars),
                    'hold_hours': round(hold_bars * 0.25, 2),
                    'daily_cond_at_entry': day_at_entry,
                    'daily_cond_met': day_met,
                    'closed_by': ('end_of_data' if i == n - 1 else
                                  ('daily_reverse' if EXIT_TF == '1d' else 'reverse_15m')),
                })
                in_pos = False
        i += 1
    return trades


# ─────────────────────────── تجميع وإحصاء ───────────────────────────
def bootstrap_ci(vals, n_boot, seed=12345):
    if len(vals) < 3:
        return (None, None)
    rng = np.random.default_rng(seed)
    arr = np.asarray(vals, dtype=float)
    means = np.array([rng.choice(arr, size=len(arr), replace=True).mean()
                      for _ in range(n_boot)])
    return (round(float(np.percentile(means, 2.5)), 4),
            round(float(np.percentile(means, 97.5)), 4))


def aggregate(trades, label):
    if not trades:
        return {'label': label, 'n': 0}
    nets = np.array([t['net_pct'] for t in trades])
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    ci_lo, ci_hi = bootstrap_ci(nets, N_BOOTSTRAP)
    # عائد مركّب (حصة متساوية متتابعة لكل صفقة — تقريبي)
    comp = float(np.prod(1 + nets / 100) - 1) * 100
    return {
        'label': label,
        'n': len(trades),
        'win_rate_pct': round(float((nets > 0).mean() * 100), 2),
        'avg_win_pct': round(float(wins.mean()), 3) if len(wins) else 0.0,
        'avg_loss_pct': round(float(losses.mean()), 3) if len(losses) else 0.0,
        'profit_factor': round(pf, 3) if pf != float('inf') else None,
        'E_net_per_trade_pct': round(float(nets.mean()), 4),
        'E_ci95': [ci_lo, ci_hi],
        'median_net_pct': round(float(np.median(nets)), 4),
        'compounded_return_pct': round(comp, 2),
        'avg_hold_hours': round(float(np.mean([t['hold_hours'] for t in trades])), 2),
        'best_pct': round(float(nets.max()), 3),
        'worst_pct': round(float(nets.min()), 3),
    }


def print_block(title, agg):
    log(f"\n  ── {title} ──")
    if agg.get('n', 0) == 0:
        log("     (لا صفقات)")
        return
    log(f"     n={agg['n']} | WR={agg['win_rate_pct']}% | "
        f"E_net={agg['E_net_per_trade_pct']}% (CI95 {agg['E_ci95']})")
    log(f"     PF={agg['profit_factor']} | متوسط ربح={agg['avg_win_pct']}% | "
        f"متوسط خسارة={agg['avg_loss_pct']}%")
    log(f"     عائد مركّب≈{agg['compounded_return_pct']}% | "
        f"متوسط احتفاظ={agg['avg_hold_hours']}h | "
        f"أفضل={agg['best_pct']}% أسوأ={agg['worst_pct']}%")


# ─────────────────────────── main ───────────────────────────
async def main():
    start_str = f"{MONTHS * 30 + 5} days ago UTC"
    log("═" * 70)
    log("باكتيست: استراتيجية الكميات + RSI متعددة الأطر")
    log(f"إعدادات: TOP_N={TOP_N} | أشهر={MONTHS} | EMA15={EMA_FAST_15M} "
        f"EMA1d={EMA_DAILY} | RSI({RSI_PERIOD})>{RSI_THRESH} | "
        f"رسوم={FEE_PCT*100}% | فلتر الكمية={'نعم' if USE_VOLUME_FILTER else 'لا'}")
    log("═" * 70)

    client = await AsyncClient.create()
    try:
        symbols = await select_top_symbols(client, TOP_N)
        log(f"الرموز ({len(symbols)}): {', '.join(symbols)}\n")

        all_trades = []
        for idx, sym in enumerate(symbols, 1):
            df15 = await fetch_klines(client, sym, '15m', start_str)
            dfd = await fetch_klines(client, sym, '1d', start_str)
            if df15 is None or dfd is None or len(df15) < 200 or len(dfd) < 40:
                log(f"[{idx}/{len(symbols)}] {sym}: بيانات غير كافية — تخطٍّ")
                continue
            trades = simulate(sym, df15, dfd)
            all_trades.extend(trades)
            log(f"[{idx}/{len(symbols)}] {sym}: {len(trades)} صفقة "
                f"(15m={len(df15)} شمعة, يومي={len(dfd)})")
    finally:
        await client.close_connection()

    # كتابة الصفقات
    with open(OUTPUT_FILE, 'w') as f:
        for t in all_trades:
            f.write(json.dumps(t, ensure_ascii=False) + '\n')

    # تجميع
    overall = aggregate(all_trades, 'الإجمالي')
    # (أ) الفلتر القابل للتداول: الشرط اليومي محقّق عند الدخول
    entry_yes = aggregate([t for t in all_trades if t['daily_cond_at_entry']],
                          'الشرط اليومي محقّق عند الدخول (قابل للتداول)')
    entry_no = aggregate([t for t in all_trades if not t['daily_cond_at_entry']],
                         'الشرط اليومي غير محقّق عند الدخول')
    # (ب) وصفي فقط — ملوَّث بنظر مستقبلي
    with_daily = aggregate([t for t in all_trades if t['daily_cond_met']],
                           'تحقق الشرط اليومي أثناء الاحتفاظ [وصفي/ملوَّث]')
    without_daily = aggregate([t for t in all_trades if not t['daily_cond_met']],
                              'لم يتحقق أثناء الاحتفاظ [وصفي/ملوَّث]')

    log("\n" + "═" * 70)
    log(f"النتائج — إجمالي {overall.get('n', 0)} صفقة عبر {len(symbols)} رمزاً")
    log("═" * 70)
    print_block("الإجمالي (كل دخول بالشرط 1)", overall)
    log("\n  ▼ الفلتر القابل للتداول (يُقرّر عند الدخول) — هذا هو الاختبار الحقيقي للشرط 2:")
    print_block("الشرط اليومي محقّق عند الدخول", entry_yes)
    print_block("الشرط اليومي غير محقّق عند الدخول", entry_no)
    log("\n  ▼ وصفي فقط — مُلوَّث بنظر مستقبلي (لا يُتداوَل عليه؛ الفوز يسبق تحقق الشرط):")
    print_block("تحقق أثناء الاحتفاظ", with_daily)
    print_block("لم يتحقق أثناء الاحتفاظ", without_daily)

    summary = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'config': {
            'top_n': TOP_N, 'months': MONTHS, 'ema_15m': EMA_FAST_15M,
            'ema_1d': EMA_DAILY, 'rsi_period': RSI_PERIOD,
            'rsi_thresh': RSI_THRESH, 'fee_pct': FEE_PCT,
            'volume_filter': USE_VOLUME_FILTER,
        },
        'symbols': symbols,
        'overall': overall,
        'daily_cond_at_entry_yes': entry_yes,
        'daily_cond_at_entry_no': entry_no,
        'with_daily_cond_during_hold_CONTAMINATED': with_daily,
        'without_daily_cond_during_hold_CONTAMINATED': without_daily,
    }
    with open(SUMMARY_FILE, 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log(f"\n💾 الصفقات: {OUTPUT_FILE}")
    log(f"💾 الملخص: {SUMMARY_FILE}")
    log("\n⚖️  مرجع للمقارنة (baseline الحالي): WR≈37.5% / E_net≈-0.73% بعد الرسوم")


if __name__ == '__main__':
    asyncio.run(main())
