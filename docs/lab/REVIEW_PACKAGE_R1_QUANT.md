# Independent review package R1: quantitative research and trading methodology

**For:** an external reviewer independent of the author. **Status:** not yet reviewed (no external response received as of 2026-10-20). Refreshed for design revision 3 (owner decisions applied). No secrets are included.

## Artifacts (all at the commit of this PR unless noted)
- `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`: design, owner-decided rules R0–R10 (§2.2), matrices, resources (§10), lab DB and data immutability (§11).
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
  - 500 USDT target per order;
  - ≤ 5 positions, at most one per symbol per account;
  - initial exposure cap 2,500 USDT = entry cost basis + pending reservations (mark-to-market monitored, never frees cap);
  - the remaining 2,500 is an initial allocation, **not** a permanent cash floor;
  - Spot only, no leverage or borrowing, no replenishment or reset;
  - 0.10 %/side fee plus spread and slippage;
  - full-fill model kept as a stated limitation with mandatory sensitivity tests;
  - no automatic permanent freeze at 1,000 USDT, no automatic reset or resumption; `SUSPENDED_REVIEW` at a 30 % drawdown from peak equity or equity < 2,000 USDT; 8 consecutive losses → alert and review only; accounting-integrity failure → immediate block of new orders; open positions keep their predeclared exits (owner-decided 2026-10-21).

## Questions
1. Are R1 (fixed nominal cap on cost basis + reservations), R2, R4 (no permanent cash floor) and R9 (suspension and review instead of a terminal account) defensible? Do they bias comparisons between strategies? Are the owner's R9 triggers (suspend at 30 % drawdown from peak or equity < 2,000; alert-only at 8 consecutive losses; immediate block on integrity failure) reasonable, should they be identical for all strategies, and is the PROP re-arm rule after an owner resume (drawdown from the review point; 2,000 trigger on a new crossing) sound?
2. Suspension creates a conditional (path-dependent) sample: how should results of suspended-then-resumed accounts be reported so that review decisions do not select outcomes?
3. How should strategies with different turnover and holding periods be compared fairly? Consider daily net return series, an active return vs equal-weight buy-and-hold, cost drag and capacity.
4. Execution realism at 500 USDT per order in top-20 liquid pairs:
   - Is full-fill at the observed price plus modelled slippage acceptable?
   - Is a depth-share flag (R6) enough?
   - Should partial fills and `minNotional` be modelled?
5. Is the cost model (0.10 %/side + tiered half-spread + 0.05 % slippage, ×2 stress) adequate? Should the tracker's 0.30 % be retired for lab accounts?
6. Statistical validity:
   - the multiplicity across ≤ 5 parallel strategies;
   - pre-registration;
   - Romano–Wolf and Deflated Sharpe;
   - day-clustered dependence;
   - the power limits.
7. Contamination: is the data-access matrix (§3) sufficient to keep the holdout sealed? Is any forward data path a leak into "discovery"?
8. Is the four-mode separation (backtest / shadow / forward Paper / confirmation) correct? When may Paper results inform an admission?
9. Treatment of failed or inconclusive strategies: retention, reporting, and no silent re-runs.

10. Resources and fairness (§10): does a shared research budget (R1 4 vCPU / R2 5 vCPU; R3 deferred) bias strategy comparison? For example, do backtest throughput or queueing alter which variants get evaluated? Is keeping the A29 20 % prospective reserve separate from compute correct?

## Acceptance tests the reviewer should require or confirm
- Accounting invariants under concurrency.
- Cost reconciliation against `a48-cost-v1`.
- Same-symbol, two-account independence.
- Pre-registration hash recorded before the first intent.
- Every variant logged.
- No post-freeze data mounted in a backtest.
- Cost/fill sensitivity (×1.5, ×2, adverse tick, 10 % no-fill) reported with every result.
- A fired suspension or integrity block rejects entries but lets predeclared exits run; 8 consecutive losses produce only an alert; no automatic resumption, refill or reset.

## Response template
```
Reviewer: <name / affiliation / independence statement>    Date:    Commit reviewed: <sha>
Verdict: GO | REVISE | NO-GO
Findings: [id, severity BLOCKER/MAJOR/MINOR, statement, evidence, recommended correction]
Alternatives considered and trade-offs:
Required acceptance tests:
Owner decisions remaining:
```
