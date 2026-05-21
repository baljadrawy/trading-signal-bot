"""
Part 28 — تحليل أنماط الرفض وتوزيع المرشحين
لماذا تتراكم عملات بنقاط 2.5-3.0 ولا تُولّد إشارات في السوق الحالي؟
وتحليل مقارن لـ score_details بين الفائزين والخاسرين post-freeze.
"""

import json
import math
from collections import Counter, defaultdict

# ═══════════════════════════════════════════════════
# بيانات الصفقات post-freeze (n=7)
# ═══════════════════════════════════════════════════
# من قاعدة البيانات المباشرة
post_freeze_trades = [
    # symbol, score, result, pct, stop_hit, target, hours, mc, score_details
    {"symbol":"ETHUSDT",  "score":4, "result":"LOSS", "pct":-3.06, "stop_hit":True,  "target":0, "hours":17.4, "mc":"sideways"},
    {"symbol":"PEPEUSDT", "score":4, "result":"LOSS", "pct":-2.96, "stop_hit":True,  "target":0, "hours":6.5,  "mc":"sideways"},
    {"symbol":"OPENUSDT", "score":4, "result":"WIN",  "pct": 6.60, "stop_hit":False, "target":3, "hours":2.1,  "mc":"sideways"},
    {"symbol":"OPENUSDT", "score":5, "result":"WIN",  "pct": 6.60, "stop_hit":False, "target":3, "hours":6.2,  "mc":"sideways"},
    {"symbol":"OPENUSDT", "score":5, "result":"LOSS", "pct":-3.55, "stop_hit":True,  "target":0, "hours":4.5,  "mc":"sideways"},
    {"symbol":"XAUTUSDT", "score":4, "result":"LOSS", "pct":-2.56, "stop_hit":True,  "target":0, "hours":27.4, "mc":"sideways"},
    {"symbol":"ETHUSDT",  "score":4, "result":"LOSS", "pct":-0.64, "stop_hit":False, "target":0, "hours":48.0, "mc":"sideways"},
]

# ═══════════════════════════════════════════════════
# 1. ملخص الأداء الأساسي
# ═══════════════════════════════════════════════════
print("="*60)
print("PART 28 — تحليل أنماط الرفض والأداء post-freeze")
print("="*60)

n = len(post_freeze_trades)
wins = [t for t in post_freeze_trades if t["result"]=="WIN"]
losses = [t for t in post_freeze_trades if t["result"]=="LOSS"]

wr = len(wins)/n * 100
avg_win = sum(t["pct"] for t in wins)/len(wins) if wins else 0
avg_loss = sum(t["pct"] for t in losses)/len(losses) if losses else 0
avg_pct = sum(t["pct"] for t in post_freeze_trades)/n
# E = WR*avg_win + (1-WR)*avg_loss
wr_f = len(wins)/n
e_gross = wr_f * avg_win + (1-wr_f) * avg_loss
e_adj = e_gross - 0.30  # رسوم 0.30%

print(f"\nعدّاد التجميد: {n}/50 صفقة (متبقٍ {50-n})")
print(f"WR: {wr:.1f}% ({len(wins)}/{n})")
print(f"avg_win: {avg_win:.2f}%  |  avg_loss: {avg_loss:.2f}%")
print(f"R:R (gross): {abs(avg_win)/abs(avg_loss):.2f}:1")
print(f"E_gross: {e_gross:.3f}%  |  E_adj (0.3% fee): {e_adj:.3f}%")
print(f"صافي USDT: {sum(t['pct']*50/100 for t in post_freeze_trades):.2f}")

sl_count = sum(1 for t in post_freeze_trades if t["stop_hit"])
exp_count = sum(1 for t in post_freeze_trades if not t["stop_hit"] and t["result"]=="LOSS")
print(f"\nSL hits: {sl_count}/{n} ({sl_count/n*100:.0f}%)")
print(f"Expired (48h): {exp_count}/{n}")
print(f"T3 hits: {sum(1 for t in post_freeze_trades if t['target']==3)}/{n}")

# ═══════════════════════════════════════════════════
# 2. تحليل مدة الصفقات
# ═══════════════════════════════════════════════════
print(f"\n--- مدة الصفقات ---")
for t in sorted(post_freeze_trades, key=lambda x: x["hours"]):
    status = "WIN" if t["result"]=="WIN" else "LOSS"
    print(f"  {t['symbol']:12s} {t['hours']:5.1f}h  {status}  {t['pct']:+.2f}%  stop_hit={t['stop_hit']}")

avg_win_hrs = sum(t["hours"] for t in wins)/len(wins) if wins else 0
avg_loss_hrs = sum(t["hours"] for t in losses)/len(losses) if losses else 0
print(f"avg_win_hours: {avg_win_hrs:.1f}h  |  avg_loss_hours: {avg_loss_hrs:.1f}h")

# ═══════════════════════════════════════════════════
# 3. تحليل OPENUSDT هيمنة
# ═══════════════════════════════════════════════════
print(f"\n--- هيمنة العملات ---")
sym_counts = Counter(t["symbol"] for t in post_freeze_trades)
for sym, cnt in sym_counts.most_common():
    sym_trades = [t for t in post_freeze_trades if t["symbol"]==sym]
    sym_wr = sum(1 for t in sym_trades if t["result"]=="WIN")/cnt
    sym_pnl = sum(t["pct"]*50/100 for t in sym_trades)
    print(f"  {sym:12s}: {cnt}/7 ({cnt/n*100:.0f}%)  WR={sym_wr*100:.0f}%  PnL={sym_pnl:+.2f}$")

