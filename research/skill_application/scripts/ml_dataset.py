#!/usr/bin/env python3
"""
مولّد بيانات ML: لكل شمعة على 4h و1d (كل الأنظمة، 2017-2026) يحسب:
  - مكتبة ميزات شاملة (~60): كلاسيكية (pandas_ta) + Ichimoku + ICT/SMC، كلها بلا look-ahead.
  - تسمية triple-barrier محسّنة: يصل +k·ATR قبل -1·ATR خلال أفق N؛ عند انتهاء الوقت = حكم اتجاهي
    (فوق الدخول = نجاح اتجاهي) + تسجيل العائد الفعلي. intrabar متشائم (الستوب أولاً) = نزيه.
  - k ∈ {1.0, 1.5, 2.0}؛ أفق 4h=60 شمعة، 1d=30 شمعة.
المخرج: parquet لكل صف = (رمز، إطار، وقت) + ميزات + تسميات.
لا look-ahead: كل الميزات من بيانات ≤ شمعة القرار؛ نقاط البنية مؤكَّدة بإزاحة L شمعات.
"""
import os, sys, glob, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/tradmin/trading-signal-bot/research/skill_application/scripts')
import target_policy_bt as E   # reuse load()
import pandas_ta as pta

ROOT = "/home/tradmin/trading-signal-bot/research/skill_application"
DATA = f"{ROOT}/data/bt_data"
OUT = f"{ROOT}/out"
TFS = ["4h", "1d"]
HORIZON = {"4h": 60, "1d": 30}          # شموع
KS = [1.0, 1.5, 2.0, 2.5, 3.0]
SWING_L = 2                              # fractal confirmation lag (شمعتان بعد القمة/القاع)
WARM = 220                               # ema200 + اندماج
STRIDE = 1


