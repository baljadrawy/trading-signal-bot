"""
الباكتيستر — الجزء 15: Feature Edge Lab الصارم (Walk-Forward + FDR + E_adj)
============================================================================
تقوية مختبر حافة الميزات (الجزء 8) بثلاثة محاور:

1. Walk-Forward IC: تُحسب IC على نوافذ متحركة (train→test) لا كامل التاريخ.
   الترتيب = استقرار IC عبر النوافذ (IC_mean / IC_std)، ليس IC اللحظي.

2. عينة غير منحازة: كل صفقة في DB (لا صفقات الاستراتيجية القديمة فقط)،
   مُقسَّمة زمنياً بلا data leakage.

3. مقياس E_adj: Expectancy بعد رسوم 0.3% لأعلى decile من الميزة
   (لا IC الخام).

4. تصحيح مقارنات متعددة: Benjamini-Hochberg FDR على كل الميزات.

النتيجة: الميزات التي تصمد = حافة حقيقية. الباقي = وهم in-sample.

قيود الخادم: aarch64، نواتان، ~2GB RAM. لا حزم جديدة (pandas/numpy/asyncpg فقط).
المخرج: backtest_results_part15.jsonl + ملخص طباعي.
"""

import asyncio
import json
import math
import sys
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/shared')

from shared.database import Database

OUTPUT_FILE = '/app/backtest_results_part15.jsonl'

# ─── ثوابت ───────────────────────────────────────────────────────────────────
FEE_PCT         = 0.003      # 0.3% رسوم + انزلاق
N_WF_WINDOWS    = 5          # عدد نوافذ Walk-Forward
TRAIN_RATIO     = 0.6        # 60% تدريب، 40% اختبار
TOP_DECILE_FRAC = 0.10       # أعلى 10% من الميزة
MIN_N_WINDOW    = 10         # حد أدنى للحساب الموثوق
FDR_ALPHA       = 0.10       # مستوى FDR المقبول (Benjamini-Hochberg)


# ═══════════════════════════════════════════════════════════════════════════
# 1. تحميل البيانات
# ═══════════════════════════════════════════════════════════════════════════

async def load_all_trades() -> List[Dict]:
    """
    يحمّل كل صفقات trade_results مع score_details من DB.
    مُرتَّبة زمنياً لضمان Walk-Forward صحيح.
    """
    rows = await Database.fetch("""
        SELECT
            tr.result,
            tr.profit_percent,
            s.signal_time,
            s.timeframe,
            s.market_condition,
            s.score,
            s.score_details
        FROM trade_results tr
        JOIN signals s ON tr.signal_id = s.id
        WHERE tr.profit_percent IS NOT NULL
          AND s.score_details IS NOT NULL
        ORDER BY s.signal_time ASC
    """)
    trades = []
    for r in rows:
        sd_raw = r['score_details']
        try:
            if isinstance(sd_raw, str):
                sd = json.loads(sd_raw)
            else:
                sd = dict(sd_raw)
        except Exception:
            sd = {}
        profit_pct = float(r['profit_percent'])
        profit_adj = profit_pct - (FEE_PCT * 100)
        trades.append({
            'signal_time':      str(r['signal_time']),
            'result':           r['result'],
            'profit_pct':       profit_pct,
            'profit_adj':       profit_adj,
            'timeframe':        r['timeframe'],
            'market_condition': r['market_condition'],
            'score':            float(r['score'] or 0),
            'sd':               sd,
        })
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# 2. توليد الميزات
# ═══════════════════════════════════════════════════════════════════════════

