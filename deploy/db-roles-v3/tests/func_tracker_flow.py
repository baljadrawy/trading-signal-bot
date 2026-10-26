"""Functional parity test: the RELEASE tracker code (run inside its image) driven through one scripted Paper lifecycle.
Run once as the admin and once as tsb_tracker, each against its own clone of the same synthetic database; the
resulting non-time columns must be identical (semantics preserved) and no privilege error may occur.
Only the two network lookups are stubbed (current price, minimum notional) and the candle lookup returns None.
Env: POSTGRES_* (the role under test), R5_OUT_JSON (result file). DISPOSABLE TEST CLUSTER ONLY."""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, '/app')
os.chdir('/app')

PRICES = {}                                   # symbol -> current stubbed price
ERRORS = []


class Capture(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if any(k in msg.lower() for k in ('permission denied', 'insufficientprivilege', '42501', 'must be owner')):
            ERRORS.append(msg[:300])


async def run():
    import main                                                    # trade_tracker/main.py as deployed
    from shared.database import Database
    logging.getLogger().addHandler(Capture())
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).addHandler(Capture())

    async def price(symbol):
        return PRICES.get(symbol)

    async def min_notional(symbol):
        return 5.0

    async def candle(symbol, timeframe):
        return None

    main.get_current_price, main.get_min_notional, main.get_last_closed_candle = price, min_notional, candle
    await Database.connect()
    steps = []
    try:
        who = await Database.fetchval('SELECT current_user')
        script = [
            ('admit', {'R5AUSDT': 1.0, 'R5BUSDT': 1.002, 'R5CUSDT': 0.985}),    # marketable / resting / rejected
            ('admit', {'R5AUSDT': 1.0, 'R5BUSDT': 0.9995}),                     # B refused: risk cap (A open)
            ('track', {'R5AUSDT': 1.0105}),                                     # A: T1 (25%)
            ('track', {'R5AUSDT': 1.0205}),                                     # A: T2 (50%)
            ('track', {'R5AUSDT': 1.0305}),                                     # A: T3 closes the last 25%
            ('admit', {'R5BUSDT': 0.9995}),                                     # B: resting order fills
            ('track', {'R5BUSDT': 0.985}),                                      # B: stop
        ]
        for kind, prices in script:
            PRICES.clear(); PRICES.update(prices)
            if kind == 'admit':
                await main.register_new_signals()
            else:
                await main.track_open_trades()
            steps.append(kind)
        state = {}
        for table, order in (('paper_entry_orders', 'signal_id'), ('active_trades', 'id'), ('trade_target_fills', 'id'),
                             ('trade_results', 'id'), ('outbox_events', 'id'), ('risk_management', 'date'),
                             ('signals', 'id')):
            cols = [r['column_name'] for r in await Database.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 "
                "AND data_type NOT LIKE 'timestamp%' AND data_type <> 'date' ORDER BY ordinal_position", table)]
            if table == 'signals':
                cols = [c for c in cols if c in ('id', 'symbol', 'telegram_sent')]
            if table == 'outbox_events':
                cols = [c for c in cols if c not in ('locked_by', 'payload')] + ["payload::text AS payload"]
            sel = ', '.join(cols)
            rows = await Database.fetch(f'SELECT {sel} FROM {table} ORDER BY {order}')
            state[table] = [{k: (str(v) if v is not None else None) for k, v in dict(r).items()} for r in rows]
    finally:
        await Database.close() if hasattr(Database, 'close') else None
    return {'user': who, 'steps': steps, 'privilege_errors': ERRORS, 'state': state}


if __name__ == '__main__':
    res = asyncio.run(run())
    with open(os.environ['R5_OUT_JSON'], 'w') as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    print(f"user={res['user']} steps={len(res['steps'])} privilege_errors={len(res['privilege_errors'])} "
          f"rows={ {k: len(v) for k, v in res['state'].items()} }")
