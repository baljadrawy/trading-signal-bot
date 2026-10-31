# Defect Impact Assessment (ERG-01, workstream G3)

| Field | Value |
|---|---|
| Phase | ERG-01 Evidence Resolution Gate; documentation-only, read-only |
| Workstream | G3: impact of documented implementation defects on the evidence |
| Repository baseline | audit commit `5d977f2` (= `main` `eba90dd` plus the audit package) |
| Code versions read | `63da7d3` (research-freeze SHA), `ea8ae4f` (documented-deployed analyzer and signal_engine), `bb7825f` (documented-deployed telegram and trade_tracker), `eba90dd` (`main`), and the introducing commits found with `git log -S` / `-G` |
| Audit baseline | [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md) and [RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md](../../audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md) (2026-10-31 historical baseline) |
| Not done | no backtest, replay, simulation, trade reconstruction, P&L computation, data-file read, container or database access |

Evidence classes follow the ERG brief. Impact uses the G3 scale: **MEASURED** (an authorised measurement of realized effect exists), **MECHANICALLY INFERRED** (the effect follows from the code, but its size on realized trades has not been measured), **UNKNOWN** (neither the size nor the sign can be established within this phase).

A corrected defect is an engineering correction. Nothing in this document treats a correction as evidence that any strategy is, or would become, profitable.

---

## 1. Summary

| ID | Defect (audit IDs) | Present in source at | Runtime status | Mechanical consequence | Realized economic impact | Version identity |
|---|---|---|---|---|---|---|
| G3-01 | W3 self-referential T1 cap (HIS-30, STR-21, STR-17, CON-22, CON-33) | From `d922cfc` (2026-06-25, momentum setup) through `ea8ae4f`, incl. `63da7d3`; at `bb7825f` / `eba90dd` only as the default `legacy_window_v1` | Analyzer image documented at `ea8ae4f`, which has no switch (DOCUMENTED_ONLY, RT-16; image content NOT_VERIFIED, RT-17) | For every momentum signal the cap's "resistance" is the breakout bar's own high; when it binds, T1 sits between entry and 1R and can sit below the round-trip cost | **UNKNOWN**: frequency counts exist only in documents whose data window is not verified pre-freeze; the sign of the P&L effect is not mechanically determined | A correction is a geometry change and a declared strategy-version boundary |
| G3-02 | Alphabetical candidate truncation and lexical tie-breaks (UNI-16, UNI-17, HIS-28, STR-13) | Every commit from `2d11780` (2026-04-08) to `eba90dd`; never fixed | signal_engine image documented at `ea8ae4f` (DOCUMENTED_ONLY); `TIMEFRAMES=15m,4h,1d` is RUNTIME_VERIFIED (VER-06) | When more than 200 fresh rows exist, rows are cut by symbol name before any setup or ranking check; the cut is deterministic | **UNKNOWN**: how often the cut binds is NOT_VERIFIED; the only frequency observation in the record is from a post-freeze window and is not reproduced | A correction is a selection change and a declared strategy-version boundary; it falls outside the hashed contract sources |
| G3-03 | Same-bar re-fire on 4h/1d (HIS-25) | `63da7d3` through `eba90dd`; fix exists from `eb68e42` but only under `SIGNAL_INTEGRITY_MODE=enforce` | Mode unset, so code default `off` (VER-02, RUNTIME_VERIFIED) | One closed 4h/1d bar can be emitted again after each 2 h cooldown; signal-level n is inflated | **UNKNOWN** economically; the inflation of per-signal n is MECHANICALLY INFERRED | Enabling `enforce` is an integrity-mode change and a declared boundary |
| G3-04 | Stop slippage counted twice (HIS-31, CON-17, EXE-13, EXE-14) | `5792cd3` (2026-07-15) onward, incl. `63da7d3` and `bb7825f` | Cost settings unset, so code defaults 0.3 / 0.001 (VER-19, RUNTIME_VERIFIED) | A stop exit is charged about 0.40% instead of 0.30%; the post-T1 stop is also placed one slippage term higher | Direction **MECHANICALLY INFERRED** (conservative); realized size **UNKNOWN** | An accounting relabel alone changes no Paper behaviour; changing the break-even stop changes geometry and is a boundary |

Common findings:
- **G3-05.** Both primary defects are present in the research-freeze source `63da7d3` and in every later documented version. Paper evidence from this implementation therefore embeds the alphabetical cut since `2d11780` and W3 since the momentum setup (`d922cfc`), both before and after the freeze. Research replays use the same T1 rule (`shared/strategy_math.py:53,71-72 @ ea8ae4f · SOURCE_VERIFIED`), so Paper and replay are mutually consistent on W3. Consistency is not correctness. INFERRED.
- **G3-06.** No tracked Markdown document in the repository records a realized impact of either primary defect over a window shown to end before the 2026-08-19 research freeze (instant recorded in research_freeze.json). Every document that discusses W3 or the alphabetical cut was first committed on or after 2026-10-15 (`git log --diff-filter=A`). NOT_VERIFIED: no authorised measurement exists.
- **G3-07.** `freeze_strategy_contract_hash` is not a sufficient detector of these corrections. The hashed source list excludes both files that hold the primary defects (section 6). INFERRED from `research/foundation/contract.py:68-75 @ eba90dd · SOURCE_VERIFIED`.

---

## 2. Method and limits

