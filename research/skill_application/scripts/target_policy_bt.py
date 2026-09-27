#!/usr/bin/env python3
"""
اختبار سياسة الهدف (target policy) — هل ربط T1 بمستوى ارتداد مقيس (منتصف بولينجر / EMA20)
يرفع نسبة بلوغ T1 والربح الصافي مقابل الهدف الحالي 1R، في السوق الهابط — على بيانات تاريخية كاملة.
نسخة متجهية (numpy) سريعة، تُكرّر منطق البوت الحيّ بدقة (شموع مغلقة، نوافذ تشمل شمعة القرار).

الأذرع (نفس الدخول تماماً عبرها):
  A 1R(base): T1=1R T2=1.8R T3=2.2R (الحالي، مع سقف T1 عند مقاومة 20)
  B bb_mid  : T1=منتصف بولينجر، T2=الباند العلوي، T3=علوي+1ATR
  C ema20   : T1=EMA20،        T2=الباند العلوي، T3=علوي+1ATR
  D 0.5R    : T1=0.5R T2=1.0R T3=1.8R   (ضابط: هل مجرد تقريب الهدف يكفي؟)

العدالة: نطاق دخول موحّد = score>=3 & down-market & (bb_mid>entry & ema20>entry).
بوابة تحقق: A على نطاقه الطبيعي (بلا اشتراط المتوسط) → نقارن reach_t1 بالحيّ (~25% بالهابط) ونتوقّع net<0.
"""
import os, sys, glob, zipfile, json, math
import numpy as np, pandas as pd
import ta
from numpy.lib.stride_tricks import sliding_window_view

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
DATA = f"{ROOT}/data/bt_data"
TFS = ["1h", "4h", "1d"]
TF_HOURS = {"1h": 1.0, "4h": 4.0, "1d": 24.0}
MAX_SL = {'1d': 0.03, '4h': 0.05, '1h': 0.04, '15m': 0.02}
WARM = 210
MIN_SCORE = 3.0
FEES = {'gross': 0.0, 'net03': 0.3, 'net06': 0.6}
ARMS = ('A', 'B', 'C', 'D')
NAMES = {'A': 'A 1R(base)', 'B': 'B bb_mid', 'C': 'C ema20', 'D': 'D 0.5R'}

# الأوزان الفعّالة في النقاط (فقط هذه الخمسة تدخل _calculate_scores في البوت)
W = {'bearish':  {'rsi': 1.0, 'bollinger': 1.0, 'stoch_rsi': 0.2332, 'rsi_divergence': 1.0, 'fibonacci': 1.0},
     'sideways': {'rsi': 1.0, 'bollinger': 0.0, 'stoch_rsi': 1.4176, 'rsi_divergence': 2.0, 'fibonacci': 1.0}}


def load(sym, tf):
    files = sorted(glob.glob(f"{DATA}/{sym}/{tf}/{sym}-{tf}-*.zip"))
    if not files:
        return None
    rows = []
    for f in files:
        try:
            z = zipfile.ZipFile(f); n = z.namelist()[0]
            for ln in z.read(n).decode().splitlines():
                p = ln.split(',')
                if p[0][:1].isalpha():
                    continue
                rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])))
        except Exception:
            pass
    if len(rows) < WARM + 60:
        return None
    df = pd.DataFrame(rows, columns=['t', 'open', 'high', 'low', 'close', 'volume'])
    df = df.drop_duplicates('t').sort_values('t').reset_index(drop=True)
    df['t'] = df['t'].apply(lambda x: x // 1000 if x > 1e14 else x)
    return df


def indicators(df):
    c = df['close']
    df['rsi'] = ta.momentum.RSIIndicator(c, window=14).rsi()
    df['ema20'] = ta.trend.EMAIndicator(c, window=20).ema_indicator()
    df['ema50'] = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    df['ema200'] = ta.trend.EMAIndicator(c, window=200).ema_indicator()
    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2.0)
    df['bb_u'] = bb.bollinger_hband(); df['bb_m'] = bb.bollinger_mavg(); df['bb_l'] = bb.bollinger_lband()
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], c, window=14).average_true_range()
    df['avg_atr'] = df['atr'].rolling(20).mean()
    st = ta.momentum.StochRSIIndicator(c, window=14, smooth1=14, smooth2=3)
    df['stoch_k'] = st.stochrsi_k(); df['stoch_d'] = st.stochrsi_d()
    return df


