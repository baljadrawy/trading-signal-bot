#!/bin/bash
# Build the disposable schema template (P1_SCHEMA_TEMPLATE) from THIS tree, as the local runs do:
# init.sql + the two legacy migrate_* files + database/migrations/NNN_*.sql in order.
set -euo pipefail
: "${PGURL:?admin URL of the disposable CI PostgreSQL}" "${TEMPLATE:=p1_schema}"
psql "$PGURL" -q -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $TEMPLATE" -c "CREATE DATABASE $TEMPLATE"
base="${PGURL%/*}/$TEMPLATE"
for f in database/init.sql database/migrate_features_snapshot_2026_06_23.sql \
         database/migrate_live_learning_2026_06_25.sql $(ls database/migrations/[0-9][0-9][0-9]_*.sql | sort); do
  psql "$base" -q -v ON_ERROR_STOP=1 -f "$f" >/dev/null
done
echo "template $TEMPLATE built"