- **Source reading.** `git show <commit>:<path>`, `git grep`, `git log -S` / `-G` / `--diff-filter=A` and `git merge-base --is-ancestor`. Line numbers are those of the named commit.
- **Documents.** Only tracked Markdown and governance files. The known post-freeze sections named in the brief were not used. Every count in A42 §B.3, A43 §A.2, A45 §A45-C and A46 §A46-C is treated as **count withheld (window not verified pre-freeze)**. None of these documents states a data window that ends before the freeze: A42 and A45 read the `signals` table at the time of writing (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L3-9 @ eba90dd`, `docs/a45/A45_SETUP_RESEARCH.md:L5-11 @ eba90dd` · DOCUMENTED_ONLY).
- **Arithmetic.** The thresholds in sections 3.4 and 4.4 are algebra on the code's own formulas and constants. They are not trade statistics and carry no frequency.
- **Runtime.** No code behaviour here is runtime-verified. Behaviour is SOURCE_VERIFIED at the documented commit. Image content parity is DOCUMENTED_ONLY (RT-16) and was not verified (RT-17). Environment values come only from the audit addendum (VER-xx · RUNTIME_VERIFIED).
- **Not opened.** `research/governance/contamination_registry.jsonl`, which the lab review package cites as recording W3 contamination (`docs/lab/REVIEW_PACKAGE_R1_QUANT.md:L13 @ eba90dd`). It is a JSONL artefact and is outside the brief's read scope. Its content is NOT_VERIFIED.

---
## 3. G3-01: W3 self-referential T1 cap (HIS-30, STR-21, STR-17)

### 3.1 Affected source versions

| Commit | Where | State | Class |
|---|---|---|---|
| `ad1654b` (2026-04-08) | `analyzer/technical_analyzer.py` | Introduces the `resistance * 0.99` cap ("prevent target_1 from being below entry"), first found with `git log -S"resistance * 0.99"`. No momentum setup exists yet. | SOURCE_VERIFIED |
| `d922cfc` (2026-06-25) | `analyzer/simple_entry.py` | Adds the momentum breakout setup (file creation, `git log --diff-filter=A`). From here the cap's window can contain the breakout bar. | SOURCE_VERIFIED |
| `63da7d3` (freeze SHA) | `analyzer/technical_analyzer.py:388-390, 442-446`; `analyzer/simple_entry.py:26-44` | Window `df.tail(20)` includes the decision bar; cap applied unconditionally; momentum breaks the prior 20-bar high | SOURCE_VERIFIED |
| `ea8ae4f` (documented-deployed analyzer) | `analyzer/technical_analyzer.py:409-411, 463-467` | Same rule, hard-coded, no switch; `a4a7561` is **not** an ancestor (`git merge-base --is-ancestor`) | SOURCE_VERIFIED |
| `a4a7561` (2026-10-20) | `shared/t1_cap.py` (new), `analyzer/technical_analyzer.py`, `shared/config.py`, `shared/strategy_math.py`, `shared/trade_geometry.py` | Adds `T1_CAP_POLICY`; default `legacy_window_v1` keeps the defect; `independent_swing_v1` = A46 G1. The commit message says "Not deployed" | SOURCE_VERIFIED |
| `bb7825f`, `eba90dd` | `analyzer/technical_analyzer.py:466-469`; `shared/config.py:121-124`; `shared/t1_cap.py:37-39, 66-74` | Contain `a4a7561`; the default reproduces the defect exactly | SOURCE_VERIFIED |

The research copy carries the same rule: `shared/strategy_math.py:53, 71-72 @ ea8ae4f · SOURCE_VERIFIED`. That file does not exist at `63da7d3` (`git cat-file -e` fails) · SOURCE_VERIFIED.

### 3.2 Code mechanism

At `ea8ae4f`, `_calculate_levels` (`analyzer/technical_analyzer.py:404-480 @ ea8ae4f · SOURCE_VERIFIED`):
1. `recent = df.tail(20)` and `resistance = max(recent.high)`. The window is the decision bar plus the 19 bars before it (L409-411).
2. Entry = the decision bar's close; for momentum and reversion the stop comes from `plan_signal_stop` (L432-443), and `risk = entry − stop` (L449).
3. `target_1 = entry + 1.0·risk`; T2 and T3 are 1.8R and 2.2R (L454-456).
4. If `target_1 > resistance > entry` and `0.99·resistance > entry`, then `target_1 = 0.99·resistance` (L463-467). T2 and T3 are not touched.

Momentum entry (`analyzer/simple_entry.py:26-44 @ ea8ae4f · SOURCE_VERIFIED`) requires `close > max(high of the prior 20 bars)`, which is `df.high.iloc[-21:-1]`, with `MOM_BREAKOUT_N` = 20 (`shared/config.py:76 @ ea8ae4f`; runtime unset, so default 20, VER-18 · RUNTIME_VERIFIED).

**G3-01a. Deterministic self-reference.** With N = 20, the 19 earlier bars of the cap window are a subset of the 20 prior bars, all with highs below the close, and the decision bar's high is at least its close. So, for **every** momentum signal, `resistance` equals the breakout bar's own high H. This holds whether or not the cap binds. INFERRED (algebra on SOURCE_VERIFIED code). It agrees with `shared/t1_cap.py:6-9 @ bb7825f` and A46 §A46-C item 5 (`docs/a46/A46_TRADE_GEOMETRY.md:L88-94 @ eba90dd · DOCUMENTED_ONLY`).

It is **not** look-ahead: H belongs to the closed decision bar (A46 L90 · DOCUMENTED_ONLY; consistent with the closed-bar handling in A45 W13).

For **reversion** the decision bar sits near the lower Bollinger band. The cap level then normally comes from earlier bars, and A46 reports that the defect does not apply (`docs/a46/A46_TRADE_GEOMETRY.md:L93 @ eba90dd · DOCUMENTED_ONLY`).

### 3.3 Intended behaviour

- The code comment states the intent: if T1 is above resistance, use the resistance level, but only if it is above entry (`analyzer/technical_analyzer.py:463 @ ea8ae4f · SOURCE_VERIFIED`, translated).
- A45 W3 calls the result a contradiction of "the cap's stated purpose (the recent resistance level)" and classifies it as a **CONFIRMED IMPLEMENTATION DEFECT** (logic vs intent). It adds: "The effect on P&L is not established" (`docs/a45/A45_SETUP_RESEARCH.md:L95 @ eba90dd · DOCUMENTED_ONLY`).
- A42 records the same point as "[D/H]": "the level was just broken, so it is not resistance" (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L129-131 @ eba90dd · DOCUMENTED_ONLY`). The severity labels disagree (CON-33 · CONTRADICTORY). Both documents agree on the mechanism.
- The corrected reference (A46 G1, `independent_swing_v1`) is the nearest confirmed swing high above entry among bars that closed **before** the decision bar; with no such level, T1 = 1R (`shared/t1_cap.py:10-11, 42-55 @ bb7825f · SOURCE_VERIFIED`). G1 is disabled in `shared/trade_geometry.py:13, 31 @ ea8ae4f · SOURCE_VERIFIED`.