def regime_array(close, e20, e50, e200, atr, avg):
    """يطابق _detect_market_condition. يرجع مصفوفة سلاسل."""
    e200f = np.where(np.isnan(e200), e50, e200)
    out = np.full(len(close), 'sideways', dtype=object)
    bull = (close > e20) & (e20 > e50) & (e50 > e200f)
    bear = (close < e20) & (e20 < e50) & (e50 < e200f)
    out[bull] = 'bullish'; out[bear] = 'bearish'
    vol = atr > avg * 1.5
    out[vol] = 'volatile'   # volatile يغلب (كما في الكود: يُفحص أولاً)
    return out


def rsi_div_array(low, rsi, lb=14):
    """يطابق _detect_rsi_divergence الحيّ: recent=[i-lb+1..i], older=[i-2lb+1..i-lb]."""
    N = len(low); out = np.zeros(N, bool)
    if N < 2 * lb:
        return out
    win = sliding_window_view(low, lb)          # win[k] = low[k:k+lb]
    amin = win.argmin(axis=1)                    # offset of min داخل النافذة التي تبدأ عند k
    i = np.arange(2 * lb - 1, N)
    rs = i - lb + 1                              # بداية نافذة recent
    osr = i - 2 * lb + 1                         # بداية نافذة older
    r_idx = rs + amin[rs]
    o_idx = osr + amin[osr]
    cond = (low[r_idx] < low[o_idx]) & (rsi[r_idx] > rsi[o_idx])
    out[i] = np.where(np.isnan(rsi[r_idx]) | np.isnan(rsi[o_idx]), False, cond)
    return out


def fib_array(high, low, close, lb=50):
    """يطابق _calculate_fibonacci_score الحيّ: نافذة lb تشمل شمعة القرار i."""
    s_hi = pd.Series(high).rolling(lb).max().to_numpy()
    s_lo = pd.Series(low).rolling(lb).min().to_numpy()
    diff = s_hi - s_lo
    out = np.zeros(len(close))
    valid = diff > 0
    best = np.zeros(len(close))
    got1 = np.zeros(len(close), bool)
    for f in (0.382, 0.5, 0.618):
        lv = s_hi - f * diff
        with np.errstate(invalid='ignore', divide='ignore'):
            prox = np.abs(close - lv) / lv
        m1 = valid & (lv > 0) & (prox <= 0.01)
        got1 |= m1
        m05 = valid & (lv > 0) & (prox <= 0.02) & (best < 0.5)
        best[m05] = 0.5
    out = np.where(got1, 1.0, best)
    return out


