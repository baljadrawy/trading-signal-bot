# A45 — Strategy Setup & Signal Quality Research

## Scope

| Field | Value |
|---|---|
| Date | 2026-10-15 (UTC) |
| Verified state | Production Paper images `p1d-59297305`, schema **9**. The running analyzer files (`technical_analyzer.py`, `simple_entry.py`, `main.py`, `orderbook_analyzer.py`, `shared/{regime,signal_stop,ohlcv,macro_context}.py`) are **sha256-identical** to `59297305`. A44 `feature/a44-integration` @ `4375c94` (code `eb68e42`) is not deployed. Its only analyzer change is the enforce-only `candle_identity` stamp (11 lines); the setup logic is unchanged |
| Branch | `feature/a45-setup-research` from `4375c94` (worktree `~/tsb-a45-worktree`): `589526d` (diagnostics + specs + tests), `cd19998` (isolation scope), then this report. Local only |
| Data read | **Decision-time features only** (distinct momentum brackets: close, breakout level, ATR fraction, volume baseline, BTC 3-day change). No outcome column. Hypothesis parameters were committed (`589526d`, 14:00:04+02:00) **before** this look |
| Not done | backtests, outcome reads, parameter fitting, prospective runs, budget use, production changes |

---

## A45-A — Production setup architecture

### A.1 Pipeline (all values are code defaults; production env overrides only the universe and TFs)

| Stage | Source | Production behaviour |
|---|---|---|
| Universe | `scanner/scanner_logic.py` `_passes_initial_filter` | Binance Spot `*USDT`, TRADING, ASCII, not stablecoins or blacklist. 24 h quote volume ≥ **10 M USDT** (`MIN_VOLUME_USDT`, env). **\|24 h change\| ≥ 1 %** (`MIN_PRICE_CHANGE_PERCENT`). If BTC's 40 h (10 × 4h) change ≤ −3 %, then \|change\| ≥ 5 %. Every 300 s |
| Candles | `technical_analyzer._get_candles` → `shared/ohlcv.prepare_ohlcv` | 201 klines fetched; closed by `close_time < now`; **last 200 closed** kept. `validate_ohlcv` rejects missing columns, unsorted, duplicate or gapped timestamps, non-finite values, non-positive prices and impossible OHLC |
| TFs | env `TIMEFRAMES=15m,4h,1d` | Each analysed independently. The order book is fetched **once** per symbol and shared |
| Warm-up | `indicator_warmup_bars()` = max(EMA200, MACD 35, StochRSI 20, BB 20, ATR 14, 50) = **200** = `CANDLES_TO_FETCH` | zero margin |
| Indicators (all computed) | `_calculate_indicators` | RSI14, MACD 12/26/9, EMA20/50/200, BB(20, 2), ATR14, ADX14, StochRSI(14, 3, 3), OBV + EMA20, volume MA20 / ratio |
| **Active in live decisions** | — | EMA20, EMA50, ATR14, ADX14, RSI14, BB(20, 2), close/open/high, volume. **Inactive** (computed or stored only): EMA200 (`trend_ok`; legacy selector only), MACD, StochRSI, OBV, BB width, volume ratio, weighted score, order-book walls and ratio |
| Regime (per TF) | `shared/regime.classify_regime` | **bullish** = ADX ≥ 25 ∧ EMA20 5-bar slope > 0 ∧ close > EMA20 (high volatility allowed); **bearish** = mirror; **sideways** = ADX < 20 ∧ ATR% percentile(100) ≤ 0.75; otherwise **volatile** |
| **Momentum (breakout)**, the only trend setup | `analyzer/simple_entry.detect_trade_setup` | regime ∈ {bullish} ∧ close > EMA20 > EMA50 ∧ close > max(high of the **prior** 20 bars) ∧ volume > 1.2 × mean(prior 20 volumes). Evaluated **before** reversion and wins |
| Reversion | same | regime ∈ {sideways} ∧ RSI < 35 ∧ close > previous close ∧ close > open ∧ BB position ≤ 0.20 |
| Stop | `shared/signal_stop.plan_signal_stop` (via `_calculate_levels`) | momentum level = prior 20-bar high; reversion level = 20-bar low (including the current bar). invalidation = level − 0.25 ATR; stop = min(invalidation, entry − 1 ATR). **Reject** if risk > TF cap (15m 2 %, 4h 5 %, 1d 3 %). So **R = max(extension + 0.25, 1) ATR**: proven in `test_extension_boundary…` |
| Targets | `_calculate_levels` | T1 = 1R, T2 = 1.8R, T3 = 2.2R. If 1R > max(high of the last 20 bars **including the current one**) > entry, then T1 = 0.99 × that high (only if still > entry) |
| Entry | tracker `decide_long_entry` | reject at or below max(stop, invalidation); market if price ≤ planned entry; otherwise a limit at planned entry, no chase; `observed_price_v0` fills |
| Exits | `shared/triple_barrier` + `partial_exits` | 25/50/25 at T1/T2/T3. After T1 the stop moves to entry × 1.003 / 0.999 (capped at T1); after T2 it trails 2.5 % (floored at T1). Expiry: 15m 48/24/12 h, 4h 96/48/24 h, 1d 240/120/72 h |
| Invalidation | `candle_invalidated` | before T1, a post-entry closed candle ≤ invalidation exits |
| Freshness | signal_engine | analysis rows up to 30 min old; the order-book spread is from the same moment. No candle-age check in production (A43; A44 `enforce` adds one) |
| Selector | `find_best_signal_live` | macro block (BTC 3-day ≤ −5 % or USDT.D rising fast) → filters (setup, OB valid, spread ≤ 0.15 %, stop valid, no open trade, 2 h cooldown) → **min(spread, −volume, symbol, TF)**, one signal per cycle. Setup strength is not used |