### 3.4 Mechanical impact

Let C be the entry (the close), H the breakout bar's high and R the risk.

| Step | Statement | Class |
|---|---|---|
| Binding condition | The cap binds iff C/0.99 < H < C + R, i.e. the upper wick is above about 1.0101% of entry and below 1R | INFERRED (algebra on L463-467) |
| Necessary condition | R must exceed about 1.0101% of entry. The TF risk caps are 2% (15m), 5% (4h) and 3% (1d) (`analyzer/technical_analyzer.py:425 @ ea8ae4f`), so the cap can bind on all three runtime TFs. On 15m the admissible window for R is narrowest | INFERRED |
| Location of T1 | When binding, T1 = 0.99·H, inside (entry, entry + R); never at or below entry | INFERRED; agrees with A46 L91 · DOCUMENTED_ONLY |
| T1 below the tracker's round-trip charge | With the flat 0.30% charge (`FEE_ROUNDTRIP_PCT` 0.3, `shared/config.py:88-90 @ ea8ae4f`; VER-19), T1's gross gain is below 0.30% when H < C × 1.003 / 0.99, i.e. an upper wick between about 1.01% and 1.31% of entry | INFERRED (formula arithmetic, not a trade statistic) |
| Same, under A46's per-leg model | A46 reports the T1 path as net-negative whenever T1 < 0.275% (20 bps baseline) or 0.376% (30 bps), and "with the high within ≈1.29 % of entry, T1 is below net break-even" | HISTORICAL_REPORTED (`docs/a46/A46_TRADE_GEOMETRY.md:L72-79, L91 @ eba90dd`) |
| Post-T1 stop | After a T1 touch the stop moves to `min(T1, entry × (1 + 0.003)/(1 − 0.001))` (`shared/triple_barrier.py:92-96, 117-119 @ bb7825f`). When the capped T1 is below about entry × 1.004 (wick below about 1.41%), the protective stop for the remaining 75% is T1 itself, filled at T1 × 0.999 (`:320`) | SOURCE_VERIFIED (code); thresholds INFERRED |
| Partial exits | Admission writes `partial_25_50_25_v1` (`trade_tracker/main.py:883 @ bb7825f`), so the capped T1 governs a 25% leg and the stop of the 75% remainder | SOURCE_VERIFIED |
| Trailing floor | After T2 the trailing stop is floored at T1 (`shared/triple_barrier.py:113-116 @ bb7825f`), so a capped T1 also lowers that floor | SOURCE_VERIFIED |
| T2 / T3 | Unchanged by the cap | SOURCE_VERIFIED |

### 3.5 Running image versus documented source

- Analyzer and signal_engine are recorded as unchanged services on the `rel-ea8ae4f-r2` images (`deploy/VERSION_BOUNDARY.md:L27-28 @ eba90dd` · DOCUMENTED_ONLY; RT-16).
- `T1_CAP_POLICY` is unset in every service (VER-05 · RUNTIME_VERIFIED). The key exists only in `bb7825f` code, and the analyzer at `ea8ae4f` cannot read it (STR-17 · SOURCE_VERIFIED; CON-22 · CONTRADICTORY between `main` and the deployed analyzer source).
- That the running analyzer executes the `ea8ae4f` rule is DOCUMENTED_ONLY. Image file content was not hashed: NOT_VERIFIED (RT-17).
- Default rows under `bb7825f` carry no `t1_cap_policy` label (`analyzer/technical_analyzer.py:484-485 @ bb7825f`). A corrected version therefore cannot rely on row labels alone and needs a declared boundary. INFERRED.

### 3.6 Existing evidence of realized impact

- A42 §B.3 item 3 and A46 C1 report how many 4h and 15m momentum T1s the cap bound: **count withheld (window not verified pre-freeze)**. HISTORICAL_REPORTED.
- A45 W3 cites the A42 figure: **count withheld (window not verified pre-freeze)**.
- A46's median R values per TF, which A46 uses to argue the cap binds "rarely on 15m and often on 4h/1d": **count withheld (window not verified pre-freeze)**.
- No document estimates the effect on realized P&L. A45 W3 says so explicitly (L95). `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L18 @ eba90dd` classifies W3 as "Mechanism, not an outcome measurement" · DOCUMENTED_ONLY.
- Realized-impact evidence admissible here: **none**. NOT_VERIFIED.

### 3.7 Direction of bias versus measured impact

