#!/usr/bin/env python3
"""FC robustness + verdict. Reads fc_periods.csv. Falsify-first.
Computes: gross/net annual (notional & capital, deployed & committed) at costs 0.3/0.4/0.6%,
for L=2,3; liquidation frequency & worst tail (Model R rebalanced + Model P passive);
winsorized means; symbol-clustered bootstrap CI; LOYO per-year; 6-mo forward stability;
remove-top-N concentration. Prints the 4-threshold GO/NO-GO table."""
import numpy as np, pandas as pd

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
IN = f"{ROOT}/scripts/fc_periods.csv"
PPY = 3*365                    # 8h periods per year = 1095
MAINT = 0.005
COSTS = [0.003, 0.004, 0.006]  # round-trip cost per spell (both legs open+close)
LS = [2, 3]

df = pd.read_csv(IN)
df = df.sort_values(['sym','period']).reset_index(drop=True)
SYMS = list(df['sym'].unique())
N_DECISION = len(df)           # committed-capital denominator (all decision periods)
YEARS = N_DECISION / PPY

def thr(L):
    return 1.0/L - MAINT

def process(L, model):
    """Return held-period frame with pnl_notional (after liquidation override) + spell ids.
    model 'R' = rebalanced (per-period reset reference); 'P' = passive (spell-entry reference)."""
    t = thr(L)
    out = []
    for sym, g in df.groupby('sym', sort=False):
        g = g.reset_index(drop=True)
        hold = g['hold'].values
        period = g['period'].values
        gross = g['gross_pnl'].values
        prise_R = g['perp_rise_R'].values
        Phigh = g['P_high'].values
        Pprev = g['P_prev'].values
        Sprev = g['S_prev'].values
        Satph = g['S_at_ph'].values
        spot_conc_R = g['spot_conc'].values
        year = g['year'].values; ym = g['ym'].values
        spell_id = -1
        in_spell = False
        spell_entry_P = np.nan; spell_entry_S = np.nan
        prev_period = None
        for i in range(len(g)):
            if not hold[i]:
                in_spell = False
                prev_period = period[i]
                continue
            # contiguity break also ends a spell
            new_spell = (not in_spell) or (prev_period is not None and period[i] - prev_period != 1)
            if new_spell:
                spell_id += 1
                in_spell = True
                spell_entry_P = Pprev[i]
                spell_entry_S = Sprev[i]
            # liquidation trigger
            if model == 'R':
                rise = prise_R[i]
                s_off = spot_conc_R[i]
            else:  # passive: cumulative from spell entry
                rise = Phigh[i]/spell_entry_P - 1
                s_off = Satph[i]/spell_entry_S - 1
            is_liq = rise >= t
            if is_liq:
                pnl = s_off - t          # spot offset minus wiped margin (funding not collected)
                out.append((sym, year[i], ym[i], pnl, 1, spell_id, 1))  # last col: forces re-hedge
                in_spell = False          # spell ends; next hold starts fresh spell (extra fee)
            else:
                out.append((sym, year[i], ym[i], gross[i], 0, spell_id, 0))
            prev_period = period[i]
    h = pd.DataFrame(out, columns=['sym','year','ym','pnl','is_liq','spell_id','rehedge'])
    return h, t

def fees_total(h, cost):
    """round-trip cost once per spell + one extra per liquidation re-hedge."""
    n_spells = h.groupby(['sym','spell_id']).ngroups
    n_rehedge = int(h['rehedge'].sum())
    return (n_spells + n_rehedge) * cost, n_spells, n_rehedge

def winsor(x, lo=0.01, hi=0.99):
    a, b = np.quantile(x, [lo, hi])
    return np.clip(x, a, b)

