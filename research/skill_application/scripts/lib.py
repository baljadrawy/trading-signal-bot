"""
Shared toolkit for the skill-application research workflow.
Isolated host venv. Read-only on DB dumps + cached OHLCV pkls. No live containers touched.

Data facts (verified 2026-06-23):
  trades.csv : 2518 closed trades (trade_results ⨝ signals), profit_usdt = GROSS (no fees).
  OHLCV cache (analyzer/research/cache):
    klines_kz_v2/SYM_1h_180d.pkl -> list[{'t':ms,'c':close}]            (close only, ~180d, to ~2026-05-21)
    klines/SYM_{1h,4h,1d}.pkl    -> list[{'t':ms,'o','h','l','c'}]      (full OHLC, ~90d, ~Feb19->May20)
Fee model: round-trip FEE_PCT% on POS_USDT -> fee_usd/trade. Default 0.3% on $50 = $0.15.
"""
import os, json, glob, math
import numpy as np
import pandas as pd

ROOT = "/home/tradmin/trading-signal-bot"
CACHE = f"{ROOT}/analyzer/research/cache"
WORK = f"{ROOT}/research/skill_application"
TRADES_CSV = f"{WORK}/data/trades.csv"

POS_USDT = 50.0
FEE_PCT = 0.3                       # round-trip %
FEE_USD = POS_USDT * FEE_PCT / 100  # $/trade

SCORE_KEYS = ["obv","rsi","macd","volume","bollinger","btc_trend","ema_cross",
              "fibonacci","stoch_rsi","order_book","rsi_divergence"]

# ----------------------------------------------------------------------------- trades
def load_trades():
    """Return trades DataFrame with score_details expanded into st_* columns + net_usdt."""
    df = pd.read_csv(TRADES_CSV)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True, errors="coerce")
    df["exit_time"]   = pd.to_datetime(df["exit_time"],   utc=True, errors="coerce")
    df["win"] = (df["result"] == "WIN").astype(int)
    df["net_usdt"] = df["profit_usdt"] - FEE_USD
    # expand score_details
    def parse(s):
        try: return json.loads(s) if isinstance(s, str) else {}
        except Exception: return {}
    sd = df["score_details"].apply(parse)
    for k in SCORE_KEYS:
        df[f"st_{k}"] = sd.apply(lambda d: float(d.get(k, 0) or 0))
    df["st_tf_conf"] = sd.apply(lambda d: float(d.get("timeframe_confirmations", 0) or 0))
    return df

def pf(net):
    net = np.asarray(net, float)
    g = net[net > 0].sum(); l = -net[net < 0].sum()
    return float(g / l) if l > 0 else float("inf")

# ----------------------------------------------------------------------------- ohlcv
def _list_to_df(rows):
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("dt").sort_index()

def ohlcv_index():
    """Map symbol -> {tf: path}. Prefers full-OHLC klines/ ; records close-only kz_v2 as '<tf>c'."""
    idx = {}
    for f in glob.glob(f"{CACHE}/klines/*_*.pkl"):
        base = os.path.basename(f)[:-4]
        if "_" not in base: continue
        sym, tf = base.rsplit("_", 1)
        idx.setdefault(sym, {})[tf] = f
    for f in glob.glob(f"{CACHE}/klines_kz_v2/*_1h_180d.pkl"):
        sym = os.path.basename(f).split("_1h_180d")[0]
        idx.setdefault(sym, {}).setdefault("1h_close180", f)
    return idx

def load_close(symbol, prefer=("1h_close180","1h","1d","4h")):
    """Return close Series (UTC index) from best available cache, or None."""
    idx = ohlcv_index().get(symbol, {})
    for tf in prefer:
        if tf in idx:
            df = _list_to_df(pd.read_pickle(idx[tf]))
            if "c" in df: return df["c"].astype(float)
    return None

def load_ohlc(symbol, prefer=("1h","4h","1d")):
    """Return OHLC DataFrame[o,h,l,c] (UTC index) from full-OHLC cache, or None."""
    idx = ohlcv_index().get(symbol, {})
    for tf in prefer:
        if tf in idx:
            df = _list_to_df(pd.read_pickle(idx[tf]))
            if {"o","h","l","c"}.issubset(df.columns):
                return df[["o","h","l","c"]].astype(float)
    return None

# ----------------------------------------------------------------------------- stats
def hurst(series, max_lag=60):
    """Hurst via rescaled-range on log returns. <0.5 mean-revert, ~0.5 random, >0.5 trend."""
    x = np.log(np.asarray(series, float))
    x = x[np.isfinite(x)]
    if len(x) < max_lag*2: return np.nan
    lags = range(2, max_lag)
    tau = [np.sqrt(np.std(x[lag:] - x[:-lag])) for lag in lags]
    tau = np.asarray(tau); m = tau > 0
    if m.sum() < 5: return np.nan
    return float(np.polyfit(np.log(np.asarray(list(lags))[m]), np.log(tau[m]), 1)[0] * 2.0)

def half_life(series):
    """OU half-life of mean reversion (bars). Large/neg -> not mean-reverting."""
    y = pd.Series(np.asarray(series, float)).dropna()
    if len(y) < 30: return np.nan
    ylag = y.shift(1).dropna(); yd = (y - y.shift(1)).dropna()
    n = min(len(ylag), len(yd)); ylag, yd = ylag.iloc[-n:].values, yd.iloc[-n:].values
    b = np.polyfit(ylag, yd, 1)[0]
    return float(-math.log(2)/b) if b < 0 else np.nan

if __name__ == "__main__":
    t = load_trades()
    print("trades:", t.shape, "| WR=%.1f%%" % (100*t.win.mean()),
          "| gross_exp=%.4f net_exp=%.4f PF_net=%.3f" % (t.profit_usdt.mean(), t.net_usdt.mean(), pf(t.net_usdt)))
    idx = ohlcv_index()
    print("ohlcv symbols indexed:", len(idx))
    s = load_close("RENDERUSDT")
    if s is not None:
        print("RENDER close:", s.shape, "Hurst=%.3f" % hurst(s), "half_life=%.1f" % half_life(s))
    o = load_ohlc("MEUSDT")
    if o is not None:
        print("ME ohlc:", o.shape, "cols", list(o.columns), str(o.index[0]), "->", str(o.index[-1]))
