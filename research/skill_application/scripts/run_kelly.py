#!/usr/bin/env python3
"""TASK E_KELLY — Risk/position-sizing reality check via kelly-criterion methodology.

For each cohort (ALL, stoch>0, COMBO=stoch>0 & rsi_divergence>0) compute on net_usdt:
  win rate, payoff ratio (avg_win/avg_loss), edge, full + conservative (Wilson-LB) Kelly.
Plus equity-curve max drawdown and longest losing streak per cohort.
Frame for a non-technical trader: survival-safe bet size at the measured edge.
"""
import json
import math
import numpy as np
import pandas as pd
import lib

OUT = lib.WORK + "/out/kelly_results.json"


def wilson_interval(wins, total, z=1.96):
    if total == 0:
        return (0.0, 1.0)
    p = wins / total
    denom = 1.0 + z**2 / total
    centre = p + z**2 / (2.0 * total)
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4.0 * total)) / total)
    return (max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom))


def kelly_block(net):
    """Kelly stats on a net-PnL array. Uses payoff-ratio Kelly: f = edge / payoff."""
    net = np.asarray(net, float)
    wins = net[net > 0]
    losses = net[net < 0]
    flat = net[net == 0]
    total = len(net)
    nw, nl = len(wins), len(losses)
    out = {
        "n": total, "wins": nw, "losses": nl, "flat": len(flat),
        "win_rate": (nw / total) if total else 0.0,
        "total_net": float(net.sum()),
        "avg_net": float(net.mean()) if total else 0.0,
        "std_net": float(net.std()) if total else 0.0,
    }
    if nw == 0 or nl == 0:
        out.update({"avg_win": float(wins.mean()) if nw else 0.0,
                    "avg_loss": abs(float(losses.mean())) if nl else 0.0,
                    "payoff_ratio": None, "edge": None,
                    "kelly_full": 0.0, "kelly_conservative": 0.0,
                    "note": "need both wins and losses for Kelly"})
        return out
    avg_win = float(wins.mean())
    avg_loss = abs(float(losses.mean()))
    payoff = avg_win / avg_loss if avg_loss > 0 else float("inf")
    wr = nw / total
    edge = wr * payoff - (1.0 - wr)         # expected net units per 1 unit risked
    kelly_full = edge / payoff if payoff > 0 else 0.0
    ci_lo, ci_hi = wilson_interval(nw, total)
    cons_edge = ci_lo * payoff - (1.0 - ci_lo)
    kelly_cons = cons_edge / payoff if (payoff > 0 and cons_edge > 0) else 0.0
    out.update({
        "avg_win": avg_win, "avg_loss": avg_loss,
        "median_win": float(np.median(wins)), "median_loss": abs(float(np.median(losses))),
        "max_win": float(wins.max()), "max_loss": abs(float(losses.min())),
        "payoff_ratio": payoff,
        "win_rate_ci95": [ci_lo, ci_hi],
        "edge": edge,
        "kelly_full": kelly_full,            # may be negative -> bet 0 (or short)
        "kelly_conservative": kelly_cons,    # clamped at 0 (Wilson LB)
        "kelly_full_pct": kelly_full * 100,
        # fractional Kelly only meaningful if positive
        "kelly_quarter": max(0.0, kelly_full) * 0.25,
        "kelly_half": max(0.0, kelly_full) * 0.50,
    })
    return out


def equity_risk(net, order):
    """Max drawdown of cumulative equity and longest losing streak, in chronological order."""
    s = pd.Series(np.asarray(net, float), index=order).sort_index().values
    eq = np.cumsum(s)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak                      # <= 0, in $
    max_dd = float(dd.min()) if len(dd) else 0.0
    # longest losing streak (consecutive net<0)
    longest = cur = 0
    longest_loss_usd = cur_loss = 0.0
    worst_loss_run = 0.0
    for v in s:
        if v < 0:
            cur += 1
            cur_loss += v
            longest = max(longest, cur)
            worst_loss_run = min(worst_loss_run, cur_loss)
        else:
            cur = 0
            cur_loss = 0.0
    return {
        "final_equity": float(eq[-1]) if len(eq) else 0.0,
        "max_drawdown_usd": max_dd,
        "max_drawdown_pct_of_pos": max_dd / lib.POS_USDT * 100,
        "longest_losing_streak": int(longest),
        "worst_consecutive_loss_run_usd": float(worst_loss_run),
    }


