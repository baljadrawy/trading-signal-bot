# R-5: least-privilege PostgreSQL roles, schema 11 (design v3): isolated validation report

Date: 2026-10-17. Branch `security/r5-roles-schema11` (from `develop` `ea8ae4f`).

**Scope.** Design and isolated testing only. Nothing in this directory has been applied to production. No production
role, grant, credential, configuration, container or cron was changed. The disposable test cluster has been removed.

## 1. Verified state (read-only, 2026-10-17)

| Item | Evidence |
|---|---|
| Release | develop = `ea8ae4f`; production schema_migrations 1–11 match the repository files' sha256. The 4 release images' Python code is byte-identical to `ea8ae4f`; the scanner runs its earlier image `63b38e7a` |
| Production roles | `trading_signal_bot` (bootstrap superuser), `xsch_user`, `wishlist_user`, `wishlist_test_role`, `shared_pg_backup`. **0 `tsb_*` roles**: the P0 design was never applied |
| Production ACLs | 26 tables and 18 sequences, all owned by `trading_signal_bot`, with no GRANTs. `trading_signals` has no PUBLIC CONNECT; `shared_pg_backup` has CONNECT only |
| pg_hba | local `trust`; 127.0.0.1 `trust`; every other host `scram-sha-256` |
| Network logins as the superuser | scanner, analyzer (10-connection pool), signal_engine, telegram, tracker |
| Local-socket (`docker exec`) users of the superuser | shared-postgres globals backup, xsch backup and restore test (`BACKUP_GLOBALS_ROLE=trading_signal_bot`), p1bg backup, A56 soak monitor, `database/migrate.py`, operator commands. Local auth is `trust`, so these depend on the role **name**, not its password |
| Stopped or retired | continuous_learner (profile `learner`, stopped), optimizer (profile `disabled`), claude_review (retired, CR-2) |
| P0 artifacts | `~/backups/tsb-p0-security-20260927/MANIFEST.sha256`: 54/54 OK |

**Owner decisions D1–D8 (P0 §11). All open, none granted:**
- **D1:** stages 0–2.
- **D2:** credential location.
- **D3:** config-drift acknowledgement. Superseded in part: the services were recreated during A56; re-check before rollout.
- **D4:** unused API keys.
- **D5:** admin rotation and stages 5 and 6.
- **D6:** research access. **UNRESOLVED**, and v3 is deny-by-default.
- **D7:** Binance IP restriction.
- **D8:** commit the artifacts to a branch, with no push until decided. This branch is local-only for that reason.

## 2. What changed from P0 v2, and why

| Change | Reason (verified against code) |
|---|---|
| `tsb_tracker` gets `SELECT, INSERT, UPDATE` on `paper_entry_orders` | migration 010; tracker `_record_entry_order` / `_load_entry_order` |
| `tsb_claude_review` removed | retired service, absent from compose |
| `tsb_learner` (NOLOGIN) added | only `research/continuous_learner.py` and `rollback_learned_gates.py` write `learned_gate_history`, `learning_runs`, `learned_gates` (migration 005). A60's "missing grants" belong here, not to signal_engine |
| `tsb_research_ro`: `SELECT ON ALL TABLES` **removed** (deny-by-default) | the v2 grant exposed the sealed FORWARD_HOLDOUT; D6 is unresolved |
| `tsb_backup` added (local socket only, read-only, default privileges for future tables) | `pg_dump` without the superuser; a new table can never silently fall out of the dump |
| `tsb_dashboard_ro` (NOLOGIN) plus `dashboard_v1.sql` view allowlist | A59 deployment needs a dedicated role. It has **no usage on schema `public`** |
| `tsb_net_group` plus `hba/pg_hba.tsb.v3.snippet` | only runtime roles may log in over the network; backup, migrator and research are rejected there |
| `ownership_v3.sql` (optional, separate stage): `tsb_owner` NOLOGIN owns objects; `tsb_migrator` runs migrations through `SET ROLE` | migrations no longer need the superuser (tested: M-02) |

## 3. Test results (disposable cluster: production PostgreSQL image 16.15, `--internal` network, schema-only plus synthetic data)

