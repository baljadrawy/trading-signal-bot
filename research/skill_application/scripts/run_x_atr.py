"""
TASK X_ATR — Exit-strategy re-simulation: ATR-based stop vs fixed stop.

Holds ENTRY FIXED at recorded entry_price. Replays each trade against real 1h
intrabar OHLC over [signal_time, min(exit_time, signal_time+48h)] under alternative
exit rules. Long-only (all 2518 trades are long).

Rules compared on the SAME trade set (1h-OHLC covered):
  A. fixed   : recorded stop_loss + recorded T1/T2/T3 (SANITY-REPLAY vs recorded result)
  B. atr2.0 / atr2.5 / atr3.0 : stop at entry - k*ATR14, same targets
  C. atr*_d4 : same ATR stop but no stop active in first 4h (activation delay)

Exit/scaling semantics (identical across rules, only the STOP differs):
  - 1/3 position out at T1, 1/3 at T2, 1/3 at T3 (scaled exit).
  - After T1 fills, stop -> break-even (entry). After T2 fills, stop -> T1.
  - If stop touched on remaining qty, sell remainder at stop price.
  - Intrabar conservatism: within a bar, STOP is checked before TARGETS
    (worst-case for the alt strategy; if bar.low<=stop AND bar.high>=tp, stop wins).
  - End-of-window: sell any remainder at last close.

Fees: round-trip FEE_USD ($0.15 on $50) charged once per trade (entry+exit), as in lib.
P&L on $50 notional, weighted by tranche fraction.
"""
import json
import numpy as np
import pandas as pd
import lib

POS = lib.POS_USDT
FEE = lib.FEE_USD
CAP_H = 48
ATR_PERIOD = 14
ATR_MULTS = [2.0, 2.5, 3.0]
DELAY_H = 4

_ohlc_cache = {}
def get_ohlc(sym):
    if sym not in _ohlc_cache:
        _ohlc_cache[sym] = lib.load_ohlc(sym, prefer=("1h",))  # 1h only for intrabar fidelity
    return _ohlc_cache[sym]


def atr14(o):
    """Wilder-style ATR(14) on full history; returns Series aligned to o.index."""
    h, l, c = o["h"], o["l"], o["c"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / ATR_PERIOD, adjust=False, min_periods=1).mean()


def simulate(bars, entry, stop0, t1, t2, t3, delay_h=0):
    """
    Walk 1h bars (DataFrame o,h,l,c). Returns (net_pnl_usd, win_flag, sl_before_t1_flag, exit_reason).
    Scaled exit 1/3 at each target; stop ratchets to BE after T1, to T1 after T2.
    Intrabar: stop checked before targets (worst-case). delay_h: stop inactive for first delay_h hours.
    win_flag: net pnl (gross, pre-fee) > 0.
    sl_before_t1: stop removed the LAST remaining qty before any target tranche filled.
    """
    remaining = 1.0
    realized = 0.0  # gross fraction-weighted pct return (decimal)
    stop = stop0
    tps = [t1, t2, t3]
    ti = 0  # next target index
    t0 = bars.index[0]
    any_target = False
    exit_reason = "eow"

    for ts, b in zip(bars.index, bars.itertuples(index=False)):
        lo, hi = b.l, b.h
        stop_active = (ts - t0) >= pd.Timedelta(hours=delay_h)

        # STOP first (worst-case)
        if stop_active and remaining > 0 and lo <= stop:
            realized += (stop - entry) / entry * remaining
            sl_before_t1 = not any_target
            remaining = 0.0
            exit_reason = "stop"
            net = realized * POS - FEE
            return net, (realized > 0), sl_before_t1, exit_reason

        # TARGETS (may fill multiple tranches in one bar)
        while ti < 3 and remaining > 0 and hi >= tps[ti]:
            frac = 1.0 / 3.0
            frac = min(frac, remaining)
            realized += (tps[ti] - entry) / entry * frac
            remaining -= frac
            any_target = True
            ti += 1
            if ti == 1:
                stop = max(stop, entry)        # break-even after T1
            elif ti == 2:
                stop = max(stop, tps[0])       # T1 after T2
        if remaining <= 1e-9:
            exit_reason = "targets"
            net = realized * POS - FEE
            return net, (realized > 0), False, exit_reason

    # End of window: liquidate remainder at last close
    last_c = bars["c"].iloc[-1]
    realized += (last_c - entry) / entry * remaining
    net = realized * POS - FEE
    sl_before_t1 = False
    return net, (realized > 0), sl_before_t1, "eow"


