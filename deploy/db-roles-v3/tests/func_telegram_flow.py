"""Functional parity test: the RELEASE telegram code (run inside its image). It delivers the trade lifecycle outbox events
produced by the tracker flow, marks a signal delivered, checks the B3 delivery gate and runs every owner command
(reports, lists, /pause, /resume, /recover_risk) through the real handlers with a capturing fake bot and fake updates.
Run as the admin and as tsb_telegram against clones of the same database; results must be identical and no privilege
error may occur. No network: nothing reaches Telegram. Env: POSTGRES_*, TELEGRAM_CHAT_ID (synthetic), R5_OUT_JSON."""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, '/app')
os.chdir('/app')
ERRORS, SENT = [], []


class Capture(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if any(k in msg.lower() for k in ('permission denied', 'insufficientprivilege', '42501', 'must be owner')):
            ERRORS.append(msg[:300])


class FakeBot:
    async def send_message(self, chat_id=None, text=None, **kw):
        SENT.append(text)


class _Msg:
    def __init__(self): self.replies = []
    async def reply_text(self, text, **kw): self.replies.append(text)


class _Chat:
    def __init__(self, cid): self.id = cid


class FakeUpdate:
    def __init__(self, cid):
        self.effective_chat, self.message, self.effective_user = _Chat(cid), _Msg(), None


class FakeContext:
    def __init__(self, args=None): self.args = args or []


async def run():
    import main                                              # telegram/main.py as deployed
    from shared.database import Database
    for name in [''] + list(logging.root.manager.loggerDict):
        logging.getLogger(name).addHandler(Capture())

    async def no_price(symbol):
        return None
    main.get_current_price = no_price                         # network lookup (used by /trades)
    await Database.connect()
    who = await Database.fetchval('SELECT current_user')
    cid = int(os.environ['TELEGRAM_CHAT_ID'])
    commands = {}
    try:
        delivered = await main.deliver_trade_lifecycle_events(FakeBot(), 'r5-telegram')
        gate = await main.can_deliver_candidate()
        sid = await Database.fetchval("SELECT min(id) FROM signals")
        await main.mark_delivered(sid)
        for name, args in (('cmd_status', []), ('cmd_stats', []), ('cmd_trades', []), ('cmd_performance', []),
                           ('cmd_signals', []), ('cmd_daily', []), ('cmd_whitelist', []), ('cmd_blacklist', []),
                           ('cmd_pause', []), ('cmd_resume', []), ('cmd_recover_risk', ['r5', 'functional', 'test'])):
            u = FakeUpdate(cid)
            try:
                await getattr(main, name)(u, FakeContext(args))
                commands[name] = {'ok': True, 'replies': len(u.message.replies)}
            except Exception as e:                                  # recorded, compared across roles
                commands[name] = {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:160]}'}
        state = {}
        for table, order in (('outbox_events', 'id'), ('risk_management', 'id'), ('risk_recovery_events', 'id'),
                             ('signals', 'id')):
            cols = [r['column_name'] for r in await Database.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 "
                "AND data_type NOT LIKE 'timestamp%' AND data_type <> 'date' ORDER BY ordinal_position", table)]
            if table == 'signals':
                cols = ['id', 'symbol', 'telegram_sent']
            if table == 'outbox_events':
                cols = [c for c in cols if c not in ('locked_by', 'payload')]
            if table == 'risk_recovery_events':
                cols = [c for c in cols if c not in ('acknowledged_by',)]
            rows = await Database.fetch(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}")
            state[table] = [{k: (str(v) if v is not None else None) for k, v in dict(r).items()} for r in rows]
    finally:
        await Database.close() if hasattr(Database, 'close') else None
    return {'user': who, 'delivered': delivered, 'gate': list(gate) if isinstance(gate, tuple) else gate,
            'messages': SENT, 'commands': commands, 'privilege_errors': ERRORS, 'state': state}


if __name__ == '__main__':
    res = asyncio.run(run())
    with open(os.environ['R5_OUT_JSON'], 'w') as fh:
        json.dump(res, fh, indent=1, sort_keys=True, default=str)
    print(f"user={res['user']} delivered={res['delivered']} messages={len(res['messages'])} "
          f"commands_ok={sum(c['ok'] for c in res['commands'].values())}/{len(res['commands'])} "
          f"privilege_errors={len(res['privilege_errors'])}")
