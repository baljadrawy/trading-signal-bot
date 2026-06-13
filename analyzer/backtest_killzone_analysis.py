"""
Killzone Analysis — ICT/SMC Timing Filter Test
==============================================
الهدف: اختبار فرضية أن فلتر ICT Killzone (London + NY AM) يحسّن E_adj
       بدون أي تعديل على scoring أو logic آخر.

المجموعات:
  - in_killzone: London 07:00-10:00 UTC + NY AM 12:00-15:00 UTC
  - outside_killzone: خارج الفترتين
  - sunday: يوم الأحد (اليوم 6 = Sunday في Python)

يعمل على: 2440 صفقة في trade_results + signals
لا يعدّل أي كود حيّ — تحليل بحثي فقط.
"""

import asyncio
import asyncpg
import json
import math
import statistics
import os
from datetime import datetime, timezone

# ─────────────────────────────────────────
# إعداد الاتصال بقاعدة البيانات
# ─────────────────────────────────────────
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "trading_signals")
DB_USER = os.getenv("POSTGRES_USER", "trading_signal_bot")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "")

FEE_RT = 0.003  # رسوم round-trip 0.3%


async def get_connection():
    return await asyncpg.connect(
        host=DB_HOST, port=DB_PORT,
        database=DB_NAME, user=DB_USER, password=DB_PASS
    )


# ─────────────────────────────────────────
# جلب البيانات الكاملة
# ─────────────────────────────────────────
async def fetch_all_trades(conn) -> list:
    """
    يجلب كل الصفقات المغلقة مع signal_time من جدول signals.
    يستخدم signal_time كتوقيت الإشارة (UTC).
    """
    sql = """
        SELECT
            s.id            AS signal_id,
            s.symbol,
            s.timeframe,
            s.signal_time   AS created_at,
            s.market_condition,
            s.score,
            tr.result,
            tr.profit_percent,
            tr.stop_hit,
            tr.profit_usdt
        FROM signals s
        JOIN trade_results tr ON tr.signal_id = s.id
        ORDER BY s.signal_time ASC;
    """
    rows = await conn.fetch(sql)
    result = []
    for row in rows:
        d = dict(row)
        # تأكد أن profit_percent هي float
        if d["profit_percent"] is not None:
            d["profit_percent"] = float(d["profit_percent"])
        else:
            d["profit_percent"] = 0.0
        if d["profit_usdt"] is not None:
            d["profit_usdt"] = float(d["profit_usdt"])
        else:
            d["profit_usdt"] = 0.0
        result.append(d)
    return result


