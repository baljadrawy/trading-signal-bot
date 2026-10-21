# Independent review package R1: quantitative research and trading methodology

**For:** an external reviewer independent of the author. **Status: NOT YET REVIEWED.** No external or independent response has been received as of 2026-10-21. Refreshed 2026-10-21 for `main` @ `614cecd` and Draft PR #67. No secrets are included.

## Artifacts (all at the commit of this PR unless noted)
- `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`: design, owner-decided rules R0–R10 (§2.2), matrices, resources (§10), lab DB and data immutability (§11).
- `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` (`main`, merged #63): candidates, literature, power, pre-registration draft.
- `docs/strategy/S4_MECHANISM_COMPARISON.md`, `research/mechanisms/` (`main`, merged #60): cost model, signals, simulator.
- `research/power/` (`main`): Evidence Ladder power calculator.
- `docs/research_temporal_governance.md`, `research/governance/holdout_status.json` (`main`): holdout rules.
- `docs/a46/`, `docs/a47/`, `docs/a48/` (`main`): geometry, execution realism, replay fidelity.
- `lab/account.py`, `lab/REVIEW.md`, `tests/test_lab_account.py` (Draft PR #67, **not merged**): reference accounting core for R0–R10.
- `research/governance/contamination_registry.jsonl` (`main`): recorded contamination of history (incl. W3).

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

## Evidence status: completed tests vs. external review

| Item | Status | Evidence |
|---|---|---|
| Account rules R0–R10 (accounting core) | **internal tests done** | #67: 30 tests, 13/13 mutants killed (author-run, not independent) |
| Cost model a48-cost-v1 (fees + tiered half-spread + slippage) | internal tests done | `research/mechanisms/costs.py` tests (#60) |
| Power / MDE (Evidence Ladder) | internal calculator | `research/power/` |
| Holdout seal | VERIFIED read-only | `holdout_status.json`: SEALED, look count 0 |
| Hypothesis registration (registry) | **not built** | design only (§4 G5) |
| Fill / cost sensitivity (R6) | **not built** | required by design, not implemented |
| **Independent quantitative review** | **NOT DONE** | this package |

## A. Questions by topic

### A1. Hypothesis registration
1. Is a pre-registration hash (spec, parameters, universe, cost model, sample window, primary metric, stopping rule) recorded before the first intent sufficient? Which fields are mandatory?
2. Should a strategy *version* change (any parameter, rebalancing rule, R9 trigger override) always be a new registration, with the old account closed rather than reused?

### A2. Multiple-testing control
3. With ≤ 5 parallel forward strategies plus unlimited historical triage, which family is controlled (per admission, per quarter, all time)? Is α = 1/240 per admission (A29–A33) plus Romano–Wolf / Deflated Sharpe adequate?
4. How are discarded variants counted so that the family size is not understated?

### A3. Data quality and contamination
5. All history is research-exposed. Is historical backtesting acceptable for triage only, never for confirmation?
6. The forward Collector dataset has documented coverage events: a 2026-10-06 fail-closed stop and failed seal, a 2026-10-10 conn0-book outage (retrospective, fixed in 1.6.0), and recurring short Tier-0 losses on reconnects (10 occurrences, 10-14 to 10-20). All are recorded as gap records or incidents. Which exclusion or imputation rule should a future confirmation use, fixed before any look?
7. Is the data-access matrix (§3) sufficient to keep the holdout sealed, given that research-runner admission is now open (Collector HEALTHY since 2026-10-21T08:35Z)?

### A4. Fees, slippage and execution
8. Is full-fill at the observed price, moved by half-spread + slippage (≥ 0.05 %), with 0.10 %/side fees acceptable at 500 USDT orders in liquid pairs? Should partial fills, `minNotional` and lot/tick sizes be modelled before any P&L is reported?
9. #67 refuses below-model costs with a single floor. Should it require per-symbol a48 tiers?
10. The owner decided (2026-10-21) that the lab reuses the shared exit, entry and cost logic (`lab/ARCHITECTURE_ALIGNMENT.md`). Is versioned reuse of `step_barrier` decisions (break-even after T1, 2.5 % trailing after T2, timeframe expiry) with lab-side money and costs the right basis for fair comparison? Which break-even cost basis should be declared by default?

### A5. Prospective confirmation design
11. Is the four-mode separation (backtest / shadow / forward Paper / confirmation) correct? When may Paper results inform an admission?
12. Suspension (R9) makes the sample path-dependent. How should suspended-then-resumed accounts be reported so that owner reviews do not select outcomes? Is the PROP re-arm rule (drawdown re-measured from the review point) acceptable?
13. Fair comparison across turnover and holding periods: daily net returns, active vs equal-weight buy-and-hold, cost drag, capacity.

### A6. Holdout protection
14. Which technical controls (no mount of `p2`/post-freeze paths, `DatasetPermission`, freeze watchdog, look counter) are necessary and sufficient, and which must be tested before any lab job runs?
15. Does a shared compute budget (R1 4 vCPU / R2 5 vCPU, R3 deferred) bias which variants get evaluated?

## Known unresolved issues (author)
- No hypothesis registry and no R6 sensitivity tooling yet.
- Exit-model divergence between #67 and `shared/triple_barrier.py`: the alignment is proposed, not implemented (A4 Q10).
- Binance Vision licence not cleared; no `DatasetPermission` record exists, so no non-synthetic run is permitted.

## Acceptance tests the reviewer should require or confirm
- Pre-registration hash recorded before the first intent; every variant logged; no silent re-runs.
- Cost reconciliation against `a48-cost-v1`; sensitivity (×1.5, ×2, adverse tick, 10 % no-fill) with every result.
- Same-symbol, two-account independence; accounting invariants under concurrency.
- No post-freeze data mounted in a backtest; look counter unchanged by lab work.
- R9: suspension and integrity block reject entries, predeclared exits run, alert-only at 8 losses, no automatic resumption, refill or reset.

## Evidence the reviewer needs (exact versions)
- `main` @ `3bd79a4`: `docs/lab/STRATEGY_LAB_ARCHITECTURE.md` (rev 4), `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md`, `docs/strategy/S4_MECHANISM_COMPARISON.md`, `research/mechanisms/`, `research/power/`, `docs/research_temporal_governance.md`, `research/governance/holdout_status.json`, `research/governance/contamination_registry.jsonl`, `docs/p2/OPS_RECORD_2026-10-21.md`.
- Draft PR #67 (current head): `lab/account.py`, `lab/REVIEW.md`, `lab/ARCHITECTURE_ALIGNMENT.md`, `tests/test_lab_account.py`.
- Draft PR #72: the 2026-10-10 outage operational summary (data-quality governance).
- **Not provided, by design:** sealed forward-holdout data, Collector stream contents and post-freeze outcomes. The review is of methods and controls, not results.

## Independence requirement
- The reviewer must not be the author (the operating agent), and must not have contributed to the reviewed artifacts. State any relationship.
- Agent self-checks, CI runs and the author's tests are **not** independent review and do not count toward this gate.

## Expected deliverables
1. A completed response template (below) at an **exact commit SHA**.
2. A finding list. Each finding has an id, severity (BLOCKER / MAJOR / MINOR), statement, evidence (file:line or test), and a recommended correction.
3. The acceptance tests the reviewer requires, marked "must pass before merge" or "before activation".
4. An explicit verdict: GO / REVISE / NO-GO.

## How findings are accepted or rejected (owner-side rule)
- **Accepted:** a finding with reproducible evidence at the reviewed SHA. It is tracked to closure, by a fix PR or a documented owner risk acceptance.
- **Rejected:** only with a written counter-evidence note (a test, code reference or data) attached to the finding. Disagreement alone is not rejection.
- **Severity:** any open BLOCKER means NO-GO for merge or activation. A MAJOR needs a fix or an explicit owner risk acceptance. A MINOR may be deferred, but is recorded.
- **Staleness:** a review is valid only for the reviewed SHA. Later changes to the reviewed files need a delta review.

## Response template
```
Reviewer: <name / affiliation / independence statement>    Date:    Commit reviewed: <sha>
Verdict: GO | REVISE | NO-GO
Findings: [id, severity BLOCKER/MAJOR/MINOR, statement, evidence, recommended correction]
Alternatives considered and trade-offs:
Required acceptance tests:
Owner decisions remaining:
```