def extract_features(trade: Dict) -> Dict[str, float]:
    """
    يستخرج الميزات المرشّحة من score_details.
    كل ميزة = قيمة رقمية مستمرة أو ثنائية.
    """
    sd    = trade['sd']
    score = trade['score']
    entry_rr = 0.0  # لا يمكن حسابه بدون entry/stop — محذوف

    feats = {
        # مؤشرات التسجيل الخام
        'feat_rsi':            float(sd.get('rsi', 0.0)),
        'feat_bollinger':      float(sd.get('bollinger', 0.0)),
        'feat_stoch_rsi':      float(sd.get('stoch_rsi', 0.0)),
        'feat_rsi_div':        float(sd.get('rsi_divergence', 0.0)),
        'feat_fibonacci':      float(sd.get('fibonacci', 0.0)),
        'feat_macd':           float(sd.get('macd', 0.0)),
        'feat_ema_cross':      float(sd.get('ema_cross', 0.0)),
        'feat_volume':         float(sd.get('volume', 0.0)),
        'feat_obv':            float(sd.get('obv', 0.0)),
        'feat_btc_trend':      float(sd.get('btc_trend', 0.0)),
        'feat_order_book':     float(sd.get('order_book', 0.0)),
        # ميزات مشتقة
        'feat_total_score':    score,
        'feat_score_gte3':     1.0 if score >= 3.0 else 0.0,
        'feat_score_gte4':     1.0 if score >= 4.0 else 0.0,
        'feat_score_gte5':     1.0 if score >= 5.0 else 0.0,
        'feat_active_count':   float(sum(1 for v in sd.values() if isinstance(v, (int, float)) and v > 0)),
        'feat_rsi_div_active': 1.0 if float(sd.get('rsi_divergence', 0)) > 0 else 0.0,
        'feat_fib_active':     1.0 if float(sd.get('fibonacci', 0)) > 0 else 0.0,
        'feat_rsi_strong':     1.0 if float(sd.get('rsi', 0)) >= 1.2 else 0.0,
        'feat_stoch_strong':   1.0 if float(sd.get('stoch_rsi', 0)) >= 1.0 else 0.0,
        # ميزات سياقية
        'feat_is_1d':          1.0 if trade['timeframe'] == '1d' else 0.0,
        'feat_is_1h':          1.0 if trade['timeframe'] == '1h' else 0.0,
        'feat_is_bearish':     1.0 if trade['market_condition'] == 'bearish' else 0.0,
        'feat_is_sideways':    1.0 if trade['market_condition'] == 'sideways' else 0.0,
        'feat_is_bullish':     1.0 if trade['market_condition'] == 'bullish' else 0.0,
        # توليفات (interaction features)
        'feat_1d_bearish':     1.0 if (trade['timeframe'] == '1d' and trade['market_condition'] == 'bearish') else 0.0,
        'feat_1d_sideways':    1.0 if (trade['timeframe'] == '1d' and trade['market_condition'] == 'sideways') else 0.0,
        'feat_1h_sideways':    1.0 if (trade['timeframe'] == '1h' and trade['market_condition'] == 'sideways') else 0.0,
        'feat_rsi_x_div':      float(sd.get('rsi', 0)) * float(sd.get('rsi_divergence', 0)),
        'feat_rsi_x_bb':       float(sd.get('rsi', 0)) * float(sd.get('bollinger', 0)),
    }
    return feats


# ═══════════════════════════════════════════════════════════════════════════
# 3. إحصاءات أساسية
# ═══════════════════════════════════════════════════════════════════════════

