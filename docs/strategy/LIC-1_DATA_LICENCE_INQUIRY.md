# LIC-1 — Data licence inquiry for HR-04 / HR-08 (DRAFT for owner review, NOT SENT)

**Status: DRAFT – NOT SENT (D0).** Written 2026-10-27 on `research/variant-ledger` (PR #94); revision 3 adds the
owner approval block (§A) and the reply decision table (§B), and corrects the disclosure facts (§9); revision 4
(2026-10-27) records the repository visibility change in row L3 and rewords question 7 as historical. Nothing in this
file has been sent to anyone, and no data has been downloaded, opened or read to write it. It authorizes nothing: no
dataset permission, no ledger registration, no alpha, no window. Sending it is the owner's decision (roadmap RD-5,
R9; policy OD-DF-1). Claude does not send it, does not create e-mail drafts, and does not contact Binance or anyone.

*Not legal advice.* This file records what earlier source reviews found and lists the questions to confirm. It does
not draw legal conclusions, and nothing in it is a clearance.

## A. Owner approval block (tick before sending)

> **Visibility note (revision 4).** `baljadrawy/trading-signal-bot` was verified **public** on 2026-10-27 (about
> 16:00Z) and verified **private** on re-check the same day (about 17:00Z, and again at 17:07Z for this revision,
> `gh api repos/baljadrawy/trading-signal-bot --jq .private` → `true`). See row L3 for what this does and does not
> resolve. Still do not add your name, e-mail, account ID or other personal details to this file: visibility can
> change again and earlier history may already have been copied. Fill the placeholders only in the copy you send.

| # | Item | Draft value (from records) | Owner tick / edit |
|---|---|---|---|
| L1 | **Licensee** | The owner as an **individual, personal use**. No company or other legal entity (owner-confirmed 2026-10-27) | [ ] confirmed |
| L2 | **Disclosure of earlier Vision downloads** | ~596 Binance Spot USDT symbols, 15m/1h/4h/1d monthly kline archives, 2017-08 → 2026-05, checksum-verified. Downloaded 2026-06-24/25 (1h/4h/1d batch, 74,397 files) and 2026-08-19 (15m, 24,799 files), all **before** the Vision Dataset Terms appeared (site 2026-08-28, GitHub 2026-09-30). **Used** in earlier private research from 2026-06-24 to 2026-10; **kept unused from 2026-10-27**; not deleted (§9) | [ ] accurate  [ ] 4h download date confirmed |
| L3 | **Repository-visibility facts** (decide whether and how to disclose) | **Verified facts:** the repository was **public** at least until the check of 2026-10-27 about 16:00Z (the start of the public period is not recorded here) and was **private** at the re-check on 2026-10-27 about 17:00Z (re-confirmed 17:07Z). **Content:** (a) research reports with aggregate statistics computed from the downloaded data (no raw Vision archive files are tracked: `bt_data/` is git-ignored); (b) **368 cached OHLC/kline pickle files (~49 MB, about 240 USDT symbols, 1h/4h/1d) under `analyzer/research/cache/`**, committed 2026-06-13 (`f1ac14a`), i.e. before the Vision downloads; (c) this draft and its disclosure (§9) on the PR #94 branch. **Resolved by the change:** this draft, the disclosure and (a)–(b) are no longer publicly readable. **Not resolved:** the earlier exposure: while public, the history (including (a)–(c)) may already have been read, cloned or cached by third parties, and making the repository private does not undo that; and the provenance of the 368 pickle files is **still unverified** (the scripts that use the folder fetch from `api.binance.com/api/v3/klines`, REST API option B, so they are probably not Vision files, but the files were **not opened**) | [ ] include optional Q7 (historical wording)  [ ] or leave it out / take counsel first. Nothing is removed, rewritten or re-published by Claude |
| L4 | **Earlier non-Vision data** | Studies before 2026-06-24 (e.g. the edge scan ending 2026-05-22, A18 S02) cannot have used these archives. Their data source is not established in the records reviewed here (probably the REST API) | [ ] mention / [ ] leave out (the REST API is governed by the Terms of Use, not the Vision terms) |
| L5 | **Questions** | Message questions 1–8 in §5 (map in §4). Delete any you do not want to ask | [ ] approved as listed |
| L6 | **Terms version** | Vision Dataset Terms v1.0, "Last Updated: August 26, 2026", as recorded 2026-10-12 (A22). **Re-check the current version on the day of sending**; if it changed, update the subject line and §3 | [ ] re-checked on ____ |
| L7 | **Channel** | **Owner to confirm.** No official data-licensing contact for `data.binance.vision` is documented in the repository, and A22 (S6) found no public commercial-licence channel. Options to evaluate: Binance customer support from the owner's own account, asking to route the message to the Binance Vision dataset owner (the terms name Nest Exchange Limited, ADGM); or an institutional / data contact if the owner has one. **Not** a public GitHub issue | [ ] channel: ____ |
| L8 | **Send date and follow-up** | Owner sends from their own account. Follow-up after 30 days without reply; treat as "no reply" after 60 days (§B) | [ ] sent on ____  [ ] follow-up due ____ |
| L9 | **Record** | Keep the sent text and any reply in the owner's own records. In the repository, record only a reference (date, channel type, "reply received yes/no") in OD-DF-1 (§7), no personal data | [ ] |