# ─────────────────────────────────────────
# تصنيف الـ Killzone
# ─────────────────────────────────────────
def classify_killzone(dt: datetime) -> str:
    """
    dt: datetime بتوقيت UTC (قد تكون naive أو aware)
    يعيد: 'sunday' | 'in_killzone' | 'outside_killzone'
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    weekday = dt.weekday()  # 0=Mon ... 6=Sun
    hour = dt.hour          # 0-23 UTC

    if weekday == 6:
        return "sunday"

    # London Killzone: 07:00–10:00 UTC  (07 <= h < 10)
    in_london = 7 <= hour < 10
    # NY AM Killzone: 12:00–15:00 UTC  (12 <= h < 15)
    in_ny_am = 12 <= hour < 15

    if in_london or in_ny_am:
        return "in_killzone"
    return "outside_killzone"


# ─────────────────────────────────────────
# حساب المقاييس لمجموعة
# ─────────────────────────────────────────
def compute_metrics(trades: list) -> dict:
    if not trades:
        return {
            "n": 0, "n_win": 0, "n_loss": 0,
            "wr": 0.0, "e_adj": 0.0, "pf": None,
            "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "avg_raw_pct": 0.0
        }

    n = len(trades)
    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    n_win = len(wins)
    n_loss = len(losses)

    wr = n_win / n

    profits_pct = [t["profit_percent"] for t in trades]
    avg_raw = sum(profits_pct) / len(profits_pct)
    e_adj = avg_raw - FEE_RT * 100  # 0.3% => 0.3 units

    gross_win = sum(abs(t["profit_percent"]) for t in wins)
    gross_loss = sum(abs(t["profit_percent"]) for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else None

    avg_win_pct = (gross_win / n_win) if n_win > 0 else 0.0
    avg_loss_pct = (gross_loss / n_loss) if n_loss > 0 else 0.0

    return {
        "n": n,
        "n_win": n_win,
        "n_loss": n_loss,
        "wr": round(wr * 100, 2),
        "e_adj": round(e_adj, 4),
        "pf": round(pf, 3) if pf is not None else None,
        "avg_win_pct": round(avg_win_pct, 4),
        "avg_loss_pct": round(avg_loss_pct, 4),
        "avg_raw_pct": round(avg_raw, 4),
    }


# ─────────────────────────────────────────
# Independent t-test (Welch)
# ─────────────────────────────────────────
def normal_cdf(z: float) -> float:
    """CDF للتوزيع الطبيعي القياسي — Abramowitz & Stegun approx."""
    sign = 1 if z >= 0 else -1
    z = abs(z)
    t_val = 1 / (1 + 0.2316419 * z)
    poly = t_val * (0.319381530
                    + t_val * (-0.356563782
                    + t_val * (1.781477937
                    + t_val * (-1.821255978
                    + t_val * 1.330274429))))
    cdf = 1 - (1 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z) * poly
    if sign == 1:
        return cdf
    return 1 - cdf


def approximate_t_pvalue(t: float, df: float) -> float:
    """p-value تقريبي للـ t-statistic."""
    abs_t = abs(t)
    # Normal approximation (دقيق لـ df>=30، مقبول لأغراض بحثية لدى df أقل)
    z = abs_t * math.sqrt(df / (df + abs_t * abs_t))
    p = 2 * (1 - normal_cdf(abs_t))
    return min(max(p, 0.0001), 1.0)


def approximate_t_critical(df: float) -> float:
    """t-critical لـ alpha=0.025 (CI 95% two-tailed)."""
    table = [
        (1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571),
        (6, 2.447), (7, 2.365), (8, 2.306), (9, 2.262), (10, 2.228),
        (15, 2.131), (20, 2.086), (25, 2.060), (30, 2.042), (40, 2.021),
        (60, 2.000), (80, 1.990), (100, 1.984), (120, 1.980),
    ]
    for k, v in table:
        if df <= k:
            return v
    return 1.96


def welch_t_test(group_a: list, group_b: list) -> dict:
    """Welch t-test مستقل بين مجموعتين على profit_percent."""
    a = [t["profit_percent"] for t in group_a]
    b = [t["profit_percent"] for t in group_b]
    na, nb = len(a), len(b)

    if na < 2 or nb < 2:
        return {"t": None, "p_two_tailed": None, "df": None,
                "ci95": None, "note": "n صغير جداً"}

    mean_a = sum(a) / na
    mean_b = sum(b) / nb
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)

    se = math.sqrt(var_a / na + var_b / nb)
    if se < 1e-10:
        return {"t": 0.0, "p_two_tailed": 1.0, "df": na + nb - 2,
                "ci95": (0.0, 0.0), "mean_a": mean_a, "mean_b": mean_b,
                "diff": 0.0, "se": 0.0}

    t_stat = (mean_a - mean_b) / se

    # Welch-Satterthwaite df
    df_num = (var_a / na + var_b / nb) ** 2
    df_den = (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
    df = df_num / df_den if df_den > 1e-10 else na + nb - 2

    p_val = approximate_t_pvalue(t_stat, df)
    t_crit = approximate_t_critical(df)
    diff = mean_a - mean_b
    ci95 = (round(diff - t_crit * se, 4), round(diff + t_crit * se, 4))

    return {
        "mean_a": round(mean_a, 4),
        "mean_b": round(mean_b, 4),
        "diff": round(diff, 4),
        "se": round(se, 4),
        "t": round(t_stat, 3),
        "df": round(df, 1),
        "p_two_tailed": round(p_val, 4),
        "ci95": ci95,
    }


# ─────────────────────────────────────────
# Walk-Forward 60/40
# ─────────────────────────────────────────
def walk_forward_killzone(trades: list) -> dict:
    """تقسيم زمني 60/40: IS = أقدم 60%، OOS = أحدث 40%."""
    sorted_trades = sorted(trades, key=lambda t: t["created_at"])
    n = len(sorted_trades)
    split_idx = int(n * 0.6)

    is_trades = sorted_trades[:split_idx]
    oos_trades = sorted_trades[split_idx:]

    def split_kz(batch):
        kz = [t for t in batch if t["_kz"] == "in_killzone"]
        out = [t for t in batch if t["_kz"] == "outside_killzone"]
        return kz, out

    is_kz, is_out = split_kz(is_trades)
    oos_kz, oos_out = split_kz(oos_trades)

    def safe_date(t_list, idx):
        try:
            return t_list[idx]["created_at"].date().isoformat()
        except (IndexError, AttributeError):
            return None

    def kz_edge(kz, out):
        m_kz = compute_metrics(kz)
        m_out = compute_metrics(out)
        if kz and out:
            return round(m_kz["e_adj"] - m_out["e_adj"], 4)
        return None

    return {
        "IS": {
            "n_total": len(is_trades),
            "date_range": [safe_date(is_trades, 0), safe_date(is_trades, -1)],
            "in_killzone": compute_metrics(is_kz),
            "outside_killzone": compute_metrics(is_out),
            "kz_edge": kz_edge(is_kz, is_out),
        },
        "OOS": {
            "n_total": len(oos_trades),
            "date_range": [safe_date(oos_trades, 0), safe_date(oos_trades, -1)],
            "in_killzone": compute_metrics(oos_kz),
            "outside_killzone": compute_metrics(oos_out),
            "kz_edge": kz_edge(oos_kz, oos_out),
        },
    }


# ─────────────────────────────────────────
# فلتر شريحة الحافة
# ─────────────────────────────────────────
def is_edge_slice(trade: dict) -> bool:
    """1d + bearish/sideways + score=3"""
    return (
        trade["timeframe"] == "1d"
        and trade["market_condition"] in ("bearish", "sideways")
        and int(trade["score"]) == 3
    )


# ─────────────────────────────────────────
# البرنامج الرئيسي
# ─────────────────────────────────────────
async def main():
    print("=" * 65)
    print("  Killzone Analysis — ICT/SMC Timing Filter Test")
    print(f"  تاريخ التشغيل: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    conn = await get_connection()
    trades_raw = await fetch_all_trades(conn)
    await conn.close()

    print(f"\n[جلب البيانات] إجمالي الصفقات: {len(trades_raw)}")

    # ── تصنيف كل صفقة ──
    for t in trades_raw:
        t["_kz"] = classify_killzone(t["created_at"])

    # ── إحصاء المجموعات ──
    groups = {}
    for label in ("in_killzone", "outside_killzone", "sunday"):
        groups[label] = [t for t in trades_raw if t["_kz"] == label]

    print(f"\n[توزيع المجموعات]")
    for label, g in groups.items():
        print(f"  {label}: n={len(g)}")

    # ── 1. مقاييس كل مجموعة ──
    print("\n" + "=" * 65)
    print("  الجزء 1 — مقاييس المجموعات الأربع")
    print("=" * 65)

    metrics = {}
    for k, v in groups.items():
        metrics[k] = compute_metrics(v)
    non_sunday = [t for t in trades_raw if t["_kz"] != "sunday"]
    metrics["non_sunday_all"] = compute_metrics(non_sunday)
    all_m = compute_metrics(trades_raw)

    print(f"\n  {'مجموعة':<25} {'n':>5} {'WR%':>7} {'E_adj%':>8} {'PF':>6} {'avg_win%':>9} {'avg_loss%':>10}")
    print("  " + "-" * 72)
    for label in ["in_killzone", "outside_killzone", "sunday", "non_sunday_all"]:
        m = metrics[label]
        pf_s = f"{m['pf']:.3f}" if m["pf"] else "N/A"
        print(f"  {label:<25} {m['n']:>5} {m['wr']:>7.2f} {m['e_adj']:>8.4f} "
              f"{pf_s:>6} {m['avg_win_pct']:>9.4f} {m['avg_loss_pct']:>10.4f}")

    # ── 2. t-test: Killzone vs خارجها ──
    print("\n" + "=" * 65)
    print("  الجزء 2 — Killzone vs خارجها (Welch t-test + CI 95%)")
    print("=" * 65)

    kz_group = groups["in_killzone"]
    out_group = groups["outside_killzone"]
    ttest = welch_t_test(kz_group, out_group)
    diff_e_adj = metrics["in_killzone"]["e_adj"] - metrics["outside_killzone"]["e_adj"]

    print(f"\n  Killzone E_adj  = {metrics['in_killzone']['e_adj']:.4f}%")
    print(f"  Outside  E_adj  = {metrics['outside_killzone']['e_adj']:.4f}%")
    print(f"  فرق (KZ - Out)  = {diff_e_adj:+.4f}%")
    print(f"\n  Welch t-test:")
    print(f"    t          = {ttest.get('t')}")
    print(f"    df         = {ttest.get('df')}")
    print(f"    p (2-tail) = {ttest.get('p_two_tailed')}")
    print(f"    CI 95%     = {ttest.get('ci95')}  (الوحدة: %)")

    # ── 3. تأثير استبعاد الأحد ──
    print("\n" + "=" * 65)
    print("  الجزء 3 — تأثير استبعاد الأحد")
    print("=" * 65)

    sun_m = metrics["sunday"]
    ns_m = metrics["non_sunday_all"]
    print(f"\n  الكل (مع الأحد):  n={all_m['n']},  E_adj={all_m['e_adj']:.4f}%")
    print(f"  بدون الأحد:       n={ns_m['n']},  E_adj={ns_m['e_adj']:.4f}%")
    print(f"  الأحد وحده:       n={sun_m['n']},  WR={sun_m['wr']:.2f}%,  E_adj={sun_m['e_adj']:.4f}%")
    delta_sun = ns_m["e_adj"] - all_m["e_adj"]
    print(f"  أثر حذف الأحد على E_adj: {delta_sun:+.4f}%")

    # ── 4. شريحة الحافة ──
    print("\n" + "=" * 65)
    print("  الجزء 4 — شريحة الحافة (1d + bearish/sideways + score=3)")
    print("=" * 65)

    edge_trades = [t for t in trades_raw if is_edge_slice(t)]
    edge_kz = [t for t in edge_trades if t["_kz"] == "in_killzone"]
    edge_out = [t for t in edge_trades if t["_kz"] == "outside_killzone"]
    edge_sun = [t for t in edge_trades if t["_kz"] == "sunday"]

    em_all = compute_metrics(edge_trades)
    em_kz = compute_metrics(edge_kz)
    em_out = compute_metrics(edge_out)
    em_sun = compute_metrics(edge_sun)

    print(f"\n  الحافة الكلية: n={em_all['n']}, WR={em_all['wr']:.2f}%, E_adj={em_all['e_adj']:.4f}%")
    print(f"\n  {'مجموعة':<25} {'n':>5} {'WR%':>7} {'E_adj%':>8}")
    print("  " + "-" * 46)
    for label, em in [("1d+bearish/sw - KZ", em_kz),
                       ("1d+bearish/sw - خارج", em_out),
                       ("1d+bearish/sw - أحد", em_sun)]:
        wr_s = f"{em['wr']:.2f}" if em["n"] > 0 else "N/A"
        e_s = f"{em['e_adj']:.4f}" if em["n"] > 0 else "N/A"
        print(f"  {label:<25} {em['n']:>5} {wr_s:>7} {e_s:>8}")

    edge_diff = None
    if em_kz["n"] > 0 and em_out["n"] > 0:
        edge_diff = em_kz["e_adj"] - em_out["e_adj"]
        print(f"\n  فرق E_adj داخل الحافة (KZ - Out): {edge_diff:+.4f}%")
        print(f"  فرق E_adj الكلي  (KZ - Out):       {diff_e_adj:+.4f}%")
        if edge_diff > diff_e_adj:
            print("  → التحسين أقوى داخل شريحة الحافة (إشارة واعدة)")
        elif edge_diff > 0:
            print("  → التحسين موجود في الحافة لكن أضعف من الكلي")
        else:
            print("  → Killzone يضرّ الحافة أو محايد")

    # ── 5. Walk-Forward 60/40 ──
    print("\n" + "=" * 65)
    print("  الجزء 5 — Walk-Forward 60/40")
    print("=" * 65)

    wf = walk_forward_killzone(trades_raw)
    for phase in ["IS", "OOS"]:
        p = wf[phase]
        kz_e = p["in_killzone"]["e_adj"]
        out_e = p["outside_killzone"]["e_adj"]
        kz_n = p["in_killzone"]["n"]
        out_n = p["outside_killzone"]["n"]
        edge_v = p["kz_edge"]
        print(f"\n  [{phase}] n={p['n_total']}, تاريخ: {p['date_range'][0]} → {p['date_range'][1]}")
        print(f"    in_killzone:       n={kz_n}, E_adj={kz_e:.4f}%")
        print(f"    outside_killzone:  n={out_n}, E_adj={out_e:.4f}%")
        edge_s = f"{edge_v:+.4f}%" if edge_v is not None else "N/A"
        print(f"    KZ edge (KZ-Out):  {edge_s}")

    is_edge_v = wf["IS"]["kz_edge"]
    oos_edge_v = wf["OOS"]["kz_edge"]
    print()
    if is_edge_v is not None and oos_edge_v is not None:
        print(f"  IS edge:  {is_edge_v:+.4f}%")
        print(f"  OOS edge: {oos_edge_v:+.4f}%")
        if (is_edge_v > 0) == (oos_edge_v > 0):
            print("  → الاتجاه متسق IS/OOS — الأثر محتمل")
        else:
            print("  → الأثر يتعكس IS→OOS — غير مستقر")

    # ── 6. تفصيل London vs NY AM ──
    print("\n" + "=" * 65)
    print("  الجزء 6 — تفصيل London vs NY AM (ساعات UTC)")
    print("=" * 65)

    def is_london(t):
        dt = t["created_at"]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.weekday() != 6 and 7 <= dt.hour < 10

    def is_ny_am(t):
        dt = t["created_at"]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.weekday() != 6 and 12 <= dt.hour < 15

    m_lon = compute_metrics([t for t in trades_raw if is_london(t)])
    m_ny = compute_metrics([t for t in trades_raw if is_ny_am(t)])

    print(f"\n  {'جلسة':<25} {'n':>5} {'WR%':>7} {'E_adj%':>8} {'PF':>6}")
    print("  " + "-" * 54)
    for lbl, m in [("London  07-10 UTC", m_lon),
                    ("NY AM   12-15 UTC", m_ny),
                    ("خارج الكل", metrics["outside_killzone"])]:
        pf_s = f"{m['pf']:.3f}" if m["pf"] else "N/A"
        print(f"  {lbl:<25} {m['n']:>5} {m['wr']:>7.2f} {m['e_adj']:>8.4f} {pf_s:>6}")

    # ── 7. الملخص والحكم ──
    print("\n" + "=" * 65)
    print("  الملخص والحكم الإحصائي")
    print("=" * 65)

    p_val = ttest.get("p_two_tailed")
    ci = ttest.get("ci95")
    significant = p_val is not None and p_val < 0.05
    positive = diff_e_adj > 0

    print(f"\n  إجمالي الصفقات: {len(trades_raw)}")
    print(f"  نافذة الاختبار: 2026-04-08 → 2026-05-18")
    print()
    print(f"  الكل:           WR={all_m['wr']:.2f}%,  E_adj={all_m['e_adj']:.4f}%")
    print(f"  Killzone:       WR={metrics['in_killzone']['wr']:.2f}%,  E_adj={metrics['in_killzone']['e_adj']:.4f}%")
    print(f"  خارج Killzone:  WR={metrics['outside_killzone']['wr']:.2f}%,  E_adj={metrics['outside_killzone']['e_adj']:.4f}%")
    print()
    print(f"  فرق E_adj (KZ-Out): {diff_e_adj:+.4f}%")
    print(f"  p-value:            {p_val}")
    print(f"  CI 95%:             {ci}")
    print()

    if significant and positive:
        verdict = "POSITIVE_SIGNIFICANT"
        print("  [حكم] الأثر دال إحصائياً وإيجابي — Killzone يُحسّن الأداء")
    elif significant and not positive:
        verdict = "NEGATIVE_SIGNIFICANT"
        print("  [حكم] الأثر دال إحصائياً لكن سلبي — Killzone يضرّ الأداء")
    elif not significant and positive:
        verdict = "POSITIVE_NOT_SIGNIFICANT"
        print("  [حكم] فرق إيجابي لكن غير دال — قد يكون صدفة (p={:.3f})".format(p_val or 99))
    else:
        verdict = "NEGATIVE_NOT_SIGNIFICANT"
        print("  [حكم] فرق سلبي وغير دال — لا أثر لـ Killzone")

    print(f"\n  [verdict] {verdict}")

    # ── حفظ JSON ──
    def safe_serialize(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    results = {
        "run_date": datetime.now().isoformat(),
        "n_total": len(trades_raw),
        "all_trades": all_m,
        "groups": {k: metrics[k] for k in ["in_killzone", "outside_killzone", "sunday", "non_sunday_all"]},
        "t_test_kz_vs_out": ttest,
        "diff_e_adj_kz_minus_out": diff_e_adj,
        "delta_sunday_removal": delta_sun,
        "edge_slice": {
            "total": em_all,
            "in_killzone": em_kz,
            "outside_killzone": em_out,
            "sunday": em_sun,
            "diff_e_adj": edge_diff,
        },
        "walk_forward": wf,
        "sessions": {
            "london_07_10": m_lon,
            "ny_am_12_15": m_ny,
        },
        "verdict": verdict,
    }

    out_path = "/app/backtest_results_killzone.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=safe_serialize)

    print(f"\n  [نتائج محفوظة] {out_path}")
    print("=" * 65)

    return verdict, results


if __name__ == "__main__":
    asyncio.run(main())
