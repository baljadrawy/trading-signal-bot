# Variant / alpha ledger (R2)

Status: **development (D0), synthetic tests only.** Code: `research/stats/`. Tests: `tests/test_r2_variant_ledger.py`.
Roadmap: `PROFITABILITY_ROADMAP_2026-10-24.md` §5.4 and initiative #2 (R2).

## Purpose

Every variant a researcher tries spends some of the evidence. If only the winners are reported, a positive result
is just the maximum of many noisy tries. R2 makes the count of tries part of the result:

| Piece | Module | What it does |
|---|---|---|
| Variant ledger | `variant_ledger.py` | Append-only JSONL. A `register` event per variant (id, family, hypothesis ref, data-window label, metric, code SHA, evidence class, optional dataset/config hash and cost label), written **before** the result is read; at most one `result` event (n, mean, sd, skew, non-excess kurtosis). Timestamps to the minute (UTC). Running count of variants per family. |
| PSR / DSR | `sharpe_deflation.py` | Probabilistic Sharpe Ratio and Deflated Sharpe Ratio (Bailey & Lopez de Prado 2012, 2014), with N = number of trials and the variance of the trial Sharpe ratios. Per-observation units. |
| Family-wise | `familywise.py` | Holm step-down (check) and Romano–Wolf bootstrap step-down (primary), seeded, iid or circular block bootstrap. |
| Alpha budget | `alpha_budget.py` | Fixed budgets that tests draw from: governed admissions 1/240 each from a 12-admission program (1/20 in total); exploratory family 0.05 split over the family (S4: 0.05/3). Re-use of a spent look and spending past the budget are refused. |

## How it enforces multiple-testing discipline

1. **No silent variants.** A variant is registered before its result exists. A registered variant with no result is
   an abandoned trial and still counts: `deflated_sharpe()` uses N = every registered variant of the family.
2. **No rewriting history.** There is no edit or delete API; an id registers once and gets one result. Every line is
   hash-chained (`seq`, `prev`, `hash`, canonical JSON) and the whole chain is checked on every read and before every
   append, so an edited value, removed line, reorder or torn tail raises `LedgerTamper`. Tail truncation is caught by
   recording `head()` externally (e.g. in a preregistration) and calling `verify(expected_head=...)`.
3. **Deflation by the real search size.** DSR compares the observed Sharpe ratio with the expected maximum of N null
   trials, so it falls as N grows (tested). The 2014 paper's worked example (DSR ≈ 0.9004) is reproduced in tests.
4. **Family-wise control and a fixed alpha.** Romano–Wolf with Holm as a check over a family; each confirmatory test
   draws its alpha from a budget that cannot be exceeded or re-spent.

## Holds no real results

The repository contains **no ledger file and no real result**. All tests use generated random data in temporary
directories. Only the `SYNTHETIC` evidence class is accepted without an authorization reference.

## Governance

Using this ledger or these statistics on real market data or trade outcomes is a **governed research action**. It
needs explicit owner / scientific authorization and a committed preregistration (roadmap §6) before it starts, and it
stays under the holdout rules of roadmap §5 (no sealed or forward-holdout reads). The alpha values in
`alpha_budget.py` are owner-governed planning values (calibration level unvalidated, DR-2), equal to those in
`research/power/ladder_power.py` (a test keeps them identical; that package is not imported from outside); changing
them is an owner decision. Making the ledger mandatory for all research is
RD-3 (owner). Alpha spends are kept in memory (`AlphaBudget(spent_labels=...)` replays them); recording them in the
ledger next to `research/governance/validation_usage.jsonl` is not done here.