### A.2 Legacy, disabled, experimental

| Status | Items |
|---|---|
| Legacy / inactive in live | `find_best_signal`; the weighted score; min_score / min_tf DB thresholds; `trend_ok` / EMA200 gate; BTC-crash and global cooldowns; order-book score |
| Disabled | learned gates (`LEARNING_GATES_ENABLED=false`); `resting_limit_v1` |
| Experimental (unwired) | A42 signal quality, C1–C3, counterfactual replay; A43/A44 ranking v2 / `cost_per_risk_v1` / pipeline; **A45 `setup_diagnostics`, H1–H3** |

---

## A45-B — External scientific review

Every source below **except #3** was **verified this session by web search** (title, venue, year, main finding). #3 is cited from known literature and is marked as such. The full texts were not re-read, so the main finding and limitations come from the abstracts and indexed summaries.

| # | Citation | Question / market / horizon | Main finding | Limitations | Applicability to our bot | Verdict |
|---|---|---|---|---|---|---|
| 1 | Moskowitz, Ooi, Pedersen (2012), *Time series momentum*, JFE 104(2):228–250 | own-past-return predictability; 58 futures | 12-month past return predicts the next 1–12 months | futures, monthly; not crypto, not intraday | supports **trend-following at long horizons only** | challenges our 15m/4h horizon |
| 2 | Hurst, Ooi, Pedersen (2017), *A Century of Evidence on Trend-Following Investing*, JPM 44(1):15–29 | TSMOM, 67 markets, 1880–2016 | positive in every decade; good in crises | diversified multi-asset portfolio; monthly | same as #1 | neutral |
| 3 | Jegadeesh & Titman (1993), JF 48(1):65–91 (known literature; **not re-verified this session**) | cross-sectional equities, 3–12 m | winners beat losers | equities, monthly | ranking across assets ≠ our single-asset breakout | n/a |
| 4 | Liu & Tsyvinski (2021), *Risks and Returns of Cryptocurrency*, RFS 34(6):2689–2727 | BTC/ETH/XRP; daily to weekly | strong **time-series momentum**; investor attention predicts returns | 3 large coins; daily/weekly; pre-2018 sample | supports momentum in crypto **at days–weeks, large caps** | partial support (1d) |
| 5 | Liu, Tsyvinski, Wu (2022), *Common Risk Factors in Cryptocurrency*, JF 77(2):1133–1177 | cross-section of coins; weekly | market, size and momentum factors price coins | weekly long–short; costs and capacity | cross-sectional momentum, not a breakout trigger | context |
| 6 | Grobys & Sapkota (2019), *Cryptocurrencies and momentum*, Econ. Letters 180:6–10 | 143 coins, 2014–2018 | **no significant** momentum | early sample | challenges generalisation | challenges |
| 7 | Grobys & Shahzad (2026), *Cryptocurrency Momentum: Is It an Illusion?*, IJFE 31(2):2180–2193 | crypto momentum risk | realised variances follow power laws; mean and variance may be undefined, so momentum premia may be unrealisable | factor portfolios | variance-based performance metrics are uninformative; heavy tails | challenges |
| 8 | (2025) *Cryptocurrency momentum has (not) its moments*, FMPM | top-30 coins, weekly, 2016–2023 | severe crashes; one coin can drive results; volatility management helps; a large-cap phenomenon | weekly; small universe | supports volatility normalisation; warns of concentration | mixed |
| 9 | Zaremba, Bilgin, Long, Mercik, Szczygielski (2021), *Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets*, IRFA 78 | daily cross-section | **daily reversal** for most (illiquid) coins; **daily momentum only for the largest, most liquid** | daily, cross-sectional | our universe (≥ 10 M) mixes both; liquidity matters | conditional |
| 10 | Begušić & Kostanjčar (2019), *Momentum and liquidity in cryptocurrencies*, arXiv:1904.00890 | 456 coins | momentum strongest in the most liquid coins; predictability falls with liquidity in some sorts | working paper | liquidity conditioning is relevant | supports liquidity tilt |
| 11 | Shen, Urquhart, Wang (2022), *Bitcoin intraday time series momentum*, Financial Review 57:319–344 | BTC intraday | the first half-hour predicts the last half-hour; strongest in high-volume / high-volatility sessions; driven by **liquidity provision** | BTC only; session-defined | intraday persistence exists in BTC under specific timing, not a generic 15m breakout | weak / partial |
| 12 | Wen, Bouri, Xu, Zhao (2022), *Intraday return predictability in the cryptocurrency markets: momentum, reversal, or both*, NAJEF 62 | crypto intraday | **both** momentum and reversal intraday; reversal linked to overreaction | specific intraday windows | the sign of short-horizon predictability is unstable, so the breakout rationale is fragile | challenges |
| 13 | Gao, Han, Li, Zhou (2018), *Market intraday momentum*, JFE 129(2):394–414 | SPY intraday | first half-hour predicts last half-hour, more so on volatile, high-volume days | US equity ETF | do not transfer to crypto 15m | context |
| 14 | Brock, Lakonishok, LeBaron (1992), JF 47(5):1731–1764 | DJIA 1897–1986, MA and **trading-range breakout** | buy signals outperform; not explained by RW / AR / GARCH | daily; no costs; in-sample era | the original breakout evidence | historical support |
| 15 | Sullivan, Timmermann, White (1999), JF 54(5):1647–1691 | reality-check over a large rule universe | after data-snooping adjustment, the best rule shows **scant out-of-sample evidence** | equities daily | **our research history (40+ studies, many rules) has the same snooping risk** | challenges |
| 16 | Corbet, Eraslan, Lucey, Sensoy (2019), FRL 31:32–37 | high-frequency BTC; MA and range breakout | support for MA rules (VMA best); buy > sell signals | BTC only; costs and out-of-sample limited | some HF-BTC technical evidence; breakout weaker than MA | weak support |
| 17 | Hudson & Urquhart (2021), *Technical trading and cryptocurrencies*, Ann. Oper. Res. 297:191–220 | ~15,000 rules; 5 coins | in-sample predictability, but **no out-of-sample predictability for Bitcoin** (some persists in others) | daily; rule universe | in-sample technical success decays where markets mature | challenges |
| 18 | Cooper, Gutierrez, Hameed (2004), *Market States and Momentum*, JF 59(3):1345–1365 | equities 1929–1995 | momentum +0.93 %/month after up markets, −0.37 % after down markets | equities, monthly, cross-sectional | rationale for conditioning on **market state** (H1) | supports H1 (by analogy) |
| 19 | Daniel & Moskowitz (2016), *Momentum crashes*, JFE 122(2):221–247 | equities and assets | crashes occur in **rebounds after market declines**; partly forecastable; dynamic weighting doubles Sharpe | cross-sectional long–short | crash risk is regime-dependent; a long-only breakout faces it differently | caution for H1 design |
| 20 | Barroso & Santa-Clara (2015), *Momentum has its moments*, JFE 116(1):111–120 | equity momentum | momentum risk is predictable; volatility scaling nearly doubles Sharpe | portfolio-level scaling | supports **volatility normalisation** (our stops are ATR-scaled) | supports |
| 21 | Lee & Swaminathan (2000), *Price momentum and trading volume*, JF 55(5):2017–2069 | equities | high-volume winners reverse **faster** | equities, months–years | volume is not unambiguously "confirmation" | challenges the volume rule |
| 22 | Gervais, Kaniel, Mingelgrin (2001), *The high-volume return premium*, JF 56(3):877–919 | equities | unusually high volume → higher returns over the next month (visibility) | equities, monthly | volume as an attention / visibility signal, at a month horizon | weak support |
| 23 | Makarov & Schoar (2020), *Trading and arbitrage in cryptocurrency markets*, JFE 135(2):293–319 | tick data, 34 exchanges | recurrent cross-exchange arbitrage; **a common component explains ~80 % of BTC returns** | 2017–2018 | strong market-wide co-movement, so altcoin signals share one factor (dependence; H1 rationale) | supports H1, warns on dependence |
| 24 | Novy-Marx & Velikov (2016), *A taxonomy of anomalies and their trading costs*, RFS 29(1):104–147 | 23 anomalies, after costs | high-turnover anomalies lose much or all of their profitability; buy/hold spreads help | equities | turnover kills edges; our 20–30 bps per trade on sub-1 % stops is the same mechanism | supports cost discipline |
| 25 | Katsiampa (2017), *Volatility estimation for Bitcoin: a comparison of GARCH models*, Econ. Letters 158:3–6 | BTC daily | conditional heteroskedasticity; AR-CGARCH fits best | BTC daily | volatility clustering, so ATR-normalised geometry is sensible | supports |

