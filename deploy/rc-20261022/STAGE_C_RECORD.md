# Stage C record: research runner R2 correction (#71), applied 2026-10-22 15:36Z

**Owner authorization:** conditional (2026-10-22). All conditions were verified, and only this file was changed. No research job was started.

| Gate | Evidence | Result |
|---|---|---|
| Exact current file | `~/ops/research-runner/research_exec/config.py`: sha256 `e7a557b7b218dd89850d860ce60cacc3f4341666f9bf56cc7b9cde8c818a922d`, git blob `cc97e722` (= `ops/research/research_exec/config.py` before #71), mode 664 | as expected |
| Expected source | `main` `0abb22d`: blob `25b522cfeec3cb9d6e068b8898978f24370919f7`, sha256 `e380eae69a89c229d4f36e0f0c294f4d00256367ea20188c740d01dffde49d1e` | as expected |
| Change scope | `diff` installed vs source: one comment line + R2 `workers 6 → 5`, `cpu_quota_pct 600 → 500` | approved change only |
| No affected job | no `rj-*`/`rw-*` user units (loaded or inactive); `heavy.lock` and `light.lock` free; 509 job dirs all terminal (443 finished, 60 refused, 5 finished without a record, 1 `lock_busy`); no runner process; no cron entry; MI campaigns: 0 open reservations, `d4r-smoke` closed | none |
| Running services | The only related user service, `tsb-p2f-monitor.service`, runs `p2f_cont_monitor.py`, which does not import the runner. The runner reads `config.py` per invocation (`bin/research-run`). | none affected |
| Launch behaviour | only `resolve_profile("R2")` changes. No other installed file references R2 or 600 % for R2. MI (`MI_MAX_QUOTA_PCT = 600`, disabled by default, owner ceiling 2026-10-08) and R3 (800 %, `--attended`) are separate and unchanged. | as expected |
| Tests (source) | `ops/research/tests` admission + detpool + launcher_swap: 29/29 (isolated container with `--init`), including the #71 assertion R2 = (5, 500) | pass |
| Backup | `~/ops/research-runner-backup-pre-stagec-20261022T153618Z/` (mode 700): byte-identical copy (`cmp`), `SHA256SUMS`, `ROLLBACK.md` | done |
| Apply | gates re-checked immediately before; atomic same-directory `rename` of the verified source blob; mode 664 kept | done |
| After | installed sha256 `e380eae6…`, blob `25b522cf`. Every `research_exec/*.py` and `bin/research-run` equals `main`. The installed module resolves R1 4/400, **R2 5/500**, R3 8/800 (attended), LIGHT 2/200. Slice aggregate 800 % (runtime-only; `research.slice` inactive, quota `infinity` while idle). 0 units started. | validated |

**Rollback:** `cp -p ~/ops/research-runner-backup-pre-stagec-20261022T153618Z/research_exec/config.py ~/ops/research-runner/research_exec/config.py`, then expect sha256 `e7a557b7…`.

**Envelope note:** R2 now matches the owner budget (5 vCPU). The aggregate `research.slice` ceiling (800 %) and the opt-in R3/MI envelopes are pre-existing and outside Stage C. Lowering the slice to the budget is design rule A3 (admission controller), which needs separate approval.
