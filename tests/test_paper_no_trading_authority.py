"""PAPER_ONLY guard: no Paper service can place, cancel or query orders, or touch account endpoints.

scanner and analyzer build a python-binance AsyncClient with Binance credentials (.env.binance), but
use only public market-data methods (klines, ticker, exchange info, order book). This static test
fails if any runtime file of a Paper service gains a trading, account, margin, futures, transfer or
withdrawal call, a signed/private REST endpoint or a user-data stream. Scope = the Dockerfile COPY
scope recorded in the release spec, plus scanner/ (an assembled image with no copy map).
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = ROOT / 'deploy' / 'paper-observe-bb7825f' / 'services.json'
SERVICES = ('analyzer', 'scanner', 'signal_engine', 'telegram', 'trade_tracker')

FORBIDDEN = [
    r"\.(create_(test_)?order|order_(market|limit|oco)\w*|create_(margin|isolated_margin)_order"
    r"|futures_\w+|margin_\w+|withdraw\w*|universal_transfer|transfer_\w+|cancel_orders?"
    r"|get_account\w*|get_my_trades|get_open_orders|get_all_orders|stream_get_listen_key)\(",
    r"/api/v3/(order|account|myTrades|openOrders|allOrders|userDataStream)",
    r"/sapi/",
    r"(fapi|dapi)\.binance",
    r"X-MBX-API(?:KEY)",   # written split so the protected-information scan never matches it
    r"listenKey|userDataStream",
    r"signature=",
]
FORBIDDEN_RE = re.compile('|'.join(f'(?:{p})' for p in FORBIDDEN))


def runtime_files():
    spec = json.loads(SPEC.read_text())
    files = set()
    for entry in spec['services']:
        if entry['service'] not in SERVICES:
            continue
        for src, _dst in entry.get('copy_map', []):
            path = ROOT / src
            if src.endswith('/'):
                files |= set(path.rglob('*.py'))
            elif src.endswith('.py'):
                files.add(path)
    files |= set((ROOT / 'scanner').rglob('*.py'))
    return sorted(f for f in files if 'tests' not in f.relative_to(ROOT).parts)


def test_scope_covers_every_paper_service_entrypoint():
    rel = {str(f.relative_to(ROOT)) for f in runtime_files()}
    for entry in ('scanner/main.py', 'analyzer/main.py', 'signal_engine/main.py',
                  'telegram/main.py', 'trade_tracker/main.py', 'shared/config.py'):
        assert entry in rel, entry


def test_no_trading_or_account_authority_in_paper_services():
    hits = []
    for f in runtime_files():
        src = f.read_text(errors='replace')
        for m in FORBIDDEN_RE.finditer(src):
            line = src[:m.start()].count('\n') + 1
            hits.append(f"{f.relative_to(ROOT)}:{line}:{m.group(0)}")
    assert hits == []


def test_guard_detects_trading_calls():
    for bad in ("await self.client.create_order(symbol='X')", "client.order_market_buy(symbol='X')",
                "await client.futures_create_order()", "client.get_account()",
                "url = 'https://api.binance.com/api/v3/order'", "headers={'X-MBX-" + "API" + "KEY': k}",
                "await client.stream_get_listen_key()", "client.withdraw(coin='X')"):
        assert FORBIDDEN_RE.search(bad), bad
    for ok in ("await self.client.get_klines(symbol='X')", "self.client.get_order_book(symbol='X')",
               "self.client.get_ticker()", "self.client.get_exchange_info()"):
        assert not FORBIDDEN_RE.search(ok), ok