**Mechanically signed effects** (INFERRED):
- the T1 leg (25%) earns at most 0.99·H − C instead of 1R;
- the post-T1 protective stop and the post-T2 trailing floor are lower;
- on paths that touch the capped T1 and then reverse, the remainder can exit below the round-trip charge.

**Effects of the opposite sign** (INFERRED):
- a nearer T1 is reached on more paths and earlier;
- on each such path the stop moves from the original stop (−R) to about T1;
- so some paths that would have reached the original stop under a 1R T1 exit near entry instead.

**Net sign:** not determined by the mechanism. It depends on the path distribution, which needs outcome data that this phase may not read. **UNKNOWN.**

**Evidence-validity effect** (INFERRED): T1-touch rates, win counts and "protected" exits of momentum trades describe the capped geometry, not the designed 1R geometry. They are not comparable with a G1-corrected version or with any design whose T1 is 1R.

**Overall impact class for G3-01: MECHANICALLY INFERRED** for geometry; **UNKNOWN** for realized economics.

### 3.8 Version identity

- **G3-01b.** The defect is part of the frozen implementation (`63da7d3`). A correction alters frozen targets; A42 records it "not changed" for that reason (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L131 @ eba90dd` · DOCUMENTED_ONLY).
- Switching the policy is a declared strategy-version boundary that needs owner approval. This is stated in `shared/t1_cap.py:14-16 @ bb7825f`, in `shared/config.py:121-123 @ bb7825f` and in the `a4a7561` commit message · SOURCE_VERIFIED. It also follows from DFP §3 "geometry" (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L63 @ eba90dd`) and OOC §4 (`docs/governance/OWNER_OPERATING_CONTRACT.md:L36 @ eba90dd`) · DOCUMENTED_ONLY.
- The roadmap requires "a G1 correction spec as a **new strategy version**" (`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md:L62, L66 @ eba90dd` · DOCUMENTED_ONLY).
- The relation to `freeze_strategy_contract_hash` is in section 6.

---
## 4. G3-02: Alphabetical candidate truncation (UNI-16, HIS-28, STR-13)

### 4.1 Affected source versions

| Commit | Where | State | Class |
|---|---|---|---|
| before `2d11780` | `signal_engine/main.py` | `ORDER BY total_score DESC LIMIT 20` (score-ranked), shown as removed lines in the `2d11780` diff | SOURCE_VERIFIED |
| `2d11780` (2026-04-08, "multi-timeframe support with cross-confirmation") | `signal_engine/main.py` | Introduces `ORDER BY symbol, total_score DESC LIMIT 200`; the only commit found by `git log -S"LIMIT 200"` | SOURCE_VERIFIED |
| `7bf6214` (2026-08-17) | `signal_engine/signal_logic.py` | Introduces `_fixed_candidate_key` = (spread, −24 h quote volume, symbol, timeframe) | SOURCE_VERIFIED |
| `63da7d3` (freeze SHA) | `signal_engine/main.py:70-79`; `signal_engine/signal_logic.py:76-83` | Same query and same key | SOURCE_VERIFIED |
| `2edca45` (2026-09-27; the ancestor of `ea8ae4f`; the same change is `23dea90` on `feature/forward-instrumentation`) | `signal_engine/main.py:26-30, 39-53` | Add `SELECTION_LIMIT = 200` and the read-only `_v2_truncation` recorder; the query is unchanged | SOURCE_VERIFIED |
| `ea8ae4f`, `bb7825f`, `eba90dd` | `signal_engine/main.py:146-155`; `signal_engine/signal_logic.py:287-293` | Identical query at all three; **never fixed** (`git log --all -G` over `signal_engine/` finds no later change) | SOURCE_VERIFIED |

A replacement exists but is not wired in. `bounded_universe` is in `shared/candidate_selection.py:209 @ ea8ae4f` and `@ eba90dd`, and no file under `signal_engine/` references it at either commit (`git grep`) · SOURCE_VERIFIED.

### 4.2 Code mechanism

The query at `signal_engine/main.py:146-155 @ ea8ae4f · SOURCE_VERIFIED`:
- selects every `analysis_results` row with `signal_generated = false`, analysed within the last 30 minutes, whose symbol has no open trade;
- orders them by `symbol`, then by the legacy `total_score` descending;
- keeps the first 200 rows.

Then `find_best_signal_live` (`signal_engine/signal_logic.py:719-848 @ ea8ae4f · SOURCE_VERIFIED`):
1. drops rows without a `trade_type` (L755-759);
2. applies the spread, open-trade and 2 h symbol-cooldown filters (L760-800);
3. takes the `min` of `_fixed_candidate_key` over the remaining candidates (L848).

The analyzer upserts **one row per (symbol, timeframe)** and resets `signal_generated` on every analysis (`analyzer/main.py:165-174 @ ea8ae4f · SOURCE_VERIFIED`).

### 4.3 Intended behaviour

