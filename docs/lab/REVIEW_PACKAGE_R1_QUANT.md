# Independent review package R1: quantitative research and trading methodology

**For:** an external reviewer independent of the author. **Status:** not yet reviewed. No secrets are included.

## Artifacts (all at the commit of this PR unless noted)
- `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`: design, rules R1–R10, matrices.
- `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` (Draft PR #63): candidates, literature, power, pre-registration draft.
- `docs/strategy/S4_MECHANISM_COMPARISON.md`, `research/mechanisms/` (Draft PR #60): cost model, signals, simulator.
- `research/power/` (`main`): Evidence Ladder power calculator.
- `docs/research_temporal_governance.md`, `research/governance/holdout_status.json` (`main`): holdout rules.
- `docs/a46/`, `docs/a47/`, `docs/a48/` (`main`): geometry, execution realism, replay fidelity.

## Context facts (author-verified, read-only)
- The bot's tested 15m/4h strategy lost **before** costs historically: gross PF ≈ 0.73 on 2,518 / 3,401 trades, all pre-freeze.
- All history is research-exposed.
- The forward holdout (after 2026-08-19T09:33:46Z) is sealed.
- The Evidence Ladder is ≤ 365 days, α 1/240 per admission, final look only. A365-day annualized Sharpe MDE is ≈ 3.5–5.0 (illustrative).
- Approved Paper parameters per strategy:
  - 5,000 USDT initial balance;
  - 500 USDT per order;
  - ≤ 5 positions;
  - gross cap 2,500 USDT;
  - Spot only, no leverage, no replenishment or reset;
  - 0.10 %/side fee plus spread and slippage.

## Questions
1. Are R1 (fixed nominal cap on cost basis), R2, R4 (cash floor option) and R9 (terminal account) defensible? Do they bias comparisons between strategies?
2. How should strategies with different turnover and holding periods be compared fairly? Consider daily net return series, an active return vs equal-weight buy-and-hold, cost drag and capacity.
3. Execution realism at 500 USDT per order in top-20 liquid pairs:
   - Is full-fill at the observed price plus modelled slippage acceptable?
   - Is a depth-share flag (R6) enough?
   - Should partial fills and `minNotional` be modelled?
4. Is the cost model (0.10 %/side + tiered half-spread + 0.05 % slippage, ×2 stress) adequate? Should the tracker's 0.30 % be retired for lab accounts?
5. Statistical validity:
   - the multiplicity across ≤ 5 parallel strategies;
   - pre-registration;
   - Romano–Wolf and Deflated Sharpe;
   - day-clustered dependence;
   - the power limits.
6. Contamination: is the data-access matrix (§3) sufficient to keep the holdout sealed? Is any forward data path a leak into "discovery"?
7. Is the four-mode separation (backtest / shadow / forward Paper / confirmation) correct? When may Paper results inform an admission?
8. Treatment of failed or inconclusive strategies: retention, reporting, and no silent re-runs.

9. Resources and fairness (§10): does a shared research budget (R1 4 vCPU / R2 ≤ 6) bias strategy comparison? For example, do backtest throughput or queueing alter which variants get evaluated? Is keeping the A29 20 % prospective reserve separate from compute correct?

## Acceptance tests the reviewer should require or confirm
- Accounting invariants under concurrency.
- Cost reconciliation against `a48-cost-v1`.
- Same-symbol, two-account independence.
- Pre-registration hash recorded before the first intent.
- Every variant logged.
- No post-freeze data mounted in a backtest.

## Response template
```
Reviewer: <name / affiliation / independence statement>    Date:    Commit reviewed: <sha>
Verdict: GO | REVISE | NO-GO
Findings: [id, severity BLOCKER/MAJOR/MINOR, statement, evidence, recommended correction]
Alternatives considered and trade-offs:
Required acceptance tests:
Owner decisions remaining:
```