def feats(df):
    """يضيف أعمدة الميزات الكلاسيكية + Ichimoku (كلها backward-looking)."""
    o, h, l, c, v = df['open'], df['high'], df['low'], df['close'], df['volume']
    F = {}
    # momentum
    for n in (7, 14, 21):
        F[f'rsi{n}'] = pta.rsi(c, length=n)
    st = pta.stochrsi(c, length=14)
    if st is not None:
        F['stochrsi_k'] = st.iloc[:, 0]; F['stochrsi_d'] = st.iloc[:, 1]
    sto = pta.stoch(h, l, c)
    if sto is not None:
        F['stoch_k'] = sto.iloc[:, 0]; F['stoch_d'] = sto.iloc[:, 1]
    macd = pta.macd(c)
    if macd is not None:
        F['macd'] = macd.iloc[:, 0]; F['macd_hist'] = macd.iloc[:, 1]; F['macd_sig'] = macd.iloc[:, 2]
    F['roc5'] = pta.roc(c, length=5); F['roc10'] = pta.roc(c, length=10)
    F['cci'] = pta.cci(h, l, c, length=20)
    F['willr'] = pta.willr(h, l, c, length=14)
    F['mfi'] = pta.mfi(h, l, c, v, length=14)
    tsi = pta.tsi(c)
    if tsi is not None: F['tsi'] = tsi.iloc[:, 0]
    F['cmo'] = pta.cmo(c, length=14)
    ao = pta.ao(h, l)
    if ao is not None: F['ao'] = ao
    # trend
    for n in (9, 20, 50, 100, 200):
        ema = pta.ema(c, length=n)
        F[f'ema{n}_dist'] = c / ema - 1
    e20 = pta.ema(c, length=20)
    F['ema20_slope'] = e20 / e20.shift(5) - 1
    e50 = pta.ema(c, length=50)
    F['ema50_slope'] = e50 / e50.shift(5) - 1
    adx = pta.adx(h, l, c, length=14)
    if adx is not None:
        F['adx'] = adx.iloc[:, 0]; F['dmp'] = adx.iloc[:, 1]; F['dmn'] = adx.iloc[:, 2]
    ar = pta.aroon(h, l, length=14)
    if ar is not None:
        F['aroon_u'] = ar.iloc[:, 0]; F['aroon_d'] = ar.iloc[:, 1]
    psar = pta.psar(h, l, c)
    if psar is not None:
        # long+short مدمجة: المسافة النسبية لأقرب نقطة psar
        ps = psar.iloc[:, 0].fillna(psar.iloc[:, 1])
        F['psar_dist'] = c / ps - 1
    ich = pta.ichimoku(h, l, c)
    if ich is not None and isinstance(ich, tuple):
        ic = ich[0]
        try:
            span_a = ic.iloc[:, 0]; span_b = ic.iloc[:, 1]
            tenkan = ic.iloc[:, 2] if ic.shape[1] > 2 else None
            kijun = ic.iloc[:, 3] if ic.shape[1] > 3 else None
            top = pd.concat([span_a, span_b], axis=1).max(axis=1)
            bot = pd.concat([span_a, span_b], axis=1).min(axis=1)
            F['ich_above_cloud'] = (c > top).astype(float)
            F['ich_below_cloud'] = (c < bot).astype(float)
            F['ich_cloud_thick'] = (top - bot) / c
            if tenkan is not None: F['ich_tenkan_dist'] = c / tenkan - 1
            if kijun is not None: F['ich_kijun_dist'] = c / kijun - 1
        except Exception:
            pass
    # volatility
    atr = pta.atr(h, l, c, length=14)
    F['atr_pct'] = atr / c
    F['atr_ratio'] = atr / atr.rolling(50).mean()
    bb = pta.bbands(c, length=20, std=2.0)
    if bb is not None:
        low_b = bb.iloc[:, 0]; up_b = bb.iloc[:, 2]
        F['bb_pos'] = (c - low_b) / (up_b - low_b)
        F['bb_width'] = (up_b - low_b) / bb.iloc[:, 1]
    kc = pta.kc(h, l, c, length=20)
    if kc is not None:
        F['kc_pos'] = (c - kc.iloc[:, 0]) / (kc.iloc[:, 2] - kc.iloc[:, 0])
    F['rvol20'] = c.pct_change().rolling(20).std()
    # volume
    obv = pta.obv(c, v)
    F['obv_slope'] = obv / obv.shift(10) - 1
    F['cmf'] = pta.cmf(h, l, c, v, length=20)
    F['vol_ratio'] = v / v.rolling(20).mean()
    F['vol_ratio50'] = v / v.rolling(50).mean()
    # السيولة: لوغاريتم وسيط حجم التداول بالدولار (close*volume) — ميزة + أساس فلتر السيولة/الانزلاق
    F['log_dvol20'] = np.log10((c * v).rolling(20).median() + 1.0)
    # price action
    for n in (1, 3, 6, 12, 24, 48):
        F[f'ret{n}'] = c / c.shift(n) - 1
    for n in (20, 50, 100):
        F[f'dist_hi{n}'] = c / h.rolling(n).max() - 1
        F[f'dist_lo{n}'] = c / l.rolling(n).min() - 1
    rng = (h - l).replace(0, np.nan)
    F['close_in_bar'] = (c - l) / rng
    F['body_pct'] = (c - o).abs() / rng
    F['upper_wick'] = (h - pd.concat([o, c], axis=1).max(axis=1)) / rng
    F['lower_wick'] = (pd.concat([o, c], axis=1).min(axis=1) - l) / rng
    up = (c > o).astype(int)
    F['up_streak'] = up.groupby((up != up.shift()).cumsum()).cumcount() + 1
    F['up_streak'] = F['up_streak'] * (up * 2 - 1)   # موجب لصعود متتالٍ، سالب لهبوط
    fdf = pd.DataFrame(F, index=df.index)
    return fdf