- The live selector's stated intent is a "fixed execution-quality ordering" over the eligible candidates (`signal_engine/signal_logic.py:288 @ ea8ae4f · SOURCE_VERIFIED`). Nothing in code or documents gives symbol name a role in that objective.
- The `ORDER BY symbol` clause arrived with multi-timeframe cross-confirmation (`2d11780`). A plausible reading is that it grouped one symbol's rows for the legacy confirmation path. INFERRED; no comment states it.
- A43 records the root cause as "Order chosen for convenience, not for the objective" (`docs/a43/A43_SIGNAL_INTEGRITY.md:L51 @ eba90dd` · DOCUMENTED_ONLY).
- The intended replacements are documented as follows (all DOCUMENTED_ONLY):
  - A42 backlog item 7, "deterministic, not alphabetical" (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L154 @ eba90dd`);
  - A43 `bounded_universe` and I-7 (`docs/a43/A43_SIGNAL_INTEGRITY.md:L144, L158 @ eba90dd`);
  - S3 next slice 2 (`docs/s3/S3_SIGNAL_SELECTION.md:L107-112 @ eba90dd`).

### 4.4 Mechanical impact

| Step | Statement | Class |
|---|---|---|
| Row budget | Each symbol contributes up to one row per runtime timeframe. With `TIMEFRAMES=15m,4h,1d` (VER-06), that is up to 3 rows | SOURCE_VERIFIED code; RUNTIME_VERIFIED TFs |
| Binding point | 200 = 3 × 66 + 2. Once more than 200 rows qualify, the first 66 symbols in sort order keep all their rows, the 67th keeps 2 rows, and every later symbol is cut. This matches UNI-17's "above about 66 symbols × 3 timeframes" | INFERRED (arithmetic) |
| Boundary symbol | Its surviving 2 rows are those with the higher **legacy** `total_score`, which the live selector does not use. Which timeframe of the boundary symbol survives is therefore set by an inactive score | INFERRED |
| 30-minute window | The scan interval is 300 s (VER-07), so up to about six scan cycles contribute rows. A symbol that has left the scanner's filter (for example its 24 h move falls below 1%) keeps its rows in the window for up to 30 min. The qualifying count can therefore exceed the size of the current scanner list | INFERRED |
| Slots spent before filtering | The SQL has no `trade_type`, spread or cooldown predicate. Rows with no setup and rows of cooled-down symbols use slots exactly like real candidates, and the setup check comes only after the cut | SOURCE_VERIFIED (L146-155 vs L755-800) |
| Determinism | The cut is the same in every cycle while the overflow lasts. Late-alphabet symbols are excluded systematically, not at random. Their rows remain `pending` because only symbols in the returned set are marked `evaluated` (`signal_engine/main.py:179-186 @ ea8ae4f`) | SOURCE_VERIFIED / INFERRED |
| Interaction with ranking | The selector returns the best-spread candidate among the alphabetically early subset, not among all fresh setups. A43's synthetic test shows a best-spread late-alphabet candidate that production never sees (`docs/a43/A43_SIGNAL_INTEGRITY.md:L149 @ eba90dd`, synthetic) | SOURCE_VERIFIED; DOCUMENTED_ONLY (test) |
| Lexical tie-breaks (D8) | The key ends in `(symbol, timeframe)` strings. One symbol's rows share spread and volume, because the order book is fetched once per symbol (`docs/a45/A45_SETUP_RESEARCH.md:L23 @ eba90dd`). So when a symbol has setups on several timeframes, Python string order `'15m' < '1d' < '4h'` picks the timeframe | SOURCE_VERIFIED (L287-293); INFERRED |
| Sort collation | Exact name order depends on the database collation, which was not read | NOT_VERIFIED |
| Capacity context | One signal per cycle; effective capacity 2 open trades (VER-12). Open-trade symbols are excluded inside the SQL, so open trades free slots | RUNTIME_VERIFIED / SOURCE_VERIFIED |

### 4.5 Running image versus documented source

- The signal_engine image is recorded at `ea8ae4f` (RT-16; `deploy/VERSION_BOUNDARY.md:L27 @ eba90dd` · DOCUMENTED_ONLY). Image content is NOT_VERIFIED (RT-17).
- The query text is identical at `ea8ae4f`, `bb7825f` and `eba90dd`, and differs at `63da7d3` only in indentation. Whichever of these the image holds, the defect is in it. INFERRED from SOURCE_VERIFIED reads.
- `EVIDENCE_V2_ENABLED` is `true` for signal_engine (VER-20 · RUNTIME_VERIFIED). The `_v2_truncation` recorder is therefore active and writes truncation records. Those records are post-freeze FORWARD_HOLDOUT material and were not read.

### 4.6 Existing evidence of realized impact

- A42 says the frequency "is not assessed here [U]" (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L118 @ eba90dd` · DOCUMENTED_ONLY).
- A43 D7 reports a truncation frequency and a current row count, but only for a window the document itself dates after the 2026-08-19 research freeze (`docs/a43/A43_SIGNAL_INTEGRITY.md:L51 @ eba90dd`). They are **not reproduced** here (OD-7; post-freeze counts).
- UNI-17 states the frequency is NOT VERIFIED. No pre-freeze measurement exists in any tracked Markdown document.
- S3 makes measurement conditional on authorisation (`docs/s3/S3_SIGNAL_SELECTION.md:L113 @ eba90dd` · DOCUMENTED_ONLY).
- Realized-impact evidence admissible here: **none**. NOT_VERIFIED.

### 4.7 Direction of bias versus measured impact

- **Known in sign** (INFERRED):
  - a deterministic coverage loss: the effective universe is a name-ordered prefix whenever the cut binds;
  - a timeframe preference among one symbol's rows (15m over 1d over 4h).
- **Not known in sign:**
  - **Economics.** Symbol names carry no mechanical link to returns. Any economic effect depends on how the excluded subset differs from the kept one, which needs data this phase may not read. **UNKNOWN.**
  - **Evidence validity.** When the cut binds, the Paper sample describes a sub-universe chosen by name, not the scanner universe declared in the contract. The direction of any resulting bias is **UNKNOWN**. Whether this happened before the freeze is **NOT_VERIFIED**.

**Overall impact class for G3-02: MECHANICALLY INFERRED** for selection mechanics; **UNKNOWN** for frequency and economics.

### 4.8 Version identity

