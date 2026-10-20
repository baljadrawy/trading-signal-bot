# S4 Phase 1: scientific comparison of three strategy directions (2026-10-20)

**Status:** research record and pre-registration **draft**.
- It runs no experiment, admits nothing and spends no alpha.
- No historical, holdout or trading-outcome data was accessed for this document.
- Labels: **VERIFIED** (checked against a primary record), **INFERRED** (reasoned from verified facts), **NOT TESTED**.

## 1. Internal evidence inventory

| Evidence | Source | Sample / period | Class | Limitation |
|---|---|---|---|---|
| Live paper audit: gross PF 0.735, net PF 0.598, WR 37.4 %; 0/35 filters survive Bonferroni/BH-FDR; ML AUC 0.47 OOS | `research/skill_application/out/REPORT.md` (main) | 2,518 closed trades, 2026-04-09 → 06-21; 93 % in April | VERIFIED (record) | One regime-month dominates; pre-freeze strategy versions |
| Per-indicator analysis: gross PF 0.734, AUC ≈ 0.50, score inverted | `docs/claude/strategy-history.md`; analyzer scripts | 2,461 trades (subset of the same DB, to 06-07) | REPORTED (overlaps the 2,518) | Not independent of the row above |
| Pre-freeze H0: gross PF 0.729, net PF 0.593, day-clustered net t = −2.69 | A58 (2026-10-17, session report; not in repo) | 3,401 trades, 04-09 → 08-19 | REPORTED | Mixed versions; no repo artifact |
| 9-year target/exit study: every arm × year gross-negative; mean-anchored T1 worse than 1R | `docs/claude/strategy-history.md` | 595 coins incl. delisted, 2017–2026 | REPORTED | Research-exposed history (contaminated, `contamination_registry.jsonl`) |
| Cross-sectional momentum, long/short weekly: OOS 2025 Sharpe 1.6, **94 % of PnL from the short leg**; long-only ≈ market | `analyzer/momentum_*.py` (code); results REPORTED (2026-06-07) | 250 coins, daily, 2023–2025 | REPORTED, exploratory | Post-hoc grid; time-concentrated (top-5 periods = 64 %) |
| Daily ML 1d edge: real but **NO-GO** (micro-cap only, 6 months = 99 % of PnL) | `research/skill_application/scripts/ml_*` | 595 coins 2017–2026 | REPORTED, exploratory | Not TSMOM; capacity |
| Geometry: T1 self-referential cap (W3), T1 hit rate ≥ 0.81–0.96 needed, 15m fees 0.22–0.43 R | `docs/a45/`, `docs/a46/` (main); code `analyzer/technical_analyzer.py` @ea8ae4f | decision-time features | VERIFIED (code) / arithmetic | Mechanism, not an outcome measurement |
| Current strategy outcomes | FORWARD_HOLDOUT after 2026-08-19T09:33:46Z, `holdout_status.json` = SEALED, look count 0 | — | **NOT ACCESSIBLE** | By governance |
| External reviewer F-01..F-13 | text not in the repository or provided | — | UNKNOWN (themes only) | Cannot be mapped item by item |

**Synthesis (INFERRED).**
- The tested 15m/4h indicator family loses **before** costs.
- Its entries carry no measurable information (AUC ≈ 0.50).
- Geometry fixes alone cannot turn a gross-negative entry into a positive one.
- The only internal positive signals (cross-sectional momentum, daily ML) were exploratory and post-hoc. One lives in a non-executable short leg; the other in micro-caps.

## 2. Literature (title, venue and finding verified by web search on 2026-10-20 unless marked; A45 #1–#25 were verified on 2026-10-15)