Until every row is ticked, the status stays **DRAFT – NOT SENT** and the licence status stays **NOT CLEARED**.

## B. What happens after a reply (decision table)

Gates are those of `NEXT_LICENSED_DATA_STEP.md` §6: **G-DATA** (dataset permission, OD-DF-1), **RD-2**
(preregistration accepted), **X-AUTH** (scientific authorization of the single exploratory look), **G-SCI** (governed
confirmation; D1/D2 HOLD) and **G-OPS** (Paper activation). No reply outcome lifts the D1/D2 HOLD, opens a protected
holdout, or allows live trading: the project stays PAPER_ONLY whatever the licensor says.

| Outcome | How it is recognized | Gate effect | Existing Vision files | Next action |
|---|---|---|---|---|
| **Permitted** | Written reply that personal research **including strategy selection for paper testing** is permitted (questions 1–2), with the terms named; derived data may be kept privately (question 4) | G-DATA may be opened: owner records OD-DF-1 GRANTED citing the reply; then RD-2 → X-AUTH. G-SCI and G-OPS unchanged | Usable **only** if the reply also covers pre-terms copies (question 6) **and** OD-DF-1 names them; otherwise a fresh copy is needed, under a separate owner approval for acquisition | `NEXT_LICENSED_DATA_STEP.md` §7 stage X1 |
| **Permitted with restrictions** | Reply allows some uses and not others (e.g. research yes, selection for later personal trading no; attribution / share-alike required; retention limit; existing copies not covered) | OD-DF-1 GRANTED **with conditions that mirror the restriction**. A use outside the conditions is not permitted. If selection for paper testing is excluded, X-AUTH cannot be granted for HR-04/HR-08/HR-13 | As the reply says; by default stay unused | Owner reviews whether the remaining scope still serves stage X1; attribution added to reports if required; question 7 answer (if asked) applied to the repository and its history |
| **Commercial / enterprise licence required** | Reply points to §3.4 enterprise licence or a paid product | G-DATA stays closed for Vision until a licence is signed | Unused | Owner decides cost; or fallback (`NEXT_LICENSED_DATA_STEP.md` §9) |
| **No reply** | 30 days after sending → one follow-up; 60 days after sending → "no reply" | G-DATA stays closed. **Silence is not permission** | Unused | Owner chooses: counsel; or an explicit, recorded risk acceptance limited to personal, non-production research (A22 LIC-2 (c)), which can never lead to live use; or fallback §9 |
| **Ambiguous reply** | Reply does not answer questions 1, 2 or 6 | Treated as **no reply** for gate purposes | Unused | Follow-up asking the unanswered questions |
| **Refused** | Reply says the intended use is not permitted | OD-DF-1 DENIED for Vision | Stay unused; retained or deleted **as the reply requires** (a licensor instruction overrides the default "keep as evidence") | Owner reviews earlier derived material in the repository and its history, including the period it was public (question 7); fallback `NEXT_LICENSED_DATA_STEP.md` §9 |

