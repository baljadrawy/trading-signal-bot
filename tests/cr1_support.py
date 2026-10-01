"""Helpers for the CR-1 (signal.ready) tests.

The repo's `telegram/` directory shadows python-telegram-bot, so telegram/main.py
is normally importable only inside its image. These tests load the REAL file
under a private alias with minimal stand-ins for the python-telegram-bot names it
references at import time. Every stand-in is removed from sys.modules again, so
other test modules see the interpreter exactly as before.
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_ALIAS = 'tsb_cr1_telegram_main'


def _stub_ptb():
    class _Any:
        def __init__(self, *a, **k):
            self.args, self.kwargs = a, k

    tg = types.ModuleType('telegram')
    for name in ('Bot', 'BotCommand', 'InlineKeyboardButton',
                 'InlineKeyboardMarkup', 'Update'):
        setattr(tg, name, type(name, (_Any,), {}))
    ext = types.ModuleType('telegram.ext')
    for name in ('Application', 'CallbackQueryHandler', 'CommandHandler'):
        setattr(ext, name, type(name, (_Any,), {}))
    ext.ContextTypes = type('ContextTypes', (), {'DEFAULT_TYPE': object})
    tg.ext = ext
    return {'telegram': tg, 'telegram.ext': ext}


def load_telegram_main():
    if _ALIAS in sys.modules:
        return sys.modules[_ALIAS]
    for p in (str(REPO),):
        if p not in sys.path:
            sys.path.insert(0, p)
    saved = {k: sys.modules.get(k) for k in ('telegram', 'telegram.ext', 'whitelist')}
    tg_dir = str(REPO / 'telegram')
    sys.path.insert(0, tg_dir)
    try:
        sys.modules.update(_stub_ptb())
        sys.modules.pop('whitelist', None)
        spec = importlib.util.spec_from_file_location(_ALIAS, REPO / 'telegram' / 'main.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_ALIAS] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(tg_dir)
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def load_tracker_main():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import trade_tracker.main as tracker
    return tracker


def load_signal_logic():
    for p in (str(REPO), str(REPO / 'signal_engine')):
        if p not in sys.path:
            sys.path.insert(0, p)
    import signal_logic
    return signal_logic


def valid_signal(symbol='CR1USDT', **overrides):
    signal = {
        'symbol': symbol, 'timeframe': '4h', 'market_condition': 'bullish',
        'entry_price': 100.0, 'target_1': 102.0, 'target_2': 104.0, 'target_3': 106.0,
        'stop_loss': 97.0, 'total_score': 4, 'trade_type': 'reversion',
        'score_details': {}, 'confirmed_timeframes': ['4h'],
        'timeframe_confirmations': 1, 'macro_snapshot': {'usdtd_trend': 'flat'},
    }
    signal.update(overrides)
    return signal