def annual_stats(h, L, cost):
    cap = 1.0 + 1.0/L
    pnl = h['pnl'].values                    # per-unit notional, after liq
    n_held = len(pnl)
    fee_tot, n_spells, n_rehedge = fees_total(h, cost)
    # amortize fees across held periods (uniform) for per-period net series
    fee_per = fee_tot / n_held
    net_notional = pnl - fee_per             # net per-period pnl on notional
    net_w = winsor(net_notional)
    gross_w = winsor(pnl)
    # returns on CAPITAL
    net_cap = net_w / cap
    gross_cap = gross_w / cap
    frac_held = n_held / (N_DECISION)        # deployed fraction of committed capital
    res = dict(
        L=L, cost=cost, n_held=n_held, n_spells=n_spells, n_rehedge=n_rehedge,
        frac_held=frac_held,
        # NOTIONAL (capital=1) — comparable to the 8.8% rough figure
        gross_ann_notional_deployed = pnl.mean()*PPY*100,
        net_ann_notional_deployed   = net_notional.mean()*PPY*100,
        net_ann_notional_committed  = net_notional.sum()/N_DECISION*PPY*100,
        # CAPITAL (1+1/L)
        gross_ann_cap_deployed = gross_cap.mean()*PPY*100,
        net_ann_cap_deployed   = net_cap.mean()*PPY*100,
        net_ann_cap_committed  = (net_w.sum()/N_DECISION)/cap*PPY*100,
    )
    return res, net_w, cap

def per_symbol_annual(h, L, cost):
    """symbol-level net annual on CAPITAL, committed (idle=0) — for clustered bootstrap & concentration."""
    cap = 1.0+1.0/L
    fee_tot, n_spells, _ = fees_total(h, cost)
    fee_per = fee_tot / len(h)
    h = h.copy(); h['net'] = h['pnl'] - fee_per
    # denominator per symbol = that symbol's decision periods
    dec = df.groupby('sym').size()
    out = {}
    for sym, gg in h.groupby('sym'):
        w = winsor(gg['net'].values) if len(gg) > 20 else gg['net'].values
        out[sym] = (w.sum()/dec[sym])/cap*PPY*100
    return pd.Series(out)

# ============ MAIN ============
lines = []
def P(s=""):
    print(s, flush=True); lines.append(s)

P("="*100)
P(f"FC DELTA-NEUTRAL FUNDING CARRY — proper backtest | {len(SYMS)} symbols | {N_DECISION} decision-periods "
  f"| {YEARS:.2f} yr | PPY={PPY}")
P("="*100)

# gross funding-only annual (notional) for reference
held_all = df[df['hold']]
P(f"\n[REF] funding-only mean while held = {held_all['rate'].mean()*100:.4f}%/8h "
  f"-> {held_all['rate'].mean()*PPY*100:.2f}%/yr on NOTIONAL (deployed). "
  f"Committed (idle=0) = {held_all['rate'].sum()/N_DECISION*PPY*100:.2f}%/yr")
P(f"[REF] basis MtM mean while held = {held_all['basis_pnl'].mean()*100:.4f}%/8h "
  f"-> {held_all['basis_pnl'].mean()*PPY*100:.2f}%/yr (drag on carry)")

summary = {}
for L in LS:
    hR, t = process(L, 'R')
    hP, _ = process(L, 'P')
    P("\n" + "="*100)
    P(f"LEVERAGE L={L}   liq threshold thr(L)=1/L-{MAINT}={t:.3f} (perp up-move to liquidate short)   "
      f"capital/unit notional = {1+1/L:.3f}")
    P("="*100)
    # liquidation stats
    for tag, h in [('R rebalanced(per-period reset)', hR), ('P passive(no rebalance, spell-anchor)', hP)]:
        nliq = int(h['is_liq'].sum()); nheld = len(h)
        cap = 1+1/L
        if nliq:
            liq_pnls = h[h['is_liq']==1]['pnl'].values
            worst = liq_pnls.min()
            worst_cap = worst/cap*100
            # per symbol-year frequency
            sy = df.groupby(['sym','year']).size().shape[0]
            liq_per_symyear = nliq/ (df.groupby(['sym','year']).ngroups)
            P(f"  LIQ[{tag}]: events={nliq}/{nheld} held ({nliq/nheld*100:.3f}%)  "
              f"~{liq_per_symyear:.3f}/symbol-year  worst_event={worst*100:+.2f}% notional "
              f"= {worst_cap:+.2f}% of total capital")
        else:
            P(f"  LIQ[{tag}]: events=0/{nheld} — no liquidation at L={L}")
    # annual table across costs (base model = R rebalanced)
    P(f"\n  NET ANNUAL (Model R rebalanced) — winsorized 1/99")
    P(f"  {'cost':>6} | {'gross%not/dep':>13} | {'net%not/dep':>12} | {'net%not/comm':>13} | "
      f"{'gross%cap/dep':>13} | {'net%cap/dep':>12} | {'NET%cap/COMM':>13}")
    for cost in COSTS:
        r, netw, cap = annual_stats(hR, L, cost)
        P(f"  {cost*100:>5.1f}% | {r['gross_ann_notional_deployed']:>12.2f} | {r['net_ann_notional_deployed']:>11.2f} | "
          f"{r['net_ann_notional_committed']:>12.2f} | {r['gross_ann_cap_deployed']:>12.2f} | "
          f"{r['net_ann_cap_deployed']:>11.2f} | {r['net_ann_cap_committed']:>12.2f}")
        summary[(L,cost)] = r
    P(f"  spells={summary[(L,0.006)]['n_spells']}  liq-rehedges={summary[(L,0.006)]['n_rehedge']}  "
      f"frac_held={summary[(L,0.006)]['frac_held']*100:.1f}%")

