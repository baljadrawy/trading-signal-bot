"""A44 test helper: run one Paper scenario with ANOTHER code tree's own modules (its shared/ too).

Usage: python a44_tree_driver.py <tree_root> <dsn> <symbol> [price]
Runs, with the tree's code only: signal_engine.save_signal -> telegram candidate handler ->
trade_tracker admission (+ A38 reconciliation when the tree has it). Prints one JSON line.
This is the source-level equivalent of running that tree's images against the given schema.
"""
import asyncio
import json
import os
import sys
import types


def _ptb_stubs():
    class _Any:
        def __init__(self, *a, **k):
            pass
    tg = types.ModuleType('telegram')
    for n in ('Bot', 'BotCommand', 'InlineKeyboardButton', 'InlineKeyboardMarkup', 'Update'):
        setattr(tg, n, type(n, (_Any,), {}))
    ext = types.ModuleType('telegram.ext')
    for n in ('Application', 'CallbackQueryHandler', 'CommandHandler'):
        setattr(ext, n, type(n, (_Any,), {}))
    ext.ContextTypes = type('ContextTypes', (), {'DEFAULT_TYPE': object})
    tg.ext = ext
    return {'telegram': tg, 'telegram.ext': ext}


def _load(name, path, extra):
    import importlib.util
    sys.path.insert(0, extra)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(extra)


async def main(root, dsn, symbol, price):
    sys.path.insert(0, root)
    os.chdir(root)
    import asyncpg
    from shared.config import config
    from shared.database import Database
    config.ENABLE_EVIDENCE_RECORDER = False
    config.EVIDENCE_V2_ENABLED = False
    config.MAX_OPEN_TRADES = 10
    config.RISK_CANARY_MAX_OPEN_TRADES = 5
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    Database._pool = pool
    se = _load('drv_signal_logic', f'{root}/signal_engine/signal_logic.py', f'{root}/signal_engine')
    saved = {k: sys.modules.get(k) for k in ('telegram', 'telegram.ext')}
    sys.modules.update(_ptb_stubs())
    tg = _load('drv_telegram', f'{root}/telegram/main.py', f'{root}/telegram')
    for k, v in saved.items():
        sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)
    tr = _load('drv_tracker', f'{root}/trade_tracker/main.py', f'{root}/trade_tracker')
    if hasattr(tg, 'DELIVERY_PACING_SECONDS'):
        tg.DELIVERY_PACING_SECONDS = 0

    async def get_price(s):
        return price

    async def notional(s):
        return 5.0
    tr.get_current_price, tr.get_min_notional = get_price, notional
    sig = {'symbol': symbol, 'timeframe': '4h', 'market_condition': 'bullish', 'entry_price': 100.0,
           'target_1': 102.0, 'target_2': 104.0, 'target_3': 106.0, 'stop_loss': 97.0,
           'total_score': 4, 'trade_type': 'reversion', 'score_details': {},
           'confirmed_timeframes': ['4h'], 'timeframe_confirmations': 1,
           'macro_snapshot': {'usdtd_trend': 'flat'}}
    sid = await se.SignalEngine().save_signal(sig)
    owner, mgr, delivered = tg.worker_id('drv-tg'), tg.ApprovalManager(), 0
    for et in tg.CANDIDATE_EVENT_TYPES:
        for ev in await tg.claim(et, owner, limit=5):
            delivered += bool(await tg.handle_candidate_event(None, mgr, owner, et, ev))
    towner = tr.worker_id('drv-tr')
    events = await tr.claim('signal.delivered', towner, limit=50)
    await tr.register_new_signals()
    if hasattr(tr, 'reconcile_delivery_events'):
        await tr.reconcile_delivery_events(events, towner)
    trade = await pool.fetchrow("SELECT id, entry_price FROM active_trades WHERE signal_id=$1", sid)
    key = await pool.fetchval("SELECT setup_key FROM signals WHERE id=$1", sid)
    await pool.close()
    print(json.dumps({'signal_id': sid, 'delivered': delivered, 'trade_opened': trade is not None,
                      'setup_key': key, 'schema_required': __import__('shared.schema').schema
                      .REQUIRED_SCHEMA_VERSION}))


if __name__ == '__main__':
    root, dsn, symbol = sys.argv[1], sys.argv[2], sys.argv[3]
    asyncio.run(main(root, dsn, symbol, float(sys.argv[4]) if len(sys.argv) > 4 else 99.5))