def main():
    df = lib.load_trades().copy()
    df = df.sort_values("signal_time").reset_index(drop=True)

    cohorts = {
        "ALL": np.ones(len(df), bool),
        "stoch_gt0": (df.st_stoch_rsi > 0).values,
        "COMBO_stoch_and_div": ((df.st_stoch_rsi > 0) & (df.st_rsi_divergence > 0)).values,
    }

    results = {}
    for name, mask in cohorts.items():
        sub = df[mask]
        net = sub.net_usdt.values
        gross = sub.profit_usdt.values
        blk = kelly_block(net)
        blk_gross = kelly_block(gross)
        risk = equity_risk(net, sub.signal_time.values)
        blk["risk"] = risk
        blk["gross_for_contrast"] = {
            "edge": blk_gross["edge"], "kelly_full": blk_gross["kelly_full"],
            "payoff_ratio": blk_gross["payoff_ratio"], "win_rate": blk_gross["win_rate"],
            "avg_net": blk_gross["avg_net"],
        }
        results[name] = blk

    # COMBO temporal breakdown (5/7 in May claim) — survival check
    combo = df[cohorts["COMBO_stoch_and_div"]].copy()
    combo["month"] = combo.signal_time.dt.to_period("M").astype(str)
    combo_months = combo.groupby("month").agg(
        n=("win", "size"), wins=("win", "sum"),
        net=("net_usdt", "sum")).reset_index()
    results["COMBO_monthly"] = combo_months.to_dict("records")
    results["COMBO_trades"] = combo[["signal_time", "symbol", "result",
                                     "profit_usdt", "net_usdt"]].assign(
        signal_time=lambda d: d.signal_time.astype(str)).to_dict("records")

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # ---- readable report ----
    print("=" * 78)
    print("KELLY / POSITION-SIZING REALITY CHECK  (net of 0.3% round-trip fees)")
    print("=" * 78)
    for name in ["ALL", "stoch_gt0", "COMBO_stoch_and_div"]:
        r = results[name]
        print(f"\n### {name}  (n={r['n']}, wins={r['wins']}, losses={r['losses']})")
        print(f"  win_rate            = {r['win_rate']*100:.2f}%")
        if r.get("payoff_ratio") is not None:
            print(f"  avg_win / avg_loss  = ${r['avg_win']:.4f} / ${r['avg_loss']:.4f}"
                  f"  -> payoff = {r['payoff_ratio']:.3f}")
            print(f"  edge (net units)    = {r['edge']:+.4f}")
            print(f"  FULL KELLY          = {r['kelly_full']*100:+.2f}%   "
                  f"(conservative/Wilson-LB = {r['kelly_conservative']*100:.2f}%)")
            gc = r["gross_for_contrast"]
            print(f"  [gross contrast]    edge={gc['edge']:+.4f}  kelly={gc['kelly_full']*100:+.2f}%")
        else:
            print(f"  {r.get('note')}")
        print(f"  avg_net/trade       = ${r['avg_net']:+.4f}   total_net=${r['total_net']:+.2f}")
        rk = r["risk"]
        print(f"  max drawdown        = ${rk['max_drawdown_usd']:.2f} "
              f"({rk['max_drawdown_pct_of_pos']:.1f}% of one $50 position)")
        print(f"  longest losing streak = {rk['longest_losing_streak']} trades "
              f"(worst run ${rk['worst_consecutive_loss_run_usd']:.2f})")

    print("\n### COMBO monthly survival breakdown")
    for m in results["COMBO_monthly"]:
        print(f"  {m['month']}: n={m['n']} wins={m['wins']} net=${m['net']:+.3f}")
    print("\nWrote", OUT)


if __name__ == "__main__":
    main()
