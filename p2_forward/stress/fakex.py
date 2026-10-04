"""Offline fake Binance-Spot public market-data server (TLS WebSocket + REST) for the G3-F4 stress harness.

Runs in its OWN container (own cgroup, so its CPU is never charged to the collector's 0.5-CPU budget) with no
external network; the collector container joins its network namespace and reaches it over loopback only.
Message rates are calibrated to G3-v6 (conn0-book ~530 msgs/s incl. !miniTicker@arr, conn1-depth ~48 msgs/s).
Deterministic: every random choice comes from a seeded generator.
"""
import asyncio
import heapq
import os
import json
import random
import ssl
import sys
import time

from aiohttp import web, WSMsgType

from . import fakedata as F

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
LISTING_MS = 1_577_836_800_000                 # 2020-01-01: first-ever candle of every synthetic symbol
U = [1_000_000]                                # global, monotonic update id (as on Binance)
STATS = {"ws_msgs": 0, "rest": 0, "conns": 0, "universe_evals": 0}
SHIFT = os.environ.get("STRESS_UNIVERSE_SHIFT") == "1"                # P2-CR V3: universe drifts per evaluation


def book_rate(sym: str) -> float:
    return 60.0 if sym in ("BTCUSDT", "ETHUSDT") else 6.7          # 2 x 60 + 61 x 6.7 + 1 market/s ~ 530/s


def _book(sym: str, rnd) -> str:
    p = F.price(sym) * (1 + rnd.uniform(-0.001, 0.001))
    U[0] += 1
    return json.dumps({"stream": f"{sym.lower()}@bookTicker",
                       "data": {"u": U[0], "s": sym, "b": f"{p:.8f}", "B": f"{rnd.uniform(0.1, 50):.8f}",
                                "a": f"{p * 1.0001:.8f}", "A": f"{rnd.uniform(0.1, 50):.8f}"}}, separators=(",", ":"))


def _depth(stream: str, sym: str, n: int, rnd) -> str:
    p = F.price(sym)
    U[0] += 1
    bids = [[f"{p * (1 - 0.0001 * (i + 1)):.8f}", f"{rnd.uniform(0.01, 20):.8f}"] for i in range(n)]
    asks = [[f"{p * (1 + 0.0001 * (i + 1)):.8f}", f"{rnd.uniform(0.01, 20):.8f}"] for i in range(n)]
    return json.dumps({"stream": stream, "data": {"lastUpdateId": U[0], "bids": bids, "asks": asks}},
                      separators=(",", ":"))


def _market(rnd) -> str:
    E = int(time.time() * 1000) - 3
    syms = rnd.sample(F.symbols(), 300)
    data = []
    for s in syms:
        p = F.price(s)
        data.append({"e": "24hrMiniTicker", "E": E, "s": s, "c": f"{p:.8f}", "o": f"{p * 0.99:.8f}",
                     "h": f"{p * 1.02:.8f}", "l": f"{p * 0.97:.8f}", "v": "123456.00000000", "q": "9876543.21000000"})
    return json.dumps({"stream": "!miniTicker@arr", "data": data}, separators=(",", ":"))


async def ws_handler(request):
    ws = web.WebSocketResponse(autoping=True, heartbeat=None, max_msg_size=8 * 2**20)
    await ws.prepare(request)
    STATS["conns"] += 1
    rnd = random.Random(1000 + STATS["conns"])
    streams = [s for s in request.query.get("streams", "").split("/") if s]
    heap = []                                   # (due, seq, stream)
    seq = [0]

    def add(s):
        seq[0] += 1
        heapq.heappush(heap, (time.time() + rnd.uniform(0, 1.0), seq[0], s))

    for s in streams:
        add(s)

    async def sender():
        while not ws.closed:
            now = time.time()
            if not heap or heap[0][0] > now:
                await asyncio.sleep(min(0.02, (heap[0][0] - now) if heap else 0.02))
                continue
            due, _, s = heapq.heappop(heap)
            sym = s.split("@")[0].upper()
            msg = None
            if s.endswith("@bookTicker"):
                msg = _book(sym, rnd)
                nxt = due + rnd.expovariate(book_rate(sym))
            elif "@depth" in s:
                n = int(s.split("@depth")[1].split("@")[0])
                if n == 20 or rnd.random() < 0.74:                   # quiet Tier-1/2 books skip some seconds
                    msg = _depth(s, sym, n, rnd)
                nxt = due + 1.0
            elif s == "!miniTicker@arr":
                msg = _market(rnd)
                nxt = due + 1.0
            else:
                continue
            seq[0] += 1
            heapq.heappush(heap, (max(nxt, now - 1.0), seq[0], s))
            if msg is not None:
                try:
                    await ws.send_str(msg)
                    STATS["ws_msgs"] += 1
                except (ConnectionResetError, RuntimeError):
                    return

    task = asyncio.create_task(sender())
    try:
        async for m in ws:
            if m.type == WSMsgType.TEXT:
                req = json.loads(m.data)
                if req.get("method") == "SUBSCRIBE":
                    for s in req.get("params", []):
                        add(s)
                await ws.send_str(json.dumps({"result": None, "id": req.get("id")}))
            elif m.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        task.cancel()
    return ws


def _hdr():
    return {"x-mbx-used-weight-1m": "3"}


async def rest_time(request):
    STATS["rest"] += 1
    return web.json_response({"serverTime": int(time.time() * 1000)}, headers=_hdr())


async def rest_exinfo(request):
    STATS["rest"] += 1
    STATS["universe_evals"] += 1
    return web.json_response(F.exchange_info(STATS["universe_evals"] if SHIFT else 0), headers=_hdr())


async def rest_ticker(request):
    STATS["rest"] += 1
    return web.json_response(F.tickers(shift=STATS["universe_evals"] if SHIFT else 0), headers=_hdr())


async def rest_klines(request):
    STATS["rest"] += 1
    q = request.query
    L = TF_MS[q["interval"]]
    start = int(q.get("startTime", 0))
    o = LISTING_MS if start == 0 else (start // L) * L
    if o + L > int(time.time() * 1000) + L:                           # future: nothing
        return web.json_response([], headers=_hdr())
    p = F.price(q["symbol"])
    k = [o, f"{p:.8f}", f"{p * 1.01:.8f}", f"{p * 0.99:.8f}", f"{p * 1.001:.8f}", "1234.50000000", o + L - 1,
         "98765.43210000", 4321, "600.00000000", "48000.00000000", "0"]
    return web.json_response([k], headers=_hdr())


async def stats_task(path):
    while True:
        await asyncio.sleep(10)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), **STATS}) + "\n")


def serve(cert: str, key: str, port: int, stats_path: str) -> None:
    app = web.Application()
    app.router.add_get("/stream", ws_handler)
    app.router.add_get("/api/v3/time", rest_time)
    app.router.add_get("/api/v3/exchangeInfo", rest_exinfo)
    app.router.add_get("/api/v3/ticker/24hr", rest_ticker)
    app.router.add_get("/api/v3/klines", rest_klines)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert, key)

    async def on_start(app_):
        app_["stats"] = asyncio.create_task(stats_task(stats_path))
    app.on_startup.append(on_start)
    print(f"fakex listening 127.0.0.1:{port}", flush=True, file=sys.stderr)
    web.run_app(app, host="127.0.0.1", port=port, ssl_context=ctx, print=None)