def score_array(df, mc):
    """نقاط متجهية تحت أوزان حالة سوق mc (bearish/sideways)."""
    w = W[mc]
    rsi = df['rsi'].to_numpy()
    close = df['close'].to_numpy(); high = df['high'].to_numpy(); low = df['low'].to_numpy()
    bb_u = df['bb_u'].to_numpy(); bb_l = df['bb_l'].to_numpy()
    sk = df['stoch_k'].to_numpy(); sd = df['stoch_d'].to_numpy()
    # rsi
    rsi_s = np.select(
        [(rsi >= 20) & (rsi < 30), (rsi >= 30) & (rsi < 40), (rsi >= 40) & (rsi < 50)],
        [w['rsi'] * 1.5, w['rsi'] * 1.0, w['rsi'] * 0.3], default=0.0)
    rsi_s = np.where(np.isnan(rsi), 0.0, rsi_s)
    tot = rsi_s.astype(float)
    # bollinger (مشروط rsi_s>=1.0)
    rng = bb_u - bb_l
    with np.errstate(invalid='ignore', divide='ignore'):
        pos = np.where(rng > 0, (close - bb_l) / np.where(rng > 0, rng, 1.0), 99.0)
    bb_s = np.where((rng > 0) & (rsi_s >= 1.0) & (pos <= 0.3), w['bollinger'],
           np.where((rng > 0) & (rsi_s >= 1.0) & (pos <= 0.5), w['bollinger'] * 0.5, 0.0))
    tot += bb_s
    # stoch
    sd2 = np.where(np.isnan(sd), sk, sd)
    st_s = np.where(sk >= 0.9, w['stoch_rsi'] * 0.3,
           np.where((sk < 0.2) & (sk > sd2), w['stoch_rsi'], 0.0))
    st_s = np.where(np.isnan(sk), 0.0, st_s)
    tot += st_s
    # divergence
    div = rsi_div_array(low, rsi)
    tot += np.where(div, w['rsi_divergence'], 0.0)
    # fibonacci
    tot += fib_array(high, low, close) * w['fibonacci']
    return tot


def simulate(hi, lo, cl, i, entry, stop, t1, t2, t3, tf):
    hh = TF_HOURS[tf]; peak = entry; ht = 0; n = len(cl)
    for j in range(i + 1, n):
        h = hi[j]; l = lo[j]; c = cl[j]
        hours = (j - i) * hh
        if h >= t3 and ht < 3: ht = 3
        elif h >= t2 and ht < 2: ht = 2
        elif h >= t1 and ht < 1: ht = 1
        if h > peak: peak = h
        if ht == 3: return ((t3 - entry) / entry * 100, j, 1, 1)
        if ht >= 2: eff = max(t1, peak * (1 - 2.5 / 100))
        elif ht >= 1: eff = entry
        else: eff = stop
        if l <= eff: return ((eff - entry) / entry * 100, j, int(ht >= 1), int(ht >= 2))
        if hours >= 24 and ht == 1: return ((c - entry) / entry * 100, j, 1, int(ht >= 2))
        if hours >= 48: return ((c - entry) / entry * 100, j, int(ht >= 1), int(ht >= 2))
    return None


def blank():
    return {'n': 0, 'gsum': 0.0, 'g2': 0.0, 't1': 0, 't2': 0,
            'pos': {k: 0.0 for k in FEES}, 'neg': {k: 0.0 for k in FEES}, 'win': {k: 0 for k in FEES}}


def add(store, arm, year, g, r1, r2):
    d = store.setdefault(arm, {})
    for scope in ('all', year):
        s = d.get(scope)
        if s is None: s = blank(); d[scope] = s
        s['n'] += 1; s['gsum'] += g; s['g2'] += g * g; s['t1'] += r1; s['t2'] += r2
        for k, fee in FEES.items():
            net = g - fee
            if net > 0: s['pos'][k] += net; s['win'][k] += 1
            else: s['neg'][k] += -net


def metrics(s, feekey='net06'):
    if not s or s['n'] == 0: return None
    n = s['n']; pos = s['pos'][feekey]; neg = s['neg'][feekey]
    pf = (pos / neg) if neg > 0 else float('inf')
    exp = s['gsum'] / n - FEES[feekey]
    sd = math.sqrt(max(s['g2'] / n - (s['gsum'] / n) ** 2, 0)); se = sd / math.sqrt(n) if n else 0
    return {'n': n, 'reach_t1': s['t1'] / n * 100, 'reach_t2': s['t2'] / n * 100,
            'wr': s['win'][feekey] / n * 100, 'exp_net': exp, 'pf': pf, 't_stat': (exp / se) if se else 0}


