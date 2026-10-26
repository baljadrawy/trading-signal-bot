#!/usr/bin/env bash
# Tracker functional parity: the release tracker image runs func_tracker_flow.py as the admin (par_admin) and as
# tsb_tracker (par_role, temporarily renamed trading_signals so pg_hba scoping stays active). Disposable cluster only.
set -euo pipefail
O=$(cd "$(dirname "$0")/.." && pwd); RUN=${RUN:?}; IMG=${TRACKER_IMAGE:-tsb-a561-trade_tracker:rel-ea8ae4f-r2}; umask 077
PS=(docker exec -i tsb-r5-pg psql -X -q -v ON_ERROR_STOP=1 -U trading_signal_bot -d postgres)
"${PS[@]}" -c "DROP DATABASE IF EXISTS par_admin" -c "DROP DATABASE IF EXISTS par_role" \
  -c "CREATE DATABASE par_admin TEMPLATE flow_base" -c "CREATE DATABASE par_role TEMPLATE flow_base" \
  -c "REVOKE CONNECT ON DATABASE par_admin, par_role FROM PUBLIC" -c "GRANT CONNECT ON DATABASE par_role TO tsb_tracker"
for who in admin role; do
  if [ $who = admin ]; then u=trading_signal_bot; key=TSB_PW_TRADING_SIGNAL_BOT; db=par_admin
  else u=tsb_tracker; key=TSB_PW_TSB_TRACKER; db=trading_signals
       "${PS[@]}" -c "ALTER DATABASE trading_signals RENAME TO ts_main_hold" -c "ALTER DATABASE par_role RENAME TO trading_signals"; fi
  { printf 'POSTGRES_HOST=tsb-r5-pg\nPOSTGRES_PORT=5432\nPOSTGRES_DB=%s\nPOSTGRES_USER=%s\n' $db $u
    sed -n "s/^$key=/POSTGRES_PASSWORD=/p" "$RUN/test.env"
    printf 'PAPER_TRADING=true\nEVIDENCE_V2_ENABLED=false\nENABLE_EVIDENCE_RECORDER=false\nR5_OUT_JSON=/out/tracker_flow_%s.json\n' $who; } > "$RUN/flow.env"
  rc=0; docker run --rm --network tsb-r5-net --label purpose=r5-disposable-test --env-file "$RUN/flow.env" \
    -v "$O/tests:/t:ro" -v "$RUN/out:/out" --entrypoint python "$IMG" /t/func_tracker_flow.py > "$RUN/out/tracker_flow_$who.log" 2>&1 || rc=$?
  rm -f "$RUN/flow.env"
  [ $who = role ] && "${PS[@]}" -c "ALTER DATABASE trading_signals RENAME TO par_role" -c "ALTER DATABASE ts_main_hold RENAME TO trading_signals"
  echo "$who rc=$rc: $(tail -1 "$RUN/out/tracker_flow_$who.log" | cut -c1-200)"
done
python3 - "$RUN/out" <<'PY'
import json, sys
d = sys.argv[1]; a = json.load(open(f'{d}/tracker_flow_admin.json')); r = json.load(open(f'{d}/tracker_flow_role.json'))
s = a['state']
print('users:', a['user'], r['user'], '| privilege errors:', len(a['privilege_errors']), len(r['privilege_errors']))
print('PARITY (identical non-time state):', a['state'] == r['state'])
for t in a['state']:
    if a['state'][t] != r['state'][t]: print('  differs:', t)
print('entry orders:', [(x['signal_id'], x['order_kind'], x['status'], x['fill_basis'] or x['terminal_reason']) for x in s['paper_entry_orders']])
print('trades:', [(x['symbol'], x['status'], x['highest_target_hit'], x['remaining_fraction'], x['entry_fill_model']) for x in s['active_trades']])
print('fills:', [(x['active_trade_id'], x['target_number'], x['quantity_fraction']) for x in s['trade_target_fills']])
print('results:', [(x['symbol'], x['notes'], x['target_reached'], x['stop_hit'], x['cost_usdt'], x['economic_result'] is not None, x['label_policy']) for x in s['trade_results']])
print('outbox:', [(x['event_type'], x['status']) for x in s['outbox_events']])
sys.exit(0 if a['state'] == r['state'] and not a['privilege_errors'] and not r['privilege_errors'] else 1)
PY
