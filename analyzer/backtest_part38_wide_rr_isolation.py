"""
الباكتيستر — الجزء 38: Wide R:R Isolation (المسار B)
=====================================================
هدف التجربة: هل الأهداف الضيقة (T1≈1.2R, T2≈2.5R, T3≈3.9R) هي المشكلة؟

المنهج:
  - نفس الحافة المثبتة: 1d + bearish/sideways + score>=3
  - OHLC: 1h candles لنافذة 48h بعد كل إشارة (SL-first عند تصادم)
  - إعادة محاكاة الـ baseline بنفس الكود (لا مقارنة بـ live profit_percent)
  - ثلاث variants تختلف فقط في T1/T2/T3 multipliers:
      Baseline: T1=entry + R×current_k1,  T2= current_k2×R, T3=current_k3×R
                (يُحسب فعلياً من s.target_1 ..target_3 في DB)
      Variant A: T1=entry+2R,  T2=entry+4R,  T3=entry+6R
      Variant B: T1=entry+3R,  T2=entry+5R,  T3=entry+8R
  - TripleBarrier موحّد: break-even بعد T1 + trailing 2.5% بعد T2 + expiry 48h
  - SL-first: عند (high>=T AND low<=SL) في نفس الشمعة → نُفعّل SL
  - Walk-Forward: 5 نوافذ، 60% train / 40% OOS (على timeline الإشارة)
  - Bootstrap CI: 10,000 iteration على E_adj
  - E_adj = profit_pct - 0.3% fees

قيود:
  - لا حزم جديدة (numpy/pandas/asyncpg/binance/pickle فقط)
  - معالجة متدفّقة — لا تجميع في الذاكرة
  - لا حذف من DB
  - Pickle cache لتجنب طلبات API مكررة
  - حد ذاكرة آمن لـ aarch64/3.7GB RAM

تحذيرات إحصائية:
  - n≈291 pre-freeze مناسب للمحاكاة
  - post-freeze n=12 — يُورَد كـ directional check فقط، ليس قرار
  - عدم تطابق CI مع baseline: 50 صفقة OOS مطلوبة قبل التطبيق الحيّ

المخرج: backtest_results_part38.jsonl + ملخص طباعي
"""

import asyncio
import json
import math
import pickle
import random
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

import numpy as np
import pandas as pd
from binance import AsyncClient
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('backtester.part38')

OUTPUT_FILE = '/app/backtest_results_part38.jsonl'
CACHE_FILE  = '/app/part38_1h_cache.pkl'

# ثوابت
HOURS_WINDOW   = 48        # نافذة المحاكاة
FEE_PCT        = 0.003     # 0.3% رسوم per trade
N_WF_WINDOWS   = 5
TRAIN_RATIO    = 0.60
MIN_N_WINDOW   = 8
N_BOOTSTRAP    = 10000
API_DELAY_S    = 0.12      # تأخير بين طلبات API

# Variant multipliers (R = entry - stop_loss)
VARIANTS = {
    'baseline': None,        # يستخدم الأهداف من DB مباشرة
    'variant_a': (2.0, 4.0, 6.0),   # T1=2R, T2=4R, T3=6R
    'variant_b': (3.0, 5.0, 8.0),   # T1=3R, T2=5R, T3=8R
}

