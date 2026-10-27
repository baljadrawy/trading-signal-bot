# LIC-1 — Data licence inquiry for HR-04 / HR-08 (DRAFT for owner review, NOT SENT)

**Status: DRAFT (D0).** Written 2026-10-27 on `research/variant-ledger` (PR #94). Nothing in this file has been sent
to anyone, and no data has been downloaded, opened or read to write it. It authorizes nothing: no dataset permission,
no ledger registration, no alpha, no window. Sending it is the owner's decision (roadmap RD-5, R9; policy OD-DF-1).

*Not legal advice.* This file records what earlier source reviews found and lists the questions to confirm. It does
not draw legal conclusions, and nothing in it is a clearance.

## 0. Relation to the earlier draft (reused, not duplicated)

The first LIC-1 draft is A22 §3–§4 (`docs/audits/2026-10-12/A22_P2_H1_PRE_EXECUTION_READINESS.md`, local commit
`8cb5c9e` on the held branch `feature/mi-am4a-stage-b-prep-20261011`; **not on `main`**). It was written for P2-H1
(Vision 1h/1d/15m archives) and also proposed LIC-2 (licence basis for running P2-H1). This file **supersedes the A22
inquiry text for the HR-04 / HR-08 step**. It keeps A22's source findings (quoted as recorded on 2026-10-12 and **not
re-verified here**: no network access was used) and adds the point-in-time universe, delisted symbols, the pre-freeze
window and vendor options. If the owner prefers the A22 wording, the two can be merged into one message: questions
Q1–Q4 of §4 below cover A22 questions 1, 2, 4 and 5; A22 question 3 (live use of a researched strategy) is Q5.

## 1. Purpose

Exploratory, non-confirmatory qualification of HR-04 (daily time-series momentum, long/cash), HR-08 (volatility-
targeted sizing) and HR-13 (no-trade band) in `docs/strategy/HYPOTHESIS_REGISTER.md`, following the plan in
`docs/strategy/NEXT_LICENSED_DATA_STEP.md`. The engineering for this step (point-in-time universe, delisting exits,
HAC t, stationary bootstrap, monthly EW benchmark, labelled summary) is synthetic-only today
(`research/strategies/pit_universe.py`, `research/stats/inference.py`, `research/strategies/result_summary.py`).

The project is R&D / PAPER_ONLY (`docs/governance/OWNER_OPERATING_CONTRACT.md` §1). No profitability is claimed for
any hypothesis. An exploratory result could at most nominate a candidate; confirmation stays on the D1/D2 HOLD.

## 2. Dataset needed

| Item | Specification |
|---|---|
| Instrument set | Binance Spot, USDT quote pairs (same venue as the Paper bot) |
| Granularity | daily (1d) klines, UTC days |
| Fields | open time, open, high, low, close, base volume, **quote volume**, number of trades |
| Universe inputs | listing date, **delisting date**, symbol status history (trading / halted / delisted), renames / migrations, for **every** pair that ever traded in the period, including pairs that are delisted today |
| Period | 2019-01-01 to 2026-08-18 inclusive, **strictly before the 2026-08-19 freeze instant**. No bar that closes at or after the freeze instant is requested, loaded or used, not even for warm-up. The sealed FORWARD_HOLDOUT stays sealed |
| Size | about 600–1,500 symbols × at most about 2,800 days; small (tens of MB compressed) |
| Survivorship | the point-in-time top-20 universe is rebuilt at each date from data up to that date; delisted symbols must be present up to their last traded day |
| Format / provenance | content-addressed snapshot with checksums (`research/data_governance`), data-quality certificate before use |

Not needed: order book, trades, funding, futures, intraday bars, account or personal data.

## 3. Source options and what each is recorded to permit

The cells below summarize earlier reviews (A18/A19 2026-10-11, A22 2026-10-12). They are **as recorded, not
re-verified**, and every one ends in a question for §4 or for the vendor.

