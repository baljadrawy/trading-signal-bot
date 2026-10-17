# db-roles-v3: least-privilege PostgreSQL roles (R-5). Design and tests only; nothing here is applied

Read `R5_REPORT.md` first.

| File | Purpose |
|---|---|
| `roles_v3.sql` / `roles_v3_rollback.sql` | role design v3 (schema 11) and its rollback |
| `dashboard_v1.sql` | A59 view allowlist (apply only with A59 deployment approval) |
| `ownership_v3.sql` / `ownership_v3_rollback.sql` | optional stage: non-superuser owner and migrator |
| `research_d6c_prototype.sql` | D6 option (c) prototype. Test cluster only; **not** approved |
| `hba/pg_hba.tsb.v3.snippet` | network login scoping |
| `tools/provision_db_credentials.py` | SCRAM-verifier credential provisioning (no plaintext reaches the server) |
| `r5_test_env.sh` | disposable cluster: `up`, `test`, `smoke`, `rollback-cycle`, `down` |
| `tests/` | role suite, pg_hba suite, release-image functional parity (tracker, telegram), SQL inventory |
| `evidence/` | outputs of the final clean run on 2026-10-17 |

To reproduce (from a scratch directory; never against production):
```
RUN=<private dir> PROD_SCHEMA=<schema-only dump> DEPLOYED=<dir with each container's /app> \
  ./r5_test_env.sh up && ./r5_test_env.sh test && ./r5_test_env.sh smoke && ./r5_test_env.sh rollback-cycle && ./r5_test_env.sh down
```
