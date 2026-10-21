# Research admission controller: enforceable concurrency model (design)

Status: **design only.** No host quota, slice, unit, Docker or runner change has been made. Budgets come from `docs/lab/STRATEGY_LAB_ARCHITECTURE.md` §10.3: R1 = 4 vCPU and R2 = 5 vCPU in total for research + lab; R3 deferred. The 10 vCPU project ceiling is **not enforced**.

## 1. Facts that constrain the design (VERIFIED in `ops/research/`)

- Profiles: R1 4 / 400 %, R2 6 / 600 % (500 % proposed in Draft #71), R3 8 / 800 %, LIGHT 2 / 200 %.
- R1, R2 and R3 share the `heavy` lock. **LIGHT has its own `light` lock**, so LIGHT and a heavy job can run together.
- `research.slice` carries an aggregate cap of 800 %. It is effective **only for units the runner places under it** (`systemd-run --user --slice=research.slice`). Docker containers (future lab), production services and anything started outside the runner are not in it.
- Production caps total 5.0 vCPU. Telegram, tracker and the shared postgres are **uncapped**.

## 2. Model: one aggregate budget, enforced by admission plus one slice

| Rule | Mechanism | Effect |
|---|---|---|
| A1. **Budget token.** An admitted job holds `cpu_quota_pct` from a single budget B (R1 mode: 400, R2 mode: 500). Admission fails if `held + requested > B` | runner admission (state file under the existing `flock`; one writer) | LIGHT (200) + R2 (500) = 700 > 500 → LIGHT waits or is refused. LIGHT + R1 = 600 > 400 → refused unless R1 is lowered to 200 |
| A2. **Mode.** B is R1 = 400 by default. R2 mode (500) needs `--allow-elevated` for that job and drops back to R1 when the job ends | runner state | no automatic escalation |
| A3. **Slice backstop.** `research.slice` `CPUQuota` = B, set on start from the mode | runner-owned slice property | the kernel enforces the total for runner jobs even if the admission bookkeeping were wrong |
| A4. **Lab share.** Future lab containers live under a separate system `tsblab.slice` (100 %). While it is active, B is reduced by 100 (R1 300, R2 400) | admission reads `tsblab.slice` presence and quota | research + lab ≤ 4 / 5 vCPU, as §10.3 specifies |
| A5. **Fail closed.** If the budget state is unreadable, a slice property cannot be read back, or the Collector or monitor is not HEALTHY/allow-listed (existing rule), admission refuses | existing admission + new checks | no silent over-commit |
| A6. **Uncapped production.** Not controllable by this design. Admission additionally refuses when host PSI cpu some avg60 > 20 % or MemAvailable < 4 GiB (§10.4) | existing host signals | research yields to production under pressure; this is not a guarantee |

## 3. What this does not solve

- The 10 vCPU project ceiling is still arithmetic. Enforcing it needs a parent slice for all project containers (S3, deferred).
- A job started outside the runner bypasses everything. That is a policy rule, not a technical control.

## 4. Tests required before any change (on non-production units)

1. LIGHT is refused, or queued, while R2 holds 500. In R1 mode a 400 job blocks LIGHT.
2. An injected corrupt budget state causes a refusal.
3. The slice read-back mismatch test.
4. A CPU-burn job is throttled at B. Production PSI is unchanged.
5. R2 mode returns to R1 after the job ends.
6. With `tsblab.slice` present, B is reduced by 100.

## 5. Owner decisions

- Approve A1–A6.
- Choose LIGHT behaviour under a held budget: **queue** (recommended) or **refuse**.
- Approve setting `research.slice` to B (A3). This is a host change and needs separate approval.