| Option | Recorded terms (summary) | What it appears to allow | Open questions |
|---|---|---|---|
| **A. Binance public data** (`data.binance.vision`, "Binance Vision Dataset Terms" v1.0, last updated 2026-08-26, CC BY-NC-SA 4.0 basis) | §4.1 permitted uses include "algorithmic historical backtesting for purely personal non-production research"; §3.4 "commercial utilization requires a separate, written enterprise data license"; §2.4 derived data governed by the terms; §4.2 no live proprietary trading execution with the Datasets; §4.3–4.5 no commercial exploitation or hosting; §1.4 amendments do not affect datasets already downloaded. A22 noted the on-site PDF metadata title began "[Draft]" | personal, non-production, non-commercial research; derived data kept private | whether this project's research counts as "purely personal non-production"; whether delisted-symbol archives are complete; status of any copies downloaded before the terms were published (A22 §3.3 item 1) |
| **B. Binance REST market-data API** (`/api/v3/klines`, `exchangeInfo`) under the Binance Terms of Use (snapshot "Last Updated: 10 October 2025") and the API terms | ToU cl. 22: licence "solely as necessary to allow you to receive the Binance Services for non-commercial personal or internal business use"; cl. 26(c): no resale or commercial purposes unless agreed in writing; cl. 26(i): no scripts "in any manner not purposely provided". API terms were not read first-hand (A22 S8) | possibly internal research use; a different and **also unconfirmed** basis | whether bulk historical download of klines for internal research is a purpose "purposely provided"; whether delisted symbols are retrievable at all through the API (they usually leave `exchangeInfo`) |
| **C. Commercial vendor** (e.g. Kaiko, CoinAPI, Tardis.dev, Amberdata, CryptoCompare/CCData) | written commercial licence; terms and prices not reviewed | typically explicit research and internal-use rights, scope per contract | per vendor: research / internal use for possible proprietary trading, retention after termination, derived data, delisted-symbol coverage, survivorship-free universe, cost |
| **D. No historical data** (prospective only, collector via API) | n/a | avoids the question at the cost of time | power: a forward year cannot confirm a realistic effect (HR-04 power note) |

Copies of Vision archives that may exist on the research host from earlier work (A18/A22) are **not** covered by any
`DatasetPermission`, were not opened for this draft and must not be used until OD-DF-1 records a permission naming
them.

## 4. Questions the inquiry must answer (to confirm, not assumed)

- **Q1 Purpose fit.** Is private, internal historical backtesting of trading-strategy hypotheses by the licensee,
  with no third parties, no compensation, no redistribution and no signal distribution, a permitted use? Does that
  stay true when the purpose is to decide whether a strategy merits further **paper** (simulated) forward testing?
- **Q2 Licensee status.** Does the answer differ if the licensee acts as an individual or as a business entity
  (internal business use)?
- **Q3 Derived data.** May internal derived data (indicators, universe membership, returns, research reports) be
  kept privately and indefinitely? Must it carry attribution or share-alike terms if never distributed?
- **Q4 Delisted symbols and history.** Does the permitted dataset include delisted pairs and their listing /
  delisting dates for 2019-01-01 to 2026-08-18? Is retention allowed after a licence ends, and for how long?
- **Q5 Later live use.** If a strategy researched on the data is later run (only after separate approvals, which
  this project does not hold) with live market data from the API, is that a restricted use of the historical data?
- **Q6 Earlier downloads.** Which terms govern copies downloaded before the current dataset terms were published?
- **Q7 Commercial path.** If any of the above needs a commercial or enterprise licence, what is the channel, scope
  and indicative cost?

Owner-side facts to record before sending (not assumptions of this draft): who the licensee is (individual or
entity), the sending channel, and whether the message may mention the earlier downloads.

## 5. Inquiry text (English, for the owner to send; placeholders only)

Suggested channel: a Binance institutional / data-licensing or support contact that can route to the Binance Vision
data owner, or the chosen vendor's sales / licensing desk (adapt the first paragraph). A public GitHub issue is not
recommended because it would disclose the project.