def spearman_rho(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation."""
    n = len(x)
    if n < 3:
        return 0.0

    def rank_list(lst):
        sorted_idx = sorted(range(n), key=lambda i: lst[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = float(rank + 1)
        return ranks

    rx = rank_list(x)
    ry = rank_list(y)
    mr = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mr) * (ry[i] - my) for i in range(n))
    dx  = math.sqrt(sum((rx[i] - mr) ** 2 for i in range(n)))
    dy  = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def ttest_one_sample(values: List[float], mu: float = 0.0) -> Tuple[float, float]:
    """
    اختبار t أحادي العينة: هل متوسط IC يختلف عن الصفر؟
    يعيد (t_stat, p_value) تقريبي.
    """
    n = len(values)
    if n < 2:
        return 0.0, 1.0
    mean_v = sum(values) / n
    var_v  = sum((v - mean_v) ** 2 for v in values) / (n - 1)
    std_v  = math.sqrt(var_v) if var_v > 0 else 0.0
    if std_v == 0:
        return 0.0, 1.0
    t = (mean_v - mu) / (std_v / math.sqrt(n))
    # تقريب p-value من t ودرجات حرية (n-1)
    # نستخدم تقريب بسيط: p = 2*(1 - normal_cdf(|t|)) لـ n كبيرة
    # لـ n صغيرة نعتمد على جدول محافظ
    abs_t = abs(t)
    df = n - 1
    # تقريب محافظ لـ p-value (student-t → normal للـ df>10)
    if df >= 10:
        # تقريب normal
        p = 2.0 * (1.0 - _normal_cdf(abs_t))
    else:
        # جدول محافظ لـ df صغيرة
        critical = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57,
                    6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23}
        crit = critical.get(df, 2.23)
        p = 0.05 if abs_t >= crit else 0.20
    return round(t, 3), round(min(p, 1.0), 4)


def _normal_cdf(z: float) -> float:
    """تقريب دالة التوزيع التراكمي للتوزيع الطبيعي."""
    # Abramowitz and Stegun approximation
    sign = 1 if z >= 0 else -1
    z = abs(z)
    t_val = 1.0 / (1.0 + 0.2316419 * z)
    poly  = t_val * (0.319381530
              + t_val * (-0.356563782
              + t_val * (1.781477937
              + t_val * (-1.821255978
              + t_val * 1.330274429))))
    phi = 1.0 - (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * z * z) * poly
    return 0.5 + sign * (phi - 0.5)


def top_decile_expectancy_adj(
    feat_vals: List[float],
    adj_returns: List[float],
    frac: float = TOP_DECILE_FRAC,
) -> Tuple[float, int]:
    """
    يحسب E_adj لأعلى decile من الميزة (بعد رسوم 0.3%).
    يعيد (expectancy_adj, n_in_decile).
    """
    if len(feat_vals) < 10:
        return 0.0, 0

    paired  = sorted(zip(feat_vals, adj_returns), key=lambda p: p[0], reverse=True)
    k       = max(1, int(len(paired) * frac))
    top_k   = paired[:k]
    rets    = [r for _, r in top_k]

    wins  = [r for r in rets if r > 0]
    losses= [r for r in rets if r <= 0]
    n     = len(rets)
    if n == 0:
        return 0.0, 0
    wr    = len(wins) / n
    avg_w = sum(wins)   / len(wins)   if wins   else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    e_adj = wr * avg_w + (1 - wr) * avg_l
    return round(e_adj, 4), n


# ═══════════════════════════════════════════════════════════════════════════
# 4. Walk-Forward IC
# ═══════════════════════════════════════════════════════════════════════════

def walk_forward_ic(
    trades: List[Dict],
    feat_name: str,
    n_windows: int = N_WF_WINDOWS,
) -> Dict:
    """
    يحسب IC على نوافذ Walk-Forward.

    المنهج:
    - يُقسِّم البيانات المرتبة زمنياً إلى n_windows شرائح.
    - كل نافذة: أول TRAIN_RATIO تدريب، الباقي اختبار.
    - IC يُحسَب على الاختبار فقط (OOS).
    - الترتيب = ICIR = IC_mean / IC_std (مقياس الاستقرار عبر النوافذ).
    - شرط: يجب أن تتضمن النافذة على الأقل 2 قيمة مختلفة للميزة.
    - ICIR يُحسَب فقط عند توفر نافذتين أو أكثر (وإلا p=0.2 كتقدير محافظ).
    """
    n = len(trades)
    if n < n_windows * MIN_N_WINDOW:
        return {
            'feature': feat_name,
            'ic_per_window': [],
            'ic_mean': 0.0,
            'ic_std': 0.0,
            'icir': 0.0,
            't_stat': 0.0,
            'p_value': 1.0,
            'n_oos_total': 0,
            'note': 'insufficient_data',
        }

    # استخرج الميزة لكل صفقة
    feat_vals = [t.get('_features', {}).get(feat_name, 0.0) for t in trades]

    # تحقق من التباين الكلي
    if len(set(feat_vals)) < 2:
        return {
            'feature': feat_name,
            'ic_per_window': [],
            'ic_mean': 0.0,
            'ic_std': 0.0,
            'icir': 0.0,
            't_stat': 0.0,
            'p_value': 1.0,
            'n_oos_total': 0,
            'note': 'no_variance',
        }

    # تقسيم إلى نوافذ زمنية
    window_size = n // n_windows
    ic_list = []
    n_oos_total = 0

    for w in range(n_windows):
        start = w * window_size
        end   = start + window_size if w < n_windows - 1 else n
        window_trades = trades[start:end]

        n_win = len(window_trades)
        split = int(n_win * TRAIN_RATIO)
        if split < 2 or (n_win - split) < MIN_N_WINDOW:
            continue

        oos_trades = window_trades[split:]
        oos_feat   = [t.get('_features', {}).get(feat_name, 0.0) for t in oos_trades]
        oos_ret    = [t['profit_adj'] for t in oos_trades]

        # يجب وجود تباين في النافذة OOS
        if len(set(oos_feat)) < 2:
            continue

        ic = spearman_rho(oos_feat, oos_ret)
        ic_list.append(ic)
        n_oos_total += len(oos_trades)

    if not ic_list:
        return {
            'feature': feat_name,
            'ic_per_window': [],
            'ic_mean': 0.0,
            'ic_std': 0.0,
            'icir': 0.0,
            't_stat': 0.0,
            'p_value': 1.0,
            'n_oos_total': 0,
            'note': 'all_windows_skipped',
        }

    ic_mean = sum(ic_list) / len(ic_list)

    # ICIR: يحتاج >= 2 نوافذ لحساب std موثوق
    if len(ic_list) >= 2:
        ic_var  = sum((v - ic_mean) ** 2 for v in ic_list) / (len(ic_list) - 1)
        ic_std  = math.sqrt(ic_var) if ic_var > 0 else 1e-9
        icir    = ic_mean / ic_std
        t_stat, p_val = ttest_one_sample(ic_list, mu=0.0)
    else:
        # نافذة واحدة فقط: ICIR = IC الخام (لا انقسام)
        ic_std  = 0.0
        icir    = ic_mean  # IC_mean نفسه بلا تطبيع
        t_stat  = 0.0
        p_val   = 0.20  # تقدير محافظ

    # تحقق من إشارة ICIR (cap للتفادي القيم المتطرفة بسبب std صغير جداً)
    icir = max(-50.0, min(50.0, icir))

    return {
        'feature':        feat_name,
        'ic_per_window':  [round(v, 4) for v in ic_list],
        'ic_mean':        round(ic_mean, 4),
        'ic_std':         round(ic_std, 4),
        'icir':           round(icir, 3),
        't_stat':         t_stat,
        'p_value':        p_val,
        'n_oos_total':    n_oos_total,
        'n_windows_used': len(ic_list),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. تصحيح مقارنات متعددة (Benjamini-Hochberg FDR)
# ═══════════════════════════════════════════════════════════════════════════

def benjamini_hochberg(
    feature_results: List[Dict],
    alpha: float = FDR_ALPHA,
) -> List[Dict]:
    """
    يُطبِّق تصحيح Benjamini-Hochberg على p-values للميزات.
    يُضيف حقلَين: 'bh_rejected' (True = ميزة ذات دلالة بعد التصحيح)
    و 'bh_threshold' (العتبة المحدودة لهذه الميزة).

    المنهج BH:
    1. رتّب الميزات تصاعدياً حسب p_value.
    2. احسب عتبة BH_i = (i/m) * alpha.
    3. أكبر k حيث p_k <= BH_k يُعتبر حد الرفض.
    4. كل الميزات من رتبة 1 إلى k تُرفض H0 (أي دالة إحصائياً).
    """
    m = len(feature_results)
    if m == 0:
        return feature_results

    # ترتيب بحسب p_value تصاعدياً
    sorted_results = sorted(
        enumerate(feature_results),
        key=lambda x: x[1].get('p_value', 1.0)
    )

    # حساب عتبات BH
    bh_thresholds = [(i + 1) / m * alpha for i in range(m)]

    # أكبر k حيث p_k <= threshold_k
    max_k = -1
    for rank, (orig_idx, res) in enumerate(sorted_results):
        if res.get('p_value', 1.0) <= bh_thresholds[rank]:
            max_k = rank

    # علامة الرفض
    for rank, (orig_idx, res) in enumerate(sorted_results):
        feature_results[orig_idx]['bh_rejected']  = (rank <= max_k)
        feature_results[orig_idx]['bh_threshold'] = round(bh_thresholds[rank], 5)
        feature_results[orig_idx]['bh_rank']      = rank + 1

    return feature_results


# ═══════════════════════════════════════════════════════════════════════════
# 6. تشغيل الكامل
# ═══════════════════════════════════════════════════════════════════════════

async def run_strict_feature_lab():
    print("=" * 70)
    print("الجزء 15: Feature Edge Lab الصارم (Walk-Forward + FDR + E_adj)")
    print(f"تاريخ التشغيل: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    await Database.connect()
    trades = await load_all_trades()
    await Database.disconnect()

    n_total = len(trades)
    n_win   = sum(1 for t in trades if t['result'] == 'WIN')
    wr_base = n_win / n_total if n_total > 0 else 0
    print(f"\nإجمالي الصفقات: {n_total} (WIN={n_win}, WR={wr_base*100:.1f}%)")
    print(f"النطاق الزمني: {trades[0]['signal_time'][:10]} → {trades[-1]['signal_time'][:10]}")
    print(f"تكلفة افتراضية/صفقة: {FEE_PCT*100:.1f}%")
    print(f"Walk-Forward: {N_WF_WINDOWS} نوافذ، train={int(TRAIN_RATIO*100)}%/OOS={int((1-TRAIN_RATIO)*100)}%")
    print(f"FDR alpha: {FDR_ALPHA} (Benjamini-Hochberg)")
    print()

    # توليد الميزات
    for t in trades:
        t['_features'] = extract_features(t)

    feature_names = list(trades[0]['_features'].keys())
    n_feats = len(feature_names)
    print(f"عدد الميزات: {n_feats}")
    print()

    # ── حساب Walk-Forward IC لكل ميزة ──────────────────────────────────────
    print("جاري حساب Walk-Forward IC ...")
    wf_results = []
    for fname in feature_names:
        res = walk_forward_ic(trades, fname, n_windows=N_WF_WINDOWS)
        wf_results.append(res)

    # ── حساب E_adj لأعلى decile ─────────────────────────────────────────────
    for res in wf_results:
        fname = res['feature']
        fvals = [t['_features'].get(fname, 0.0) for t in trades]
        arets = [t['profit_adj'] for t in trades]
        e_adj, n_dec = top_decile_expectancy_adj(fvals, arets, frac=TOP_DECILE_FRAC)
        res['top_decile_e_adj'] = e_adj
        res['top_decile_n']     = n_dec

    # ── تصحيح BH ─────────────────────────────────────────────────────────────
    wf_results = benjamini_hochberg(wf_results, alpha=FDR_ALPHA)

    # ── ترتيب: أولاً bh_rejected=True ثم ICIR تنازلياً ──────────────────────
    wf_results.sort(
        key=lambda r: (
            -int(r.get('bh_rejected', False)),   # رُفضت H0 أولاً
            -abs(r.get('icir', 0.0)),            # ثم ICIR
        )
    )

    # ── طباعة النتائج ──────────────────────────────────────────────────────
    print()
    print(f"{'الميزة':32s} {'ICIR':>6}  {'IC_mean':>8}  {'IC_std':>7}  {'p_val':>6}  {'BH':>4}  {'E_adj_top10%':>13}  {'N_OOS':>7}")
    print("-" * 100)

    surviving = []
    illusions  = []

    for r in wf_results:
        if r.get('note') in ('no_variance', 'insufficient_data', 'all_windows_skipped'):
            continue

        bh_mark  = "YES" if r.get('bh_rejected') else "no"
        ic_mean  = r.get('ic_mean', 0.0)
        ic_std   = r.get('ic_std', 0.0)
        icir     = r.get('icir', 0.0)
        p_val    = r.get('p_value', 1.0)
        e_adj    = r.get('top_decile_e_adj', 0.0)
        n_oos    = r.get('n_oos_total', 0)

        flag = ""
        if r.get('bh_rejected') and e_adj > 0:
            flag = "<< صامدة"
            surviving.append(r)
        elif not r.get('bh_rejected') and abs(ic_mean) >= 0.05:
            flag = "(وهم in-sample)"
            illusions.append(r)

        print(
            f"{r['feature']:32s} "
            f"{icir:>+6.3f}  "
            f"{ic_mean:>+8.4f}  "
            f"{ic_std:>7.4f}  "
            f"{p_val:>6.3f}  "
            f"{bh_mark:>4}  "
            f"{e_adj:>+13.4f}  "
            f"{n_oos:>7}  "
            f"{flag}"
        )

    # ── ملخص ──────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("== الملخص ==")
    print()

    print(f"الميزات الصامدة بعد الصرامة (bh_rejected=YES + E_adj>0): {len(surviving)}")
    if surviving:
        for r in surviving:
            windows_str = ", ".join(str(v) for v in r.get('ic_per_window', []))
            print(f"  {r['feature']}:")
            print(f"    ICIR={r['icir']:+.3f}, IC_mean={r['ic_mean']:+.4f}±{r['ic_std']:.4f}")
            print(f"    IC النوافذ: [{windows_str}]")
            print(f"    E_adj أعلى 10%: {r['top_decile_e_adj']:+.4f}% (n={r['top_decile_n']})")
            print(f"    p_value={r['p_value']:.4f} (بعد BH)")
    else:
        print("  لا ميزات صامدة — كل الميزات إما غير دالة أو E_adj سالبة.")

    print()
    print(f"الميزات التي كانت تبدو قوية in-sample لكنها لم تصمد (وهم): {len(illusions)}")
    if illusions:
        for r in illusions[:5]:
            print(f"  {r['feature']}: IC_mean={r['ic_mean']:+.4f}, p={r['p_value']:.3f}, E_adj_top10%={r['top_decile_e_adj']:+.4f}%")

    print()
    print("== تفاصيل IC النوافذ (أفضل 10 ميزات بـ ICIR) ==")
    top10 = [r for r in wf_results
             if r.get('note') not in ('no_variance', 'insufficient_data', 'all_windows_skipped')][:10]
    for r in top10:
        windows_str = ", ".join(f"{v:+.3f}" for v in r.get('ic_per_window', []))
        print(f"  {r['feature']:30s}: [{windows_str}]  ICIR={r['icir']:+.3f}")

    # ── حفظ النتائج ──────────────────────────────────────────────────────
    output = {
        'run_date':         datetime.utcnow().isoformat(),
        'n_total':          n_total,
        'n_windows':        N_WF_WINDOWS,
        'train_ratio':      TRAIN_RATIO,
        'fee_pct':          FEE_PCT,
        'fdr_alpha':        FDR_ALPHA,
        'top_decile_frac':  TOP_DECILE_FRAC,
        'n_features':       n_feats,
        'surviving_count':  len(surviving),
        'illusion_count':   len(illusions),
        'surviving_features': [
            {
                'feature':         r['feature'],
                'icir':            r['icir'],
                'ic_mean':         r['ic_mean'],
                'ic_std':          r['ic_std'],
                'ic_per_window':   r['ic_per_window'],
                'p_value':         r['p_value'],
                'bh_rejected':     r.get('bh_rejected', False),
                'top_decile_e_adj': r['top_decile_e_adj'],
                'top_decile_n':    r['top_decile_n'],
            }
            for r in surviving
        ],
        'all_features': [
            {k: v for k, v in r.items() if k != 'ic_per_window'}
            for r in wf_results
            if r.get('note') not in ('no_variance', 'insufficient_data')
        ],
        'methodology': (
            f'Walk-Forward {N_WF_WINDOWS} نوافذ × OOS IC، '
            f'مُرتَّب بـ ICIR (IC_mean/IC_std)، '
            f'FDR BH alpha={FDR_ALPHA}، '
            f'E_adj بعد رسوم {FEE_PCT*100:.1f}% لأعلى {int(TOP_DECILE_FRAC*100)}%'
        ),
    }

    import decimal
    def safe_json(obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        raise TypeError(f'Not serializable: {type(obj)}')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=safe_json)

    print(f"\nالنتائج محفوظة في: {OUTPUT_FILE}")
    print("=" * 70)
    return output


if __name__ == '__main__':
    asyncio.run(run_strict_feature_lab())
