"""
ICT Validation Screen — اختبار حاسم رخيص قبل بناء نظام ICT الكامل
==================================================================
الفرضية المُختبرة (التي حسمها المراجع كالوحيدة المحتملة):
  هل تركيبة الناجين الهندسيين من part33 (target_width / sl_distance / score)
  تعزل شريحة ذات expectancy موجب صافٍ بعد رسوم 0.3% — بفترة ثقة تتجاوز الصفر؟

المنهج (متعمَّد التفاؤل = in-sample best):
  نبحث grid كامل عن أفضل شريحة ممكنة (n>=MIN_N) باختيار رجعي كامل.
  لو فشل هذا السقف المتفائل → كَيْل نظيف. لو نجح → يبرّر بناء OOS صارم.

العتبة المسجّلة مسبقاً (قبل رؤية النتيجة):
  PASS = الحد الأدنى لفترة الثقة 95% لـ (net expectancy %) > 0.
  لا حزم جديدة. بيانات موجودة فقط. لا سحب API. لا حمل على الخادم.
"""
import asyncio, json, sys
from collections import namedtuple
sys.path.insert(0, '/app'); sys.path.insert(0, '/app/shared')
import numpy as np
from shared.database import Database

FEE_RT_PCT = 0.30          # رسوم ذهاب+إياب على Binance spot (تقدير متحفظ)
MIN_N = 100                # أصغر شريحة مقبولة إحصائياً
N_BOOT = 10000
RNG = np.random.RandomState(7)


async def load():
    await Database.connect()
    rows = await Database.fetch("""
        SELECT s.entry_price, s.target_1, s.stop_loss, s.score,
               s.timeframe, tr.result, tr.profit_percent
        FROM signals s JOIN trade_results tr ON tr.signal_id=s.id
        WHERE tr.result IN ('WIN','LOSS')
          AND s.entry_price>0 AND s.stop_loss>0 AND s.target_1>0
        ORDER BY s.signal_time ASC
    """)
    return rows


def boot_ci(x, n=N_BOOT):
    x = np.asarray(x, float)
    means = x[RNG.randint(0, len(x), size=(n, len(x)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main():
    rows = asyncio.get_event_loop().run_until_complete(load())
    n = len(rows)
    entry = np.array([float(r['entry_price']) for r in rows])
    tgt   = np.array([float(r['target_1']) for r in rows])
    sl    = np.array([float(r['stop_loss']) for r in rows])
    score = np.array([float(r['score']) for r in rows])
    win   = np.array([1 if r['result']=='WIN' else 0 for r in rows])
    pnl   = np.array([float(r['profit_percent'] or 0.0) for r in rows])  # % محقق
    net   = pnl - FEE_RT_PCT                                              # صافٍ بعد الرسوم

    tgt_w = (tgt-entry)/entry*100.0     # عرض الهدف %
    sl_d  = (entry-sl)/entry*100.0      # مسافة الستوب %
    rr    = np.where(sl_d>0, tgt_w/sl_d, np.nan)

    base_wr = win.mean()*100
    avg_rr  = np.nanmedian(rr)
    # ترجمة هدف 70% WR إلى expectancy ضمني (نموذج R: win=+rr, loss=-1, ناقص رسوم)
    fee_R = FEE_RT_PCT/np.nanmedian(sl_d)  # الرسوم بوحدات R
    e70_R = 0.70*avg_rr - 0.30*1 - fee_R
    be_wr = (1+fee_R)/(avg_rr+1)*100       # WR التعادل عند R:R الوسيط

    print(f"=== BASELINE (n={n}, {rows[0] and ''}) ===")
    print(f"base WR              = {base_wr:.1f}%")
    print(f"median R:R (T1)      = {avg_rr:.2f}")
    print(f"median SL dist       = {np.nanmedian(sl_d):.2f}%")
    print(f"avg realized PnL     = {pnl.mean():.4f}%   net of fee = {net.mean():.4f}%")
    print(f"break-even WR @R:R   = {be_wr:.1f}%   (need this just to not lose)")
    print(f"target 70% WR  =>  implied expectancy = {e70_R:+.3f} R  (the user's claim)")
    print(f"PRE-REGISTERED PASS BAR: best in-sample subset (n>={MIN_N}) bootstrap CI-low(net%) > 0")
    print()

    # ── grid على الناجين الهندسيين: نبحث أفضل شريحة متفائلة ──
    rr_grid    = np.nanpercentile(rr[~np.isnan(rr)], [0,20,40,50,60,70,80,90])
    sl_grid    = np.nanpercentile(sl_d, [0,20,40,60,80,90])
    score_grid = sorted(set(np.percentile(score,[0,50,70,80,90,95]).round(2)))

    best = None
    Cand = namedtuple('Cand','net_mean ci_lo ci_hi wr n rr_min sl_max sc_min')
    for rmin in rr_grid:
        for smax in sl_grid:
            for scmin in score_grid:
                m = (rr>=rmin) & (sl_d<=smax) & (score>=scmin) & ~np.isnan(rr)
                k = int(m.sum())
                if k < MIN_N:
                    continue
                nm = net[m].mean()
                if best is None or nm > best.net_mean:
                    lo, hi = boot_ci(net[m])
                    best = Cand(nm, lo, hi, win[m].mean()*100, k,
                               float(rmin), float(smax), float(scmin))

    print("=== BEST IN-SAMPLE SUBSET (full hindsight, optimistic ceiling) ===")
    if best is None:
        print("no subset reached MIN_N — insufficient power")
    else:
        print(f"filter: R:R>={best.rr_min:.2f}  SLdist<={best.sl_max:.2f}%  score>={best.sc_min:.2f}")
        print(f"n={best.n}  WR={best.wr:.1f}%  net expectancy={best.net_mean:+.4f}%")
        print(f"bootstrap 95% CI (net %) = [{best.ci_lo:+.4f}, {best.ci_hi:+.4f}]")
        verdict = "PASS — justifies rigorous OOS/ICT-native build" if best.ci_lo>0 \
                  else "FAIL — even the optimistic ceiling cannot clear fees"
        print(f"VERDICT: {verdict}")

    out = {"n":n,"base_wr":round(base_wr,2),"median_rr":round(float(avg_rr),3),
           "be_wr":round(float(be_wr),2),"net_mean_all":round(float(net.mean()),4),
           "best":(best._asdict() if best else None),"fee_rt_pct":FEE_RT_PCT}
    with open('/app/ict_validation_screen.json','w') as f:
        json.dump(out, f, indent=2, default=float)
    print("\nsaved -> analyzer/ict_validation_screen.json")


if __name__ == '__main__':
    main()