## 0. Relation to the earlier draft (reused, not duplicated)

The first LIC-1 draft is A22 §3–§4 (`docs/audits/2026-10-12/A22_P2_H1_PRE_EXECUTION_READINESS.md`, local commit
`8cb5c9e` on the held branch `feature/mi-am4a-stage-b-prep-20261011`; **not on `main`**). It was written for P2-H1
(Vision 1h/1d/15m archives) and also proposed LIC-2 (licence basis for running P2-H1). This file **supersedes the A22
inquiry text for the HR-04 / HR-08 step**. It keeps A22's source findings (quoted as recorded on 2026-10-12 and **not
re-verified here**: no network access was used) and adds the point-in-time universe, delisted symbols, the pre-freeze
window and vendor options. The message in §5 now covers all five A22 questions (A22 1 → message 6, A22 2 → 1 and 2,
A22 3 → 3, A22 4 → 4, A22 5 → 8).

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

Not needed: order book, trades, funding, futures, intraday bars, account or personal data. The archives already on
disk end in 2026-05, so even a permission that covers them leaves 2026-06-01 → 2026-08-18 to be acquired under the
confirmed terms (separate owner approval).

## 3. Source options and what each is recorded to permit

The cells below summarize earlier reviews (A18/A19 2026-10-11, A22 2026-10-12). They are **as recorded, not
re-verified**, and every one ends in a question for §4 or for the vendor.

| Option | Recorded terms (summary) | What it appears to allow | Open questions |
|---|---|---|---|
| **A. Binance public data** (`data.binance.vision`, "Binance Vision Dataset Terms" v1.0, last updated 2026-08-26, CC BY-NC-SA 4.0 basis) | §4.1 permitted uses include "algorithmic historical backtesting for purely personal non-production research"; §3.4 "commercial utilization requires a separate, written enterprise data license"; §2.4 derived data governed by the terms; §4.2 no live proprietary trading execution with the Datasets; §4.3–4.5 no commercial exploitation or hosting; §1.4 amendments do not affect datasets already downloaded. A22 noted the on-site PDF metadata title began "[Draft]" | personal, non-production, non-commercial research; derived data kept private | whether this project's research counts as "purely personal non-production"; whether delisted-symbol archives are complete; status of copies downloaded before the terms were published (A22 §3.3 item 1) |
| **B. Binance REST market-data API** (`/api/v3/klines`, `exchangeInfo`) under the Binance Terms of Use (snapshot "Last Updated: 10 October 2025") and the API terms | ToU cl. 22: licence "solely as necessary to allow you to receive the Binance Services for non-commercial personal or internal business use"; cl. 26(c): no resale or commercial purposes unless agreed in writing; cl. 26(i): no scripts "in any manner not purposely provided". API terms were not read first-hand (A22 S8) | possibly personal research use; a different and **also unconfirmed** basis | whether bulk historical download of klines for research is a purpose "purposely provided"; whether delisted symbols are retrievable at all through the API (they usually leave `exchangeInfo`) |
| **C. Commercial vendor** (e.g. Kaiko, CoinAPI, Tardis.dev, Amberdata, CryptoCompare/CCData) | written commercial licence; terms and prices not reviewed | typically explicit research and internal-use rights, scope per contract | per vendor: research use by an individual for possible personal trading, retention after termination, derived data, delisted-symbol coverage, survivorship-free universe, cost |
| **D. No historical data** (prospective only, collector via API) | n/a | avoids the question at the cost of time | power: a forward year cannot confirm a realistic effect (HR-04 power note) |

