"""
Verification for the 2026-06-23 scanner/analyzer improvements.
1) PARITY: live `ta` library vs `pandas_ta` reference (RSI/ATR) — catches silent computation bugs.
2) REPAINT: how much RSI/StochRSI/ATR move when the still-forming candle is included vs dropped.
Uses cached OHLC (lib.load_ohlc) as a stand-in price path; the last bar plays the 'forming' candle.
"""
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, ta, pandas_ta as pta
import lib

def rsi_ta(close, n=14):   return ta.momentum.RSIIndicator(close=close, window=n).rsi()
def atr_ta(h,l,c,n=14):    return ta.volatility.AverageTrueRange(high=h, low=l, close=c, window=n).average_true_range()

print("="*70)
print("(1) PARITY  ta vs pandas_ta  (last closed value)")
print("="*70)
syms = ["MEUSDT","ARUSDT","TAOUSDT"]
for s in syms:
    o = lib.load_ohlc(s)
    if o is None or len(o) < 60:
        print(f"  {s:10} no OHLC"); continue
    c,h,l = o['c'], o['h'], o['l']
    r_ta  = float(rsi_ta(c).iloc[-1]); r_pt = float(pta.rsi(c, length=14).iloc[-1])
    a_ta  = float(atr_ta(h,l,c).iloc[-1])
    a_pt_s= pta.atr(h,l,c, length=14, mamode='rma')
    a_pt  = float(a_pt_s.iloc[-1]) if a_pt_s is not None else float('nan')
    print(f"  {s:10} RSI: ta={r_ta:7.3f} pta={r_pt:7.3f}  Δ={abs(r_ta-r_pt):.3f}   "
          f"ATR: ta={a_ta:.6g} pta={a_pt:.6g}  Δ%={100*abs(a_ta-a_pt)/a_ta:.2f}")

print()
print("="*70)
print("(2) REPAINT  — indicators WITH forming candle vs WITHOUT (the fix)")
print("    simulates: live reads forming bar; fix drops it. shows last-value drift.")
print("="*70)
def stoch_k(close):
    s = ta.momentum.StochRSIIndicator(close=close, window=14, smooth1=14, smooth2=3)
    return s.stochrsi_k()
rows=[]
for s in syms:
    o = lib.load_ohlc(s)
    if o is None or len(o) < 60: continue
    full = o
    closed = o.iloc[:-1]          # the fix: drop the (forming) last bar
    rsi_f = float(rsi_ta(full['c']).iloc[-1]); rsi_c = float(rsi_ta(closed['c']).iloc[-1])
    stk_f = float(stoch_k(full['c']).iloc[-1]); stk_c = float(stoch_k(closed['c']).iloc[-1])
    atr_f = float(atr_ta(full['h'],full['l'],full['c']).iloc[-1]); atr_c = float(atr_ta(closed['h'],closed['l'],closed['c']).iloc[-1])
    rows.append((s, rsi_f, rsi_c, stk_f, stk_c, atr_f, atr_c))
    print(f"  {s:10} RSI {rsi_f:6.2f}->{rsi_c:6.2f} (Δ{rsi_f-rsi_c:+.2f}) | "
          f"StochK {stk_f:4.2f}->{stk_c:4.2f} (Δ{stk_f-stk_c:+.2f}) | "
          f"ATR Δ%={100*(atr_f-atr_c)/atr_c:+.2f}")
if rows:
    dr = np.mean([abs(r[1]-r[2]) for r in rows]); dk = np.mean([abs(r[3]-r[4]) for r in rows])
    # how often would the stoch>0 gate flip? stoch contributes only when k<0.2 w/ cross -> boundary sensitive
    print(f"\n  mean |ΔRSI| = {dr:.2f} points | mean |ΔStochK| = {dk:.3f}")
    print("  → including the forming candle moves the exact values the gates/score read.")
    print("  → the fix makes live indicators identical to backtest (closed-candle) values.")
