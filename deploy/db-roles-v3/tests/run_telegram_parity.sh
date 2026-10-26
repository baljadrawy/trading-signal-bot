#!/usr/bin/env bash
# Telegram functional parity on clones of the post-tracker state (par_role): admin vs tsb_telegram, pg_hba active.
set -euo pipefail
O=$(cd "$(dirname "$0")/.." && pwd); RUN=${RUN:?}; IMG=${TELEGRAM_IMAGE:-tsb-a561-telegram:rel-ea8ae4f-r2}; umask 077
PS=(docker exec -i tsb-r5-pg psql -X -q -v ON_ERROR_STOP=1 -U trading_signal_bot -d postgres)
"${PS[@]}" -c "DROP DATABASE IF EXISTS tg_admin" -c "DROP DATABASE IF EXISTS tg_role" \
  -c "CREATE DATABASE tg_admin TEMPLATE par_role" -c "CREATE DATABASE tg_role TEMPLATE par_role" \
  -c "REVOKE CONNECT ON DATABASE tg_admin, tg_role FROM PUBLIC" -c "GRANT CONNECT ON DATABASE tg_role TO tsb_telegram"
for who in admin role; do
  if [ $who = admin ]; then u=trading_signal_bot; key=TSB_PW_TRADING_SIGNAL_BOT; db=tg_admin
  else u=tsb_telegram; key=TSB_PW_TSB_TELEGRAM; db=trading_signals
       "${PS[@]}" -c "ALTER DATABASE trading_signals RENAME TO ts_main_hold" -c "ALTER DATABASE tg_role RENAME TO trading_signals"; fi
  { printf 'POSTGRES_HOST=tsb-r5-pg\nPOSTGRES_PORT=5432\nPOSTGRES_DB=%s\nPOSTGRES_USER=%s\n' $db $u
    sed -n "s/^$key=/POSTGRES_PASSWORD=/p" "$RUN/test.env"
    printf 'PAPER_TRADING=true\nTELEGRAM_CHAT_ID=424242\nTELEGRAM_BOT_TOKEN=\nEVIDENCE_V2_ENABLED=false\nENABLE_EVIDENCE_RECORDER=false\nR5_OUT_JSON=/out/telegram_flow_%s.json\n' $who; } > "$RUN/flow.env"
  rc=0; docker run --rm --network tsb-r5-net --label purpose=r5-disposable-test --env-file "$RUN/flow.env" \
    -v "$O/tests:/t:ro" -v "$RUN/out:/out" --entrypoint python "$IMG" /t/func_telegram_flow.py > "$RUN/out/telegram_flow_$who.log" 2>&1 || rc=$?
  rm -f "$RUN/flow.env"
  [ $who = role ] && "${PS[@]}" -c "ALTER DATABASE trading_signals RENAME TO tg_role" -c "ALTER DATABASE ts_main_hold RENAME TO trading_signals"
  echo "$who rc=$rc: $(tail -1 "$RUN/out/telegram_flow_$who.log" | cut -c1-220)"
done
python3 - "$RUN/out" <<'PY'
import json, sys
d = sys.argv[1]; a = json.load(open(f'{d}/telegram_flow_admin.json')); r = json.load(open(f'{d}/telegram_flow_role.json'))
same = {k: a[k] == r[k] for k in ('delivered', 'gate', 'messages', 'commands', 'state')}
print('users:', a['user'], r['user'], '| privilege errors:', len(a['privilege_errors']), len(r['privilege_errors']))
print('PARITY:', same)
print('delivered:', a['delivered'], '| gate:', a['gate'], '| commands:', {k: v.get('ok') for k, v in a['commands'].items()})
print('failed commands (both):', {k: v for k, v in a['commands'].items() if not v['ok']})
print('outbox after delivery:', [(x['event_type'], x['status'], x['outcome']) for x in a['state']['outbox_events']])
sys.exit(0 if all(same.values()) and not a['privilege_errors'] and not r['privilege_errors'] else 1)
PY