Copies of Vision archives on the research host from earlier work (§9) are **not** covered by any
`DatasetPermission`, were not opened for this draft and must not be used until OD-DF-1 records a permission naming
them.

## 4. Questions the inquiry must answer (to confirm, not assumed)

| Internal ID | Topic | Message question (§5) |
|---|---|---|
| Q1 + Q8 | **Personal research.** Is private historical backtesting and statistical analysis by an individual (no third parties, no compensation, no redistribution, no signals) "purely personal non-production research" under §4.1? | 1 |
| Q1 (2nd part) | **Strategy selection / qualification.** Is it still permitted when the purpose is to decide whether a strategy merits **paper** (simulated) forward testing that uses only live API data? | 2 |
| Q5 + Q9 | **Later use of a selected strategy.** If such a strategy were later traded by the individual with own funds (no clients, no service) using only live API data, is that "live proprietary trading execution" (§4.2)? If so, which licence is needed? | 3 |
| Q3 | **Derived data.** May private derived data (indicators, universe lists, returns, reports, models) be kept indefinitely, also after a licence ends? Attribution / share-alike if never distributed? | 4 |
| Q4 | **Coverage.** Does the dataset include delisted pairs and their listing / delisting dates for 2019-01-01 → 2026-08-18? | 5 |
| Q6 | **Earlier downloads.** Which terms govern the copies downloaded before the terms were published, may they be kept and used for the above, and does anything need to be done about their earlier use? | 6 |
| Q10 (optional, L3) | **Earlier public repository.** The repository was public for a period and is now private. Was that period compatible with the terms (aggregate statistics; separately, REST API kline caches), and is any step needed now (e.g. removal from history)? | 7 |
| Q7 | **Commercial path.** If any use needs an enterprise licence: contact, scope, indicative cost | 8 |
| Q2 | Individual vs business entity | **Resolved by the owner (L1): individual.** Not asked |

Redistribution is not asked about: the message states that none is intended.

## 5. Inquiry text (English, for the owner to send; placeholders only)

Channel: **owner to confirm** (§A row L7). Adapt the greeting if a vendor is approached instead (option C).

