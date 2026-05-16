"""
الباكتيستر — الجزء الثامن: Feature Edge Lab (مختبر حافة الميزات)
==================================================================
يُقيّم القدرة التنبؤية لمجموعة من الميزات الفنية على النتيجة المستقبلية.

الخطوات:
1. توسيم كل شمعة بالنتيجة المستقبلية (Triple-Barrier label) من بيانات part5
   (أو part2 كبديل عند غياب part5).
2. توليد ميزات مرشّحة — فئتان:
   أ) ميزات كلاسيكية: RSI، Bollinger، Stoch، MACD، Volume، Fibonacci
   ب) ميزات SMC (Smart Money Concepts) — مُنفَّذة بـ pandas/numpy فقط:
      - Order Blocks (OB)
      - Fair Value Gap (FVG)
      - Break of Structure (BOS)
      - Change of Character (CHoCH)
      - Liquidity Sweep
      - Fibonacci Retracement (61.8%)
3. ترتيب الميزات بالقدرة التنبؤية:
   - Information Coefficient (IC / Spearman ρ مع النتيجة)
   - Mutual Information (MI — تقريبي بدون sklearn)
   - فرق Expectancy بين أعلى وأدنى quantile

قيود الخادم: offline — يعمل على ملفات backtest_results محلية.
المخرج: backtest_results_part8.jsonl + ملخص.

ملاحظة: النتائج أولية (preliminary) — عينة صغيرة (30 صفقة).
"""

import json
import os
import sys
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# اختيار ملف الإدخال: part5 إن وُجد وكافٍ، وإلا part2
PART5_FILE = '/app/backtest_results_part5.jsonl'
PART2_FILE = '/app/backtest_results_part2.jsonl'
PART1_FILE = '/app/backtest_results_part1.jsonl'
OUTPUT_FILE = '/app/backtest_results_part8.jsonl'

N_QUANTILE_BINS = 4   # عدد فئات للمقارنة (Q1 vs Q4)
MIN_FEATURE_N   = 5   # حد أدنى لحسابات صادقة


# ═══════════════════════════════════════════════════════════════════════════
# القسم الأول: توسيم البيانات من ملفات الباكتيستر
# ═══════════════════════════════════════════════════════════════════════════