def run(syms):
    main = {}; valid = {}; per_sym = {a: {} for a in ARMS}
    nsym = 0
    for sym in syms:
        for tf in TFS:
            df = load(sym, tf)
            if df is None: continue
            try:
                df = indicators(df)
            except Exception:
                continue
            L = len(df)
            close = df['close'].to_numpy(); high = df['high'].to_numpy(); low = df['low'].to_numpy()
            e20 = df['ema20'].to_numpy(); e50 = df['ema50'].to_numpy(); e200 = df['ema200'].to_numpy()
            atr = df['atr'].to_numpy(); avg = df['avg_atr'].to_numpy()
            bb_m = df['bb_m'].to_numpy(); bb_u = df['bb_u'].to_numpy()
            years = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            reg = regime_array(close, e20, e50, e200, atr, avg)
            sc_bear = score_array(df, 'bearish'); sc_side = score_array(df, 'sideways')
            sc = np.where(reg == 'bearish', sc_bear, np.where(reg == 'sideways', sc_side, 0.0))
            down = (reg == 'bearish') | (reg == 'sideways')
            cand = down & (sc >= MIN_SCORE)
            cand[:WARM] = False; cand[L - 1:] = False
            cd = max(1, int(math.ceil(48.0 / TF_HOURS[tf])))

            # رولينق دعم 20 (low min على [i-19..i]) ومقاومة 20 (high max)
            sup20 = pd.Series(low).rolling(20).min().to_numpy()
            res20 = pd.Series(high).rolling(20).max().to_numpy()

            def levels(i):
                entry = close[i]; a = atr[i]
                stop = max(entry - a * 1.5, sup20[i] * 0.99)
                if stop >= entry: stop = entry * 0.97
                cap = MAX_SL.get(tf, 0.04); mr = entry * cap
                if (entry - stop) > mr: stop = entry - mr
                return entry, stop

            def arm_targets(i, arm, entry, stop):
                risk = entry - stop
                if arm == 'A':
                    t1 = entry + risk; t2 = entry + risk * 1.8; t3 = entry + risk * 2.2
                    if t1 > res20[i] > entry: t1 = res20[i] * 0.99
                elif arm == 'D':
                    t1 = entry + risk * 0.5; t2 = entry + risk; t3 = entry + risk * 1.8
                elif arm == 'B':
                    t1 = bb_m[i]; t2 = bb_u[i]; t3 = bb_u[i] + atr[i]
                else:  # C
                    t1 = e20[i]; t2 = bb_u[i]; t3 = bb_u[i] + atr[i]
                if not (t1 > entry) or np.isnan(t1): return None
                t2 = max(t2, t1 + entry * 0.001); t3 = max(t3, t2 + entry * 0.001)
                return t1, t2, t3

            idxs = np.nonzero(cand)[0]

            # بوابة التحقق: A على النطاق الطبيعي (non-overlap بخروج A)
            nxt = WARM
            for i in idxs:
                if i < nxt: continue
                entry, stop = levels(i)
                if entry <= 0 or np.isnan(stop) or stop >= entry: continue
                tg = arm_targets(i, 'A', entry, stop)
                if tg is None: continue
                r = simulate(high, low, close, i, entry, stop, *tg, tf)
                if r is None: continue
                g, xi, r1, r2 = r
                yr = int(years[i]) if not np.isnan(years[i]) else 0
                add(valid, 'A', yr, g, r1, r2); nxt = xi + 1

            # المقارنة العادلة: نطاق موحّد + cooldown ثابت
            last = -10**9
            for i in idxs:
                if i - last < cd: continue
                entry, stop = levels(i)
                if entry <= 0 or np.isnan(stop) or stop >= entry: continue
                if not (bb_m[i] > entry and e20[i] > entry): continue
                tgs = {}; ok = True
                for arm in ARMS:
                    tg = arm_targets(i, arm, entry, stop)
                    if tg is None: ok = False; break
                    tgs[arm] = tg
                if not ok: continue
                yr = int(years[i]) if not np.isnan(years[i]) else 0
                for arm, tg in tgs.items():
                    r = simulate(high, low, close, i, entry, stop, *tg, tf)
                    if r is None: continue
                    g, xi, r1, r2 = r
                    add(main, arm, yr, g, r1, r2)
                    ps = per_sym[arm].setdefault(sym, 0.0)
                    per_sym[arm][sym] = ps + (g - FEES['net06'])
                last = i
        nsym += 1
        if nsym % 25 == 0: print(f"  processed {nsym}/{len(syms)} symbols", flush=True)
    return main, valid, per_sym