- **G3-02a.** Replacing the cut, or changing the tie-break, changes which candidate is selected. DFP §3 names "selection" as a declared strategy-version boundary (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L63 @ eba90dd`). S3 states "Each changes behaviour, so each needs owner approval and a new Paper window" (`docs/s3/S3_SIGNAL_SELECTION.md:L112 @ eba90dd`). Both DOCUMENTED_ONLY.
- A43 says `bounded_universe` causes "no behaviour change below 200 rows" (`docs/a43/A43_SIGNAL_INTEGRITY.md:L250 @ eba90dd` · DOCUMENTED_ONLY). That is true of the cut. But whether a given period was below 200 rows is itself NOT_VERIFIED, so the change cannot be declared behaviour-neutral in advance. INFERRED.

---
## 5. Secondary defects

### 5.1 G3-03: Same-bar re-fire on 4h/1d (HIS-25)

| Field | Finding | Class |
|---|---|---|
| Affected versions | 2 h symbol cooldown since `4651e1e` (2026-05-11). Present at `63da7d3` (`signal_engine/signal_logic.py:154-168`), at `ea8ae4f` (`COOLDOWN_SQL`, `signal_engine/signal_logic.py:25-26`) and unchanged through `eba90dd` | SOURCE_VERIFIED |
| Mechanism | The analyzer re-upserts each (symbol, timeframe) row on every scan with `signal_generated = false` (`analyzer/main.py:165-174 @ ea8ae4f`). A closed 4h or 1d bar stays the latest bar for 4 h or 24 h, so the same bracket reappears. The only guard is the 2 h wall-clock cooldown (`signal_engine/signal_logic.py:417-431 @ ea8ae4f`). So one bar can be emitted again after each cooldown lapse. A 15m bar is shorter than the cooldown and cannot re-fire this way | SOURCE_VERIFIED / INFERRED |
| Intended behaviour | The cooldown's stated aim is to stop repeated signals on the same struggling coin (`signal_engine/signal_logic.py:418-422 @ ea8ae4f`, translated). It does not establish candle identity. A42 and A43 classify the re-fire as a defect (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L123-127`, `docs/a43/A43_SIGNAL_INTEGRITY.md:L45-46 @ eba90dd`) | SOURCE_VERIFIED / DOCUMENTED_ONLY |
| Fix status | The A44 signal identity and insert-once fix (`eb68e42`) is an ancestor of `ea8ae4f`. It acts only when `SIGNAL_INTEGRITY_MODE=enforce` (`signal_engine/signal_logic.py:730-737`; default `off`, `shared/config.py:118 @ ea8ae4f`). Runtime: unset, so `off` (VER-02) | SOURCE_VERIFIED; RUNTIME_VERIFIED (mode) |
| Running image | signal_engine documented at `ea8ae4f`; image content NOT_VERIFIED (RT-16, RT-17) | DOCUMENTED_ONLY |
| Realized evidence | A42 and A43 counts of repeated rows and of setups traded twice: **count withheld (window not verified pre-freeze)**. A42 notes that tracker admission of repeats "was not checked" (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L126 @ eba90dd`) | HISTORICAL_REPORTED |
| Direction vs measured | **Signed for inference:** per-signal statistics over 4h/1d count one setup more than once. That inflates n and understates dependence (INFERRED). **Economic sign:** UNKNOWN; where a repeat is traded, it doubles exposure to one setup | INFERRED / UNKNOWN |
| Impact class | **MECHANICALLY INFERRED** (evidence validity); **UNKNOWN** (economics) | — |
| Version identity | Switching to `enforce` is an "integrity mode" change, a declared boundary under DFP §3 (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L63 @ eba90dd`). `SIGNAL_INTEGRITY_MODE` is not a field of the hashed contract (section 6) | DOCUMENTED_ONLY / INFERRED |

### 5.2 G3-04: Stop slippage counted twice (HIS-31, CON-17)

| Field | Finding | Class |
|---|---|---|
| Affected versions | `modeled_stop_exit` and `STOP_SLIPPAGE` introduced in `5792cd3` (2026-07-15). The config comment linking the two arrived with `1d090be` (2026-07-29). Present at `63da7d3` (`shared/config.py:76-78, 93`; `shared/triple_barrier.py:308-322`), `ea8ae4f` (`shared/config.py:88-90, 105`) and `bb7825f` / `eba90dd` (`shared/config.py:92, 107`, the lines EXE-13 cites) | SOURCE_VERIFIED |
| Mechanism | A stop exit is filled at `stop × (1 − 0.001)` (`shared/triple_barrier.py:320 @ bb7825f`). Net P&L then subtracts the flat 0.30% (`trade_tracker/main.py:409-416 @ bb7825f`; `shared/fees.py:41-74`, EXE-14), and that 0.30% already includes about 0.1% slippage (`shared/config.py:88-90 @ ea8ae4f`). The same pair of terms sets the post-T1 stop at `entry × 1.003 / 0.999` (`shared/triple_barrier.py:92-96 @ bb7825f`) | SOURCE_VERIFIED |
| Intended behaviour | The config comment describes 0.3 as "0.1%/side fee + ~0.1% slippage … consistent with STOP_SLIPPAGE=0.1%", i.e. one slippage allowance. The repository's own decomposition says stop slippage "is charged twice" (`shared/execution_calibration.py:349-357 @ bb7825f`) | SOURCE_VERIFIED |
| Fix status | Not changed in production accounting. A47 classifies it as "MODEL ASSUMPTION (conservative), not changed" (`docs/a47/A47_EXECUTION_REALISM.md:L67-71 @ eba90dd`). The research ledger `a48-cost-v1` counts slippage once (`docs/a48/A48_REPLAY_FIDELITY.md:L142-147 @ eba90dd`) | DOCUMENTED_ONLY |
| Running image | Cost settings unset, so defaults 0.3 / 0.001 (VER-19 · RUNTIME_VERIFIED). Tracker image documented at `bb7825f` (RT-16 · DOCUMENTED_ONLY) | — |
| Realized evidence | A47's example is arithmetic: about 0.098% double-counted on a full stop exit at 0.98 × entry (L67). No pre-freeze realized total is recorded | HISTORICAL_REPORTED / NOT_VERIFIED |
| Direction vs measured | **Accounting:** conservative. Reported net P&L on stop paths is lower, by up to about 0.1 pp of the stopped fraction, never higher (INFERRED). **Geometry:** the post-T1 stop sits about one slippage term higher than a single-count rule would place it; the P&L sign of that is not determined (UNKNOWN) | INFERRED / UNKNOWN |
| Impact class | **MECHANICALLY INFERRED** (direction of the accounting bias); **UNKNOWN** (realized size) | — |
| Version identity | A ledger relabel changes no Paper behaviour. A change to the break-even stop changes geometry and is a boundary (DFP L63). `roundtrip_cost` and `stop_slippage` are explicit contract fields (`research/foundation/contract.py:54-58, 89-90 @ eba90dd`), so changing either changes the contract hash | DOCUMENTED_ONLY / SOURCE_VERIFIED |