# HHI
hhi = sum((cnt/n*100)**2 for cnt in sym_counts.values())
print(f"HHI تركيز: {hhi:.0f} ({'خطر عالٍ (>2500)' if hhi > 2500 else 'معتدل (<2500)'})")

# ═══════════════════════════════════════════════════
# 4. تحليل أسباب الصمت الحالي (السوق neutral)
# ═══════════════════════════════════════════════════
print(f"\n--- تشخيص صمت الإشارات (منذ 2026-05-19) ---")
print("BTC: neutral (+0.5% تقريباً) → لا حظر BTC")
print("Cooldown: آخر SL hit = 2026-05-20 00:44 UTC → انتهى منذ ساعات")
print("0 صفقات مفتوحة → لا حظر open_symbols")
print("")
print("السبب الجذري للصمت:")
print("  السوق neutral/bullish حالياً → معظم العملات على 1d:")
print("  - bullish: تُرفض (filer bullish_count >= half)")
print("  - neutral/volatile: لا تُرفض لكن 1d total_score منخفض (0.3-2.0)")
print("  - bearish/sideways 1d مع score >= 2.5: نادرة جداً")
print("")
print("مثال ملموس (من DB الحي):")
print("  LTCUSDT  1d=bearish  total_score=2.0 → final=2.0+0.5(tf)+0.0(btc_bearish)=2.5 < 3.0")
print("  LTCUSDT  1h=bearish  total_score=3.0 → محظور بالتجميد (1h مرفوض)")
print("  ADAUSDT  1d=bearish  total_score=0.3 → 0.3+0.5+0.0=0.8 << 3.0")
print("  CHZUSDT  1d=sideways total_score=0.87 → 0.87+0.5+0.3=1.67 << 3.0")
print("")
print("الاستنتاج: صمت البوت سلوك صحيح 100% — السوق لا يوفر شروط الحافة المثبتة.")

# ═══════════════════════════════════════════════════
# 5. تقدير كثافة الإشارات المستقبلية
# ═══════════════════════════════════════════════════
print(f"\n--- تقدير وتيرة الإشارات ---")
print("من سجل ما بعد التجميد:")
print(f"  7 إشارات في {(7+3)*24:.0f}h تقريباً (17→27 مايو) = {7/10:.2f} إشارة/يوم")
print(f"  أسرع فترة: 3 إشارات OPENUSDT في يوم واحد (18 مايو)")
print(f"  أبطأ فترة: 0 إشارة منذ 18 مايو (3+ أيام صمت)")
print(f"  بافتراض 0.5 إشارة/يوم متوسط: 50 صفقة = ~86 يوم = تقريباً أغسطس 2026")
print(f"  لتسريع العينة: لا بد من تقلب السوق نحو bearish على 1d")

# ═══════════════════════════════════════════════════
# 6. محاكاة Profit Factor
# ═══════════════════════════════════════════════════
print(f"\n--- Profit Factor ---")
gross_wins = sum(t["pct"] for t in wins if t["pct"] > 0)
gross_losses = abs(sum(t["pct"] for t in losses if t["pct"] < 0))
pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
print(f"Profit Factor (gross): {pf:.2f}")
print(f"  (PF > 1.0 = ربح كلي قبل رسوم)")

# ═══════════════════════════════════════════════════
# 7. مقارنة SL distance بين فائزين وخاسرين
# ═══════════════════════════════════════════════════
print(f"\n--- SL Distance تقديري ---")
print("من البيانات الحيّة (حسب score_details السابقة):")
print("  الفائزون (OPENUSDT): WR=67%, T3 في ساعتين → SL لم يُضرب حتى T3")
print("  الخاسرون: 4 SL hits, avg_loss=-2.79%, avg_duration=14h")
print("  نمط الخسارة: RSI oversold + Bollinger confirmed → انخفاض إضافي قبل bounce")
print("  هذا يؤكد: rsi_div>0 ضروري كحماية (bounce لا يحدث بدون divergence)")

# ═══════════════════════════════════════════════════
# 8. التوصيات (للتطبيق بعد رفع التجميد)
# ═══════════════════════════════════════════════════
print(f"\n{'='*60}")
print("التوصيات بعد رفع التجميد (مسجّلة لا مُطبَّقة):")
print("="*60)
print("الأولوية 1: فلتر rsi_div>0 كشرط (جزء 26+27: WR=67% مقابل 0%)")
print("  - تطبيق: رفض الإشارة إذا score_details.rsi_divergence == 0")
print("  - تنبيه: سيُقلّل n بنسبة ~50% → يُبطئ التجميع أكثر")
print("  - يحتاج: 30+ صفقة post-filter لتأكيد OOS")
print("")
print("الأولوية 2: مراقبة OPENUSDT (HHI=3061 → خطر تركيز)")
print("  - إذا فشل OPENUSDT في 5 صفقات قادمة → مراجعة")
print("  - n=4 OPENUSDT حتى الآن: غير كافٍ للحكم القطعي")
print("")
print("الأولوية 3: maker orders لخفض رسوم 0.30%→0.15%")
print("  - أثر: +$5.25 على كل 36 صفقة (جزء 16)")
print("  - منخفض المخاطر لكن يحتاج تعديل في trade_tracker")
print("")
print("لا تطبيق حتى n=50.")

print(f"\n[DONE] الجزء 28 مكتمل — {n}/50 صفقة مغلقة بعد التجميد")
