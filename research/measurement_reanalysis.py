# research/measurement_reanalysis.py
"""Non-destructive re-analysis of the recorded live-learning cohort: applies the
two recording fixes (dedup + modeled stop-fill) to EXISTING trades and prints the
before/after impact. Read-only — never writes to the DB. Run in the venv:

    research/skill_application/.venv/bin/python research/measurement_reanalysis.py
"""
import subprocess, io, sys
sys.path.insert(0, '.')
import pandas as pd
from shared.candle import candle_seconds, is_within_candle
from shared.triple_barrier import modeled_stop_exit

FEE_PCT = 0.6          # round-trip fee for net@fee
NOTIONAL = 50.0        # $ per trade
SLIPPAGE = 0.001       # match STOP_SLIPPAGE default

QUERY = """
COPY (
  SELECT tr.id, s.symbol, s.trade_type, s.timeframe,
         EXTRACT(EPOCH FROM s.signal_time) AS signal_ts,
         s.entry_price::float AS entry, s.stop_loss::float AS stop_loss,
         tr.profit_percent::float AS profit_percent, tr.stop_hit, tr.target_reached
  FROM trade_results tr JOIN signals s ON s.id = tr.signal_id
  WHERE s.trade_type IS NOT NULL
  ORDER BY s.signal_time
) TO STDOUT WITH CSV HEADER
"""


def load():
    out = subprocess.run(
        ["docker", "exec", "-i", "postgres", "psql", "-U", "trading_signal_bot",
         "-d", "trading_signals", "-A", "-c", QUERY],
        capture_output=True, text=True, check=True).stdout
    df = pd.read_csv(io.StringIO(out))
    df['stop_hit'] = df['stop_hit'].astype(str).str.lower().isin(['t', 'true', '1'])
    return df


def metrics(df, label):
    n = len(df)
    wr = 100.0 * (df.profit_percent > 0).mean() if n else 0.0
    gross = (df.profit_percent / 100 * NOTIONAL).sum()
    net = ((df.profit_percent - FEE_PCT) / 100 * NOTIONAL).sum()
    print(f"{label:22s} n={n:4d}  WR={wr:5.1f}%  gross=${gross:8.2f}  net@{FEE_PCT}%=${net:8.2f}")


def reprice_stops(df):
    df = df.copy()
    for i, r in df.iterrows():
        if not r.stop_hit:
            continue
        eff_stop = r.entry if r.target_reached >= 1 else r.stop_loss  # approx dynamic stop
        _, pct = modeled_stop_exit(r.entry, eff_stop, SLIPPAGE)
        df.at[i, 'profit_percent'] = pct
    return df


def dedup(df):
    keep, last = [], {}   # (symbol,timeframe) -> last kept signal_ts
    for r in df.itertuples():
        k = (r.symbol, r.timeframe)
        if k in last and is_within_candle(r.signal_ts, last[k], r.timeframe):
            continue
        keep.append(r.Index); last[k] = r.signal_ts
    return df.loc[keep]


def main():
    df = load()
    print("=== BEFORE (as recorded) ===")
    metrics(df, "overall")
    for t in sorted(df.trade_type.dropna().unique()):
        metrics(df[df.trade_type == t], f"  {t}")

    fixed = dedup(reprice_stops(df))
    print("\n=== AFTER (dedup + modeled stops) ===")
    metrics(fixed, "overall")
    for t in sorted(fixed.trade_type.dropna().unique()):
        metrics(fixed[fixed.trade_type == t], f"  {t}")

    print(f"\nrows: {len(df)} -> {len(fixed)}  (removed {len(df)-len(fixed)} pseudo-replicated)")


if __name__ == "__main__":
    main()