---

## 6. Version identity and `freeze_strategy_contract_hash`

### 6.1 What the freeze record identifies

- `research/governance/research_freeze.json @ eba90dd` records `freeze_git_sha` `63da7d3`, `freeze_git_dirty` true, a `freeze_strategy_contract_hash` (value not reproduced), and partition and holdout policy versions 1.0.0 · SOURCE_VERIFIED.
- The builder sets `strategy_contract_hash = contract_hash(current_contract())` (`research/data_governance/build_freeze.py:60, 86-88 @ eba90dd` · SOURCE_VERIFIED).
- `current_contract()` (`research/foundation/contract.py:15-104 @ eba90dd` · SOURCE_VERIFIED) hashes two things:
  - explicit fields: universe, entry, regime, stop, targets (R multiples, fractions 0.25/0.50/0.25, `t1_resistance_cap_factor` 0.99), position, cost and risk;
  - `logic_sources`: SHA-256 digests of nine files, namely `analyzer/simple_entry.py`, `shared/regime.py`, `shared/signal_stop.py`, `shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `shared/strategy_math.py`, `scanner/scanner_logic.py` and `signal_engine/signal_logic.py` (L68-75).
- `research/foundation/contract.py` and `shared/strategy_math.py` do not exist at `63da7d3` (`git cat-file -e`). `contract.py` was first committed in `d221514` (2026-09-27). So the recorded hash was computed on a dirty tree descended from `63da7d3`, and it cannot be reproduced from `63da7d3` alone. INFERRED from SOURCE_VERIFIED facts.

### 6.2 Coverage of each correction by the hash

| Correction | Files or settings it would change | In the hashed contract? | Consequence | Class |
|---|---|---|---|---|
| G3-01 via `T1_CAP_POLICY=independent_swing_v1` | env key; `analyzer/technical_analyzer.py`; `shared/t1_cap.py` | **No.** The key is not a contract field, and neither file is in `logic_sources`. The 0.99 factor is unchanged | A recomputed hash would not register the switch | INFERRED |
| G3-01 code path (`a4a7561` itself) | also edits `shared/strategy_math.py` | **Yes** (`logic_sources`) | Source at `bb7825f` / `eba90dd` hashes differently from pre-`a4a7561` source even under the legacy default | INFERRED; NOT_VERIFIED by recomputation (it would need repository code to run) |
| G3-02 cut (`ORDER BY symbol … LIMIT 200`) | `signal_engine/main.py` | **No** | A recomputed hash would not register the fix | INFERRED |
| G3-02 tie-break (D8) | `signal_engine/signal_logic.py` | **Yes** | The hash changes | INFERRED |
| G3-03 `enforce` mode | env key | **No** | The hash would not register it | INFERRED |
| G3-04 cost or break-even change | contract `cost` fields; `shared/triple_barrier.py` | **Yes** | The hash changes | INFERRED |

**G3-08.** The contract hash is therefore neither a sufficient nor a complete test of "same strategy version" for these corrections. Two of the three primary-defect corrections (the T1 policy switch and the selection cut) are invisible to it. Version identity must come from declared boundaries, which the governance documents require. INFERRED.

### 6.3 Governance rules that apply

- **OOC §4.** "Significant Paper strategy changes create explicit version boundaries and require operational approval for activation; never retroactively attribute prior outcomes to a new version" (`docs/governance/OWNER_OPERATING_CONTRACT.md:L36 @ eba90dd` · DOCUMENTED_ONLY).
- **DFP §3.** "Behaviour changes to Paper (geometry, selection, integrity mode) are declared strategy-version boundaries" (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L63 @ eba90dd` · DOCUMENTED_ONLY). G3-01 is geometry, G3-02 is selection and G3-03 is integrity mode.
- **Boundary record.** Entries are append-only. Trades from different versions are never pooled without stratification, and no outcome is attributed retroactively to a later version (`deploy/VERSION_BOUNDARY.md:L3-5 @ eba90dd` · DOCUMENTED_ONLY).
  - The one existing entry concerns the economic-halt policy only.
  - Its lineage note records that `T1_CAP_POLICY` is present in `bb7825f` config and unused by the services it covers (L24-26).