| ID | Test | Expected | Actual | Result |
|---|---|---|---|---|
| M-01 | production v9 schema (P0 dump 2026-09-27) + the real 010/011 files applied like `migrate.py` | structure = production v11 | 425/425 normalized catalog lines identical | PASS |
| M-02 | same, migrations run by `tsb_migrator` (non-superuser) through `SET ROLE tsb_owner` | structure = production v11 | identical; all objects owned by `tsb_owner` | PASS |
| M-03 | `roles_v3.sql` applied twice | idempotent | no error | PASS |
| M-04 | `roles_v3.sql` on `tsb_owner`-owned objects | applies | applied, suite green | PASS |
| S-* | every SQL statement of each service, from the deployed code: 213 statements (static plus every f-string rendered with the real constants and helpers), `EXPLAIN (GENERIC_PLAN)` under the service's role | permitted | 213 permitted, 0 non-executable, 1 denial by design (tracker's copy of `risk_epoch.record_recovery`; asserted uncalled in the tracker's call graph) | PASS |
| MIN-* | every granted table privilege revoked one at a time | some statement then fails | true for every privilege of all 6 code roles | PASS |
| W-01 | single-writer matrix (signals, trades, entry orders, results, fills, recovery events, learner tables); no DELETE/TRUNCATE on accounting tables | exact sets | exact | PASS |
| SEQ-* | sequence USAGE equals the tables each role inserts into; no UPDATE (setval); backup SELECT only | exact | exact; nextval granted/denied as expected | PASS |
| F-OBX | outbox enqueue (idempotent), claim, defer (no attempt consumed), fail→retry, fail→dead letter `retry_exhausted`, dead-letter read, ack: as signal_engine, telegram, tracker | works | works | PASS |
| F-B3 | B3 gate (missing→fail-closed, halt, resume) as scanner, telegram, tracker; ungranted role fails closed visibly | as P0 | as P0 | PASS |
| F-SE | signal_engine's real insert-once SQL (`setup_key`), risk counter, outbox; duplicate setup not re-emitted | idempotent | idempotent | PASS |
| F-TRK | **release tracker image**, real `register_new_signals` / `track_open_trades`, as admin vs `tsb_tracker` (pg_hba active): marketable fill, resting fill (`legacy_observed`), fill rejection, risk-cap refusal, T1/T2/T3 25/50/25, stop loss, cost 0.15, net labels, outbox | identical state, 0 privilege errors | identical, 0 errors (also identical after the rollback/re-apply cycle) | PASS |
| F-TG | **release telegram image**: 6 lifecycle notifications delivered and acked, B3 delivery gate, `mark_delivered`, 11 owner commands (reports with net-label SQL, lists, /pause, /resume, /recover_risk), as admin vs `tsb_telegram` | identical messages and state, 0 errors | identical, 11/11, 0 errors | PASS |
| F-RISK | tracker advisory lock and streak; telegram pause/resume/recovery; symbol-list upserts | works | works | PASS |
| D-* | per-role forbidden writes; `COPY TO PROGRAM`, `pg_read_file`, `ALTER SYSTEM`, CREATE ROLE/DATABASE/TABLE/TEMP/SCHEMA, TRUNCATE, DROP, ALTER, SET ROLE admin/groups/backup/owner, `pg_authid`, onward GRANT, terminating other roles' sessions, other databases | denied | denied | PASS |
| H-01 | research role: all 26 tables and 18 sequences, `pg_stats` (after ANALYZE; the admin sees rows), column privileges, dashboard schema | denied / 0 rows | denied / 0 | PASS |
| H-02 | research and dashboard roles cannot log in (NOLOGIN, even with a password) | refused | refused | PASS |
| H-03 | D6 option (c) prototype, in a rolled-back transaction only: synthetic rows at 09:33:45 visible, at 09:33:46 and later invisible; base tables still denied; not left applied | as stated | as stated | PASS (prototype, NOT adopted) |
| A-01 | dashboard role: 6 allowlisted views readable; columns contain no price/P&L/result/target/fraction/error-text; public tables denied; writes and CREATE denied | as stated | as stated | PASS |
| B-01..05 | `pg_dump` as `tsb_backup` (local socket) = all 26 tables, 0 errors; read-only; future tables readable by backup only; `pg_dump` as a runtime role fails | as stated | as stated | PASS |
| SEP-01 | runtime, research and dashboard roles cannot use or SET admin/backup/migrator/owner; migrator holds no table privilege | as stated | as stated | PASS |
| HBA-* | 57 cases: runtime roles reach `trading_signals` only; backup, migrator and research rejected on the network everywhere; NOLOGIN network roles still refused; admin and xsch/wishlist/shared_pg_backup unaffected; 0 pg_hba errors | as stated | 57/57 | PASS |
| C-01..04 | 10-connection pool + 2 healthcheck connections fit the limit of 20; the 21st is refused; a denied statement rolls back the whole tracker transaction; session timeouts apply | as stated | as stated | PASS |
| R-01..04 | rollback refuses while a `tsb_*` session is connected; full rollback leaves 0 roles, 0 non-owner ACL entries, 0 default ACLs, no dashboard schema, PUBLIC TEMP restored, ownership back with the admin; re-apply then full re-test | as stated | as stated; re-test 98 passed (20 skips by design) + tracker parity PASS | PASS |
| SMK-01 | the 5 deployed images start their real `main.py` under their roles on the internal network | DB startup under role, 0 privilege errors | 0 privilege errors; all 5 wrote `last_started_at`; tracker ran its loop (heartbeat success); scanner, analyzer, signal_engine and telegram then exited on the expected DNS failure (no internet) | **PARTIAL**: their runtime loops need network; covered statically (S-*) |
| LRN | continuous_learner runtime | n/a | **NOT RUN**: stopped by governance; covered statically (33/33 statements, minimality) | SKIP |