def fmt(m):
    if not m: return "n=0"
    pf = 'inf' if m['pf'] == float('inf') else f"{m['pf']:.3f}"
    return (f"n={m['n']:>6}  reachT1={m['reach_t1']:>5.1f}%  reachT2={m['reach_t2']:>5.1f}%  "
            f"WR={m['wr']:>5.1f}%  Exp(net%)={m['exp_net']:>+7.3f}  t={m['t_stat']:>+5.2f}  PF={pf}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    print(f"symbols with data: {len(syms)} | MIN_SCORE={MIN_SCORE} down-market only | fees={FEES}", flush=True)
    main, valid, per_sym = run(syms)

    out = []
    out.append("=" * 112)
    out.append("VALIDATION GATE — Arm A (1R) on NATURAL down-market entries (compare reachT1 to live ~25%, expect net<0)")
    out.append("=" * 112)
    out.append("A_natural   " + fmt(metrics(valid.get('A', {}).get('all'))))
    out.append("")
    out.append("=" * 112)
    out.append("TARGET-POLICY COMPARISON — identical entries (down-market, score>=3, price below bb_mid & ema20)")
    out.append("=" * 112)
    for feek, lbl in (('net06', 'net@0.6% (realistic incl slippage)'), ('net03', 'net@0.3%'), ('gross', 'GROSS 0%')):
        out.append(f"--- {lbl} ---")
        for arm in ARMS:
            out.append(f"{NAMES[arm]:<12}" + fmt(metrics(main.get(arm, {}).get('all'), feek)))
        out.append("")
    out.append("=" * 112)
    out.append("PER-YEAR (walk-forward) — Exp(net@0.6%)/reachT1%/n")
    out.append("=" * 112)
    yrs = sorted({y for arm in main.values() for y in arm if y != 'all' and y})
    out.append("arm".ljust(12) + "".join(f"{y:>16}" for y in yrs))
    for arm in ARMS:
        cells = []
        for y in yrs:
            m = metrics(main.get(arm, {}).get(y))
            cells.append(f"{m['exp_net']:+.2f}/{m['reach_t1']:.0f}/{m['n']}" if m else "—")
        out.append(NAMES[arm].ljust(12) + "".join(f"{c:>16}" for c in cells))
    out.append("")
    out.append("=" * 112)
    out.append("CONCENTRATION — top-5 symbols by |net@0.6| and net excluding them")
    out.append("=" * 112)
    for arm in ('A', 'B', 'C'):
        items = sorted(per_sym[arm].items(), key=lambda kv: abs(kv[1]), reverse=True)
        tot = sum(per_sym[arm].values()); top5 = items[:5]; t5 = sum(v for _, v in top5)
        out.append(f"[{NAMES[arm]}] total={tot:+.1f}  ex_top5={tot - t5:+.1f}  top5={[(k, round(v, 1)) for k, v in top5]}")
    text = "\n".join(out)
    print(text)
    os.makedirs(f"{ROOT}/out", exist_ok=True)
    with open(f"{ROOT}/out/target_policy_result.txt", "w") as f:
        f.write(text)
    def dump(store):
        return {arm: {str(sc): {kk: s[kk] for kk in ('n', 'gsum', 'g2', 't1', 't2', 'pos', 'neg', 'win')}
                      for sc, s in d.items()} for arm, d in store.items()}
    with open(f"{ROOT}/out/target_policy_stats.json", "w") as f:
        json.dump({'main': dump(main), 'valid': dump(valid), 'fees': FEES, 'n_symbols': len(syms)}, f)
    print(f"\nWROTE {ROOT}/out/target_policy_result.txt + stats.json", flush=True)