> **Subject:** Request for written clarification — Binance Vision Dataset Terms (v1.0, last updated 26 August 2026):
> personal research use by an individual
>
> Dear Binance Vision / Data Licensing team,
>
> I am a private individual, writing on my own behalf (not for a company). I would be grateful for a written answer
> on how I may use Binance Spot historical market data for personal research.
>
> **Earlier downloads (disclosure).** On 24–25 June 2026 (1h, 4h and 1d) and 19 August 2026 (15m) I downloaded
> monthly Spot kline archives for about 596 USDT pairs, covering August 2017 to May 2026, from data.binance.vision,
> and verified them against the published checksums. Both dates were before the Vision Dataset Terms appeared on the
> site (28 August 2026) and on GitHub (30 September 2026). I used these files in my own private research
> (backtests and statistical studies) between June and October 2026. I have not shared or redistributed the archive
> files. Since 27 October 2026 I have stopped using them until I receive your answer; I have kept them unchanged.
>
> **Intended use.** Personal, non-production research only: testing a small number of predefined trading-strategy
> hypotheses on daily (1d) Spot USDT klines from 1 January 2019 to 18 August 2026, including pairs that have since
> been delisted, and comparing them with simple buy-and-hold benchmarks. The results would be used only to decide
> whether a strategy deserves further **simulated (paper) testing**, which uses live Binance API market data, not
> the historical files. I do not provide commercial services, paid signals or client funds, and I will not
> redistribute, resell, host or publish the data or datasets derived from it.
>
> **Questions.**
> 1. Is this private backtesting and statistical analysis by an individual "algorithmic historical backtesting for
>    purely personal non-production research" under clause 4.1?
> 2. Is it still permitted when its purpose is to decide whether a strategy merits further paper (simulated)
>    forward testing that uses only live API data?
> 3. If I later traded such a strategy for my own personal investing (own funds, no clients, no commercial
>    service), using only live Binance API market data, would that be "live proprietary trading execution" under
>    clause 4.2? If it would, which licence would I need?
> 4. May I keep private derived data (indicators, universe lists, returns, research notes) indefinitely, including
>    after any licence ends? Do attribution or share-alike terms apply if nothing is distributed?
> 5. Do the datasets include delisted pairs, and is there a recommended source for listing and delisting dates?
> 6. Which terms govern the files I downloaded before the Dataset Terms were published? Does clause 1.4 apply to
>    them, may I keep and use them for the research described above, and is any step needed regarding my earlier
>    use of them?
> 7. [Optional, only if the owner ticks L3:] My research code and notes are kept in a GitHub repository that was
>    public for a period and is now private. It contains research reports with aggregate statistics computed from
>    the data (no archive files), and separately some cached klines that I believe were retrieved through the
>    public REST API. Was the earlier public period compatible with the terms, and is any step needed now, for
>    example removing some of this content from the repository history?
> 8. If any of these uses requires a commercial or enterprise data licence under clause 3.4, could you tell me the
>    contact, scope and indicative terms?
>
> Thank you for your help.
>
> Kind regards,
> [OWNER NAME — fill only in the sent copy]
> [OWNER CONTACT — fill only in the sent copy]

## 6. What we will and will not do with the data (commitments for the permission record)

**Will:** store one content-addressed, checksummed snapshot on the research host; verify data quality; compute the
pre-registered exploratory analysis of `NEXT_LICENSED_DATA_STEP.md` §4 through the research runner (CPU and memory
caps); keep derived results internally; record every use in the validation-usage log; delete or retain the data per
the licence's retention term (default proposal: retain while the permission is valid, delete within 30 days after it
ends unless the licence says otherwise).

**Will not:** redistribute, publish, resell, host or share the raw data or derived datasets; provide signals or data
to third parties; use the historical data in any live order execution (the project is PAPER_ONLY and holds no live
authorization); load any bar at or after the 2026-08-19 freeze instant; read any protected holdout; claim
profitability from an exploratory result. Because the repository was public for a period and its visibility can
change (§A row L3), results from licensed data are committed only as the reply allows (default: aggregate
statistics with attribution, never data tables).

## 7. Owner decision record template — OD-DF-1 (dataset permission)

Copy into `docs/governance/DEVELOPMENT_FIRST_POLICY.md` §7 (or the owner-decision register) when decided. A granted
permission becomes a `research/mechanisms/simulate.DatasetPermission(source, licence_cleared=True,
holdout_excluded=True, reference="OD-DF-1/<id>")`; any summary labelled other than SYNTHETIC must name it as
`authorization_ref` (`research/strategies/result_summary.authorize_label`).

```text
OD-DF-1/<id> — Dataset permission
Decision:            GRANTED | GRANTED WITH CONDITIONS | DENIED | DEFERRED
Decided by / date:   <owner>, <YYYY-MM-DD>
LIC-1 outcome (§B):  Permitted | Permitted with restrictions | Commercial licence required | No reply | Ambiguous | Refused
LIC-1 sent / reply:  <send date>, <channel type>; reply <date or "none">  (no personal data here)
Dataset:             <source option A/B/C>, <exact product / endpoint / vendor>, <fields>
Period:              <start> .. <end>  (end strictly before the 2026-08-19 freeze instant)
Universe coverage:   delisted symbols included: yes/no; listing/delisting dates: yes/no
Licence basis:       <document, version, date>; counsel: <ref or "none">
Earlier copies:      covered by this permission: yes/no (default no; stay unused)
Scope granted:       exploratory, non-confirmatory research for <HR-04, HR-08, HR-13>; no redistribution;
                     no live use; retention <term>; attribution <required/not required>
Snapshot:            <content hash>, data-quality certificate <ref>, holdout_excluded=true
Conditions:          <e.g. no use beyond the named hypotheses; re-decision if the terms change>
Not granted:         confirmatory testing (D1/D2 HOLD), alpha consumption, Paper/live activation
```