**Suite counts:**
- role suite: 112 passed, 6 skipped (not-applicable "own database" combinations);
- with pg_hba active: 98 passed, 20 skipped (14 backup/migrator network logins rejected by design, covered by HBA-*; 6 not applicable);
- pg_hba: 57/57;
- no failures.

The skipped cases are listed as skipped, not as passed.

**Untested production-specific dependencies:**
- the real `pg_hba.conf` edit procedure (owner/mode/inode);
- the live 10-connection analyzer pool under real load;
- Binance/Telegram-dependent loops of scanner, analyzer and signal_engine;
- credential injection through compose overrides;
- the xsch/shared-postgres backups (they use the admin over the local socket and are unaffected by design, but untested here).

## 4. Rollout plan (planning only; each stage needs its own approval; stop on any failure)

**Prerequisites:**
- the A56 soak is closed;
- OPS-1 is closed: R-1 G2 and G3 have passed;
- a fresh verified backup exists;
- CP-7 key escrow is decided;
- D1–D8 are decided; D6 may stay "deny";
- an inventory of every client that uses the `trading_signal_bot` password (section 1).

1. **Stage 0, read-only pre-flight.**
   - Images, compose blob and drift check.
   - Take a fresh schema-only dump and run `r5_test_env.sh up && test && rollback-cycle && down` against it. Expect the counts in section 3.
2. **Stage 1, additive.**
   - Run `roles_v3.sql` as the admin over the local socket.
   - Provision credentials with `tools/provision_db_credentials.py` (SCRAM verifiers only).
   - No service changes yet. Rollback: `roles_v3_rollback.sql`.
3. **Stage 2, one service at a time**, in this order: scanner → analyzer → signal_engine → tracker → telegram.
   - Use a per-service credential file, then `up -d --no-deps --no-build --pull never --force-recreate <svc>`.
   - Gates, within 5 minutes and then a ≥ 30-minute soak:
     - healthy, restarts unchanged, image unchanged;
     - `pg_stat_activity` shows `tsb_<svc>` and no admin session from that container;
     - 0 `permission denied` / `42501` / `too many connections`;
     - heartbeat advancing;
     - the A56 gate SQL is still green.
   - Rollback per service: restore the previous compose file and recreate that one service.
   - **One service per approval window. Never all at once.**
4. **Stage 3, backups to `tsb_backup`.**
   - p1bg `pg_dump -U tsb_backup`. This changes the R-1 script, so it is its own change.
   - The xsch/shared-postgres globals dumps need cluster-wide reads and stay on the admin.
5. **Stage 4, pg_hba v3 snippet.**
   - Back up `pg_hba.conf` in place, insert the snippet, require 0 `pg_hba_file_rules` errors **before** `pg_reload_conf()`.
   - Verify xsch-app and wishlist-app are healthy.
   - Rollback: restore the file, then reload.
6. **Stage 5, remove admin credentials from the shared `.env`, and SEC-1 rotation (not executed).**
   - Once no network client uses the admin password, rotate it with a SCRAM verifier.
   - That closes SEC-1 for runtime use: the committed literal no longer matches anything.
   - Local-socket jobs are unaffected (trust).
   - Git history is untouched unless a separate plan is approved.
7. **Stage 6, optional ownership stage (`ownership_v3.sql`).**
   - Migrations run as `tsb_migrator` with `SET ROLE tsb_owner`. This needs a `migrate.py` option, which is a code change.
   - Rollback: `ownership_v3_rollback.sql`.
8. **Later, separate approvals:**
   - the dashboard (A59 deployment): `dashboard_v1.sql` plus LOGIN for `tsb_dashboard_ro`;
   - learner restart: LOGIN for `tsb_learner`;
   - D6.

## 5. Residual risks

- **The bootstrap superuser stays.** `trading_signal_bot` remains the cluster superuser, the object owner and the break-glass role, with local-socket trust. Anyone with `docker exec` on the postgres container is effectively a superuser; that is unchanged by design.
- **xsch and wishlist** keep depending on the admin for globals backups and the restore test.
- **Metadata stays visible to every role:** catalog names, `pg_stat_user_tables` row counts and activity. No row data is exposed.
- **The dashboard allowlist** (`risk_state.pause_reason`) shows halt reasons as text, which can name a loss-streak halt. Anything beyond the allowlist is an owner decision.
- **The backup role reads holdout-bearing rows.** It is operational only: local socket, never issued for research.
- **Future migrations must add GRANTs.** Deny-by-default makes a missing grant fail loudly at runtime. Run this suite before every deployment that adds a table.
