# S4 mechanism comparison (exploratory planning, 2026-10-20)

**Status:** planning record for roadmap S4. It chooses **no** family, admits nothing and spends no alpha. No historical, protected or holdout data was used; no performance number below comes from a backtest. Tooling: `research/mechanisms/` (`s4-mech-v1`, synthetic-tested).

## 1. What constrains every candidate

| Constraint | Source | Consequence |
|---|---|---|
| Costs | Roadmap ground rules | 0.10 %/side fee, 0.20 % round trip, no BNB discount; spread and slippage separate; tracker 0.30 % reported beside it. `research/mechanisms/costs.py` refuses discounted fees |
| Prior evidence | A42–A46, A58 (pre-freeze H0: gross PF 0.73, net PF 0.59) | Negative for the **tested** 15m/4h indicator setups. It is not evidence against mechanisms at other horizons or on other data |
| Market | The bot trades Binance **Spot**, long only | Any mechanism whose return sits in a short leg is not executable here without a new venue decision |
| Data | A18/A19: Binance Vision licence **HOLD**; holdout after 2026-08-19T09:33:46Z sealed | No exploratory historical calculation can run until a dataset has a recorded permission. `simulate.run` enforces this |
| Power | `research/power` (S5-PWR-1), illustrative until validated | The 365-day daily-HAC annualised Sharpe MDE is about **3.5–7.0** depending on scenario and dependence (canonical table). A realistic daily strategy (Sharpe well below 2) **cannot be confirmed by one 365-day forward window**. Every path needs either a longer validation design or a much larger effect |

The power row is the binding fact: it applies to every mechanism equally, so it is a reason to redesign validation, not a reason to prefer one family.

## 2. Candidates

### M1 — Daily time-series momentum (TSMOM)
- **Hypothesis.** Assets whose own trailing return (weeks) is positive continue to drift up; slow information diffusion and trend-chasing flows. Strongest published evidence is in diversified futures (Moskowitz, Ooi and Pedersen, 2012). Crypto evidence exists at 1–4 week horizons (Liu and Tsyvinski, 2021), concentrated in large caps (A45-B).
- **Instruments.** Liquid spot pairs against USDT.
- **Data.** Daily closes; volatility for scaling. Same data as the current bot, at a different horizon.
- **Long/short.** Long-only is executable on Spot: long or cash per asset. The short side, which is part of the published effect, is not available.
- **Execution and fees.** Low turnover (weekly-scale signal changes), so fees are a small fraction of the gross per trade. Main risks are gap moves, not fills.
- **Failure modes.** Crypto assets are highly correlated, so the long-only version is close to a timed market exposure (beta), not an independent signal. Crashes after rallies; regime dependence; parameter choice (lookback) is a multiple-testing risk.
- **Research cost.** Low (`signals.TimeSeriesMomentum` exists).
- **Power.** Effective sample ≈ number of independent trend episodes, not days. Very low.

### M2 — Cross-sectional relative strength (XS momentum)
- **Hypothesis.** Recent relative winners outperform relative losers (Liu, Tsyvinski and Wu, 2022, crypto factor evidence).
- **Data.** Daily closes for a point-in-time universe, including delisted assets (survivorship).
- **Long/short.** The published spread is long/short. The internal 2026-06-07 study (context only, research-exposed) found most of that effect in the **short** leg. Long-only top-k on Spot is mostly market beta plus a small tilt.
- **Execution and fees.** Higher turnover than M1 (rank changes), so the cost per unit of signal is higher.
- **Failure modes.** Momentum crashes; small-cap illiquidity; universe-construction bias.
- **Research cost.** Low (`signals.CrossSectionalMomentum` exists). A point-in-time universe dataset is required.
- **Power.** Better than M1 when the long/short spread is used, because several positions on each side cancel the common market factor. Long-only loses that advantage.