## 8. Statement on data use

No real market data has been used for HR-04 / HR-08 / HR-13. All engineering and tests so far run on data generated
inside the tests (`evidence_class="SYNTHETIC"`). This statement covers these three hypotheses only: earlier project
research **did** use the downloaded Vision archives (§9). No real market data will be read for this step until
OD-DF-1 records a dataset permission, the preregistration is accepted (RD-2) and the exploratory run is authorized
(`NEXT_LICENSED_DATA_STEP.md` §6). The code refuses non-synthetic input without a permission record
(`DatasetPermission` gate) and refuses a non-synthetic summary label without an authorization reference.

## 9. Licensee, intended use and disclosure facts (owner-confirmed 2026-10-27; corrected in revision 3)

- **Licensee:** the project owner as an **individual, for personal use**. No company or other legal entity is involved.
- **Purpose:** private cryptocurrency trading-strategy research, backtesting, statistical analysis and **Paper (simulated)
  trading**.
- **Not done:** no commercial services, no paid signals, no client funds, no redistribution or publication of market
  data or derived datasets. See §A row L3 for what the repository contains and when it was public.
- **Possible future personal investment use is disclosed** (message question 3). It is not planned or authorized.
  Live trading stays forbidden by the project's own rules, and any such use would need the provider's explicit
  permission first.

**Earlier Vision downloads** (A18 2026-10-11 and A22 §3.1 records, not re-verified):
- **What:** Binance Spot USDT klines at 15m, 1h, 4h and 1d for about 596 symbols, 2017-08 to 2026-05, from the public
  data archive, all files checked against the upstream checksums.
- **When downloaded:** 1h/4h/1d batch (74,397 files) on 2026-06-24/25; 15m (24,799 files + checksums) on 2026-08-19.
  A22 lists that batch as "1h / 1d"; A18 shows the same 74,397 files include 4h, so the owner confirms the 4h date
  (row L2). Both dates precede the terms' "Last Updated" date (2026-08-26), the on-site publication (2026-08-28) and
  the GitHub publication (2026-09-30). Before 2026-09-30 the repository README said only "Licence / MIT", which
  plausibly referred to the scripts.
- **Where:** the owner's private server only. 15m under the research data area; 1h/4h/1d in a `bt_data` folder inside
  the production checkout (A18 flagged this as a governance defect). `bt_data/` is git-ignored and was never in
  the repository, including while it was public (row L3).
- **How they were used:** in earlier private research **from 2026-06-24 (first download) to 2026-10**, including a
  9-year multi-symbol backtest, a 595-symbol ML daily study, falling-wedge and SMC studies, and the A18 inventory
  (A18 S03–S06). Revision 2 said "2026-05 to 2026-10"; that start date is corrected, because no Vision file existed
  locally before 2026-06-24. Studies before that date used other data (row L4).
- **Terms on record:** Vision Dataset Terms v1.0, CC BY-NC-SA 4.0 basis, §4.2 excludes "live proprietary trading
  execution". Re-check before sending (row L6).
- **From 2026-10-27, these files stay unused** for HR-04/HR-08/HR-13 or any other research until permission is
  confirmed and recorded as OD-DF-1. They are kept unchanged as historical evidence and are not deleted, unless a
  licensor reply requires otherwise (§B).

**Channel:** owner to confirm (row L7). The owner sends it from their own account. This draft has **not** been sent.
