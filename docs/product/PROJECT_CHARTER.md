# Trading Signal Bot — Product Charter / المرجع المعتمد
**Approved by owner:** 2026-09-27. **Status:** Product direction approved; implementation and activation NOT approved.  
**Canonical status:** This charter and the Decision Log supersede stale narrative in older README/CLAUDE/live-learning documents where they conflict. Changes require an explicit owner decision recorded in the Decision Log.

## 1. Mission / الهدف
Build a reproducible, risk-governed crypto signal and paper-trading research platform that:
1. Observes every current-strategy candidate and trade with point-in-time provenance.
2. Studies multi-year market data and discovers historically recurring patterns of rallies, drawdowns, breakouts, false breakouts and regime transitions.
3. Estimates **calibrated probabilities**, uncertainty and event horizons for future price moves; historical resemblance is evidence to test, **not** a guarantee that history repeats.
4. Eventually issues bounded, auditable **market-risk instructions** to reduce new positions/exposure when downside risk is elevated and to restore/increase permitted opportunities when upside conditions improve, **only after separate validation and owner approval**.
5. Lets the owner review operations, research and ML experiments via a future web command center, with Telegram for alerts and limited operational commands.

## 2. Non-negotiable governance
- **Current state: PAPER_TRADING=HALTED; PAPER_ONLY; LIVE_TRADING=FORBIDDEN.** Never restart paper, run /recover_risk or /resume, connect funded exchange keys, or enable live without the owner's separate explicit approval.
- Preserve B3 fail-closed protections, risk epochs, safety pauses, sealed holdout and current deployed strategy. No strategy/risk threshold change as a side effect of instrumentation or research.
- The existing holdout is SEALED for new research, but previously viewed outcomes mean it is **not pristine independent evidence**. New claims require predeclared prospective out-of-sample tests.
- Retired continuous_learner/optimizer must not restart automatically; no auto-training, auto-deploy, or automatic model promotion.
- The separate `baljadrawy/trading-bot` integration is **DEFERRED**. It is not running on the signal-bot host according to the 2026-09-27 audit; its runtime elsewhere is unverified. No integration or real order execution in this roadmap.
- P0 PostgreSQL least-privilege design was validated in isolation but production rollout is deferred by owner. No new research process may inherit cluster SUPERUSER privileges; revisit security before resuming trading or widening service access.
- Preserve existing production and backup evidence. Use isolated branches and synthetic test data; no production deployment or migrations without separate approval.

## 3. Three coordinated research tracks
### A. Forward strategy instrumentation
Deterministic candle/candidate IDs, candle_open_time, code/config/strategy hashes; append-only meaningful decision changes; rejected candidates and reasons; macro-blocked/no-trade cycles; B3 admission and Telegram silent refusals; fill/no-fill and trade lifecycle; data-quality reconciliation. Never train the current policy on stale outcomes from obsolete policies.

### B. Independent historical + forward market intelligence
Reuse the existing historical OHLCV snapshot before buying data. Analyze BTC, ETH, ETH/BTC, market breadth, BTC.D/ETH.D/USDT.D, TOTAL/TOTAL2/TOTAL3, stablecoin supply/flows, derivatives/liquidity, timestamped events when point-in-time data exists. Record provider, observation timestamp, availability timestamp, coverage and gaps; no current macro substituted into history. Collect current market context independently while trading is halted. Prefer Parquet + DuckDB research and as-of joins; avoid new microservices/Kafka by default.

### C. Market prediction + risk throttling
- Event definitions must be fixed **before** experiments: e.g. downside/upside threshold over 1h/4h/24h/7d, maximum adverse/favorable excursion, time to event and false-breakout conditions. Thresholds are **TBD research parameters**, not approved trading settings.
- Build simple baselines first (unconditional/event frequency, volatility-adjusted baseline, logistic/tree baseline); then historical-neighbor retrieval, regime models and trade-quality models only if justified.
- Use temporal/walk-forward validation, purging/embargo for overlapping labels, point-in-time features, delisting-aware universes and transaction-cost assumptions. Show sample sizes, effective independent episodes, calibration, false alarms, precision/recall, Brier/log loss, regime stability and decision utility.
- Run predictions in **SHADOW** with timestamped forecasts and realized outcomes; compare against baselines on prospective independent periods. A convincing backtest alone cannot authorize production influence.
- Distinguish **price downside/drawdown prediction** from **execution slippage prediction**; the latter needs historical spread/order-book/fill data and is a separate future model.

## 4. Bounded risk-control contract — approved concept, NOT activated
Future component: `MarketRiskAdvisor` emits signed/versioned, timestamped `RiskRecommendation` with model/version, event horizon, calibrated downside/upside probability, uncertainty, feature freshness, regime, evidence IDs, suggested exposure multiplier, validity/expiry, explanation and audit ID. An independent deterministic `RiskPolicyGate` validates recommendations before they can affect paper trading.

- High downside risk: suggest fewer **new** trades, lower aggregate exposure and/or block new entries. **Do not automatically liquidate existing positions**; their exits follow existing rules unless the owner separately approves a tested liquidation policy.
- Favorable upside: suggest restoring previously reduced exposure or increasing new opportunities **within the already approved B3 and portfolio limits**. Multipliers above the existing baseline, changed max_open_trades/stake, or any relaxation of B3 require **a separate owner-approved change** backed by prospective tests.
- For initial design, proposed effective new-entry budget = `min(B3_remaining_budget, baseline_budget × bounded_multiplier)`; bounded_multiplier is `0..1` until any later explicit approval for >1. These are design constraints, not deployed settings.
- Stale/missing features, uncalibrated model, low confidence, disagreement, expired forecast, model outage or inconsistent data => no ML-based risk expansion; retain existing safety gates, optionally conservatively reduce new entries only if the fallback is explicitly tested and approved. No silent override.
- Use hysteresis/cooldowns and minimum evidence to prevent oscillating trade limits; exact thresholds and owner approval gates TBD. Log every recommendation, policy decision, override and counterfactual.
- No live execution adapter, automatic order placement or strategy mutation as part of this charter.

## 5. Operator experience (future)
**Web command center:** overview/health, candidates and rejection reasons, trades and PnL, market intelligence, pattern library, probabilistic forecasts, ML Lab (datasets/versions/metrics/calibration/drift), risk recommendation vs applied policy, approvals and immutable audit trail. Reuse Grafana for infrastructure/operational metrics where practical.
**Telegram:** alerts, status/report/risk/models and safe pause; sensitive changes, model promotion and risk recovery require an authenticated audited approval workflow. Do not implement a one-click bypass of B3.

## 6. Success criteria
Success is not a high historical accuracy score. Require prospective calibration, controlled false-alarm rate, better risk-adjusted paper outcomes **after fees, spread and slippage**, no unacceptable reduction in opportunity capture, stable behavior across regimes, traceable data lineage, parity with the frozen strategy where required, and safe failure under outages. Define numerical thresholds and test windows *before* evaluation; do not invent targets after seeing results.

## 7. Deferred / separate decisions
Execution-bot integration, real trading, P0 production-role rollout, paid historical datasets, model-driven liquidation, above-baseline position expansion and custom full web UI are separately gated. Security incident: xsch bearer token was exposed in a Claude transcript on 2026-09-27; rotate it and assess any other active leaked credentials. **Never store secrets or the sensitive P0 security report in this repository.**