def ict_feats(df):
    """ميزات ICT/SMC بلا look-ahead: نقاط البنية مؤكَّدة بإزاحة SWING_L شمعات."""
    h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy(); o = df['open'].to_numpy()
    N = len(df); L = SWING_L
    # كشف fractals: قمة عند j لو high[j] أعلى من L شمعات قبلها وبعدها → تُعرف عند j+L فقط
    sw_hi_price = np.full(N, np.nan); sw_lo_price = np.full(N, np.nan)
    cur_hi = np.nan; cur_lo = np.nan; prev_hi = np.nan; prev_lo = np.nan
    cur_hi_arr = np.full(N, np.nan); cur_lo_arr = np.full(N, np.nan)
    prev_hi_arr = np.full(N, np.nan); prev_lo_arr = np.full(N, np.nan)
    for i in range(N):
        # عند الوصول للشمعة i، أي fractal مركزه j=i-L أصبح مؤكَّداً الآن
        j = i - L
        if j - L >= 0:
            seg_h = h[j-L:j+L+1]; seg_l = l[j-L:j+L+1]
            if h[j] == seg_h.max() and np.argmax(seg_h) == L:
                prev_hi = cur_hi; cur_hi = h[j]
            if l[j] == seg_l.min() and np.argmin(seg_l) == L:
                prev_lo = cur_lo; cur_lo = l[j]
        cur_hi_arr[i] = cur_hi; cur_lo_arr[i] = cur_lo
        prev_hi_arr[i] = prev_hi; prev_lo_arr[i] = prev_lo
    F = {}
    # كسر البنية صعوداً: الإغلاق فوق آخر قمة مؤكَّدة
    F['bos_up'] = (c > cur_hi_arr).astype(float)
    F['bos_dn'] = (c < cur_lo_arr).astype(float)
    # CHoCH صعودي: كسر قمة + البنية السابقة هابطة (قمم متنازلة وقيعان متنازلة)
    downtrend = (cur_hi_arr < prev_hi_arr) & (cur_lo_arr < prev_lo_arr)
    F['choch_up'] = ((c > cur_hi_arr) & downtrend).astype(float)
    # premium/discount: الموضع داخل المدى [قاع، قمة] المؤكَّد
    rng = cur_hi_arr - cur_lo_arr
    F['pd_pos'] = np.where(rng > 0, (c - cur_lo_arr) / rng, 0.5)   # <0.5 = discount
    F['in_discount'] = (F['pd_pos'] < 0.5).astype(float)
    # المسافة لأقرب قمة/قاع مؤكَّد (سيولة)
    F['dist_swhi'] = np.where(cur_hi_arr > 0, c / cur_hi_arr - 1, 0.0)
    F['dist_swlo'] = np.where(cur_lo_arr > 0, c / cur_lo_arr - 1, 0.0)
    # اقتناص سيولة صعودي: اخترق قاع L شمعات ثم أغلق فوقه (stop hunt)
    prior_lo = pd.Series(l).rolling(10).min().shift(1).to_numpy()
    F['liq_sweep_up'] = ((l < prior_lo) & (c > prior_lo)).astype(float)
    # FVG صعودية: low[i] > high[i-2] (فجوة) — تُعرف عند i
    bull_fvg = np.zeros(N)
    bull_fvg[2:] = (l[2:] > h[:-2]).astype(float)
    F['bull_fvg'] = bull_fvg
    # Order block صعودي قريب: آخر شمعة هابطة قبل اندفاع كسر قمة، المسافة لقاعها
    # تبسيط: لو bos_up حدث في آخر 5 شموع، المسافة لأدنى سعر في تلك النافذة (منطقة OB)
    ob_zone = pd.Series(np.where(F['bos_up'] == 1, l, np.nan)).ffill(limit=5).to_numpy()
    F['dist_bull_ob'] = np.where(ob_zone > 0, c / ob_zone - 1, 0.0)
    return pd.DataFrame(F, index=df.index)


def labels(df, tf):
    """triple-barrier محسّن لكل k. متشائم intrabar (يفحص الستوب قبل الهدف)."""
    h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    atr = pta.atr(df['high'], df['low'], df['close'], length=14).to_numpy()
    N = len(df); Nh = HORIZON[tf]
    out = {}
    atr_pct = atr / c
    for k in KS:
        kk = str(k).replace('.', '')
        hit = np.full(N, np.nan); dirw = np.full(N, np.nan)
        ret = np.full(N, np.nan); bars = np.full(N, np.nan)
        for i in range(N):
            a = atr_pct[i]
            if not np.isfinite(a) or a <= 0 or i + 1 >= N:
                continue
            entry = c[i]; tgt = entry * (1 + k * a); stp = entry * (1 - a)
            end = min(i + Nh, N - 1)
            res_hit = 0; res_ret = np.nan; res_bar = end - i
            done = False
            for j in range(i + 1, end + 1):
                # متشائم: الستوب يُفحص أولاً داخل الشمعة
                if l[j] <= stp:
                    res_hit = 0; res_ret = -a; res_bar = j - i; done = True; break
                if h[j] >= tgt:
                    res_hit = 1; res_ret = k * a; res_bar = j - i; done = True; break
            if not done:
                res_ret = c[end] / entry - 1   # حكم اتجاهي عند انتهاء الوقت
            hit[i] = res_hit
            dirw[i] = 1.0 if (res_hit == 1 or (not done and res_ret > 0)) else 0.0
            ret[i] = res_ret; bars[i] = res_bar
        out[f'hit_k{kk}'] = hit
        out[f'dir_k{kk}'] = dirw
        out[f'ret_k{kk}'] = ret
        out[f'bars_k{kk}'] = bars
    return pd.DataFrame(out, index=df.index)


