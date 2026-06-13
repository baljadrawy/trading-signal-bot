#!/usr/bin/env python3
"""
تحليل أداء كل مؤشر منفرد + التوليفات، من بيانات الصفقات المغلقة الحقيقية.
مصدر البيانات: signals.score_details (المساهمة الموزونة وقت التوليد) JOIN trade_results.
ملاحظات منهجية صارمة:
- الأداء هنا "شرطي / هامشي" (marginal within already-selected signals)، ليس standalone حقيقياً:
  كل صفقة مرّت أصلاً بفلتر score>=3 + مراجعة Claude. لا يوجد counterfactual.
- score_details يعكس الأوزان وقت توليد كل إشارة؛ الأوزان تغيّرت عبر الزمن (regime-mixed).
- الرسوم: القيم في DB إجمالية (gross). الصافي = خصم FEE_PCT=0.3% round-trip.
"""
import sys, asyncio, json
import numpy as np
import pandas as pd

sys.path.insert(0, '/app')
from shared.database import Database

FEE_PCT = 0.3          # round-trip fee %
POSITION = 50.0        # USDT per trade
FEE_USDT = FEE_PCT / 100.0 * POSITION   # = 0.15
MIN_N_ADV = 30         # حد أدنى لإظهار Sharpe / PF / AUC
INDICATORS = ['rsi','macd','ema_cross','bollinger','volume','stoch_rsi',
              'obv','rsi_divergence','fibonacci','order_book','btc_trend']

def auc_rank(scores, labels):
    """ROC-AUC عبر Mann-Whitney (rank-based), بدون sklearn."""
    scores = np.asarray(scores, float); labels = np.asarray(labels, int)
    n1 = labels.sum(); n0 = len(labels) - n1
    if n1 == 0 or n0 == 0: return np.nan
    order = scores.argsort(kind='mergesort')
    ranks = np.empty(len(scores), float)
    sb = scores[order]; i = 0; r = 1
    while i < len(sb):
        j = i
        while j+1 < len(sb) and sb[j+1] == sb[i]: j += 1
        ranks[order[i:j+1]] = (r + (r + (j-i))) / 2.0
        r += (j-i+1); i = j+1
    return (ranks[labels==1].sum() - n1*(n1+1)/2.0) / (n1*n0)

def max_drawdown(equity):
    if len(equity) == 0: return 0.0
    eq = np.cumsum(equity); peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())

def block(df, label):
    """يحسب كل المقاييس لمجموعة صفقات df (net)."""
    n = len(df)
    if n == 0:
        return {'label': label, 'n': 0}
    wins = int((df.result == 'WIN').sum()); losses = n - wins
    net_pct = df.profit_percent.values - FEE_PCT
    net_usdt = df.profit_usdt.values - FEE_USDT
    wr = wins / n * 100
    avg_ret_g = float(df.profit_percent.mean())
    avg_ret_n = float(net_pct.mean())
    exp_g = float(df.profit_usdt.mean())
    exp_n = float(net_usdt.mean())
    pos = net_usdt[net_usdt > 0].sum(); neg = -net_usdt[net_usdt < 0].sum()
    pf = (pos / neg) if neg > 0 else np.inf
    sharpe = float(net_pct.mean() / net_pct.std()) if n >= MIN_N_ADV and net_pct.std() > 0 else np.nan
    # equity ordered by exit_time
    dfx = df.sort_values('exit_time')
    mdd = max_drawdown(dfx.profit_usdt.values - FEE_USDT)
    dur = float(df.duration_hours.mean()) if 'duration_hours' in df and df.duration_hours.notna().any() else np.nan
    return {'label': label, 'n': n, 'wins': wins, 'losses': losses, 'wr': wr,
            'avg_ret_g': avg_ret_g, 'avg_ret_n': avg_ret_n,
            'exp_g': exp_g, 'exp_n': exp_n, 'pf': pf, 'sharpe': sharpe,
            'mdd': mdd, 'dur': dur}

