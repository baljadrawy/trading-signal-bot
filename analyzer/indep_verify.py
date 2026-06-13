"""Independent cross-check of cross-sectional momentum L/S backtest. Written from scratch."""
import os, zipfile, io
import numpy as np
import pandas as pd

BASE = "/app/logs/bt_data"
SYMFILE = "/app/bt_symbols.txt"
FEE_RATE = 0.004  # per leg turnover unit
HOLD = 14
LOOKBACK_MOM = 30
ADV_WIN = 30
TOP_N = 30        # universe size
REBAL = 14

def load_symbol(sym):
    """Return a DataFrame indexed by date with columns close, dollar_vol. None if no data."""
    d = os.path.join(BASE, sym, "1d")
    if not os.path.isdir(d):
        return None
    rows = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".zip"):
            continue
        try:
            z = zipfile.ZipFile(os.path.join(d, fn))
        except Exception:
            continue
        for member in z.namelist():
            if not member.endswith(".csv"):
                continue
            txt = z.read(member).decode()
            for line in txt.splitlines():
                if not line.strip():
                    continue
                parts = line.split(",")
                try:
                    ot = float(parts[0])
                    close = float(parts[4])
                    vol = float(parts[5])
                except Exception:
                    continue
                # normalize timestamp: microseconds -> ms
                if ot > 1e14:
                    ot = ot / 1000.0
                rows.append((ot, close, vol))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ot_ms", "close", "volume"])
    df["date"] = pd.to_datetime(df["ot_ms"], unit="ms").dt.normalize()
    df = df.drop_duplicates(subset="date").sort_values("date").set_index("date")
    df["dollar_vol"] = df["close"] * df["volume"]
    return df[["close", "dollar_vol"]]

def main():
    with open(SYMFILE) as f:
        symbols = [l.strip() for l in f if l.strip()]

    closes = {}
    advols = {}
    for s in symbols:
        df = load_symbol(s)
        if df is None or len(df) < 60:
            continue
        closes[s] = df["close"]
        advols[s] = df["dollar_vol"]

    print(f"Loaded {len(closes)} symbols with data")

    close_df = pd.DataFrame(closes).sort_index()
    dv_df = pd.DataFrame(advols).reindex(close_df.index)

    # BTC regime
    if "BTCUSDT" not in close_df.columns:
        raise SystemExit("No BTC data")
    btc = close_df["BTCUSDT"].dropna()
    ema50 = btc.ewm(span=50, adjust=False).mean()
    ema200 = btc.ewm(span=200, adjust=False).mean()
    regime_on = (btc > ema50) & (btc > ema200)

    dates = close_df.index
    n = len(dates)

    # rebalance entry indices: every REBAL days, need t+HOLD available
    prev_long = set()
    prev_short = set()
    records = []  # (entry_date, year, net_ret, active)

    i = LOOKBACK_MOM  # need lookback history
    while i + HOLD < n:
        t = dates[i]
        # ADV over prior 30 days (i-30 .. i-1)
        adv_slice = dv_df.iloc[i-ADV_WIN:i]
        adv = adv_slice.mean(axis=0)  # NaN if missing
        # require valid close at t and at t-mom and t+hold
        row_t = close_df.iloc[i]
        row_tm = close_df.iloc[i-LOOKBACK_MOM]
        row_th = close_df.iloc[i+HOLD]

        valid = adv.notna() & row_t.notna() & row_tm.notna() & row_th.notna() & (row_t > 0) & (row_tm > 0)
        adv_valid = adv[valid].dropna()
        # universe = top 30 by ADV
        universe = adv_valid.sort_values(ascending=False).head(TOP_N).index.tolist()

        entry_year = t.year
        if len(universe) < 10 or entry_year < 2024:
            # advance; only record active periods within 2024-2025 entry window
            if entry_year >= 2024 and len(universe) >= 10:
                pass
            i += REBAL
            continue

        # momentum within universe
        mom = (row_t[universe] / row_tm[universe] - 1.0)
        mom = mom.sort_values(ascending=False)
        k = max(1, int(round(len(universe) * 0.10)))
        longs = mom.head(k).index.tolist()
        shorts = mom.tail(k).index.tolist()

        # forward returns
        fwd = (row_th[universe] / row_t[universe] - 1.0)
        long_ret = fwd[longs].mean()
        short_ret = fwd[shorts].mean()

        active = bool(regime_on.get(t, False))
        if active:
            gross = 0.5 * (long_ret - short_ret)
            new_long, new_short = set(longs), set(shorts)
            def leg_turnover(prev, new):
                u = prev | new
                if not u:
                    return 0.0
                return len(prev ^ new) / (2.0 * len(u))
            cost = (leg_turnover(prev_long, new_long) + leg_turnover(prev_short, new_short)) * FEE_RATE
            net = gross - cost
            prev_long, prev_short = new_long, new_short
        else:
            net = 0.0
            # cash period: positions cleared
            prev_long, prev_short = set(), set()

        records.append({"date": t, "year": entry_year, "net": net, "active": active})
        i += REBAL

    res = pd.DataFrame(records)
    print(f"\nTotal rebalance periods (2024-25 entries, valid universe): {len(res)}")

    def metrics(sub, label):
        if len(sub) == 0:
            print(f"{label}: no periods"); return
        rets = sub["net"].values
        active = sub[sub["active"]]
        n_active = int(sub["active"].sum())
        comp = np.prod(1 + rets) - 1
        mu, sd = rets.mean(), rets.std(ddof=1) if len(rets) > 1 else np.nan
        sharpe = (mu / sd * np.sqrt(52)) if sd and sd > 0 else np.nan
        pos = rets[rets > 0].sum()
        neg = rets[rets < 0].sum()
        pf = (pos / abs(neg)) if neg < 0 else np.inf
        # max drawdown on equity
        eq = np.cumprod(1 + rets)
        peak = np.maximum.accumulate(eq)
        dd = (eq / peak - 1).min()
        print(f"\n=== {label} ===")
        print(f"  periods total={len(sub)}  active(non-cash)={n_active}")
        print(f"  compounded return = {comp*100:.2f}%")
        print(f"  Sharpe (per-period mean/std * sqrt52) = {sharpe:.3f}")
        print(f"  Profit Factor = {pf:.3f}")
        print(f"  MaxDrawdown = {dd*100:.2f}%")
        # Sharpe/PF on ACTIVE-only too
        if n_active > 1:
            ar = active["net"].values
            asd = ar.std(ddof=1)
            ash = (ar.mean()/asd*np.sqrt(52)) if asd>0 else np.nan
            ap = ar[ar>0].sum(); an = ar[ar<0].sum()
            apf = ap/abs(an) if an<0 else np.inf
            print(f"  [active-only] Sharpe={ash:.3f}  PF={apf:.3f}")
        return rets

    full_rets = metrics(res, "FULL 2024-2025")
    metrics(res[res["year"]==2024], "2024")
    metrics(res[res["year"]==2025], "2025 (OOS)")

    # profit concentration top-10 periods share
    if len(res):
        srt = np.sort(res["net"].values)[::-1]
        total = res["net"].sum()
        top10 = srt[:10].sum()
        print(f"\nProfit concentration: total net (sum) = {total*100:.2f}%, top-10 periods sum = {top10*100:.2f}%, share = {top10/total*100 if total!=0 else float('nan'):.1f}%")

    # dump active period dates for inspection
    print("\nActive period entries:")
    for _, r in res[res["active"]].iterrows():
        print(f"  {r['date'].date()}  net={r['net']*100:+.2f}%")

if __name__ == "__main__":
    main()
