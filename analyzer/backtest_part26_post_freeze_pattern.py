#!/usr/bin/env python3
"""
Part 26 — Post-Freeze Pattern Deep Dive (n=7)
تحليل أنماط الفائزين/الخاسرين بعد التجميد بناءً على score_details
هدف: تحديد أي المؤشرات الفعلية تُفرّق الفائز من الخاسر في n=7 post-freeze
"""

import json

# البيانات الكاملة لـ n=7 post-freeze (من DB مباشرة)
trades = [
    {
        "symbol": "ETHUSDT", "result": "LOSS", "profit_pct": -3.0615,
        "stop_hit": True, "target_reached": 0,
        "details": {"rsi": 1.0, "bollinger": 1.0, "fibonacci": 1.13, "stoch_rsi": 0,
                    "order_book": 0.5, "rsi_divergence": 0, "obv": 0, "macd": 0, "volume": 0}
    },
    {
        "symbol": "PEPEUSDT", "result": "LOSS", "profit_pct": -2.9570,
        "stop_hit": True, "target_reached": 0,
        "details": {"rsi": 1.0, "bollinger": 1.0, "fibonacci": 1.13, "stoch_rsi": 0,
                    "order_book": 0.5, "rsi_divergence": 0, "obv": 0, "macd": 0, "volume": 0}
    },
    {
        "symbol": "OPENUSDT", "result": "WIN", "profit_pct": 6.6,
        "stop_hit": False, "target_reached": 3,
        "details": {"rsi": 0.3, "bollinger": 0, "fibonacci": 0.0, "stoch_rsi": 0.94,
                    "order_book": 0.7, "rsi_divergence": 2.0, "obv": 0, "macd": 0, "volume": 0}
    },
    {
        "symbol": "OPENUSDT", "result": "WIN", "profit_pct": 6.6,
        "stop_hit": False, "target_reached": 3,
        "details": {"rsi": 0, "bollinger": 0, "fibonacci": 0.57, "stoch_rsi": 0.94,
                    "order_book": 0.7, "rsi_divergence": 2.0, "obv": 0, "macd": 0, "volume": 0}
    },
    {
        "symbol": "OPENUSDT", "result": "LOSS", "profit_pct": -3.5519,
        "stop_hit": True, "target_reached": 0,
        "details": {"rsi": 0, "bollinger": 0, "fibonacci": 0.57, "stoch_rsi": 0.94,
                    "order_book": 0.7, "rsi_divergence": 2.0, "obv": 0, "macd": 0, "volume": 0}
    },
    {
        "symbol": "XAUTUSDT", "result": "LOSS", "profit_pct": -2.5577,
        "stop_hit": True, "target_reached": 0,
        "details": {"rsi": 0.3, "bollinger": 0, "fibonacci": 1.13, "stoch_rsi": 0,
                    "order_book": 0.5, "rsi_divergence": 2.0, "obv": 0, "macd": 0, "volume": 0}
    },
    {
        "symbol": "ETHUSDT", "result": "LOSS", "profit_pct": -0.6449,
        "stop_hit": False, "target_reached": 0,
        "details": {"rsi": 1.0, "bollinger": 1.0, "fibonacci": 1.13, "stoch_rsi": 0,
                    "order_book": 0.3, "rsi_divergence": 0, "obv": 0, "macd": 0, "volume": 0}
    },
]

wins = [t for t in trades if t["result"] == "WIN"]
losses = [t for t in trades if t["result"] == "LOSS"]

print("=" * 60)
print("PART 26 — POST-FREEZE PATTERN ANALYSIS (n=7)")
print("=" * 60)
print(f"\nWins: {len(wins)} | Losses: {len(losses)} | WR: {len(wins)/len(trades)*100:.1f}%")

avg_win = sum(t["profit_pct"] for t in wins) / len(wins) if wins else 0
avg_loss = sum(t["profit_pct"] for t in losses) / len(losses) if losses else 0
total_pnl = sum(t["profit_pct"] for t in trades)
# R:R
rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
expectancy = (len(wins)/len(trades)) * avg_win + (len(losses)/len(trades)) * avg_loss

print(f"avg_win: {avg_win:.3f}% | avg_loss: {avg_loss:.3f}%")
print(f"R:R = {rr:.2f}:1 | Expectancy = {expectancy:.3f}%")
print(f"Total PnL (sum %): {total_pnl:.3f}%")

# تحليل كل مؤشر: متوسط الفائزين vs الخاسرين
indicators = ["rsi", "bollinger", "fibonacci", "stoch_rsi", "order_book", "rsi_divergence"]
print("\n--- مقارنة المؤشرات: Wins vs Losses ---")
print(f"{'مؤشر':<20} {'avg_win':>10} {'avg_loss':>10} {'Delta':>10} {'تفسير'}")
print("-" * 65)