def regime_col(df):
    import ta as ta_lib
    c = df['close']; e20 = pta.ema(c, 20); e50 = pta.ema(c, 50); e200 = pta.ema(c, 200)
    atr = pta.atr(df['high'], df['low'], c, 14); avg = atr.rolling(20).mean()
    e200f = e200.fillna(e50)
    reg = np.where(atr > avg * 1.5, 'volatile',
          np.where((c > e20) & (e20 > e50) & (e50 > e200f), 'bullish',
          np.where((c < e20) & (e20 < e50) & (e50 < e200f), 'bearish', 'sideways')))
    return reg


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = sorted({os.path.basename(p) for p in glob.glob(f"{DATA}/*") if os.path.isdir(p)})
    syms = [s for s in syms if glob.glob(f"{DATA}/{s}/*/*.zip")]
    if limit: syms = syms[:limit]
    print(f"building ML dataset on {len(syms)} symbols, TFs={TFS}, horizon={HORIZON}, k={KS}", flush=True)
    parts = []; nsym = 0
    for sym in syms:
        for tf in TFS:
            df = E.load(sym, tf)
            if df is None or len(df) < WARM + HORIZON[tf] + 10:
                continue
            try:
                Ff = feats(df); Fi = ict_feats(df); Fl = labels(df, tf)
            except Exception as ex:
                print(f"  skip {sym} {tf}: {ex}", flush=True); continue
            block = pd.concat([Ff, Fi, Fl], axis=1)
            block['symbol'] = sym; block['tf'] = tf
            block['t'] = df['t'].to_numpy()
            block['year'] = pd.to_datetime(df['t'], unit='ms', errors='coerce').dt.year.to_numpy()
            block['regime'] = regime_col(df)
            block = block.iloc[WARM:len(df) - 1]            # تجاهل الإحماء وآخر شمعة
            block = block.iloc[::STRIDE]
            block = block.dropna(subset=['hit_k15'])         # لازم تسمية صالحة
            parts.append(block)
        nsym += 1
        if nsym % 25 == 0: print(f"  {nsym}/{len(syms)} symbols, rows so far={sum(len(p) for p in parts):,}", flush=True)
    full = pd.concat(parts, ignore_index=True)
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/ml_dataset.parquet"
    full.to_parquet(path)
    feat_cols = [col for col in full.columns if col not in
                 ('symbol', 'tf', 't', 'year', 'regime') and not col.startswith(('hit_', 'dir_', 'ret_', 'bars_'))]
    print(f"\nDONE rows={len(full):,} features={len(feat_cols)} -> {path}", flush=True)
    print("feature list:", feat_cols, flush=True)
    print("\n=== label base rates (hit target before stop) ===", flush=True)
    for tf in TFS:
        sub = full[full.tf == tf]
        for k in KS:
            kk = str(k).replace('.', '')
            hr = sub[f'hit_k{kk}'].mean() * 100; dr = sub[f'dir_k{kk}'].mean() * 100
            print(f"  {tf} k={k}: hit={hr:.1f}%  dir-success={dr:.1f}%  n={len(sub):,}", flush=True)
    print("\n=== by regime (k=1.5, hit%) ===", flush=True)
    for tf in TFS:
        sub = full[full.tf == tf]
        print(f"  {tf}:", {r: round(sub[sub.regime == r]['hit_k15'].mean() * 100, 1)
                           for r in ('bullish', 'sideways', 'bearish', 'volatile')}, flush=True)