| Source | Market / horizon | Main finding | Relevance / limitation |
|---|---|---|---|
| Moskowitz, Ooi, Pedersen (2012) JFE 104(2) — doi:10.1016/j.jfineco.2011.11.003 | 58 futures, 1–12 m | 12-month own return predicts next 1–12 months | Origin of TSMOM; not crypto |
| Huang, Li, Wang, Zhou (2020) JFE 135(3):774–794 — doi:10.1016/j.jfineco.2019.08.004 | same markets | asset-by-asset regressions show **little TSMOM in- or out-of-sample** | Direct challenge to M1 |
| Kim, Tse, Wald (2016) J. Financial Markets 30:103–124 — doi:10.1016/j.finmar.2016.05.003 | futures | alpha driven by **volatility scaling**; unscaled TSMOM ≈ buy-and-hold | Benchmark must be B&H; scaling is the effect |
| Moreira, Muir (2017) JF 72(4):1611–1644 — doi:10.1111/jofi.12513 | equity factors | volatility-managed portfolios raise Sharpe | In-sample spanning |
| Cederburg, O'Doherty, Wang, Yan (2020) JFE — doi:10.1016/j.jfineco.2020.04.015 | 103 strategies | **real-time** volatility management mostly **underperforms** unmanaged | Counter-evidence to M4 |
| Liu, Tsyvinski (2021) RFS 34(6):2689–2727 — doi:10.1093/rfs/hhaa113 (A45 #4) | BTC/ETH/XRP, daily–weekly | time-series momentum; attention | Large caps, early sample |
| Liu, Tsyvinski, Wu (2022) JF 77(2):1133–1177 — doi:10.1111/jofi.13119 (A45 #5) | cross-section, weekly | market, size, momentum factors | Long/short, weekly |
| Borgards (2021) NAJEF 57 — https://ideas.repec.org/a/eee/ecofin/v57y2021ics1062940821000590.html | 20 coins, inter/intraday | longer and larger momentum periods than US stocks | Dynamic definition, not a trading rule |
| Dobrynskaya, *Cryptocurrency Momentum and Reversal*, J. Alternative Investments (forthcoming per author) — https://www.hse.ru/en/news/559533243.html | ~2,000 coins, 1–12 w | momentum ≤ 2 weeks; insignificant 2–4 w; **reversal ≥ 4 weeks** | Horizon must be short (≤ 2 w) |
| Fieberg, Liedtke, Poddig, Walker, Zaremba (2025) JFQA, *A Trend Factor for the Cross-Section of Cryptocurrency Returns* — https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178 | > 3,000 coins | multi-horizon trend factor survives costs, in big/liquid coins | ML-combined signal; long/short |
| Grobys, Kolari, Sandretto, Shahzad, Äijö (2025) FMPM, *Cryptocurrency momentum has (not) its moments* — https://osuva.uwasa.fi/handle/10024/20018 | large caps, weekly | **severe crashes**; one coin can drive results; vol management mitigates | Concentration risk |
| Grobys, Sapkota (2019) Econ. Letters 180 (A45 #6) | 143 coins | no significant momentum | Early sample |
| Daniel, Moskowitz (2016) JFE 122(2) (A45 #19); Barroso, Santa-Clara (2015) JFE 116(1) (A45 #20) | equities | crashes after rebounds; risk scaling helps | Regime dependence |
| Novy-Marx, Velikov (2016) RFS 29(1) (A45 #24) | 23 anomalies | high-turnover anomalies lose most profit after costs | Turnover is decisive |
| Harvey, Liu, Zhu (2016) RFS 29(1):5–68 — doi:10.1093/rfs/hhv059 | 316 factors | require t ≥ 3 for new factors | Multiple testing |
| Bailey, López de Prado (2014) JPM 40(5):94–107 — doi:10.3905/jpm.2014.40.5.094 | method | Deflated Sharpe Ratio | Selection bias, non-normality |
| Bailey, Borwein, López de Prado, Zhu (2015/17) J. Comput. Finance — https://www.risk.net/journal-of-computational-finance/2471206/the-probability-of-backtest-overfitting | method | PBO via CSCV | Overfitting |
| White (2000) Econometrica 68(5):1097–1126; Hansen (2005) JBES 23(4):365–380; Romano, Wolf (2005) Econometrica 73(4):1237–1282 — doi:10.1111/j.1468-0262.2005.00615.x | method | Reality Check, SPA, stepwise FWER | Family-wise control vs a benchmark |
| Lo (2002) FAJ 58(4):36–52 — doi:10.2469/faj.v58.n4.2453 | method | Sharpe-ratio sampling error; serial correlation inflates annualized SR | Dependence |
| Newey, West (1987) Econometrica 55(3):703–708; Politis, Romano (1994) JASA 89(428):1303–1313 | method | HAC variance; stationary bootstrap | Dependence-aware inference |

**What the literature does and does not say (INFERRED).**
- Crypto momentum is horizon-sensitive: positive at ≤ 2 weeks and reversing at ≥ 4 weeks (Dobrynskaya).
- It is concentrated in large, liquid coins, and it is crash-prone.
- The classic TSMOM alpha is contested (Huang et al.) and largely a volatility-scaling effect (Kim, Tse, Wald), whose real-time value is itself contested (Cederburg et al.).
- **None of it shows that our implementation will be profitable.**

## 3. Ranked assessment

| Rank | Direction | Economic rationale | Data fit | Turnover / cost sensitivity | Main risks | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Daily TSMOM, long/cash, liquid large caps** (± volatility scaling) | under-reaction / trend-chasing flows at 1–2 weeks | daily closes (same source as the bot) | low–medium | mostly **timed beta**; contested alpha; short-horizon reversal | **TEST FIRST** (cheapest, executable on Spot); the hypothesis must be *risk-adjusted improvement over B&H*, not alpha |
| 2 | **Cross-sectional momentum** (top-k weekly) | relative under-reaction; factor evidence | point-in-time universe incl. delisted | medium–high | edge in the **short leg** (not executable on Spot); crashes; one-coin dominance | **TEST SECOND**, as research. Long-only spot form expected weak; long/short needs a venue decision |
| 3 | **Existing 15m/4h strategy + corrected T1** | none demonstrated (AUC ≈ 0.50) | 15m/4h bars + replay (A48 Mode 3) | **high** (0.22–0.43 R/trade at 15m) | gross-negative entry; a T1 fix cannot create information | **BASELINE ARM ONLY**; evaluate the T1 fix as a correction, never as an edge |

## 4. Pre-registration draft: common historical framework (requires owner decisions §6)

- **Classification of results:** every historical period is research-exposed (`contamination_registry.jsonl`: 2017–2022 LIKELY, 2023–2025 and 2026-07-01 → freeze KNOWN_RESEARCHED; 2026-01 → 06 is not registered, although live trades from April–June 2026 were researched: a registry gap to record). Historical results are **exploratory qualification only** (A29: historical triage). **No historical result is confirmatory.** Confirmation stays with the Evidence Ladder, prospectively.
- **Data:** Binance Spot daily klines (USDT pairs). Allowed only after a recorded `DatasetPermission` (licence cleared, holdout excluded). **End date strictly before 2026-08-19T09:33:46Z.**
- **Universe (point-in-time, monthly):** the top 20 by trailing 30-day quote volume among pairs listed ≥ 90 days, using only data up to the rebalance date. Exclude stablecoins, leveraged and wrapped tokens. Delisted coins are kept until their last trade.
- **Periods:** 2019-01-01 → 2022-12-31 (specification sanity, no tuning); 2023-01-01 → 2026-08-18 (one logged look per hypothesis in `validation_usage.jsonl`). Walk-forward annual refits are needed only for parameters, and **parameters are fixed from the literature**, not fitted.
- **Primary specifications (fixed before any data):**
  - **H1 TSMOM:** lookback 14 days (≤ 2 w per Dobrynskaya). Position long if the trailing 14-day return > 0, else cash. Equal risk budget 1/N. Daily signal at the 00:00 UTC close, executed at the next close. A variant with 20-day volatility scaling (target daily vol = universe median) is reported.
  - **H2 XS:** rank by 14-day return; long top 5 equal weight; weekly rebalance; long-only primary; a long/short arm is reported as non-executable research.
  - **H3 baseline:** current setups with `T1_CAP_POLICY` legacy vs `independent_swing_v1`, A48 `ohlc_uncertainty_v1`, fills reported as intervals.
- **Benchmarks:** BTC B&H, ETH B&H, an equal-weight B&H of the same universe (monthly rebalance), and cash.
- **Costs:**
  - fee 0.10 %/side;
  - half-spread by tier (declared: 0.01 % BTC/ETH, 0.04 % other top 20; stress ×2);
  - slippage 0.05 %/side (stress 0.10 %);
  - tracker 0.30 % reported separately.
- **Metrics:**
  - net daily return; active return vs EW B&H; Sharpe, Sortino;
  - maximum drawdown and duration; Calmar;
  - turnover and cost drag; beta to BTC;
  - share of PnL from the top-5 months and top-1 coin;
  - rolling 1-year Sharpe dispersion.
- **Inference:**
  - **Primary endpoint:** mean daily **active** net return of H1 vs EW B&H, tested with a Newey–West HAC t (Bartlett, lag 7, as in the ladder), confirmed by a stationary bootstrap (mean block 20 days).
  - **Family-wise control:** Romano–Wolf stepdown over {H1, H2, H3} against the benchmark (Holm as a conservative check).
  - **Multiplicity reporting:** Deflated Sharpe with N = every variant run, reported (logged), not only the primary ones.
- **Failure criteria (predeclared; any one rejects the direction):**
  1. primary HAC t ≤ 0 in the 2023–2026 look;
  2. cost drag > 50 % of gross return;
  3. MDD worse than EW B&H with no Sharpe gain;
  4. > 50 % of PnL from 5 months or from 1 coin;
  5. the result reverses under ×2 cost stress.
- **Power (outcome-free; §A3):** even with 8 years at a family α of 0.05/3, the power for a true annualized Sharpe of 1.0 is about 0.76; with one year it is about 0.13. Expect **inconclusive** results for realistic effects. A null result is not evidence of no edge.

## 5. What was done vs not

| Item | Status |
|---|---|
| Internal evidence inventory, file references | done (read-only) |
| Literature review with verified sources | done |
| Outcome-free power analysis (`research/power` + the same formula beyond 365 d) | done |
| Fee arithmetic (formulas, declared assumptions) | done (appendix) |
| Any backtest of H1/H2/H3 | **NOT TESTED** (no dataset permission) |
| Current strategy performance | **NOT ACCESSIBLE** (sealed holdout) |
| Mapping to reviewer F-01..F-13 | UNKNOWN (text not provided) |

## 6. Owner decisions required

1. **Dataset permission** (A18/A19 licence + OD-DF-1): Binance Spot daily klines, ending before the freeze, for exploratory qualification.
2. **Accept this pre-registration** (or amend it) **before** any data is touched.
3. **Validation design for small effects** (OD-DF-2): historical qualification is exploratory only; the prospective window is ≤ 365 days under A29/A30. Decide whether H1 enters the ladder as a candidate after qualification.

## Appendix A: formulas and assumptions

- **A1 Portfolio return.** Weights are set at close t and held to close t+1: r^p_{t+1} = Σ_i w_{i,t} r_{i,t+1}; cash earns 0.
- **A2 Costs.**
  - Turnover TO_t = Σ_i |w_{i,t} − w̃_{i,t}|, where w̃ is the drifted weight.
  - Cost_t = TO_t (f + s/2 + q), with fee f = 0.001, half-spread s/2 and slippage q.
  - Net = gross − cost (implemented in `research/mechanisms/simulate.py`, Draft PR #60).
  - Annual drag ≈ TO_year × (f + s/2 + q). Example (illustrative, not measured): TO_year = 20 at 0.16 %/side gives about 3.2 %/yr.
- **A3 Power.** MDE(annualized SR) = (c + z_power) · √LRV · √(365/T).
  - Governed: c = z(1 − 1/276) = 2.685 (A33 calibration level, NORMAL_THEORY; ≤ 365 days only).
  - Exploratory: c = z(1 − 0.05/3) = 2.128.
  - Power = Φ(SR · √(T/365) / √LRV − c).
  - Results:

    | Horizon T | MDE governed, LRV = 1 | MDE governed, LRV = 2 | MDE exploratory, LRV = 1 |
    |---|---|---|---|
    | 365 d | 3.53 | 4.99 | 2.97 |
    | 1,461 d | 1.76 | 2.49 | 1.48 |
    | 2,922 d | 1.25 | 1.76 | 1.05 |

- **A4 HAC.** σ̂²_LR = γ̂_0 + 2 Σ_{l=1}^{L} (1 − l/(L+1)) γ̂_l (Bartlett, L = 7); t = mean / √(σ̂²_LR / T).
- **A5 Deflated Sharpe.** Following Bailey and López de Prado (2014), with N = the logged number of variants and the skew/kurtosis of the daily net series.
- **A6 Reproducibility.** Content-addressed dataset (`research/data_governance`), dataset permission record, git SHA, config hash, cost-model label, and every variant logged before results are read.