> **Subject:** Licensing question: internal research use of Binance Spot daily kline history
>
> Dear Binance Data / Licensing team,
>
> I am writing on behalf of [OWNER NAME OR ENTITY], [individual / company, jurisdiction]. I would like to confirm
> the permitted use of Binance Spot historical market data before using it, and I would be grateful for a written
> answer.
>
> **Data.** Daily (1d) klines for Binance Spot USDT pairs from 1 January 2019 to 18 August 2026 inclusive (open,
> high, low, close, base and quote volume, number of trades), together with listing and delisting dates and symbol
> status history, **including pairs that have since been delisted**. Source: [data.binance.vision archives / REST API
> klines / please advise the appropriate source].
>
> **Intended use.** Internal, non-production historical research only: testing a small number of predefined
> trading-strategy hypotheses on past data and comparing them with simple buy-and-hold benchmarks. Results are used
> only internally to decide whether a hypothesis deserves further simulated (paper) testing.
>
> **What we will not do.** We will not redistribute, resell, publish, host or share the data or any dataset derived
> from it; we will not provide signals or data to third parties or for compensation; and we will not use the
> historical data in any live order execution.
>
> **Questions.**
> 1. Is this internal research use permitted under the terms that apply to the data source named above? If so,
>    which terms (name, version and date) govern it?
> 2. Does the answer depend on whether the user is an individual or a business acting for its internal purposes?
> 3. May internal derived data (indicators, universe lists, research reports) be kept privately, and are
>    attribution or share-alike terms required if nothing is ever distributed?
> 4. Does the permitted data include delisted pairs and their listing and delisting dates? How long may the data
>    be retained, including after any licence ends?
> 5. If a strategy researched this way were later operated with live API market data, would that be a restricted
>    use of the historical data?
> 6. [Only if the owner decides to mention earlier downloads:] Which terms apply to archive files downloaded from
>    data.binance.vision on [DATES] before the current dataset terms were published?
> 7. If any of these uses requires a commercial or enterprise data licence, could you tell us the contact, scope
>    and indicative terms?
>
> Thank you for your help.
>
> Kind regards,
> [OWNER NAME]
> [OWNER CONTACT DETAILS]

## 6. What we will and will not do with the data (commitments for the permission record)

**Will:** store one content-addressed, checksummed snapshot on the research host; verify data quality; compute the
pre-registered exploratory analysis of `NEXT_LICENSED_DATA_STEP.md` §4 through the research runner (CPU and memory
caps); keep derived results internally; record every use in the validation-usage log; delete or retain the data per
the licence's retention term (default proposal: retain while the permission is valid, delete within 30 days after it
ends unless the licence says otherwise).

**Will not:** redistribute, publish, resell, host or share the raw data or derived datasets; provide signals or data
to third parties; use the historical data in any live order execution (the project is PAPER_ONLY and holds no live
authorization); load any bar at or after the 2026-08-19 freeze instant; read any protected holdout; claim
profitability from an exploratory result.

## 7. Owner decision record template — OD-DF-1 (dataset permission)

Copy into `docs/governance/DEVELOPMENT_FIRST_POLICY.md` §7 (or the owner-decision register) when decided. A granted
permission becomes a `research/mechanisms/simulate.DatasetPermission(source, licence_cleared=True,
holdout_excluded=True, reference="OD-DF-1/<id>")`; any summary labelled other than SYNTHETIC must name it as
`authorization_ref` (`research/strategies/result_summary.authorize_label`).

```text
OD-DF-1/<id> — Dataset permission
Decision:            GRANTED | DENIED | DEFERRED
Decided by / date:   <owner>, <YYYY-MM-DD>
Dataset:             <source option A/B/C>, <exact product / endpoint / vendor>, <fields>
Period:              <start> .. <end>  (end strictly before the 2026-08-19 freeze instant)
Universe coverage:   delisted symbols included: yes/no; listing/delisting dates: yes/no
Licence basis:       <document, version, date>; LIC-1 reply ref: <ref or "none">; counsel: <ref or "none">
Scope granted:       exploratory, non-confirmatory research for <HR-04, HR-08, HR-13>; no redistribution;
                     no live use; retention <term>
Snapshot:            <content hash>, data-quality certificate <ref>, holdout_excluded=true
Conditions:          <e.g. no use beyond the named hypotheses; re-decision if the terms change>
Not granted:         confirmatory testing (D1/D2 HOLD), alpha consumption, Paper/live activation
```

## 8. Statement on data use

No unlicensed data has been used for HR-04 / HR-08 / HR-13. All engineering and tests so far run on data generated
inside the tests (`evidence_class="SYNTHETIC"`). No real market data will be read for this step until OD-DF-1 records
a dataset permission, the preregistration is accepted (RD-2) and the exploratory run is authorized
(`NEXT_LICENSED_DATA_STEP.md` §6). The code refuses non-synthetic input without a permission record
(`DatasetPermission` gate) and refuses a non-synthetic summary label without an authorization reference.