async def main():
    rows = await Database.fetch("""
        SELECT tr.result, tr.profit_percent, tr.profit_usdt, tr.duration_hours,
               tr.exit_time, s.score, s.score_details, s.market_condition
        FROM trade_results tr JOIN signals s ON tr.signal_id = s.id
        WHERE tr.profit_percent IS NOT NULL AND s.score_details IS NOT NULL
        ORDER BY tr.exit_time ASC
    """)
    recs = []
    for r in rows:
        d = r['score_details']
        d = json.loads(d) if isinstance(d, str) else dict(d)
        rec = {'result': r['result'],
               'profit_percent': float(r['profit_percent']),
               'profit_usdt': float(r['profit_usdt']) if r['profit_usdt'] is not None else float(r['profit_percent'])/100*POSITION,
               'duration_hours': float(r['duration_hours']) if r['duration_hours'] is not None else np.nan,
               'exit_time': r['exit_time'],
               'market_condition': r['market_condition'] or 'unknown'}
        for ind in INDICATORS:
            try: rec[ind] = float(d.get(ind, 0) or 0)
            except: rec[ind] = 0.0
        recs.append(rec)
    df = pd.DataFrame(recs)
    N = len(df)
    base_wr = (df.result=='WIN').mean()*100
    out = []
    out.append(f"TOTAL closed trades = {N} | overall WR = {base_wr:.1f}% | "
               f"net expectancy/trade = {(df.profit_usdt - FEE_USDT).mean():.4f}$ "
               f"(gross {df.profit_usdt.mean():.4f}$) | fee={FEE_PCT}% pos={POSITION}$")
    out.append("")

    # ===== (1) لكل مؤشر: شرطي (فُعّل >0) =====
    out.append("="*120)
    out.append("(1) PER-INDICATOR  — conditional/marginal (trades where indicator contribution > 0). NOT standalone.")
    out.append("="*120)
    hdr = f"{'indicator':<15}{'n':>6}{'W':>5}{'L':>5}{'WR%':>7}{'avgRet_n%':>11}{'Exp_net$':>10}{'PF_net':>8}{'Sharpe':>8}{'MaxDD$':>9}{'durH':>7}{'AUC_bin':>8}{'AUC_wt':>8}"
    out.append(hdr); out.append("-"*len(hdr))
    per_ind = {}
    for ind in INDICATORS:
        fired = df[df[ind] > 0]
        b = block(fired, ind)
        per_ind[ind] = b
        # AUC over ALL trades: binary fired vs WIN, and weighted magnitude vs WIN
        labels = (df.result=='WIN').astype(int).values
        auc_bin = auc_rank((df[ind] > 0).astype(int).values, labels) if b['n']>=MIN_N_ADV and 0<b['n']<N else np.nan
        auc_wt  = auc_rank(df[ind].values, labels) if b['n']>=MIN_N_ADV else np.nan
        if b['n']==0:
            out.append(f"{ind:<15}{0:>6}{'—':>5}{'—':>5}{'  n=0 (never fired live)':>40}")
            continue
        pf = b['pf']; pf_s = '∞' if pf==np.inf else f"{pf:.2f}"
        sh = '—' if np.isnan(b['sharpe']) else f"{b['sharpe']:.3f}"
        du = '—' if np.isnan(b['dur']) else f"{b['dur']:.1f}"
        ab = '—' if np.isnan(auc_bin) else f"{auc_bin:.3f}"
        aw = '—' if np.isnan(auc_wt) else f"{auc_wt:.3f}"
        out.append(f"{ind:<15}{b['n']:>6}{b['wins']:>5}{b['losses']:>5}{b['wr']:>7.1f}"
                   f"{b['avg_ret_n']:>11.3f}{b['exp_n']:>10.4f}{pf_s:>8}{sh:>8}{b['mdd']:>9.2f}{du:>7}{ab:>8}{aw:>8}")
    out.append("")
    out.append("AUC_bin = discrimination of binary fired/not (≈standalone view). AUC_wt = weighted magnitude (current-weights view).")
    out.append("Sharpe/PF/AUC suppressed (—) when n<%d. avgRet_n & Exp_net are AFTER %.1f%% fee." % (MIN_N_ADV, FEE_PCT))

    # ===== (3) حسب حالة السوق =====
    out.append(""); out.append("="*120)
    out.append("(3) PER-INDICATOR × MARKET CONDITION  — conditional, net. cells show: n / WR% / Exp_net$")
    out.append("="*120)
    conds = ['bullish','bearish','sideways','volatile']
    out.append(f"{'indicator':<15}" + "".join(f"{c:>26}" for c in conds))
    for ind in INDICATORS:
        line = f"{ind:<15}"
        for c in conds:
            sub = df[(df[ind]>0) & (df.market_condition==c)]
            if len(sub)==0:
                line += f"{'—':>26}"
            else:
                wr = (sub.result=='WIN').mean()*100
                en = (sub.profit_usdt - FEE_USDT).mean()
                line += f"{f'{len(sub)}/{wr:.0f}%/{en:+.3f}':>26}"
        out.append(line)

    # ===== (2) أفضل التوليفات =====
    out.append(""); out.append("="*120)
    out.append("(2) TOP INDICATOR COMBINATIONS  — exact set of indicators that fired together (>0). net. min n=20.")
    out.append("="*120)
    df['combo'] = df.apply(lambda r: '+'.join([i for i in INDICATORS if r[i]>0]) or '(none)', axis=1)
    combos = []
    for combo, g in df.groupby('combo'):
        if len(g) < 20: continue
        b = block(g, combo)
        combos.append(b)
    combos.sort(key=lambda x: x['exp_n'], reverse=True)
    qualifying = len(combos)
    out.append(f"qualifying combos with n>=20: {qualifying}")
    hdr2 = f"{'#':>3} {'n':>5}{'WR%':>7}{'Exp_net$':>10}{'PF':>7}{'Sharpe':>8}{'MaxDD$':>9}{'durH':>7}  combo"
    out.append(hdr2); out.append("-"*len(hdr2))
    for i, b in enumerate(combos[:20], 1):
        pf = b['pf']; pf_s = '∞' if pf==np.inf else f"{pf:.2f}"
        sh = '—' if np.isnan(b['sharpe']) else f"{b['sharpe']:.3f}"
        du = '—' if np.isnan(b['dur']) else f"{b['dur']:.1f}"
        out.append(f"{i:>3} {b['n']:>5}{b['wr']:>7.1f}{b['exp_n']:>10.4f}{pf_s:>7}{sh:>8}{b['mdd']:>9.2f}{du:>7}  {b['label']}")

    # ===== zero-weight rationale =====
    out.append(""); out.append("="*120)
    out.append("ZERO-WEIGHT INDICATORS — live evidence (conditional net) behind disabling")
    out.append("="*120)
    for ind in ['macd','ema_cross','volume','btc_trend']:
        b = per_ind[ind]
        cur_w = "0 (disabled by optimizer)"
        if b['n']==0:
            out.append(f"{ind:<15}: n=0 live (weight always 0 → never contributed). No live sample.")
        else:
            pf_str = '∞' if b['pf']==np.inf else f"{b['pf']:.2f}"
            out.append(f"{ind:<15}: n={b['n']}  WR={b['wr']:.1f}%  Exp_net={b['exp_n']:+.4f}$  PF={pf_str}  "
                       f"(fired historically before optimizer zeroed it; regime-mixed)")

    text = "\n".join(out)
    print(text)
    with open('/app/logs/indicator_perf_report.txt','w') as f:
        f.write(text)

asyncio.run(main())