### Synthesis (stated as evidence, not proof)

1. **Horizon.** The strongest and most replicated momentum evidence is at **weeks to months**, in diversified or liquid large-cap portfolios (#1, #2, #4, #5, #8). Our momentum fires on **15m and 4h** bars, where crypto evidence shows both momentum **and** reversal (#11, #12) and out-of-sample decay (#15, #17). Daily equity results are not transferred here.
2. **Conditioning.** Market state (#18, #19, #23) and liquidity (#9, #10) condition momentum. Our setup conditions on its **own** TF's ADX regime, not on the crypto market's trend.
3. **Volume.** Volume is double-edged: attention (#22) vs faster reversal of high-volume winners (#21). There is no strong basis for "volume > 1.2 × mean" as confirmation.
4. **Costs and tails.** Turnover costs (#24) and power-law tails (#7, #8) make short-horizon, small-stop strategies fragile, and make Sharpe or variance metrics unreliable.

---

## A45-C — Strategy weakness assessment

| # | Finding | Evidence | Class |
|---|---|---|---|
| W1 | **Horizon mismatch.** The breakout rationale (persistence) is weakest exactly at the bot's 15m/4h horizons | §B synthesis 1. Internal context (already-authorised aggregate findings, not used for selection): earlier live reviews found momentum net-negative | ECONOMIC DESIGN CONCERN |
| W2 | **Late, extended entries.** Entry = breakout bar close. The production stop makes R = max(extension + 0.25, 1) ATR. Median extension is ~0.5 ATR, and **33.5 % (15m) / 35.9 % (4h)** of distinct momentum setups close > 0.75 ATR above the level, so they buy extension with wider risk | decision-time features (n = 799 / 223) | ECONOMIC DESIGN CONCERN (effect on returns: RESEARCH HYPOTHESIS) |
| W3 | **The T1 cap refers to the breakout bar's own high.** "Resistance" includes the current bar, and for momentum that bar has just broken the 20-bar high. So the cap fires when the upper wick is ≈1.01 %–1R, placing T1 just under a price already traded. This contradicts the cap's stated purpose (the recent resistance level) | code + `test_18` (fires; does not fire when the wick > 1R); A42: 90/223 4h momentum T1s capped | **CONFIRMED IMPLEMENTATION DEFECT** (logic vs intent). The effect on P&L is not established |
| W4 | **Redundant trend conditions.** "bullish" already requires close > EMA20 and a positive EMA20 slope; the setup re-checks close > EMA20 and adds EMA20 > EMA50. The independent conditions are only breakout + volume + EMA20 > EMA50 | code (`regime.py`, `simple_entry.py`) | ECONOMIC DESIGN CONCERN (indicator stacking, no added information) |
| W5 | **The volume rule rarely binds.** The median breakout bar has **2.3×** its 20-bar baseline, versus a 1.2× threshold. On 15m the baseline ignores the intraday volume cycle | decision-time features; §B #21/#22 | RESEARCH HYPOTHESIS |
| W6 | **Own-TF regime only.** Momentum is allowed when the symbol's TF is "bullish", even if the crypto market is falling: BTC 3-day change < 0 for **30 %** (15m) / **14 %** (4h) of momentum setups. The macro block only stops ≤ −5 % | decision-time features; §B #18/#23 | RESEARCH HYPOTHESIS |
| W7 | **Stops below cost.** On thin-ATR 15m bars, 20 bps exceeds R (A42: 30/799 15m brackets); after T1, 75 % exits at ≈ net 0 | A42-B; `test_19` | ECONOMIC DESIGN CONCERN |
| W8 | **Setup strength is not used in selection.** The ranking is spread → volume; extension, cost/R and regime strength are invisible to the selector | code | ECONOMIC DESIGN CONCERN |
| W9 | **Stale execution inputs.** The spread and the setup can be up to 30 min old; superseded candles are re-emitted (A43; fixed in A44 `enforce`) | A43 | CONFIRMED IMPLEMENTATION DEFECT (fixed in A44 candidate, not deployed) |
| W10 | **EMA200 at the warm-up boundary.** Seed weight is 0.138 at 200 bars (bias about 0.35 % on a trend); it feeds only the inactive `trend_ok` | `test_23`, measured | CONFIRMED (inactive; no live effect) |
| W11 | **Dependence and effective n.** One market factor (~80 % common component, #23), concurrent signals, overlapping TFs, same-candle re-fires (A43) | A43, literature | ECONOMIC DESIGN CONCERN for inference |
| W12 | **Selection bias and data snooping.** The universe is pre-filtered on \|24 h move\| ≥ 1 % (attention; #4). The project has run 40+ rule and indicator studies on overlapping history (#15 risk) | code; project history | RESEARCH HYPOTHESIS / methodological risk |
| W13 | Look-ahead, out-of-order, duplicate, missing, incomplete candles | `validate_ohlcv` and `closed_klines` handle all of them (tests 13–17) | no defect found |
| W14 | Survivorship | the universe is the live exchange list at scan time (delisted coins absent from history) | INSUFFICIENT EVIDENCE (matters for any historical study, not for live) |

No finding above is claimed as the cause of losses.

---

## A45-D — Safe engineering (local, unwired)

**`shared/setup_diagnostics.py`** (`a45-sd-v1`, commit `589526d`):
- `explain_setups`: condition-level restatement of the production setups. **Decision parity is asserted on 600 random frames** × 5 regimes.
- `setup_geometry`: extension and risk in ATR, stop anchor, T1-cap provenance (`current_bar` / `prior_bars`), cost/R, flags.
- `validate_indicator_frame`: active-input finiteness, candle hygiene (reuses `validate_ohlcv`), EMA seed weights, regime history, provenance (bars, `ta` version, last candle).
- H1–H3 as disabled `PolicyDecision` specs, reusing A42's `PolicyDecision`.

Production imports none of it (asserted).

**`tests/test_a45_setup_diagnostics.py`: 26 tests**, the 24 required scenarios plus parity plus the 0.75-ATR boundary. All decisions are made by **production** code (`TechnicalAnalyzer._calculate_indicators` / `_calculate_levels`, `detect_trade_setup`, `classify_regime`, `validate_ohlcv`, `closed_klines`) plus A42–A44 components (replay, eligibility, exposure, candle identity).

**Regressions:**

| Run | Passed | Failed | Skipped |
|---|---|---|---|
| Default suite, A44 base `4375c94` | 838 | 0 | 793 |
| Default suite, **A45** | **864** | **0** | 793 |

- The +26 are the new tests. The A42 isolation list was extended by one declared experimental module.
- **Skips:** unchanged and DSN-gated (DB suites). A45 changed no DB or production path, so A44's full DB matrix (1627 / 1 env-mapped / 3) remains the evidence for those paths.

---

## A45-E — Candidate hypotheses (specified, not executed)

| | **H1 Market-state-conditioned momentum** | **H2 Extension cap (entry timing)** | **H3 Slot-adjusted volume confirmation** |
|---|---|---|---|
| Mechanism | altcoin breakouts against a falling crypto market are more likely to fail (common factor #23; market-state momentum #18) | buying a bar that already moved > 0.75 ATR past the level buys overreaction (#12) and pays a wider stop | 15m volume has an intraday cycle; "spikes" versus the last 20 bars partly measure the clock, not information |
| Data | BTC 3-day change (already in `macro_snapshot`) | breakout level, close, ATR (already in `execution_features`) | ≥ 20 days of 15m bars (1,921): **more history than the analyzer fetches (200)** |
| Rule | momentum only if BTC 3-day change ≥ 0 | momentum only if (close − level)/ATR ≤ 0.75 | momentum volume > 1.2 × mean(volume of the same slot on the previous 20 days) |
| Parameters | lookback = existing macro input; threshold 0 = the sign | 0.75 = the production stop-anchor boundary (proven) | 20 days (one trading month); multiple 1.2 = production |
| Why net expectancy could improve | fewer trades in a hostile market state | entries closer to the level; R = 1 ATR, so cost/R is consistent | removes clock-driven false confirmations |
| Why it could fail | crypto crashes happen in rebounds (#19), so the gate may miss rebounds; BTC 3-day is noisy | the strongest moves may be the extended ones (persistence); the filter keeps weaker bars | the volume rule rarely binds (W5), so little effect; adds a data dependency |
| Frequency (decision-time features; parameters fixed before the look) | −30 % (15m), −14 % (4h) of momentum setups | −33.5 % (15m), −35.9 % (4h) | unknown (needs slot history) |
| Turnover / costs | proportional reduction | proportional reduction; cost/R per kept trade improves | small |
| Leakage risk | BTC change must be from closed 4h candles before the decision (it is: macro uses closed klines) | none (all decision-time) | slot alignment must use closed candles only |
| Regime sensitivity | **by construction**, a regime rule | low (an idiosyncratic per-signal variable) | intraday-session dependent |
| Validation need | dependence is market-wide, so the effective n is the number of regime episodes | per-signal, so better effective n | requires a new data contract |

All three are **gates**: they change frequency, so under fixed $50 notional they help only if the removed subset has a lower mean net return than the kept one (A42-B). None is a ranking change.

---

## A45-F — Evaluation protocol for the most testable hypothesis: **H2**

H1 has the stronger literature, but its gating variable is market-wide. Removed trades cluster in a few regime episodes, so its effective n is too small for any credible test within 365 days. H2 varies per signal.

| Element | Specification |
|---|---|
| Question | Do momentum setups with breakout extension > 0.75 ATR have lower mean net return than those ≤ 0.75 ATR, under the frozen exits? |
| Estimand | Δ = E[net % │ ext ≤ 0.75] − E[net % │ ext > 0.75], per distinct setup (one per closed candle; A44 identity) |
| Baseline / change | baseline = the production momentum setup; change = the H2 gate. **Fixed**: 0.75 ATR, ATR14, prior-20-bar level |
| Universe | every momentum setup emitted by the A44 `enforce` stream (one per setup, fresh), all TFs, with stratified reporting (15m / 4h) |
| Outcome | net % per setup = frozen exit replay (25/50/25, break-even, trail, TF expiry) at the **20 bps** baseline. Spread and slippage are reported separately. Admitted setups use their Paper result; non-admitted ones (capacity, cooldown) use the calibrated counterfactual replay (A44 prerequisite) |
| Unfilled | a limit not filled counts as 0 return (an opportunity, not a trade), reported separately; rejection at entry follows `decide_long_entry` |
| Dependence | daily aggregation of each group's mean; HAC / block bootstrap on the daily series (A30/A32); the paired-day difference removes the common market move |
| Effective n | ~6,400 distinct momentum setups a year (58-day rate annualised), about 1/3 above the cap. iid MDE ≈ 3.48 · σ · √(1/n₁ + 1/n₂) ≈ **0.12 %/setup** at an assumed σ = 1.5 %. **Design effect for day clustering is unknown; plausibly 3–10×, giving an MDE of 0.2–0.4 %/setup** |
| Multiple testing | one admission at α = 1/240 within the FWER 5 % / 12-admission ledger; no other variants (no alternative thresholds) |
| Prospective | ≤ 365 days, final look only, on a declared window starting after A44 enforce activation; no pooling across windows |
| Failure / invalidation | Δ ≤ 0 at the final look, a CI including 0, or a sign reversal between 15m and 4h → H2 rejected. Invalidated by any change to frozen exits, costs, the counterfactual model or integrity mode during the window |
| Admission conditions | (1) A44 deployed with `enforce` (a separate approval); (2) counterfactual replay calibrated against tracker polls (bias of paired differences shown ≈ 0); (3) a pre-registered power analysis on the **measured** setup rate and day-clustering design effect showing MDE ≤ 0.2 %; (4) owner approval of the alpha slot |
| Power verdict now | **probably inadequate** within 365 days unless the measured design effect is small. Weaker standards are not proposed |

---

## A45-G — Recommendation: **REVISE STRATEGY**

**Evidence:**
1. The setup's economic rationale is weakest at its own horizon. Crypto momentum evidence is strongest at days to weeks in liquid large caps (#4, #5, #8, #9). At 15m/4h the literature shows both momentum and reversal and out-of-sample decay (#11, #12, #15, #17). Internal history (already-authorised aggregates, context only) agrees: no post-fee edge across 40+ technical studies.
2. The improvements that can be specified (H1–H3) are second-order gates. Under fixed notional and no established gross edge, they cannot create an edge, only shift frequency. Their likely effect sizes sit at or below the prospective MDE (A45-F).
3. One confirmed defect (W3, the self-referencing T1 cap) and several design concerns (W2, W4, W7, W8) are structural, not parametric.

A refinement experiment now would spend ladder alpha on a setup whose premise is doubtful.

### H — Prioritised roadmap

| Track | Next work | Rationale | Gate |
|---|---|---|---|
| **1 Engineering corrections** | (a) Deploy A44 (integrity) when approved. (b) Specify a W3 fix as a **new strategy version**: cap T1 by the prior 20 bars only, excluding the current bar. (c) Calibrate the A42 counterfactual replay against tracker polls (synthetic, then shadow) | measurement validity first | owner approvals; a W3 version is a strategy change |
| **2 Strategy revision (design, no data fitting)** | Write a **new-version spec** aligned with the literature's horizon: daily (1d) time-series momentum on the liquid large-cap subset. Fixed literature parameters (e.g. sign of the 28-day return, volatility-scaled sizing per #20), market-state conditioning (#18), the existing cost model, and **no** intraday breakout trigger. Keep the current setup as the baseline arm | the only horizon with supportive crypto evidence | design review; no backtest on exposed data |
| **3 Scientific confirmation** | Only after 1(a) and 1(c): pre-register **one** admission. Either the revised-version vs baseline comparison, or H2 if the owner prefers refinement; power analysis on measured rates first | FWER discipline | Evidence Ladder admission |
| **4 Production** | nothing until a confirmed result; each step owner-approved | — | — |

**Not claimed:** any profitable strategy. The synthetic tests show engineering properties only.

---

## Sources (verified via web search this session)

- [MOP 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf)
- [Hurst et al. 2017](https://jpm.pm-research.com/content/44/1/15.abstract)
- [Liu & Tsyvinski RFS](https://www.nber.org/papers/w24877)
- [Liu, Tsyvinski, Wu JF](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119)
- [Grobys & Sapkota 2019](https://www.sciepub.com/reference/398655)
- [Grobys & Shahzad IJFE](https://onlinelibrary.wiley.com/doi/abs/10.1002/ijfe.70036)
- [Crypto momentum has (not) its moments](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- [Zaremba et al. 2021](https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html)
- [Begušić & Kostanjčar](https://arxiv.org/abs/1904.00890)
- [Shen, Urquhart, Wang 2022](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290)
- [Wen et al. 2022](https://ideas.repec.org:443/a/eee/ecofin/v62y2022ics1062940822000833.html)
- [Gao et al. 2018](https://doi.org/10.1016/j.jfineco.2018.05.009)
- [BLL 1992](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x)
- [STW 1999](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00163)
- [Corbet et al. 2019](https://ideas.repec.org/a/eee/finlet/v31y2019icp32-37.html)
- [Hudson & Urquhart 2021](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- [Cooper et al. 2004](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00665.x)
- [Daniel & Moskowitz 2016](https://econpapers.repec.org/RePEc:eee:jfinec:v:122:y:2016:i:2:p:221-247)
- [Barroso & Santa-Clara 2015](https://econpapers.repec.org/RePEc:eee:jfinec:v:116:y:2015:i:1:p:111-120)
- [Lee & Swaminathan 2000](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00280)
- [Gervais et al. 2001](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00349)
- [Makarov & Schoar 2020](https://ideas.repec.org/a/eee/jfinec/v135y2020i2p293-319.html)
- [Novy-Marx & Velikov 2016](https://econpapers.repec.org/RePEc:oup:rfinst:v:29:y:2016:i:1:p:104-147.)
- [Katsiampa 2017](https://www.researchgate.net/publication/317723547_Volatility_estimation_for_Bitcoin_A_comparison_of_GARCH_models)