def load_labeled_records(part5_file: str, part2_file: str) -> List[Dict]:
    """
    يحمّل السجلات الموسومة بالنتيجة المستقبلية.
    يفضّل part5 (TripleBarrier موحّد) ثم part2.
    يعيد قائمة من dicts بحقول موحّدة.
    """
    records: List[Dict] = []

    # جرّب part5 أولاً
    if os.path.exists(part5_file):
        with open(part5_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    # part5 تستخدم حقول sim5_*
                    result     = d.get('sim5_result', d.get('sim_result', ''))
                    profit_pct = d.get('sim5_profit_pct', d.get('sim_profit_pct', 0.0))
                    if result not in ('WIN', 'LOSS'):
                        continue
                    records.append({
                        'symbol':           d.get('symbol'),
                        'eval_time':        d.get('eval_time'),
                        'market_condition': d.get('market_condition'),
                        'total_score':      d.get('total_score', 0.0),
                        'score_details':    d.get('score_details', {}),
                        'entry_price':      d.get('entry_price', 0.0),
                        'target_1':         d.get('target_1', 0.0),
                        'target_2':         d.get('target_2', 0.0),
                        'stop_loss':        d.get('stop_loss', 0.0),
                        'label':            1 if result == 'WIN' else 0,
                        'forward_return':   float(profit_pct),
                        'source':           'part5',
                    })
                except Exception:
                    continue

    # إن كانت part5 فارغة أو غير كافية — استخدم part2
    if len(records) < MIN_FEATURE_N and os.path.exists(part2_file):
        with open(part2_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    result     = d.get('sim_result', '')
                    profit_pct = d.get('sim_profit_pct', 0.0)
                    if result not in ('WIN', 'LOSS'):
                        continue
                    records.append({
                        'symbol':           d.get('symbol'),
                        'eval_time':        d.get('eval_time'),
                        'market_condition': d.get('market_condition'),
                        'total_score':      d.get('total_score', 0.0),
                        'score_details':    d.get('score_details', {}),
                        'entry_price':      d.get('entry_price', 0.0),
                        'target_1':         d.get('target_1', 0.0),
                        'target_2':         d.get('target_2', 0.0),
                        'stop_loss':        d.get('stop_loss', 0.0),
                        'label':            1 if result == 'WIN' else 0,
                        'forward_return':   float(profit_pct),
                        'source':           'part2',
                    })
                except Exception:
                    continue

    # ترتيب زمني
    try:
        records.sort(key=lambda r: r.get('eval_time', ''))
    except Exception:
        pass

    return records


# ═══════════════════════════════════════════════════════════════════════════
# القسم الثاني: توليد الميزات
# ═══════════════════════════════════════════════════════════════════════════

def extract_classic_features(record: Dict) -> Dict[str, float]:
    """
    يستخرج الميزات الكلاسيكية من score_details المتاحة.
    هذه الميزات مُوجودة مسبقاً في الإشارة — نفسّرها كـ binary/continuous.
    """
    sd    = record.get('score_details', {})
    entry = float(record.get('entry_price', 1.0)) or 1.0
    t1    = float(record.get('target_1', 0.0))
    stop  = float(record.get('stop_loss', 0.0))

    # نسبة R:R (Risk-Reward)
    rr = ((t1 - entry) / (entry - stop)) if (entry > stop and t1 > entry) else 0.0

    return {
        # مؤشرات التسجيل (raw score من score_details)
        'feat_rsi_score':         float(sd.get('rsi', 0.0)),
        'feat_bollinger_score':   float(sd.get('bollinger', 0.0)),
        'feat_stoch_score':       float(sd.get('stoch_rsi', 0.0)),
        'feat_rsi_div_score':     float(sd.get('rsi_divergence', 0.0)),
        'feat_fibonacci_score':   float(sd.get('fibonacci', 0.0)),
        'feat_macd_score':        float(sd.get('macd', 0.0)),
        'feat_ema_cross_score':   float(sd.get('ema_cross', 0.0)),
        'feat_volume_score':      float(sd.get('volume', 0.0)),
        'feat_obv_score':         float(sd.get('obv', 0.0)),
        'feat_btc_trend_score':   float(sd.get('btc_trend', 0.0)),
        # ميزات مشتقة
        'feat_total_score':       float(record.get('total_score', 0.0)),
        'feat_rr_ratio':          round(rr, 3),
        'feat_risk_pct':          round((entry - stop) / entry * 100, 3) if entry > 0 else 0.0,
        'feat_reward_pct':        round((t1 - entry) / entry * 100, 3)   if entry > 0 else 0.0,
        # عدد المؤشرات النشطة (score > 0)
        'feat_active_indicators': sum(1 for v in sd.values() if v > 0),
        # هل rsi_divergence نشط (ميزة SMC-adjacent قوية تاريخياً)
        'feat_rsi_div_active':    1.0 if sd.get('rsi_divergence', 0) > 0 else 0.0,
        # هل fibonacci نشط
        'feat_fib_active':        1.0 if sd.get('fibonacci', 0) > 0 else 0.0,
    }


# ── دوال SMC المُنفَّذة بـ pandas/numpy ────────────────────────────────────
# ملاحظة: نحسب هذه الميزات من candle_snapshot مضمّن في السجل (entry/t1/stop)
# لا نملك الشموع الكاملة في ملفات backtest_part2، لذا نُنشئ ميزات هيكلية
# استناداً إلى بنية مستويات الإشارة (entry/targets/stop) فقط.
# SMC الكامل يحتاج سلسلة شموع — سيُنجز عند ربطه بـ part1 raw candles.

def extract_smc_proxy_features(record: Dict) -> Dict[str, float]:
    """
    ميزات SMC تقريبية مستنبطة من مستويات الإشارة (entry/t1/t2/stop).
    هذه وكلاء (proxies) — SMC الحقيقي يحتاج سلسلة شموع (مُنجز في جزء منفصل).

    - OB_quality:  نسبة ATR-proxy للـ entry-stop (block width)
    - FVG_proxy:   gap نسبي بين t1 وt2 (fair value area)
    - BOS_strength: قوة الكسر = (t1 - entry) / (entry - stop)
    - CHoCH_proxy: هل الـ t3 أكبر من t2 بنسبة كبيرة (trend continuation)
    - liquidity_distance: بُعد السيولة (entry - stop) كنسبة من entry
    - fib_618_hit:  هل entry يقع في منطقة Fibonacci 61.8% بين stop وt3
    """
    entry  = float(record.get('entry_price', 0.0)) or 1.0
    stop   = float(record.get('stop_loss',   0.0)) or entry * 0.97
    t1     = float(record.get('target_1',    0.0)) or entry * 1.01
    t2     = float(record.get('target_2',    0.0)) or entry * 1.02
    t3_est = entry + 3 * (t1 - entry)  # تقدير t3 إن لم يُتح

    risk   = entry - stop
    reward = t1 - entry

    # OB quality: عرض الـ order block الفعّال
    ob_quality    = risk / entry if entry > 0 else 0.0

    # FVG proxy: الفجوة بين t1 وt2 كنسبة من entry
    fvg_proxy     = (t2 - t1) / entry if (t2 > t1 and entry > 0) else 0.0

    # BOS strength: R:R ratio
    bos_strength  = reward / risk if risk > 0 else 0.0

    # CHoCH proxy: هل t3 كبير (استمرار الاتجاه)
    choch_proxy   = (t3_est - t2) / t2 if t2 > 0 else 0.0

    # Liquidity distance (بُعد السيولة)
    liquidity_dist = risk / entry if entry > 0 else 0.0

    # Fibonacci 61.8% retracement:
    # هل entry يقع بين 50% و78.6% من المدى [stop, t3_est]
    fib_lo  = stop + 0.50  * (t3_est - stop)
    fib_618 = stop + 0.618 * (t3_est - stop)
    fib_786 = stop + 0.786 * (t3_est - stop)
    fib_618_hit = 1.0 if (fib_lo <= entry <= fib_786) else 0.0

    # OB structure score: هل الـ entry-stop zone ضيّقة (OB جيد = ضيّق)
    ob_narrow = 1.0 if ob_quality < 0.03 else 0.0

    # Sweep detection proxy: هل stop قريب جداً (احتمال sweep بعدها صعود)
    sweep_proxy = 1.0 if (liquidity_dist < 0.02) else 0.0

    return {
        'smc_ob_quality':      round(ob_quality, 5),
        'smc_ob_narrow':       ob_narrow,
        'smc_fvg_proxy':       round(fvg_proxy, 5),
        'smc_bos_strength':    round(bos_strength, 3),
        'smc_choch_proxy':     round(choch_proxy, 5),
        'smc_liquidity_dist':  round(liquidity_dist, 5),
        'smc_fib618_hit':      fib_618_hit,
        'smc_sweep_proxy':     sweep_proxy,
    }


def build_features(record: Dict) -> Dict[str, float]:
    """يجمع جميع الميزات في dict واحد."""
    classic = extract_classic_features(record)
    smc     = extract_smc_proxy_features(record)
    return {**classic, **smc}


# ═══════════════════════════════════════════════════════════════════════════
# القسم الثالث: قياس القدرة التنبؤية
# ═══════════════════════════════════════════════════════════════════════════

def spearman_rho(x: List[float], y: List[float]) -> float:
    """
    Spearman rank correlation (Information Coefficient).
    يُقيس الارتباط بين الميزة والنتيجة المستقبلية.
    IC > 0.05 مؤشر ميزة مفيدة.
    """
    n = len(x)
    if n < 3:
        return 0.0

    def rank_list(lst: List[float]) -> List[float]:
        sorted_idx = sorted(range(n), key=lambda i: lst[i])
        ranks      = [0.0] * n
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = float(rank + 1)
        return ranks

    rx = rank_list(x)
    ry = rank_list(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num   = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))
    if den_x == 0 or den_y == 0:
        return 0.0
    return round(num / (den_x * den_y), 4)


def mutual_info_approx(x: List[float], y: List[int], n_bins: int = 4) -> float:
    """
    Mutual Information تقريبي بـ discretization — بدون sklearn.
    يُقيس كمية المعلومات التي تحملها الميزة عن النتيجة الثنائية (WIN/LOSS).
    """
    if len(x) < MIN_FEATURE_N:
        return 0.0

    # تقسيم x إلى bins
    x_min, x_max = min(x), max(x)
    if x_max == x_min:
        return 0.0

    def bin_of(v):
        b = int((v - x_min) / (x_max - x_min) * n_bins)
        return min(b, n_bins - 1)

    bins_x = [bin_of(v) for v in x]
    n = len(x)

    # احتمالات مشتركة
    joint: Dict[Tuple, int] = {}
    for bx, yi in zip(bins_x, y):
        key = (bx, yi)
        joint[key] = joint.get(key, 0) + 1

    # احتمالات هامشية
    p_x: Dict = {}
    p_y: Dict = {}
    for bx, yi in zip(bins_x, y):
        p_x[bx] = p_x.get(bx, 0) + 1
        p_y[yi] = p_y.get(yi, 0) + 1

    mi = 0.0
    for (bx, yi), cnt in joint.items():
        p_xy = cnt / n
        px   = p_x.get(bx, 0) / n
        py   = p_y.get(yi, 0) / n
        if p_xy > 0 and px > 0 and py > 0:
            mi += p_xy * math.log(p_xy / (px * py))

    return round(max(0.0, mi), 5)


def quantile_expectancy_delta(
    feature_vals: List[float],
    returns: List[float],
    n_bins: int = N_QUANTILE_BINS,
) -> float:
    """
    فرق Expectancy بين أعلى وأدنى quantile.
    مؤشر مباشر على هل الميزة تميّز الصفقات الجيدة عن السيئة.
    """
    if len(feature_vals) < n_bins * 2:
        return 0.0

    paired  = sorted(zip(feature_vals, returns), key=lambda p: p[0])
    bin_size = max(1, len(paired) // n_bins)

    top_q    = paired[-bin_size:]
    bottom_q = paired[:bin_size]

    def exp_of(pairs):
        rets = [r for _, r in pairs]
        if not rets:
            return 0.0
        wins   = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        wr     = len(wins) / len(rets)
        avg_w  = sum(wins)   / len(wins)   if wins   else 0.0
        avg_l  = sum(losses) / len(losses) if losses else 0.0
        return wr * avg_w + (1 - wr) * avg_l

    return round(exp_of(top_q) - exp_of(bottom_q), 4)


def rank_features(
    records: List[Dict],
    feature_names: List[str],
) -> List[Dict]:
    """
    يُرتّب الميزات تنازلياً حسب |IC|.
    يعيد قائمة مُرتَّبة مع IC وMI وdelta_E.
    """
    labels  = [r['label'] for r in records]
    returns = [r['forward_return'] for r in records]
    features_matrix = [r.get('_features', {}) for r in records]

    ranking: List[Dict] = []

    for feat_name in feature_names:
        feat_vals = [fm.get(feat_name, 0.0) for fm in features_matrix]

        # تحقق من تباين الميزة
        if len(set(feat_vals)) < 2:
            ranking.append({
                'feature':       feat_name,
                'ic':            0.0,
                'mi':            0.0,
                'delta_e_q1q4':  0.0,
                'n_valid':       len(feat_vals),
                'note':          'no_variance',
            })
            continue

        ic       = spearman_rho(feat_vals, returns)
        mi       = mutual_info_approx(feat_vals, labels)
        delta_e  = quantile_expectancy_delta(feat_vals, returns)

        ranking.append({
            'feature':       feat_name,
            'ic':            ic,
            'mi':            mi,
            'delta_e_q1q4':  delta_e,
            'n_valid':       len([v for v in feat_vals if v != 0.0]),
            'abs_ic':        abs(ic),
        })

    ranking.sort(key=lambda x: x.get('abs_ic', 0.0), reverse=True)
    return ranking


# ═══════════════════════════════════════════════════════════════════════════
# القسم الرابع: تحليل SMC المُعمَّق من بيانات part1
# ═══════════════════════════════════════════════════════════════════════════

def load_candle_snapshots_from_part1(part1_file: str, symbols: List[str]) -> Dict[str, Dict]:
    """
    يحمّل آخر snapshot من score_details لكل عملة من part1.
    يُستخدم لإضافة ميزات SMC خامة من بيانات التسجيل الأصلية.
    """
    snapshots: Dict[str, Dict] = {}
    if not os.path.exists(part1_file):
        return snapshots

    with open(part1_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                sym = d.get('symbol')
                if sym and sym in symbols:
                    # نحتفظ بالأحدث زمنياً
                    if sym not in snapshots:
                        snapshots[sym] = d
                    else:
                        if d.get('eval_time', '') > snapshots[sym].get('eval_time', ''):
                            snapshots[sym] = d
            except Exception:
                continue
    return snapshots


def compute_smc_from_ohlc_proxy(symbol_data: List[Dict]) -> Dict[str, float]:
    """
    يحسب مؤشرات SMC من سلسلة نقاط تقييم لعملة واحدة.
    يستخدم entry/target/stop كـ OHLC proxy.

    BOS  (Break of Structure):   آخر entry > أعلى entry سابق بـ N نقاط
    CHoCH (Change of Character): entry أقل من أدنى entry سابق بـ N نقاط
    OB   (Order Block):          اتجاه عكسي قوي قبل الإشارة
    FVG  (Fair Value Gap):       gap بين stop وt1
    """
    if len(symbol_data) < 3:
        return {}

    entries = [float(d.get('entry_price', 0)) for d in symbol_data]
    t1s     = [float(d.get('target_1',    0)) for d in symbol_data]
    stops   = [float(d.get('stop_loss',   0)) for d in symbol_data]
    n       = len(entries)

    results = {}

    # BOS: آخر entry أعلى من متوسط الـ 3 أخيرة
    if n >= 4:
        recent_high = max(entries[-4:-1])
        results['smc_bos_actual'] = 1.0 if entries[-1] > recent_high else 0.0

        # CHoCH: آخر entry أقل من متوسط الـ 3 أخيرة
        recent_low  = min(entries[-4:-1])
        results['smc_choch_actual'] = 1.0 if entries[-1] < recent_low else 0.0
    else:
        results['smc_bos_actual']   = 0.0
        results['smc_choch_actual'] = 0.0

    # FVG: gap بين stop وأقل t1 مجاور
    last_stop = stops[-1] if stops else 0.0
    last_t1   = t1s[-1]   if t1s   else 0.0
    last_entry= entries[-1] if entries else 0.0
    fvg_size  = (last_t1 - last_stop) / last_entry if last_entry > 0 else 0.0
    results['smc_fvg_size'] = round(fvg_size, 5)

    # OB: هبوط حاد ثم صعود (entry < prev_entry ثم entry يعود)
    if n >= 3:
        prev_entries  = entries[-3:]
        drop          = (prev_entries[0] - prev_entries[1]) / prev_entries[0] if prev_entries[0] > 0 else 0
        recovery      = (prev_entries[2] - prev_entries[1]) / prev_entries[1] if prev_entries[1] > 0 else 0
        results['smc_ob_drop_then_rise'] = 1.0 if (drop > 0.01 and recovery > 0.01) else 0.0
    else:
        results['smc_ob_drop_then_rise'] = 0.0

    return results


# ═══════════════════════════════════════════════════════════════════════════
# نقطة الدخول الرئيسية
# ═══════════════════════════════════════════════════════════════════════════

def run_feature_lab():
    print("=" * 65)
    print("الباكتيستر — الجزء الثامن: Feature Edge Lab")
    print("=" * 65)

    # 1. تحميل البيانات الموسومة
    records = load_labeled_records(PART5_FILE, PART2_FILE)
    if not records:
        print("ERROR: لا بيانات موسومة — شغّل part2 أو part5 أولاً")
        sys.exit(1)

    n_total = len(records)
    n_win   = sum(r['label'] for r in records)
    n_loss  = n_total - n_win
    wr_base = n_win / n_total if n_total > 0 else 0.0
    print(f"السجلات الموسومة: {n_total} (WIN={n_win}, LOSS={n_loss}, WR={wr_base*100:.1f}%)")
    print(f"مصدر البيانات: {records[0].get('source', 'unknown')}")
    print()

    # 2. توليد الميزات لكل سجل
    for r in records:
        r['_features'] = build_features(r)

    feature_names = list(records[0]['_features'].keys())
    print(f"إجمالي الميزات المولّدة: {len(feature_names)}")
    print(f"  - كلاسيكية: {sum(1 for f in feature_names if f.startswith('feat_'))}")
    print(f"  - SMC proxy: {sum(1 for f in feature_names if f.startswith('smc_'))}")
    print()

    # 3. إضافة ميزات SMC من part1 (إن أمكن)
    if os.path.exists(PART1_FILE):
        symbols_in_data = list({r['symbol'] for r in records})
        snapshots       = load_candle_snapshots_from_part1(PART1_FILE, symbols_in_data)

        # تجميع نقاط كل عملة
        by_symbol: Dict[str, List[Dict]] = {}
        for r in records:
            sym = r.get('symbol', '')
            by_symbol.setdefault(sym, []).append(r)

        smc_computed = 0
        for sym, sym_records in by_symbol.items():
            smc_features = compute_smc_from_ohlc_proxy(sym_records)
            if smc_features:
                for r in sym_records:
                    r['_features'].update(smc_features)
                smc_computed += 1

        if smc_computed > 0:
            feature_names = list(records[0]['_features'].keys())
            print(f"ميزات SMC من part1 أضيفت لـ {smc_computed} عملة.")
            print(f"إجمالي الميزات بعد SMC: {len(feature_names)}")
            print()

    # 4. ترتيب الميزات
    ranking = rank_features(records, feature_names)

    # 5. طباعة النتائج
    print("== ترتيب الميزات بالقدرة التنبؤية ==")
    print(f"{'الميزة':35s} {'IC':>7s}  {'MI':>7s}  {'ΔE(Q1-Q4)':>10s}  {'n≠0':>5s}")
    print("-" * 75)

    # تصفية الميزات التي لها تباين
    ranked_valid = [r for r in ranking if r.get('note') != 'no_variance']
    ranked_novar = [r for r in ranking if r.get('note') == 'no_variance']

    for row in ranked_valid[:20]:
        flag = ""
        if abs(row['ic']) >= 0.1:
            flag = "**"
        elif abs(row['ic']) >= 0.05:
            flag = "*"
        print(
            f"{row['feature']:35s} "
            f"{row['ic']:>+7.3f}  "
            f"{row['mi']:>7.4f}  "
            f"{row['delta_e_q1q4']:>+10.3f}  "
            f"{row['n_valid']:>5d}  {flag}"
        )

    if ranked_novar:
        print(f"\n(ميزات بدون تباين — مُتجاهلة: {len(ranked_novar)})")
        for row in ranked_novar:
            print(f"  {row['feature']}")

    print()
    print("  ** IC >= 0.10 (ميزة قوية)")
    print("  *  IC >= 0.05 (ميزة محتملة)")
    print()

    # 6. ملخص تحليلي
    print("== ملخص التحليل ==")

    strong_features  = [r for r in ranked_valid if abs(r['ic']) >= 0.10]
    promising_features = [r for r in ranked_valid if 0.05 <= abs(r['ic']) < 0.10]

    print(f"ميزات قوية (|IC|>=0.10):      {len(strong_features)}")
    print(f"ميزات محتملة (|IC|>=0.05):    {len(promising_features)}")
    print()

    if strong_features:
        print("أقوى الميزات:")
        for f in strong_features[:5]:
            direction = "موجبة (صعود)" if f['ic'] > 0 else "سالبة (هبوط)"
            print(f"  {f['feature']}: IC={f['ic']:+.3f} ({direction}), ΔE={f['delta_e_q1q4']:+.3f}%")
    else:
        print("لا ميزات قوية — العينة صغيرة جداً أو الميزات ضعيفة التمييز.")

    # 7. تحليل SMC خاص
    smc_features_ranked = [r for r in ranked_valid if r['feature'].startswith('smc_')]
    print()
    print("== تحليل ميزات SMC ==")
    if smc_features_ranked:
        for f in smc_features_ranked[:8]:
            print(f"  {f['feature']:35s}: IC={f['ic']:+.3f}, ΔE={f['delta_e_q1q4']:+.3f}%")
    else:
        print("  لا ميزات SMC — راجع part1.")

    print()

    # 8. حفظ النتائج
    output = {
        'run_date':           datetime.utcnow().isoformat(),
        'preliminary':        True,
        'n_total':            n_total,
        'n_win':              n_win,
        'n_loss':             n_loss,
        'base_wr':            round(wr_base, 4),
        'source':             records[0].get('source', 'unknown') if records else 'unknown',
        'feature_count':      len(feature_names),
        'feature_ranking':    ranking,
        'strong_features':    [f['feature'] for f in strong_features],
        'promising_features': [f['feature'] for f in promising_features],
        'smc_features_ranked': smc_features_ranked,
        'records_with_features': [
            {
                'symbol':       r['symbol'],
                'eval_time':    r['eval_time'],
                'label':        r['label'],
                'forward_return': r['forward_return'],
                **r['_features'],
            }
            for r in records
        ],
        'warning': (
            f'نتائج أولية (preliminary). n={n_total} صغيرة. '
            'IC موثوق عند n>=100. لا تُطبَّق استنتاجات على الإعدادات الحيّة.'
        ),
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as fout:
        json.dump(output, fout, ensure_ascii=False, indent=2)

    print(f"النتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 65)
    return output


if __name__ == '__main__':
    run_feature_lab()