### M3 — Funding / basis (perpetual-futures carry)
- **Hypothesis.** Perpetual-futures funding rates and spot–futures basis pay a premium to the side that absorbs leveraged demand (He, Manela, Ross and von Wachter, 2022; Schmeling, Schrimpf and Todorov, 2023 on crypto carry). Market-neutral as spot long + perpetual short.
- **Data.** Funding-rate history, perpetual and spot prices, exchange margin rules. Licence and data contract needed (A42 C3, A18/A19).
- **Long/short.** Requires a derivatives short. **Not executable** with the current Spot-only, Paper-only bot. It would need a new venue and execution model, plus explicit owner decisions.
- **Execution and fees.** Two legs, two fee schedules; funding settles every 8 h; liquidation and margin risk.
- **Failure modes.** Funding compression; exchange and counterparty risk; basis blow-outs.
- **Research cost.** High.
- **Power.** The effective sample is funding episodes, but the carry is closer to a measurable accrual than to a directional bet, so power can be better than M1/M2 *if* data exist.

### M4 — Volatility-managed market exposure
- **Hypothesis.** Scaling exposure inversely to recent realised volatility improves risk-adjusted returns of a market position (Moreira and Muir, 2017, equities). It is a risk overlay, not alpha.
- **Data.** Daily closes only.
- **Long/short.** Long-only by construction.
- **Execution and fees.** Low turnover.
- **Failure modes.** Volatility clustering may break; it is still market exposure.
- **Role.** A risk-control module that can sit on top of M1/M2. It is tested on a variance endpoint, not as an alpha claim (like A42 C2).
- **Research cost.** Very low (`vol_window`, `target_daily_vol` in `TimeSeriesMomentum`).

### M5 — Short-horizon reversal and intraday setups (current family)
- **Hypothesis.** Overreaction at 15m–4h horizons reverses.
- **Evidence.** The current family is in this class. The internal evidence on the tested implementations is negative (A58). A46-C fee arithmetic: 15m fees are 0.22–0.43 R per trade.
- **Status.** Not recommended as the next S4 family. It stays as the Paper baseline arm, and engineering fixes continue (T1 cap: PR-B1).

## 3. Comparison

| | M1 TSMOM | M2 XS momentum | M3 Funding/basis | M4 Vol-managed | M5 Intraday |
|---|---|---|---|---|---|
| Executable on current Spot venue | Yes (long/cash) | Partly (long-only tilt) | **No** | Yes | Yes |
| Data beyond current | none | point-in-time universe | funding + futures, licence | none | none |
| Turnover / cost sensitivity | low | medium | medium | low | **high** |
| Independent of market beta | weak (long-only) | weak long-only, good long/short | good | none (overlay) | unclear |
| Research cost | low | low–medium | high | very low | — |
| Main blocker | power, beta | short leg, universe data | venue, licence | not alpha | prior negative evidence, costs |

**Recommendation.** Do not pick a winner yet. The two decisions that unblock *any* mechanism come first:
1. **Data permission.** Decide whether a licence-cleared historical dataset can be used for exploratory, non-confirmatory qualification (A18/A19 HOLD). Without one, research is limited to synthetic tooling and literature.
2. **Validation design for small effects.** The 365-day ladder cannot detect realistic Sharpe ratios. Options for the owner: a longer prospective window, a multi-candidate design with shared cost, or accepting qualification on long licence-cleared history with a short prospective sanity check.

When those are decided, M1 with an M4 overlay is the cheapest first specification. It is executable on Spot, uses existing data and has low turnover. Its main risk is that the long-only form is mostly timed beta, so its baseline must be buy-and-hold of the same universe, not cash. M2 long/short and M3 need a venue decision first.

## 4. Evidence classes

| Class | Allowed now | Where |
|---|---|---|
| Deterministic engineering tests | yes | `tests/test_s4_mechanisms.py` |
| Synthetic tests | yes | same |
| Exploratory historical analysis | **only** with a recorded `DatasetPermission` (licence cleared, holdout excluded) | `research/mechanisms/simulate.py` refuses otherwise |
| Prospective observation | Paper only, owner-approved windows | — |
| Confirmatory validation | Evidence Ladder (S5) only, separate approval | — |

Exploratory results are never confirmatory and never select a candidate for admission by themselves.