findings = []
for ind in indicators:
    win_vals = [t["details"][ind] for t in wins]
    loss_vals = [t["details"][ind] for t in losses]
    avg_w = sum(win_vals) / len(win_vals) if win_vals else 0
    avg_l = sum(loss_vals) / len(loss_vals) if loss_vals else 0
    delta = avg_w - avg_l
    direction = "WIN يرتفع" if delta > 0 else "LOSS يرتفع"
    print(f"{ind:<20} {avg_w:>10.3f} {avg_l:>10.3f} {delta:>10.3f}  {direction}")
    findings.append((ind, delta, avg_w, avg_l))

# الأكثر تمييزاً
findings_sorted = sorted(findings, key=lambda x: abs(x[1]), reverse=True)
print("\n--- المؤشرات الأكثر تمييزاً (|Delta|) ---")
for i, (ind, delta, aw, al) in enumerate(findings_sorted):
    print(f"{i+1}. {ind}: delta={delta:+.3f} (W={aw:.3f}, L={al:.3f})")

# نمط الفائزين الصريح
print("\n--- نمط الفائزين (الصفقتان الرابحتان) ---")
for t in wins:
    key_inds = {k: v for k, v in t["details"].items() if v > 0}
    print(f"  {t['symbol']} +{t['profit_pct']:.1f}%: {key_inds}")

# نمط الخاسرين
print("\n--- نمط الخاسرين الخمسة ---")
for t in losses:
    key_inds = {k: v for k, v in t["details"].items() if v > 0}
    print(f"  {t['symbol']} {t['profit_pct']:.2f}%: {key_inds}")

# تحليل خاص: rsi_divergence
rsi_div_present = [t for t in trades if t["details"]["rsi_divergence"] > 0]
rsi_div_absent = [t for t in trades if t["details"]["rsi_divergence"] == 0]
print(f"\n--- rsi_divergence>0: n={len(rsi_div_present)} ---")
if rsi_div_present:
    wr_div = sum(1 for t in rsi_div_present if t["result"] == "WIN") / len(rsi_div_present) * 100
    print(f"  WR={wr_div:.1f}% | صفقات: {[t['symbol'] for t in rsi_div_present]}")
print(f"--- rsi_divergence=0: n={len(rsi_div_absent)} ---")
if rsi_div_absent:
    wr_no_div = sum(1 for t in rsi_div_absent if t["result"] == "WIN") / len(rsi_div_absent) * 100
    print(f"  WR={wr_no_div:.1f}% | صفقات: {[t['symbol'] for t in rsi_div_absent]}")

# تحليل bollinger=0 vs bollinger>0
bb_present = [t for t in trades if t["details"]["bollinger"] > 0]
bb_absent = [t for t in trades if t["details"]["bollinger"] == 0]
print(f"\n--- bollinger>0: n={len(bb_present)} ---")
if bb_present:
    wr_bb = sum(1 for t in bb_present if t["result"] == "WIN") / len(bb_present) * 100
    e_bb = sum(t["profit_pct"] for t in bb_present) / len(bb_present)
    print(f"  WR={wr_bb:.1f}% | E={e_bb:.2f}%")
print(f"--- bollinger=0: n={len(bb_absent)} ---")
if bb_absent:
    wr_no_bb = sum(1 for t in bb_absent if t["result"] == "WIN") / len(bb_absent) * 100
    e_no_bb = sum(t["profit_pct"] for t in bb_absent) / len(bb_absent)
    print(f"  WR={wr_no_bb:.1f}% | E={e_no_bb:.2f}%")

# تحليل stoch_rsi>0
stoch_p = [t for t in trades if t["details"]["stoch_rsi"] > 0]
stoch_a = [t for t in trades if t["details"]["stoch_rsi"] == 0]
print(f"\n--- stoch_rsi>0: n={len(stoch_p)} ---")
if stoch_p:
    wr_s = sum(1 for t in stoch_p if t["result"] == "WIN") / len(stoch_p) * 100
    e_s = sum(t["profit_pct"] for t in stoch_p) / len(stoch_p)
    print(f"  WR={wr_s:.1f}% | E={e_s:.2f}%")
print(f"--- stoch_rsi=0: n={len(stoch_a)} ---")
if stoch_a:
    wr_sa = sum(1 for t in stoch_a if t["result"] == "WIN") / len(stoch_a) * 100
    e_sa = sum(t["profit_pct"] for t in stoch_a) / len(stoch_a)
    print(f"  WR={wr_sa:.1f}% | E={e_sa:.2f}%")

# الخلاصة
print("\n" + "=" * 60)
print("SUMMARY / الخلاصة")
print("=" * 60)
print(f"n=7 | WR=28.6% | E={expectancy:.3f}% | R:R={rr:.2f}:1")
print(f"المؤشر الأكثر تمييزاً: {findings_sorted[0][0]} (delta={findings_sorted[0][1]:+.3f})")
print(f"rsi_divergence: div WR={wr_div:.1f}% vs no-div WR={wr_no_div:.1f}%")
print(f"bollinger: present WR={wr_bb:.1f}% vs absent WR={wr_no_bb:.1f}%")
print("NOTE: n=7 — أي نمط هنا غير دال إحصائياً. توثيق فقط.")