FREEZE_DATE = datetime(2026, 5, 17, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# 1. تحميل الإشارات من DB
# ═══════════════════════════════════════════════════════════════════════════

async def load_signals() -> List[Dict]:
    """يجلب إشارات 1d + bearish/sideways + score>=3 مع أهدافها الأصلية."""
    await Database.connect()
    try:
        rows = await Database.fetch("""
            SELECT
                s.id,
                s.symbol,
                s.market_condition,
                s.score,
                CAST(s.entry_price AS float)  AS entry_price,
                CAST(s.stop_loss   AS float)  AS stop_loss,
                CAST(s.target_1    AS float)  AS target_1,
                CAST(s.target_2    AS float)  AS target_2,
                CAST(s.target_3    AS float)  AS target_3,
                s.signal_time,
                tr.result,
                CAST(tr.profit_percent AS float) AS profit_percent,
                tr.duration_hours,
                tr.target_reached,
                tr.stop_hit,
                s.score_details::text AS sd_text
            FROM trade_results tr
            JOIN signals s ON tr.signal_id = s.id
            WHERE s.timeframe = '1d'
              AND s.market_condition IN ('bearish', 'sideways')
              AND s.score >= 3
              AND tr.result IN ('WIN', 'LOSS')
            ORDER BY s.signal_time ASC
        """)

        signals = []
        for row in rows:
            # RSI divergence من score_details
            sd = {}
            if row['sd_text']:
                try:
                    sd = json.loads(row['sd_text'])
                except Exception:
                    pass

            rsi_div = float(sd.get('rsi_divergence') or 0.0)
            sig_time = row['signal_time']
            if sig_time.tzinfo is None:
                sig_time = sig_time.replace(tzinfo=timezone.utc)

            entry = float(row['entry_price'])
            sl    = float(row['stop_loss'])
            r_dist = entry - sl  # R_distance بالسعر

            signals.append({
                'id':          row['id'],
                'symbol':      row['symbol'],
                'condition':   row['market_condition'],
                'score':       float(row['score']),
                'entry':       entry,
                'sl':          sl,
                'r_dist':      r_dist,
                'target_1_db': float(row['target_1']),
                'target_2_db': float(row['target_2']),
                'target_3_db': float(row['target_3']),
                'signal_time': sig_time,
                'result_live': row['result'],
                'profit_live': float(row['profit_percent'] or 0.0),
                'rsi_div':     rsi_div,
                'post_freeze': sig_time >= FREEZE_DATE,
            })

        logger.info(f"تحميل {len(signals)} إشارة من DB")
        return signals
    finally:
        await Database.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# 2. جلب OHLC 1h مع Cache
# ═══════════════════════════════════════════════════════════════════════════

def load_cache() -> Dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict) -> None:
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        logger.warning(f"لم يُحفَظ الـ cache: {e}")


async def fetch_1h_ohlc(
    client: AsyncClient,
    symbol: str,
    sig_time: datetime,
    hours: int,
    cache: Dict,
) -> Optional[List[Dict]]:
    """
    يجلب شموع 1h لنافذة [sig_time, sig_time + hours].
    يعيد list من dicts: {open_ms, high, low, close}.
    SL-first: عند تصادم High>=TP و Low<=SL في نفس الشمعة → نُفعّل SL.
    """
    cache_key = (symbol, sig_time.strftime('%Y%m%d_%H'), hours)
    if cache_key in cache:
        return cache[cache_key]

    try:
        start_ms = int(sig_time.timestamp() * 1000)
        end_ms   = int((sig_time + timedelta(hours=hours)).timestamp() * 1000)

        klines = await client.get_klines(
            symbol   = symbol,
            interval = '1h',
            startTime= start_ms,
            endTime  = end_ms,
            limit    = hours + 2,
        )

        if not klines:
            cache[cache_key] = None
            return None

        result = []
        for k in klines:
            result.append({
                'open_ms': int(k[0]),
                'open':    float(k[1]),
                'high':    float(k[2]),
                'low':     float(k[3]),
                'close':   float(k[4]),
            })

        cache[cache_key] = result
        return result

    except Exception as e:
        logger.warning(f"فشل جلب {symbol}: {e}")
        cache[cache_key] = None
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. محاكاة TripleBarrier مع SL-first
# ═══════════════════════════════════════════════════════════════════════════