# ---- Threshold evaluation uses L=2 & L=3 at 0.6% cost, NET on CAPITAL, committed ----
P("\n" + "="*100)
P("ROBUSTNESS (base: Model R rebalanced, cost=0.6% pessimistic, NET on capital, committed)")
P("="*100)

boot_ci = {}; loyo = {}; monthly = {}; conc = {}
for L in LS:
    hR, t = process(L, 'R')
    cost = 0.006
    # symbol-clustered bootstrap
    sym_ann = per_symbol_annual(hR, L, cost)
    arr = sym_ann.values
    rng = np.random.default_rng(11)
    boots = [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(3000)]
    lo_ci, hi_ci = np.percentile(boots, [2.5, 97.5])
    boot_ci[L] = (arr.mean(), lo_ci, hi_ci, np.median(arr))
    P(f"\n L={L}: symbol-clustered bootstrap (3000 reps) net%/yr on capital(committed): "
      f"point(sym-mean)={arr.mean():+.2f}%  95%CI=[{lo_ci:+.2f}, {hi_ci:+.2f}]  median_sym={np.median(arr):+.2f}%")
    P(f"       per-symbol net%/yr: " + "  ".join(f"{s.replace('USDT','')}={v:+.1f}" for s,v in sym_ann.sort_values().items()))
    # concentration: remove top-N positive symbols until pooled flips negative
    cap = 1+1/L
    fee_tot,_,_ = fees_total(hR, cost); fee_per = fee_tot/len(hR)
    hh = hR.copy(); hh['net'] = hh['pnl']-fee_per
    pooled = (winsor(hh['net'].values).sum()/N_DECISION)/cap*PPY*100
    # per-symbol total net contribution (pooled weighting)
    sym_contrib = {s: (winsor(gg['net'].values).sum()/N_DECISION)/cap*PPY*100 for s,gg in hh.groupby('sym')}
    sc = pd.Series(sym_contrib).sort_values(ascending=False)
    P(f"       pooled net%/yr(committed,cap)={pooled:+.2f}. top contributors: "
      + ", ".join(f"{s.replace('USDT','')}={v:+.2f}" for s,v in sc.head(5).items()))
    cum = pooled; removed = 0
    for s,v in sc.items():
        if cum <= 0: break
        cum -= v; removed += 1
    conc[L] = (pooled, removed, sc)
    P(f"       remove-top-N to flip pooled<=0: N={removed} (of {len(sc)}) "
      f"{'FRAGILE' if removed<=3 else 'ok'}")
    # LOYO per-year net (committed within year)
    P(f"       per-year net%/yr(cap,committed,winsor):")
    yr_rows = []
    for yr, gg in hh.groupby('year'):
        dec_yr = df[df['year']==yr].shape[0]
        v = (winsor(gg['net'].values).sum()/dec_yr)/cap*PPY*100 if len(gg)>20 else np.nan
        yr_rows.append((yr, v, len(gg), (gg['is_liq']==1).sum()))
    loyo[L] = yr_rows
    P("         " + "  ".join(f"{yr}:{v:+.1f}%(liq{lq})" for yr,v,n,lq in yr_rows))
    npos = sum(1 for _,v,_,_ in yr_rows if v>0)
    P(f"         years net-positive: {npos}/{len(yr_rows)}")
    # 6-month forward stability: monthly committed net, then rolling 6-mo windows share positive
    mrows = []
    for m, gg in hh.groupby('ym'):
        dec_m = df[df['ym']==m].shape[0]
        v = winsor(gg['net'].values).sum()/dec_m/cap*PPY*100 if len(gg)>5 else np.nan
        mrows.append((m, v))
    mser = pd.Series({m:v for m,v in mrows}).sort_index().dropna()
    monthly[L] = mser
    pos_month = (mser>0).mean()*100
    # every rolling 6-mo window: fraction with >=4 positive months
    ok6 = []
    vals = mser.values
    for i in range(len(vals)-5):
        w = vals[i:i+6]
        ok6.append((w>0).sum() >= 4)
    share_ok6 = np.mean(ok6)*100 if ok6 else 0
    P(f"       monthly net-positive share={pos_month:.0f}% ; 6-mo windows with >=4 pos months={share_ok6:.0f}%")