def run():
    df = lib.load_trades()
    rules = ["fixed", "atr2.0", "atr2.5", "atr3.0", "atr2.0_d4", "atr2.5_d4", "atr3.0_d4"]
    records = {r: [] for r in rules}           # net pnl per trade
    winflag = {r: [] for r in rules}
    slb_t1 = {r: [] for r in rules}
    covered_ids = []
    recorded_net = []
    recorded_win = []

    n_no_ohlc = 0
    n_signal_after = 0
    n_too_few_bars = 0

    for _, r in df.iterrows():
        sym = r["symbol"]; o = get_ohlc(sym)
        if o is None:
            n_no_ohlc += 1; continue
        st = r["signal_time"]; et = r["exit_time"]
        if st > o.index[-1]:
            n_signal_after += 1; continue
        end = min(et, st + pd.Timedelta(hours=CAP_H))
        # bars from signal bar (floor to hour) through end (clipped to data)
        start_bar = st.floor("h")
        win = o[(o.index >= start_bar) & (o.index <= max(end, start_bar))]
        if len(win) < 2:
            # allow up to data end if exit beyond data
            win = o[(o.index >= start_bar) & (o.index <= min(st + pd.Timedelta(hours=CAP_H), o.index[-1]))]
        if len(win) < 2:
            n_too_few_bars += 1; continue

        entry = float(r["entry_price"])
        t1, t2, t3 = float(r["target_1"]), float(r["target_2"]), float(r["target_3"])
        # guard: targets must be above entry and ordered; if not, skip target that's <= entry by setting unreachable
        # (keep recorded targets; sim naturally won't fill a target below current entry on the high side check)

        # ATR at signal bar (value on the bar at/just before signal)
        atr_series = atr14(o)
        atr_at = atr_series.reindex(o.index)
        # value at the start bar (or last available before)
        av = atr_at[atr_at.index <= start_bar]
        atr_val = float(av.iloc[-1]) if len(av) else float(atr_series.iloc[0])

        covered_ids.append(r["id"])
        recorded_net.append(float(r["net_usdt"]))
        recorded_win.append(int(r["win"]))

        # A. fixed
        net, w, slb, _ = simulate(win, entry, float(r["stop_loss"]), t1, t2, t3, delay_h=0)
        records["fixed"].append(net); winflag["fixed"].append(w); slb_t1["fixed"].append(slb)

        # B/C. ATR variants
        for k in ATR_MULTS:
            stop_atr = entry - k * atr_val
            net, w, slb, _ = simulate(win, entry, stop_atr, t1, t2, t3, delay_h=0)
            tag = f"atr{k:.1f}"
            records[tag].append(net); winflag[tag].append(w); slb_t1[tag].append(slb)
            net, w, slb, _ = simulate(win, entry, stop_atr, t1, t2, t3, delay_h=DELAY_H)
            tagd = f"atr{k:.1f}_d4"
            records[tagd].append(net); winflag[tagd].append(w); slb_t1[tagd].append(slb)

    n = len(covered_ids)
    rec_net = np.array(recorded_net); rec_win = np.array(recorded_win)

    summary = {}
    for r in rules:
        net = np.array(records[r]); wf = np.array(winflag[r]); sb = np.array(slb_t1[r])
        summary[r] = {
            "n": int(n),
            "net_exp": round(float(net.mean()), 4),
            "gross_exp": round(float(net.mean() + FEE), 4),
            "WR_%": round(100 * float(wf.mean()), 2),
            "PF_net": round(lib.pf(net), 3),
            "total_net": round(float(net.sum()), 2),
            "sl_before_t1_%": round(100 * float(sb.mean()), 2),
        }

    # recorded baseline on same covered set
    summary["RECORDED(baseline)"] = {
        "n": int(n),
        "net_exp": round(float(rec_net.mean()), 4),
        "gross_exp": round(float(rec_net.mean() + FEE), 4),
        "WR_%": round(100 * float(rec_win.mean()), 2),
        "PF_net": round(lib.pf(rec_net), 3),
        "total_net": round(float(rec_net.sum()), 2),
        "sl_before_t1_%": None,
    }

    # sanity: correlation of 'fixed' replay vs recorded net
    fixed_net = np.array(records["fixed"])
    corr = float(np.corrcoef(fixed_net, rec_net)[0, 1]) if n > 2 else float("nan")
    win_agree = float((np.array(winflag["fixed"]) == rec_win).mean())

    out = {
        "coverage": {
            "total_trades": int(len(df)),
            "covered_1h_intrabar": int(n),
            "pct_covered": round(100 * n / len(df), 1),
            "n_no_ohlc": int(n_no_ohlc),
            "n_signal_after_data": int(n_signal_after),
            "n_too_few_bars": int(n_too_few_bars),
            "covered_WR_%": round(100 * rec_win.mean(), 2),
            "symbols": int(pd.Series([df.set_index('id').loc[i,'symbol'] for i in covered_ids]).nunique()),
            "months": pd.Series([str(df.set_index('id').loc[i,'signal_time'])[:7] for i in covered_ids]).value_counts().to_dict(),
        },
        "sanity_replay_fixed_vs_recorded": {
            "net_corr": round(corr, 3),
            "win_agreement": round(win_agree, 3),
            "note": "fixed-replay uses scaled 1/3 exits + BE ratchet, so it is NOT identical to the bot's recorded dynamic policy; corr/agreement gauge replay fidelity.",
        },
        "rules": summary,
    }
    print(json.dumps(out, indent=2, default=str))
    with open(f"{lib.WORK}/out/x_atr_exit_resim.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    return out


if __name__ == "__main__":
    run()