def simulate_triple_barrier(
    candles: List[Dict],
    entry: float,
    sl: float,
    t1: float,
    t2: float,
    t3: float,
    trade_amount: float = 50.0,
    trail_pct: float = 2.5,
    expiry_h: int = 48,
    t1_expiry_h: int = 24,
) -> Dict:
    """
    محاكاة TripleBarrier على شموع 1h.

    SL-first rule: إذا اشتملت شمعة على (high>=T AND low<=SL) معاً
                   → نُعطي الأولوية لـ SL (محافظ).

    يعيد dict بكل تفاصيل النتيجة.
    """
    # ── حالة الصفقة ──────────────────────────────────────────────────────
    highest_target = 0
    peak           = entry
    hours_open     = 0.0
    eff_stop       = sl

    # ── MFE/MAE ──────────────────────────────────────────────────────────
    mfe_r = 0.0  # Maximum Favorable Excursion (بوحدات R)
    mae_r = 0.0  # Maximum Adverse Excursion (بوحدات R)
    r_dist = entry - sl
    if r_dist <= 0:
        return {'result': 'INVALID', 'profit_pct': 0.0, 'profit_adj': -FEE_PCT*100}

    def compute_eff_stop(ht, pk):
        if ht >= 2:
            trail = pk * (1 - trail_pct / 100)
            return max(t1, trail)
        elif ht >= 1:
            return entry  # break-even
        else:
            return sl

    for candle in candles:
        h = candle['high']
        l = candle['low']
        c = candle['close']
        hours_open += 1.0

        # تحديث MFE/MAE (قبل الخروج)
        fav  = (h - entry) / r_dist
        adv  = (entry - l) / r_dist
        mfe_r = max(mfe_r, fav)
        mae_r = max(mae_r, adv)

        # تحديث peak
        if h > peak:
            peak = h

        # تحديث أعلى هدف
        if h >= t3:
            highest_target = max(highest_target, 3)
        elif h >= t2:
            highest_target = max(highest_target, 2)
        elif h >= t1:
            highest_target = max(highest_target, 1)

        eff_stop = compute_eff_stop(highest_target, peak)

        # ── SL-first rule: إذا high>=TP و low<=SL في نفس الشمعة ──────────
        # الأهداف المحتملة لهذه الشمعة
        candle_hit_tp3 = (h >= t3)
        candle_hit_tp2 = (h >= t2) and (not candle_hit_tp3)
        candle_hit_tp1 = (h >= t1) and (not candle_hit_tp3) and (not candle_hit_tp2)
        candle_hit_sl  = (l <= eff_stop)

        # T3 — خروج فوري بالربح الأقصى (حتى مع SL-first، T3 واضح جداً)
        if highest_target == 3:
            profit_pct = ((t3 - entry) / entry) * 100
            return {
                'result':         'WIN',
                'exit_price':     t3,
                'profit_pct':     profit_pct,
                'profit_adj':     profit_pct - FEE_PCT*100,
                'profit_usdt':    profit_pct/100 * trade_amount,
                'duration_h':     hours_open,
                'exit_reason':    'T3',
                'target_reached': 3,
                'stop_hit':       False,
                'mfe_r':          round(mfe_r, 4),
                'mae_r':          round(mae_r, 4),
            }

        # Collision rule: إذا T1 أو T2 مُحتمَل مع SL في نفس الشمعة
        # → SL يسبق (محافظ)
        if candle_hit_sl:
            # هل hit حدث قبل أو بعد TP؟ نُطبّق SL-first
            exit_price = eff_stop
            profit_pct = ((exit_price - entry) / entry) * 100
            is_win     = exit_price > entry
            if highest_target >= 2:
                reason = 'trailing_stop'
            elif highest_target == 1:
                reason = 'break_even'
            else:
                reason = 'stop_loss'
            return {
                'result':         'WIN' if is_win else 'LOSS',
                'exit_price':     exit_price,
                'profit_pct':     profit_pct,
                'profit_adj':     profit_pct - FEE_PCT*100,
                'profit_usdt':    profit_pct/100 * trade_amount,
                'duration_h':     hours_open,
                'exit_reason':    reason,
                'target_reached': highest_target,
                'stop_hit':       not is_win,
                'mfe_r':          round(mfe_r, 4),
                'mae_r':          round(mae_r, 4),
            }

        # انتهاء 24h عند T1 فقط
        if hours_open >= t1_expiry_h and highest_target == 1:
            profit_pct = ((c - entry) / entry) * 100
            is_win = c > entry
            return {
                'result':         'WIN' if is_win else 'LOSS',
                'exit_price':     c,
                'profit_pct':     profit_pct,
                'profit_adj':     profit_pct - FEE_PCT*100,
                'profit_usdt':    profit_pct/100 * trade_amount,
                'duration_h':     hours_open,
                'exit_reason':    'T1_expired_24h',
                'target_reached': highest_target,
                'stop_hit':       False,
                'mfe_r':          round(mfe_r, 4),
                'mae_r':          round(mae_r, 4),
            }

        # انتهاء صلاحية 48h
        if hours_open >= expiry_h:
            profit_pct = ((c - entry) / entry) * 100
            is_win = c > entry
            return {
                'result':         'WIN' if is_win else 'LOSS',
                'exit_price':     c,
                'profit_pct':     profit_pct,
                'profit_adj':     profit_pct - FEE_PCT*100,
                'profit_usdt':    profit_pct/100 * trade_amount,
                'duration_h':     hours_open,
                'exit_reason':    'expired_48h',
                'target_reached': highest_target,
                'stop_hit':       False,
                'mfe_r':          round(mfe_r, 4),
                'mae_r':          round(mae_r, 4),
            }

    # نهاية الشموع بدون خروج → خروج بآخر سعر
    if candles:
        last_close = candles[-1]['close']
        profit_pct = ((last_close - entry) / entry) * 100
        is_win = last_close > entry
        return {
            'result':         'WIN' if is_win else 'LOSS',
            'exit_price':     last_close,
            'profit_pct':     profit_pct,
            'profit_adj':     profit_pct - FEE_PCT*100,
            'profit_usdt':    profit_pct/100 * 50.0,
            'duration_h':     hours_open,
            'exit_reason':    'end_of_data',
            'target_reached': highest_target,
            'stop_hit':       False,
            'mfe_r':          round(mfe_r, 4),
            'mae_r':          round(mae_r, 4),
        }

    return {
        'result':      'INVALID',
        'profit_pct':  0.0,
        'profit_adj':  -FEE_PCT*100,
        'mfe_r':       0.0,
        'mae_r':       0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. Walk-Forward + Bootstrap CI
# ═══════════════════════════════════════════════════════════════════════════

def walk_forward_e_adj(results: List[float], n_windows: int = 5, train_ratio: float = 0.60) -> Dict:
    """
    Walk-Forward على E_adj. يعيد المتوسط والـ CI.
    results: قائمة profit_adj مرتّبة زمنياً.
    """
    n = len(results)
    if n < n_windows * 2:
        return {'e_adj_wf': float('nan'), 'oos_n': 0, 'windows': []}

    window_size = n // n_windows
    oos_results = []
    windows = []

    for w in range(n_windows):
        start_idx = w * window_size
        split_idx = start_idx + int(window_size * train_ratio)
        end_idx   = start_idx + window_size

        oos = results[split_idx:end_idx]
        if len(oos) < 3:
            continue
        e_oos = float(np.mean(oos))
        windows.append({'w': w, 'oos_n': len(oos), 'e_oos': round(e_oos, 4)})
        oos_results.extend(oos)

    if not oos_results:
        return {'e_adj_wf': float('nan'), 'oos_n': 0, 'windows': windows}

    return {
        'e_adj_wf':  round(float(np.mean(oos_results)), 4),
        'oos_n':     len(oos_results),
        'windows':   windows,
    }


def bootstrap_ci(results: List[float], n_iter: int = 10000, alpha: float = 0.05) -> Tuple[float, float, float]:
    """
    Bootstrap CI على mean(E_adj).
    يعيد (mean, ci_lo, ci_hi).
    """
    if not results:
        return (float('nan'), float('nan'), float('nan'))

    arr = np.array(results)
    n   = len(arr)
    means = []
    for _ in range(n_iter):
        sample = arr[np.random.randint(0, n, size=n)]
        means.append(float(np.mean(sample)))

    means_arr = np.array(means)
    ci_lo = float(np.percentile(means_arr, alpha/2 * 100))
    ci_hi = float(np.percentile(means_arr, (1 - alpha/2) * 100))
    mean  = float(np.mean(arr))
    return (round(mean, 4), round(ci_lo, 4), round(ci_hi, 4))


# ═══════════════════════════════════════════════════════════════════════════
# 5. حساب إحصائيات الـ MFE
# ═══════════════════════════════════════════════════════════════════════════

def mfe_stats(sim_results: List[Dict]) -> Dict:
    """يحسب توزيع MFE بوحدات R."""
    mfes = [r['mfe_r'] for r in sim_results if 'mfe_r' in r and r['result'] != 'INVALID']
    if not mfes:
        return {}
    arr = np.array(mfes)
    return {
        'mfe_p25':   round(float(np.percentile(arr, 25)), 3),
        'mfe_p50':   round(float(np.percentile(arr, 50)), 3),
        'mfe_p75':   round(float(np.percentile(arr, 75)), 3),
        'mfe_p90':   round(float(np.percentile(arr, 90)), 3),
        'mfe_gte2r': round(float(np.mean(arr >= 2.0)) * 100, 1),
        'mfe_gte3r': round(float(np.mean(arr >= 3.0)) * 100, 1),
        'mfe_gte4r': round(float(np.mean(arr >= 4.0)) * 100, 1),
        'mfe_gte5r': round(float(np.mean(arr >= 5.0)) * 100, 1),
        'mfe_gte6r': round(float(np.mean(arr >= 6.0)) * 100, 1),
        'mfe_gte8r': round(float(np.mean(arr >= 8.0)) * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. Main
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    logger.info("═" * 60)
    logger.info("Part 38 — Wide R:R Isolation — بدء التشغيل")
    logger.info("═" * 60)

    # ── تحميل الإشارات ──────────────────────────────────────────────────
    signals = await load_signals()
    n_total  = len(signals)
    n_pre    = sum(1 for s in signals if not s['post_freeze'])
    n_post   = sum(1 for s in signals if s['post_freeze'])
    logger.info(f"إجمالي الإشارات: {n_total} (pre-freeze={n_pre}, post-freeze={n_post})")

    # ── جلب OHLC ────────────────────────────────────────────────────────
    cache  = load_cache()
    client = await AsyncClient.create()

    try:
        fetch_count = 0
        for i, sig in enumerate(signals):
            cache_key = (sig['symbol'], sig['signal_time'].strftime('%Y%m%d_%H'), HOURS_WINDOW)
            if cache_key not in cache:
                candles = await fetch_1h_ohlc(
                    client, sig['symbol'], sig['signal_time'], HOURS_WINDOW, cache
                )
                fetch_count += 1
                if fetch_count % 20 == 0:
                    save_cache(cache)
                    logger.info(f"  جُلب {fetch_count} رمز جديد...")
                await asyncio.sleep(API_DELAY_S)
            # تخزين في الإشارة
            cache_key_local = (sig['symbol'], sig['signal_time'].strftime('%Y%m%d_%H'), HOURS_WINDOW)
            sig['candles'] = cache.get(cache_key_local)

        save_cache(cache)
        logger.info(f"اكتمل جلب OHLC — {fetch_count} طلب جديد، cache: {len(cache)} مفتاح")
    finally:
        await client.close_connection()

    # ── المحاكاة لكل variant ─────────────────────────────────────────────
    variant_sim_results: Dict[str, List[Dict]] = {v: [] for v in VARIANTS}

    for sig in signals:
        candles = sig.get('candles')
        if not candles:
            continue

        entry  = sig['entry']
        sl     = sig['sl']
        r_dist = sig['r_dist']

        if r_dist <= 0:
            continue

        for vname, mults in VARIANTS.items():
            if mults is None:
                # Baseline: أهداف من DB
                t1 = sig['target_1_db']
                t2 = sig['target_2_db']
                t3 = sig['target_3_db']
            else:
                # Variant A أو B: مضاعفات R
                k1, k2, k3 = mults
                t1 = entry + k1 * r_dist
                t2 = entry + k2 * r_dist
                t3 = entry + k3 * r_dist

            sim = simulate_triple_barrier(
                candles   = candles,
                entry     = entry,
                sl        = sl,
                t1        = t1,
                t2        = t2,
                t3        = t3,
                trade_amount=50.0,
                trail_pct =2.5,
                expiry_h  =HOURS_WINDOW,
                t1_expiry_h=24,
            )

            sim['signal_id']    = sig['id']
            sim['symbol']       = sig['symbol']
            sim['signal_time']  = sig['signal_time'].isoformat()
            sim['post_freeze']  = sig['post_freeze']
            sim['rsi_div']      = sig['rsi_div']
            sim['variant']      = vname
            sim['t1_used']      = round(t1, 8)
            sim['t2_used']      = round(t2, 8)
            sim['t3_used']      = round(t3, 8)
            sim['r_dist']       = round(r_dist, 8)
            sim['r1']           = round((t1 - entry) / r_dist, 3) if r_dist > 0 else 0
            sim['r2']           = round((t2 - entry) / r_dist, 3) if r_dist > 0 else 0
            sim['r3']           = round((t3 - entry) / r_dist, 3) if r_dist > 0 else 0

            variant_sim_results[vname].append(sim)

    logger.info(f"اكتملت المحاكاة — إجمالي لكل variant: {len(variant_sim_results['baseline'])} صفقة")

    # ── حساب الإحصائيات ─────────────────────────────────────────────────
    output_records = []
    summary_lines  = []

    for vname in VARIANTS:
        for subset_name, is_post in [('all', None), ('pre_freeze', False), ('post_freeze', True)]:
            if is_post is None:
                sims = [r for r in variant_sim_results[vname] if r['result'] != 'INVALID']
            else:
                sims = [r for r in variant_sim_results[vname]
                        if r['result'] != 'INVALID' and r['post_freeze'] == is_post]

            n = len(sims)
            if n == 0:
                continue

            wins  = [r for r in sims if r['result'] == 'WIN']
            losses = [r for r in sims if r['result'] == 'LOSS']
            wr    = len(wins) / n
            profits_adj = [r['profit_adj'] for r in sims]
            profits_win  = [r['profit_pct'] for r in wins]
            profits_loss = [r['profit_pct'] for r in losses]

            avg_win  = float(np.mean(profits_win))  if wins   else 0.0
            avg_loss = float(np.mean(profits_loss)) if losses else 0.0
            e_adj    = float(np.mean(profits_adj))

            pf_num   = sum(r['profit_pct'] for r in wins)
            pf_den   = abs(sum(r['profit_pct'] for r in losses)) if losses else 1.0
            pf       = round(pf_num / pf_den, 4) if pf_den > 0 else 0.0

            # Walk-Forward
            wf = walk_forward_e_adj(profits_adj, N_WF_WINDOWS, TRAIN_RATIO)

            # Bootstrap CI
            mean_e, ci_lo, ci_hi = bootstrap_ci(profits_adj, N_BOOTSTRAP)

            # MFE stats
            mfe_s = mfe_stats(sims)

            # Exit reason distribution
            reasons = {}
            for r in sims:
                rsn = r.get('exit_reason', 'unknown')
                reasons[rsn] = reasons.get(rsn, 0) + 1

            rec = {
                'variant':        vname,
                'subset':         subset_name,
                'n':              n,
                'wr':             round(wr, 4),
                'pf':             pf,
                'avg_win_pct':    round(avg_win, 4),
                'avg_loss_pct':   round(avg_loss, 4),
                'e_adj':          round(e_adj, 4),
                'ci_lo':          ci_lo,
                'ci_hi':          ci_hi,
                'e_adj_wf':       wf.get('e_adj_wf', float('nan')),
                'oos_n':          wf.get('oos_n', 0),
                'mfe':            mfe_s,
                'exit_reasons':   reasons,
                'wf_windows':     wf.get('windows', []),
                'timestamp':      datetime.now(timezone.utc).isoformat(),
            }
            output_records.append(rec)

            # سطر ملخص
            if subset_name == 'all':
                t1_mult = VARIANTS[vname][0] if VARIANTS[vname] else 'DB'
                t3_mult = VARIANTS[vname][2] if VARIANTS[vname] else 'DB'
                summary_lines.append(
                    f"  {vname:12s} | n={n:4d} | WR={wr*100:5.1f}% | PF={pf:5.3f} | "
                    f"avgW={avg_win:+6.3f}% | avgL={avg_loss:+6.3f}% | "
                    f"E_adj={e_adj:+6.3f}% CI[{ci_lo:+.3f},{ci_hi:+.3f}] | "
                    f"WF={wf.get('e_adj_wf', float('nan')):+.3f}%"
                )
            elif subset_name == 'post_freeze':
                summary_lines.append(
                    f"    {vname:12s} post-freeze: n={n:3d} | WR={wr*100:5.1f}% | "
                    f"E_adj={e_adj:+6.3f}%"
                )

    # ── حفظ النتائج ─────────────────────────────────────────────────────
    with open(OUTPUT_FILE, 'w') as f:
        for rec in output_records:
            f.write(json.dumps(rec) + '\n')

    logger.info(f"النتائج محفوظة: {OUTPUT_FILE}")

    # ── طباعة الملخص ────────────────────────────────────────────────────
    logger.info("")
    logger.info("═" * 70)
    logger.info("PART 38 — Wide R:R Isolation — النتائج النهائية")
    logger.info("═" * 70)
    logger.info("")

    # ── MFE Distribution (baseline فقط) ──────────────────────────────────
    baseline_all = [r for r in output_records if r['variant'] == 'baseline' and r['subset'] == 'all']
    if baseline_all:
        mfe_b = baseline_all[0].get('mfe', {})
        logger.info("MFE Distribution (baseline, وحدات R):")
        logger.info(f"  P25={mfe_b.get('mfe_p25','?')}R | P50={mfe_b.get('mfe_p50','?')}R | "
                    f"P75={mfe_b.get('mfe_p75','?')}R | P90={mfe_b.get('mfe_p90','?')}R")
        logger.info(f"  MFE≥2R: {mfe_b.get('mfe_gte2r','?')}% | "
                    f"MFE≥3R: {mfe_b.get('mfe_gte3r','?')}% | "
                    f"MFE≥4R: {mfe_b.get('mfe_gte4r','?')}% | "
                    f"MFE≥5R: {mfe_b.get('mfe_gte5r','?')}% | "
                    f"MFE≥6R: {mfe_b.get('mfe_gte6r','?')}% | "
                    f"MFE≥8R: {mfe_b.get('mfe_gte8r','?')}%")
        logger.info("")

    logger.info("مقارنة الـ Variants (ALL data):")
    logger.info(f"  {'Variant':12s} | {'n':>5} | {'WR':>7} | {'PF':>6} | "
                f"{'avgWin':>8} | {'avgLoss':>8} | {'E_adj':>9} | CI 95%")
    logger.info("  " + "-" * 80)
    for vname in VARIANTS:
        recs = [r for r in output_records if r['variant'] == vname and r['subset'] == 'all']
        if recs:
            r = recs[0]
            logger.info(
                f"  {vname:12s} | {r['n']:5d} | {r['wr']*100:6.1f}% | {r['pf']:6.3f} | "
                f"{r['avg_win_pct']:+7.3f}% | {r['avg_loss_pct']:+7.3f}% | "
                f"{r['e_adj']:+8.3f}% | [{r['ci_lo']:+.3f}, {r['ci_hi']:+.3f}]"
            )

    logger.info("")
    logger.info("Walk-Forward E_adj (OOS فقط):")
    for vname in VARIANTS:
        recs = [r for r in output_records if r['variant'] == vname and r['subset'] == 'all']
        if recs:
            r = recs[0]
            logger.info(f"  {vname:12s}: WF={r['e_adj_wf']:+.4f}% (n_oos={r['oos_n']})")

    logger.info("")
    logger.info("Post-Freeze (directional only, n صغير):")
    for vname in VARIANTS:
        recs = [r for r in output_records if r['variant'] == vname and r['subset'] == 'post_freeze']
        if recs:
            r = recs[0]
            logger.info(f"  {vname:12s}: n={r['n']} | WR={r['wr']*100:.1f}% | E_adj={r['e_adj']:+.3f}%")

    logger.info("")
    logger.info("Exit Reason Distribution:")
    for vname in VARIANTS:
        recs = [r for r in output_records if r['variant'] == vname and r['subset'] == 'all']
        if recs:
            reasons = recs[0].get('exit_reasons', {})
            logger.info(f"  {vname:12s}: {dict(sorted(reasons.items(), key=lambda x: -x[1]))}")

    logger.info("")
    logger.info("═" * 70)
    logger.info("الاستنتاج:")
    # قرار مبني على CI
    baseline_rec = next((r for r in output_records if r['variant'] == 'baseline' and r['subset'] == 'all'), None)
    varA_rec     = next((r for r in output_records if r['variant'] == 'variant_a' and r['subset'] == 'all'), None)
    varB_rec     = next((r for r in output_records if r['variant'] == 'variant_b' and r['subset'] == 'all'), None)

    if baseline_rec and varA_rec and varB_rec:
        b_mean, b_lo, b_hi = baseline_rec['e_adj'], baseline_rec['ci_lo'], baseline_rec['ci_hi']
        a_mean, a_lo, a_hi = varA_rec['e_adj'], varA_rec['ci_lo'], varA_rec['ci_hi']
        c_mean, c_lo, c_hi = varB_rec['e_adj'], varB_rec['ci_lo'], varB_rec['ci_hi']

        # Variant A واعد إذا CI_lo > baseline E_adj أو CI_lo > 0
        a_promising = (a_lo > b_mean) or (a_lo > 0)
        b_promising = (c_lo > b_mean) or (c_lo > 0)

        if a_promising:
            logger.info("  Variant A (T1=2R, T2=4R, T3=6R): واعد — CI_lo يتجاوز baseline")
        else:
            logger.info(f"  Variant A: لا تحسّن إحصائي (E_adj={a_mean:+.3f}%, baseline={b_mean:+.3f}%)")

        if b_promising:
            logger.info("  Variant B (T1=3R, T2=5R, T3=8R): واعد — CI_lo يتجاوز baseline")
        else:
            logger.info(f"  Variant B: لا تحسّن إحصائي (E_adj={c_mean:+.3f}%, baseline={b_mean:+.3f}%)")

        mfe_data = baseline_rec.get('mfe', {})
        mfe3r = mfe_data.get('mfe_gte3r', 0)
        if mfe3r < 20:
            logger.info(f"  تحذير: MFE≥3R={mfe3r}% — أقل من 20% من الصفقات تصل 3R")
            logger.info("  → Wide R:R يتطلب صبراً أطول مما تُتيحه الإشارات الحالية")

    logger.info("═" * 70)
    logger.info("Part 38 — اكتمل")


if __name__ == '__main__':
    asyncio.run(main())