# ============ VERDICT TABLE ============
P("\n" + "="*100)
P("PRE-REGISTERED THRESHOLDS (ALL must pass for GO) — base Model R, cost 0.6%")
P("="*100)
def verdict_row(name, val_str, passed):
    P(f"  [{'PASS' if passed else 'FAIL'}] {name}: {val_str}")

overall_go = True
for L in LS:
    P(f"\n--- L={L} ---")
    net06 = summary[(L,0.006)]['net_ann_cap_committed']
    net06_dep = summary[(L,0.006)]['net_ann_cap_deployed']
    # T1: net annual winsorized >= +5%/yr after 0.6% (use committed on capital; also show deployed)
    t1 = net06 >= 5.0
    verdict_row("T1 net annual(cap,committed)>=+5% @0.6%",
                f"{net06:+.2f}% (deployed {net06_dep:+.2f}%)", t1)
    # T2: lower CI bound > 0
    pt, lo_ci, hi_ci, med = boot_ci[L]
    t2 = lo_ci > 0
    verdict_row("T2 symbol-clustered 95%CI lower>0", f"CI=[{lo_ci:+.2f},{hi_ci:+.2f}] pt={pt:+.2f}", t2)
    # T3: no single liq event worse than -3% of capital, at L
    cap=1+1/L
    hR,tt = process(L,'R'); hP,_=process(L,'P')
    worstR = (hR[hR['is_liq']==1]['pnl'].min()/cap*100) if hR['is_liq'].sum() else 0.0
    worstP = (hP[hP['is_liq']==1]['pnl'].min()/cap*100) if hP['is_liq'].sum() else 0.0
    t3 = (worstR > -3.0) and (worstP > -3.0)
    verdict_row("T3 worst liq event > -3% of capital",
                f"Rebalanced worst={worstR:+.2f}% ; Passive worst={worstP:+.2f}%", t3)
    # T4: >=4/6 monthly windows positive AND majority of years positive
    yr_rows = loyo[L]; npos = sum(1 for _,v,_,_ in yr_rows if v is not None and v>0)
    maj_years = npos > len(yr_rows)/2
    mser = monthly[L]; vals=mser.values
    ok6=[]
    for i in range(len(vals)-5):
        ok6.append((vals[i:i+6]>0).sum()>=4)
    share_ok6 = np.mean(ok6) if ok6 else 0
    t4 = (share_ok6 >= 0.5) and maj_years
    verdict_row("T4 >=4/6 monthly windows pos (majority) & majority years pos",
                f"6mo-windows-ok={share_ok6*100:.0f}% ; years pos={npos}/{len(yr_rows)}", t4)
    go = t1 and t2 and t3 and t4
    overall_go = overall_go and go
    P(f"  => L={L} verdict: {'GO' if go else 'NO-GO'}")

P("\n" + "="*100)
P(f"OVERALL VERDICT: {'GO' if overall_go else 'NO-GO'}  (GO requires ALL thresholds pass at BOTH L=2 and L=3)")
P("="*100)

with open(f"{ROOT}/scripts/fc_robust_out.txt","w") as f:
    f.write("\n".join(lines))
print(f"\nWROTE {ROOT}/scripts/fc_robust_out.txt")
