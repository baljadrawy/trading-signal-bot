# Strategy Research Lab: architecture design (2026-10-20)

**Status: DESIGN FOR REVIEW. Not approved for implementation or deployment.** Owner-approved direction: shared immutable data, isolated strategy containers, reuse of the existing Paper engine, and per-strategy virtual accounts with fixed parameters.
- Labels: VERIFIED (checked in code/host, read-only), INFERRED, UNKNOWN.
- Baseline: `main` @ `1432a90`; deployed release `ea8ae4f` (schema 11).
- No production, Collector, dataset or account change was made.

## 1. Verified current state (Phase A)

| # | Area | Finding | Class |
|---|---|---|---|
| A1 | Paper engine | `trade_tracker` executes **bracket trades** from `signals`: entry → T1/T2/T3 partials (25/50/25), stop, break-even after T1, expiry policy per TF. No target-weight / rebalance order type | VERIFIED (`trade_tracker/main.py`, `shared/partial_exits.py`, `shared/triple_barrier`) |
| A2 | Account model | **None.** No `account_id`, `strategy_id`, balance, cash or reservation anywhere. Size is fixed at `TRADE_AMOUNT_USDT=50`; P&L = 50 × (weighted exit / entry − 1); capital is a nominal `RISK_CAPITAL_USDT=500` used only for exposure percentages | VERIFIED (`grep`, `shared/config.py:104,129`) |
| A3 | Tables | `signals`, `active_trades`, `trade_results`, `paper_entry_orders`, `risk_management`, `risk_recovery_events`, outbox. Unique per `signal_id` in `active_trades` / `trade_results` (`004`), `signals.setup_key` partial unique (`011`) | VERIFIED (`database/migrations/`) |
| A4 | Risk | Global: one loss-streak breaker over **all** `trade_results` (B3), one pause row, global exposure limits (gross 80 %, symbol 10 %, …) | VERIFIED (`shared/risk_management.py`, `shared/risk_epoch.py`) |
| A5 | Costs | Tracker: flat 0.30 % round-trip label, stop fill × (1 − 0.1 %). Research: `a48-cost-v1` (0.10 %/side + spread + slippage once). Lab tooling: `research/mechanisms/costs.py` (Draft #60) refuses discounted fees | VERIFIED |
| A6 | Fills | Paper fills fully at the observed price (`observed_price_v0`); no partial fills, no queue, no lot/tick rounding in Paper (A47) | VERIFIED (A47/A48 docs) |
| A7 | Raw data | `~/research-data/trading-signal-bot/raw` 2.9 GB, **49,600 files, all `rw-rw-r--` owned by `tradmin`** (the same user that runs every service). Integrity rests on manifests (`ds-*/raw_files.json`, `research_freeze.json` manifest hash), not on filesystem immutability | VERIFIED |
| A8 | Collector | Isolated compose project, own network `tsb-p2-forward-net`, writes `research-data/.../p2` (`drwx------`). Post-freeze market data belongs to the **FORWARD_HOLDOUT** partition (`docs/research_temporal_governance.md`) | VERIFIED |
| A9 | Holdout | `holdout_status.json` SEALED, look count 0; freeze 2026-08-19T09:33:46Z | VERIFIED |
| A10 | Research infra | `research/mechanisms` (#60, simulator with `DatasetPermission`), `research/power` (main), A48 replay modes, `research/data_governance` (content-addressed datasets), research-runner with quotas (REPORTED) | VERIFIED / REPORTED |
| A11 | Host | 12 cores, 23 GB RAM (about 10 GB free + cache), 499 GB disk free; bot services use < 0.8 GB; shared with wishlist, xsch, hermes, postgres | VERIFIED (`docker stats`, `free`, `df`) |
| A12 | PRs | #59 (T1 flag), #60 (S4 tooling), #62 (CHG-03), #63 (Phase 1): all **Draft, unmerged** | VERIFIED |

**Consequence (INFERRED).** "Reuse the existing Paper engine" is feasible only as an **extension** of `trade_tracker`. Three things must be added:
1. account-scoped ledgers;
2. a target-position order path, which TSMOM/XS need;
3. account-scoped risk.

Production behaviour must stay byte-identical.

## 2. Target architecture (minimal)

```
                 ┌──────────── read-only, permission-gated ────────────┐
raw/ (immutable) ─► certified snapshot ds-<hash> ─► ro bind mount ─────►│ backtest job (per strategy, ephemeral)
                                                                        │   writes: lab/workspaces/<strategy>/<experiment>/
Binance public market data (live) ─► lab price feed (engine) ──────────►│ shadow/forward strategy container
                                                                        │   writes: INSERT-only lab.signal_intents
                 └──────────────────────────────────────────────────────┘
lab.signal_intents ─► lab engine = trade_tracker image in LAB_MODE (separate service, separate DB `tsb_lab`)
                      validate → reserve → fill (shared a48-cost-v1 model) → account ledger
                      ─► lab.accounts / lab.orders / lab.positions / lab.fills / lab.ledger / lab.equity_daily
experiment registry (append-only, hash-chained) + evidence store (never deleted)
Production: trade_tracker + trading_signals DB: UNCHANGED (no schema 12, no new code path active)
```

| Mode | Data | Writes | Evidence class |
|---|---|---|---|
| 1. Historical backtest | pre-freeze certified snapshot only, read-only | own workspace | exploratory (all history is research-exposed) |
| 2. Shadow signals | live public data | intents marked `shadow`, never executed | prospective observation, no P&L |
| 3. Forward Paper | live public data | intents executed by the lab engine into its own account | prospective observation (P&L), **not confirmation** |
| 4. Scientific confirmation | prospective per Evidence Ladder (A29–A33) | governed protocol only | confirmatory; separate approval |

### 2.1 Isolation model

- **Strategy container:**
  - one image per strategy version, built from a shared lab base image;
  - `read_only: true`, distinct UID per strategy (not 1000), `cap_drop: ALL`, `no-new-privileges`;
  - `cpus` 0.5, `mem_limit` 512 MB, `pids_limit` 64, `restart: "no"`.
- **Network:** an egress allowlist covering Binance public REST/WS and the lab DB only, with no access to `shared_db_net` production DB credentials.
- **Lab DB (`tsb_lab`, new, same shared cluster or a dedicated container):** separate from `trading_signals`.
  - Per-strategy role `lab_s_<id>` with `INSERT` only on `signal_intents`.
  - Row-level security pins `strategy_id = current_user`; there is no read access to other strategies' rows.
  - The lab engine role owns the account tables.
- **Idempotency:** `signal_intents` unique on `(strategy_id, strategy_version, experiment_id, intent_key)`, with `intent_key` deterministic from the strategy's decision time and symbol. Fills are unique on `(order_id, fill_seq)`, and all ledger postings happen in one transaction with the fill.
- **No netting:** positions are keyed by `(account_id, symbol)`. Two accounts holding the same symbol are independent rows, and no cross-account query exists in the engine.

### 2.2 Proposed account rules (need owner approval; written as defaults)

| # | Rule | Proposal |
|---|---|---|
| R1 | Gross exposure cap | **Fixed 2,500 USDT nominal** (50 % of the initial 5,000), never rescaled by equity. Measured as Σ open-position **cost basis** plus Σ reserved notional of working orders. Mark-to-market growth never forces a sale |
| R2 | Order size | Target 500 USDT notional. Reduced to available cash minus reservations minus fees. Rejected if below the lab minimum of 50 USDT or below the exchange `minNotional`. No upsizing after profits |
| R3 | Positions | ≤ 5 open positions per account. At most one position per symbol per account (no pyramiding) unless the strategy spec declares it in advance |
| R4 | Cash reserve | The reserve of 2,500 at the start follows from R1. **Owner choice:** (a) a hard cash floor of 2,500, so capacity shrinks after losses, or (b) no floor beyond R1/R2. Default proposal: (a) |
| R5 | Fees | 0.10 % per side on executed notional, in USDT, no BNB; buy fee added to cost basis, sell fee deducted from proceeds; spread and slippage from `a48-cost-v1` tiers |
| R6 | Fills | Full fill at the observed price adjusted by modelled slippage (unchanged Paper model). Partial fills are **not** simulated. Orders whose notional exceeds a declared share of the observed top-of-book depth (e.g. 10 %) are flagged |
| R7 | Rebalancing | Target-weight strategies trade only when the position change is at least max(25 USDT, 10 % of the position). The threshold is fixed in the strategy spec |
| R8 | Equity | Equity = cash + Σ position quantity × mark. Daily snapshot at 00:00 UTC; realized and unrealized P&L kept separately |
| R9 | Terminal account | If equity < 1,000 USDT (proposal) the account freezes: no new orders, no replenishment, no reset, and the experiment is closed as `TERMINAL_LOSS` with its evidence retained |
| R10 | Production account | Unchanged: no schema migration on `trading_signals`; the production tracker never runs LAB_MODE code |

## 3. Data-access matrix

| Data | Backtest job | Shadow / forward strategy | Lab engine | Production services | Collector |
|---|---|---|---|---|---|
| `raw/` | ✗ (only via a certified snapshot) | ✗ | ✗ | ✗ | ✗ |
| Certified pre-freeze snapshot `ds-<hash>` | ro, only with a `DatasetPermission` | ✗ | ✗ | ✗ | ✗ |
| Post-freeze market data / Collector dataset (`p2`) | **✗ (holdout partition)** | ✗ | ✗ | ✗ | rw (own) |
| Live Binance public data | ✗ (no network) | ro | ro | ro | ro |
| `trading_signals` DB (production) | ✗ | ✗ | ✗ | rw | ✗ |
| `tsb_lab.signal_intents` | ✗ | INSERT own rows only | read/update | ✗ | ✗ |
| `tsb_lab` account tables | ✗ | read own account (view) | rw | ✗ | ✗ |
| Own workspace `lab/workspaces/<s>` | rw | rw | ✗ | ✗ | ✗ |
| Evidence store / experiment registry | append (via runner) | append (via engine) | append | ✗ | ✗ |

## 4. Gap analysis

| Gap | Change | Touches production? |
|---|---|---|
| G1 No accounts | new `tsb_lab` schema: accounts, orders, fills, positions, ledger, equity_daily, signal_intents, experiments | no (new DB) |
| G2 No target-position orders | lab engine order path `target_qty` (market, full fill) beside the bracket path; shared fill and fee functions | code in the tracker image, **inactive unless `LAB_MODE`** |
| G3 Global risk | account-scoped risk (R1–R4, R9) in the lab path; B3 stays production-only | no |
| G4 Raw data writable | read-only bind mounts + distinct UIDs; optional `chmod a-w` of `raw/` (owner decision: metadata change only) | no |
| G5 No experiment registry | append-only, hash-chained JSONL (pattern of the CHG-03 ledger) plus content-addressed results | no |
| G6 Intake validation | schema, limits, idempotency, account state, timestamps vs market clock | no |
| G7 Reporting | per-account daily report and an equity/drawdown/turnover/cost view; Telegram optional | no |

## 5. Minimal roadmap (each step a separate owner approval)

1. Approve the design and the R1–R10 rules (this PR).
2. `tsb_lab` schema plus pure accounting module with synthetic tests (no host change).
3. Lab engine path in the tracker codebase behind `LAB_MODE`; a production byte-identity test (like `T1_CAP_POLICY`).
4. Strategy container template plus the intake role, tested on a disposable Postgres.
5. Shadow mode for one strategy (no P&L).
6. Forward Paper for at most 2–3 strategies, each with a pre-registered spec.
7. Governed confirmation only via the Evidence Ladder.

## 6. Required tests

- **Accounting invariants:**
  - cash + Σ cost basis − fees = initial + realized P&L;
  - no negative cash;
  - cap never exceeded under concurrent intents;
  - reservations released on reject or expiry.
- **Isolation:** strategy A cannot read or write B's rows (RLS test); same-symbol positions in two accounts are independent; no netting query.
- **Idempotency:** a replayed intent gives one order; a crash between fill and ledger leaves nothing half-written (single transaction).
- **Production identity:** with `LAB_MODE` unset, tracker outputs are byte-identical to `ea8ae4f` on the existing test corpus.
- **Data:** a mount-permission test in the container (write to the snapshot fails); no post-freeze path is mounted.
- **Resources:** OOM or CPU-throttle of one strategy does not affect the engine or production (fault injection on disposable infrastructure).

## 7. Resource estimate (INFERRED)

| Component | Count | Resources |
|---|---|---|
| Strategy containers | up to 5 | 0.5 CPU / 512 MB each |
| Lab engine | 1 | 0.5 CPU / 256 MB |
| Lab DB | 1 | about 200 MB |
| Total | — | ≤ 3.5 cores, ≤ 3.5 GB. Fits the host's headroom (about 10 GB free), but it is a **shared host**: memory limits are mandatory |
| Workspaces | — | 5 GB quota each (monitoring; ext4 has no per-directory quota) |
| Backtests | — | through the existing research-runner quotas |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Holdout leakage through post-freeze data | Matrix §3: no lab component mounts `p2` or any post-freeze snapshot |
| Paper P&L read as proof | Mode 3 is labelled prospective observation; confirmation only per the ladder |
| Multiplicity across many strategies | A pre-registered family and Romano–Wolf / Deflated Sharpe; every strategy and failure recorded |
| Shared-host contention | Hard limits, `restart: "no"`, one engine |
| Production regression | Separate DB; `LAB_MODE` inactive in production; identity tests |

## 9. Preliminary author assessment (not an independent review)

REVISE → GO is possible once R1–R10 are decided and the reviewers confirm G2 (the target-position path) is an extension, not a second engine.

## 10. Host resources, budgets and scheduling (addendum, 2026-10-20)

Categories used below:
- **HIST** — historical observation;
- **OWNER** — owner approval;
- **PROP** — proposed budget;
- **ENF** — currently enforced and verified read-only.

### 10.1 Inventory (read-only, 2026-10-20)

| Item | Value | Class |
|---|---|---|
| CPUs / RAM / swap | 12 logical; 23.4 GB (21.4 GB available); swap 4 GB (0 used) | ENF/VERIFIED |
| Load, PSI | loadavg 0.6–0.9; PSI cpu some avg60 0.20 %, memory 0, io 0.02 % | VERIFIED |
| Project CPU ceiling 10 vCPU | owner-approved; **not technically enforced**: no parent cgroup groups the project's containers and user-slice jobs | OWNER / **not ENF** |
| Production container caps | analyzer 1.5 CPU / 1 GiB; signal_engine 1.0 / 512 MiB; scanner 1.0 / 512 MiB; telegram, tracker **no CPU cap** / 256 MiB; postgres (shared) **no CPU cap** / 512 MiB | ENF |
| Collector | 1.5 CPU / 768 MiB / pids 64; measured about 0.34 CPU | ENF / VERIFIED |
| Monitor | user `tsbops.slice` CPUWeight 1000, MemoryMax 512 MiB, TasksMax 64 | ENF |
| Research runner | profiles R1 4 workers / CPUQuota 400 %, R2 6 / 600 % (`--allow-elevated`), R3 8 / 800 % (`--attended`), LIGHT 2 / 200 %; per-job MemoryMax 10 GiB; aggregate `research.slice` 800 % / 12 GiB (`~/ops/research-runner/research_exec/config.py`) | HIST/OWNER in config; **ENF only while a runner job exists** (the slice is inactive now) |
| Docker vs slices | containers run under `system.slice/docker-<id>.scope`; a lab container would **not** be inside the user `research.slice` | VERIFIED |
| I/O controls | none set (no IOWeight / io.max on any project unit) | VERIFIED |
| Other tenants | hermes 4 CPU / 4 GiB; wishlist, xsch uncapped | VERIFIED |
| Measured lab workload (synthetic) | 8-year × 20-asset daily simulation of two rules: **0.86 CPU-s, 15 MB RSS** | VERIFIED (benchmark of `research/mechanisms`, #60) |

### 10.2 Gaps between policy and enforcement

1. The 10 vCPU project ceiling is not enforced. The sum of explicit production caps is 5.0, plus three uncapped services, plus up to 8 research.
2. `research.slice` limits apply only to runner-launched jobs, and only while they run.
3. Docker-based strategy containers would bypass `research.slice`.
4. There is no I/O isolation.
5. There is no PSI-based admission for containers. The runner has its own admission checks, but containers do not.

### 10.3 One shared research budget (PROP)

| Profile | Total research + lab CPU | Split (enforceable) | Memory | Notes |
|---|---|---|---|---|
| R1 (default) | **4 vCPU** | runner `research.slice` 300 % + lab containers parent `tsblab.slice` 100 % | research 8 GiB + lab 2 GiB | sum of caps with production (5.0) = 9 ≤ 10 |
| R2 (`--allow-elevated`, after measured G5 conditions) | **up to 6 vCPU** | 450 % + 150 % | 10 + 2 GiB | sum of caps = 11 > 10, so it is compliant **only** with an enforced project parent ceiling, or at 5 vCPU total without one |
| R3 (attended only) | 8 vCPU | runner only; lab containers paused | 12 GiB | never automatic; operator present; ends to R1 |

- **Worker count ≠ CPU quota.** Workers are processes started by the runner. The quota is the cgroup `cpu.max` that bounds them.
- **Strategy containers:** each 0.25 CPU / 256 MiB / pids 64 / `restart: "no"`, inside `tsblab.slice`.
- **Capacity at R1:** ≤ 5 forward strategies (the account cap) + 1 lab engine (0.25 / 256 MiB) fit in 100 % / 2 GiB. The measurement (≈ 1 CPU-s per 8-year daily run) shows daily strategies are memory- and governance-bound, not CPU-bound.
- **Capacity at R2:** the same container count (no reason to scale strategies with CPU); the extra quota goes to backtest workers.

### 10.4 Scheduling and pressure behaviour (PROP)

- **Priority:** production services > Collector > Paper/lab engine > forward strategy containers > shadow > backtests.
- **Weights:** research `CPUWeight=idle` (or 1) and `IOWeight=10`; lab 50; production keeps its default of 100. Weights only matter under contention, so production preempts research.
- **Bounded queue:** the runner admits at most one R2 job and at most two R1 jobs at once; it queues the rest, FIFO within each priority class. `cancel` stops a job via the unit (`systemctl --user stop`) and keeps its evidence.
- **Pressure safeguards:**
  - refuse new admissions when PSI cpu some avg60 > 20 %, memory some avg10 > 1 %, MemAvailable < 4 GiB or disk free < 100 GB;
  - pause the backtest queue (no kill) while production or Collector health is degraded.
- **Protected windows (no new research admissions):**
  - Collector day close and universe refresh 23:50–00:30 UTC;
  - seal and backup at :15–:20 each hour, around 01:15 UTC (xsch), 01:20 UTC (shared-postgres) and 02:50 UTC (p1bg) local-time jobs.
- **No automatic escalation:** R2/R3 need the existing explicit flags. Nothing escalates on its own.
- **A29 20 % reserve:** this is a **scientific** allocation of prospective confirmation capacity (admissions/alpha over time) for set-aside candidates. It is **not** a CPU reservation and does not change the budgets above.

### 10.5 How enforcement would be added (stages; each a separate approval; none done)

| Stage | Change | Disruption | Rollback | Acceptance test |
|---|---|---|---|---|
| S0 | Measure: one week of PSI and per-cgroup `cpu.stat` / `memory.peak` sampling (read-only script) | none | remove the script | report of p95/p99 per service |
| S1 | Persistent `research.slice` drop-in (CPUQuota 300/450 %, MemoryMax, MemorySwapMax 0, CPUWeight idle, IOWeight 10) | none (runner only) | delete the drop-in + daemon-reload | `systemctl --user show research.slice` values; synthetic CPU-burn job throttled at the quota |
| S2 | System `tsblab.slice` (CPUQuota 100/150 %, MemoryMax 2 GiB) + lab compose `cgroup_parent: tsblab.slice` | none (new containers only) | remove the slice; containers recreated without parent | a burn in one lab container cannot exceed its slice; production PSI unchanged |
| S3 | Project ceiling: parent `tsb.slice` (CPUQuota 1000 %) for **all** project containers | **requires recreating every production container** (Class B, one service at a time) | recreate without `cgroup_parent` | per-service identity gates; Paper/Collector health over 30 min |
| S4 | PSI admission and protected windows in runner config | none | revert config | admission refused under an injected PSI threshold |

Lowest risk first: S0 → S1 → S2. S3 is optional and disruptive. Until S3, the 10 vCPU ceiling is met only by **budget arithmetic** (R1), not by enforcement.