**G3-09.** Each correction of G3-01, G3-02 or G3-03 defines a new strategy version that is not the frozen strategy.
- All evidence collected so far, before and after the freeze, belongs to the defective implementation, and stays attributed to it.
- The corrected version starts with no outcome evidence of its own.
- A correction is not evidence of an edge (`shared/t1_cap.py:14-16 @ bb7825f`; A43 `docs/a43/A43_SIGNAL_INTEGRITY.md:L261 @ eba90dd`).
- Whether a corrected version is admitted to any test is an owner decision, outside this document.

INFERRED from the rules above.

---
## 7. NOT VERIFIED items

| ID | Question | Blocker |
|---|---|---|
| G3-NV-01 | Do the running analyzer, signal_engine and trade_tracker images contain the source read here? | Image filesystem content was not hashed; that needs authorisation (RT-17) |
| G3-NV-02 | How often did the W3 cap bind on pre-freeze signals, and with what realized effect? | No pre-freeze measurement in tracked Markdown. The A42, A45 and A46 counts are from windows not verified pre-freeze. Outcome reads are outside this phase |
| G3-NV-03 | How often did the 200-row cut bind before the freeze? | The only frequency observation is post-freeze (A43 D7). Pre-freeze rows or decision records would need a data read |
| G3-NV-04 | Exact symbol sort order of `ORDER BY symbol` | Database collation not read (no database access) |
| G3-NV-05 | Does a contract hash recomputed from `ea8ae4f`, `bb7825f` or `eba90dd` equal `freeze_strategy_contract_hash`? | Recomputation would run repository code (`research/foundation/contract.py`), which the brief forbids |
| G3-NV-06 | What `research/governance/contamination_registry.jsonl` records about W3 | JSONL artefact; outside the read scope |
| G3-NV-07 | Did the tracker admit same-bar repeats before the freeze? | A42 says it was not checked. Lifecycle data would need a read |
| G3-NV-08 | The rationale for `ORDER BY symbol` in `2d11780` | No code comment or document states it; the reading in section 4.3 is INFERRED |

## 8. Inconsistencies and notes

| ID | Observation | Class |
|---|---|---|
| G3-10 | W3 severity: A42 "[D/H]" (L129) vs A45 "CONFIRMED IMPLEMENTATION DEFECT" (L95). Both agree on the mechanism | CONTRADICTORY (= CON-33) |
| G3-11 | `main` and `bb7825f` carry `T1_CAP_POLICY`, but the documented-deployed analyzer source `ea8ae4f` does not. So `main` does not describe the analyzer's T1 behaviour, and the flag cannot change the running analyzer as documented | CONTRADICTORY (= CON-22) |
| G3-12 | Break-even T1 threshold: A46 reports about 1.29% of entry under its per-leg 20 bps model. The tracker's flat 0.30% gives about 1.31% (section 3.4). These are different cost models, not a contradiction | INFERRED |
| G3-13 | `shared/config.py` line numbers drift by commit: `FEE_ROUNDTRIP_PCT` is at L78 (`63da7d3`), L90 (`ea8ae4f`) and L92 (`bb7825f`, `eba90dd`). EXE-13's L92 and L107 refer to the later commits. Consistent once the commit is named | SOURCE_VERIFIED |
| G3-14 | The audit's descriptions of HIS-30 / STR-17 / STR-21, UNI-16 / HIS-28 / STR-13, HIS-25 and HIS-31 match the source read at the named commits. HIS-30's `shared/config.py:124` default at `bb7825f` and `main` was confirmed. No divergence from the audit baseline was found | SOURCE_VERIFIED |
| G3-15 | The A42 data-read row says no outcome table was joined (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L9 @ eba90dd`), yet A42 also reports counts with no stated window end. The counts are geometry counts, not outcomes, but their window is still not shown to be pre-freeze; hence they are withheld | DOCUMENTED_ONLY |

## 9. Repository sources

- **Audit baseline:** [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md) (STR-13, STR-17, STR-21, UNI-16, UNI-17, HIS-25, HIS-28, HIS-30, HIS-31, RT-16, RT-17, RT-37, CON-17, CON-22, CON-33, EXE-13, EXE-14); [RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md](../../audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md) (VER-02, VER-05, VER-06, VER-07, VER-12, VER-18, VER-19, VER-20).
- **Research records:**
  - [A42](../../a42/A42_STRATEGY_SIGNAL_QUALITY.md), [A43](../../a43/A43_SIGNAL_INTEGRITY.md), [A45](../../a45/A45_SETUP_RESEARCH.md), [A46](../../a46/A46_TRADE_GEOMETRY.md);
  - [A47](../../a47/A47_EXECUTION_REALISM.md), [A48](../../a48/A48_REPLAY_FIDELITY.md);
  - [S3](../../s3/S3_SIGNAL_SELECTION.md), [Strategy Evolution Roadmap](../../strategy/STRATEGY_EVOLUTION_ROADMAP.md), [S4 Phase 1 comparison](../../strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md).
- **Governance:** [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [Version boundaries](../../../deploy/VERSION_BOUNDARY.md), `research/governance/research_freeze.json`.
- **Code (read with `git show` at the named commits):**
  - analyzer: `analyzer/technical_analyzer.py`, `analyzer/simple_entry.py`, `analyzer/main.py`;
  - signal_engine: `signal_engine/main.py`, `signal_engine/signal_logic.py`;
  - shared: `shared/t1_cap.py`, `shared/config.py`, `shared/triple_barrier.py`, `shared/strategy_math.py`, `shared/trade_geometry.py`, `shared/candidate_selection.py`, `shared/execution_calibration.py`;
  - other: `trade_tracker/main.py`, `research/foundation/contract.py`, `research/data_governance/build_freeze.py`.
