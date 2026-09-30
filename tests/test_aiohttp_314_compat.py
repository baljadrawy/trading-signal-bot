"""aiohttp 3.14.3 compatibility checks (security remediation 2026-09-29).

Offline only: every HTTP/WebSocket peer is a local aiohttp.web server on
127.0.0.1 inside the test process. No credentials, no Binance/Telegram access,
no database.

Runs two ways:
  * pytest (repo layout, e.g. the pytestenv image):  pytest tests/test_aiohttp_314_compat.py
  * plain python inside a service image (/app layout, no pytest installed):
        python /compat/test_aiohttp_314_compat.py <group> [<group> ...]
    groups: version retry binance ws direct_alerts direct_tracker
            direct_telegram claude_review
"""
import asyncio
import gc
import importlib
import importlib.util
import json
import os
import sys
import time
import types
import warnings
from pathlib import Path
from unittest import mock

import aiohttp
from aiohttp import web
from yarl import URL

EXPECTED_AIOHTTP = "3.14.3"
REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_MODE = Path("/app/shared").is_dir() and not (REPO_ROOT / "shared").is_dir()


class Skip(Exception):
    pass


# ----------------------------------------------------------------- helpers
def _ensure_path(p):
    p = str(p)
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_service_module(service, name, alias):
    """Import <service>/<name>.py from /app (image) or the repo checkout."""
    if IMAGE_MODE:
        _ensure_path("/app")
        path = Path("/app") / f"{name}.py"
    else:
        _ensure_path(REPO_ROOT)
        _ensure_path(REPO_ROOT / service)
        path = REPO_ROOT / service / f"{name}.py"
    if not path.is_file():
        raise Skip(f"{path} not present")
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(
        alias, path, submodule_search_locations=None)
    mod = importlib.util.module_from_spec(spec)
    if not IMAGE_MODE and service == "trade_tracker":
        mod.__package__ = "trade_tracker"  # allow `from .binance_price_stream`
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _import_shared(name):
    _ensure_path("/app" if IMAGE_MODE else REPO_ROOT)
    return importlib.import_module(f"shared.{name}")


class LocalServer:
    """Minimal aiohttp.web server on 127.0.0.1:<ephemeral>."""

    def __init__(self, app):
        self.app = app
        self.runner = None
        self.port = None

    async def __aenter__(self):
        self.runner = web.AppRunner(self.app, handle_signals=False)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        await self.runner.cleanup()


def _no_ctl(raw_headers):
    bad = []
    for k, v in raw_headers:
        for b in k + v:
            if (b < 0x20 and b != 0x09) or b == 0x7F:
                bad.append((k, v))
                break
    return bad


class Recorder:
    def __init__(self):
        self.requests = []

    def add(self, request, body=None):
        self.requests.append({
            "method": request.method,
            "path": request.path,
            "query": dict(request.query),
            "headers": dict(request.headers),
            "raw_headers": list(request.raw_headers),
            "body": body,
        })


def _run(coro_fn, results, group):
    """Run one async case with warnings captured."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        t0 = time.monotonic()
        try:
            detail = asyncio.run(coro_fn())
            status = "PASS"
        except Skip as exc:
            status, detail = "SKIP", str(exc)
        except AssertionError as exc:
            status, detail = "FAIL", f"AssertionError: {exc}"
        except Exception as exc:  # noqa: BLE001
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
        gc.collect()
        dt = time.monotonic() - t0
    warns = sorted({f"{w.category.__name__}: {str(w.message)[:160]} "
                    f"({Path(w.filename).name}:{w.lineno})" for w in caught})
    results.append({"group": group, "case": coro_fn.__name__, "status": status,
                    "seconds": round(dt, 2), "detail": detail, "warnings": warns})
    return results[-1]


# ------------------------------------------------------------ 5. version
async def case_version():
    assert aiohttp.__version__ == EXPECTED_AIOHTTP, aiohttp.__version__
    import importlib.metadata as md
    assert md.version("aiohttp") == EXPECTED_AIOHTTP
    dists = []
    for entry in sys.path:
        p = Path(entry or ".")
        if p.is_dir():
            dists += [d.name for d in p.glob("aiohttp-*.dist-info")]
    assert dists and all(d == f"aiohttp-{EXPECTED_AIOHTTP}.dist-info" for d in dists), dists
    assert not any("3.13.5" in d for d in dists), dists
    return {"aiohttp": aiohttp.__version__, "dist_info": sorted(set(dists)),
            "file": aiohttp.__file__}


# ------------------------------------------------ 4. retry_utils / alerts
async def case_retry_utils():
    ru = _import_shared("retry_utils")
    names = ["ClientConnectionError", "ClientConnectorError",
             "ServerDisconnectedError", "ClientOSError", "ClientTimeout",
             "ClientSession", "WSMsgType", "ServerTimeoutError"]
    missing = [n for n in names if not hasattr(aiohttp, n)]
    assert not missing, missing
    for cls in (aiohttp.ClientConnectionError, aiohttp.ClientConnectorError,
                aiohttp.ServerDisconnectedError, aiohttp.ClientOSError):
        assert cls in ru.NETWORK_EXC, cls
    assert ru.is_network_error(aiohttp.ServerDisconnectedError())
    assert ru.is_network_error(aiohttp.ClientOSError(104, "reset"))
    assert ru.is_network_error(asyncio.TimeoutError())
    assert not ru.is_network_error(ValueError("x"))
    alerts = _import_shared("alerts")
    assert asyncio.iscoroutinefunction(alerts.send_alert)
    return {"network_exc": len(ru.NETWORK_EXC)}


async def case_claude_review_import():
    mod = _load_service_module("claude_review", "main", "cr_main_compat")
    assert asyncio.iscoroutinefunction(mod.main)
    assert mod.send_alert is _import_shared("alerts").send_alert
    return {"module": mod.__file__}


# ------------------------------------------------ 1. python-binance 1.0.19
def _binance_app(rec):
    async def ping(request):
        rec.add(request)
        return web.json_response({})

    async def srv_time(request):
        rec.add(request)
        return web.json_response({"serverTime": int(time.time() * 1000)})

    async def klines(request):
        rec.add(request)
        if request.query.get("symbol") == "BADSYM":
            return web.json_response({"code": -1121, "msg": "Invalid symbol."}, status=400)
        n = int(request.query.get("limit", 2))
        now = int(time.time() * 1000)
        rows = [[now - (n - i) * 3600000, "1.0", "2.0", "0.5", "1.5", "10",
                 now - (n - i - 1) * 3600000 - 1, "15", 3, "5", "7.5", "0"]
                for i in range(n)]
        return web.json_response(rows)

    async def depth(request):
        rec.add(request)
        if request.query.get("symbol") == "SLOWUSDT":
            await asyncio.sleep(3)
        return web.json_response({"lastUpdateId": 1, "bids": [["1.0", "2"]],
                                  "asks": [["1.1", "3"]]})

    app = web.Application()
    app.router.add_get("/api/v3/ping", ping)
    app.router.add_get("/api/v3/time", srv_time)
    app.router.add_get("/api/v3/klines", klines)
    app.router.add_get("/api/v3/depth", depth)
    return app


async def case_binance_asyncclient():
    try:
        from binance import AsyncClient
        from binance.exceptions import BinanceAPIException
    except ImportError as exc:
        raise Skip(f"python-binance not installed: {exc}")
    import binance
    rec = Recorder()
    out = {"python_binance": getattr(binance, "__version__", "?")}
    async with LocalServer(_binance_app(rec)) as srv:
        with mock.patch.object(AsyncClient, "API_URL", f"http://127.0.0.1:{srv.port}/api"):
            # (a) production pattern: AsyncClient.create() -> _init_session(loop=...)
            client = await AsyncClient.create()
            try:
                assert isinstance(client.session, aiohttp.ClientSession)
                assert client.session._loop is asyncio.get_running_loop()
                assert await client.ping() == {}
                kl = await client.get_klines(symbol="BTCUSDT", interval="1h", limit=5)
                assert len(kl) == 5 and len(kl[0]) == 12
                ob = await client.get_order_book(symbol="BTCUSDT", limit=5)
                assert ob["bids"] == [["1.0", "2"]]
                try:
                    await client.get_klines(symbol="BADSYM", interval="1h")
                    raise AssertionError("non-2xx did not raise")
                except BinanceAPIException as exc:
                    assert exc.status_code == 400 and exc.code == -1121
            finally:
                await client.close_connection()
            assert client.session.closed
            paths = [r["path"] for r in rec.requests]
            assert paths[:5] == ["/api/v3/ping", "/api/v3/time", "/api/v3/ping",
                                 "/api/v3/klines", "/api/v3/depth"], paths
            kq = rec.requests[3]["query"]
            assert kq == {"interval": "1h", "limit": "5", "symbol": "BTCUSDT"}, kq
            assert rec.requests[4]["query"] == {"limit": "5", "symbol": "BTCUSDT"}
            for r in rec.requests:
                assert "X-MBX-APIKEY" not in r["headers"], r["headers"]
                assert r["headers"]["User-Agent"].startswith("Mozilla/5.0")
                assert r["headers"]["Accept"] == "application/json"
                assert not _no_ctl(r["raw_headers"]), _no_ctl(r["raw_headers"])
            n_anon = len(rec.requests)

            # (b) dummy api key -> X-MBX-APIKEY header (public endpoints only)
            client = await AsyncClient.create(api_key="dummy-key-not-real",
                                              api_secret="dummy-secret-not-real")
            try:
                await client.get_order_book(symbol="ETHUSDT", limit=10)
            finally:
                await client.close_connection()
            for r in rec.requests[n_anon:]:
                assert r["headers"].get("X-MBX-APIKEY") == "dummy-key-not-real", r["headers"]
                assert not _no_ctl(r["raw_headers"])

            # (c) timeout through requests_params (float, as python-binance passes it)
            for tmo in (0.5, aiohttp.ClientTimeout(total=0.5)):
                client = AsyncClient(requests_params={"timeout": tmo})
                t0 = time.monotonic()
                try:
                    await client.get_order_book(symbol="SLOWUSDT")
                    raise AssertionError("delayed endpoint did not time out")
                except asyncio.TimeoutError as exc:
                    el = time.monotonic() - t0
                    assert 0.3 < el < 2.5, el
                    out.setdefault("timeout", []).append(
                        f"{type(tmo).__name__}->{type(exc).__name__} in {el:.2f}s")
                finally:
                    await client.close_connection()
                assert client.session.closed
            # (d) default REQUEST_TIMEOUT (float 10) passed on every request worked above
            out["default_request_timeout"] = AsyncClient.REQUEST_TIMEOUT
    out["requests_seen"] = len(rec.requests)
    return out


# --------------------------------------- 2. trade_tracker price stream (WS)
def _load_price_stream():
    if IMAGE_MODE:
        _ensure_path("/app")
        if not Path("/app/binance_price_stream.py").is_file():
            raise Skip("binance_price_stream.py not in this image")
        return importlib.import_module("binance_price_stream").BinancePriceStream
    _ensure_path(REPO_ROOT)
    return importlib.import_module("trade_tracker.binance_price_stream").BinancePriceStream


async def case_ws_price_stream():
    """Production kwargs unchanged. Note: ws_connect(compress=0) is aiohttp's
    default on both 3.13.5 and 3.14.3, so the stream does NOT offer
    permessage-deflate; frames arrive uncompressed."""
    return await _ws_price_stream(force_deflate=False)


async def case_ws_price_stream_deflate():
    """Same production stream code; the spy adds compress=15 to ws_connect so
    permessage-deflate is negotiated and the 50 kB frame arrives compressed."""
    return await _ws_price_stream(force_deflate=True)


async def _ws_price_stream(force_deflate):
    BinancePriceStream = _load_price_stream()
    log = {"conns": 0, "subs": [], "pong": None, "ext_req": [], "srv_compress": [],
           "closed_by_client": asyncio.Event(), "conn2_close": None}
    ws_kwargs = []

    async def handler(request):
        log["conns"] += 1
        n = log["conns"]
        log["ext_req"].append(request.headers.get("Sec-WebSocket-Extensions"))
        ws = web.WebSocketResponse(autoping=False)
        await ws.prepare(request)
        log["srv_compress"].append(ws.compress)
        sub = await ws.receive_json(timeout=5)
        log["subs"].append(sub)
        if n == 1:
            await ws.send_str(json.dumps({"result": None, "id": sub["id"]}))
            await ws.send_str(json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": 1, "p": "100.5"}))
            await ws.send_str(json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": 1, "p": "999"}))  # dup id
            await ws.send_str(json.dumps({"e": "aggTrade", "s": "ETHUSDT", "a": 5, "p": "3"}))  # not subscribed
            big = {"e": "aggTrade", "s": "BTCUSDT", "a": 2, "p": "101.25", "pad": "x" * 50000}
            await ws.send_str(json.dumps(big))  # compressed frame (permessage-deflate)
            await ws.ping(b"srv-ping")
            while True:
                msg = await ws.receive(timeout=5)
                if msg.type == aiohttp.WSMsgType.PONG:
                    log["pong"] = msg.data
                    break
            await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b"server bye")
        else:
            await asyncio.sleep(2.5)  # several receive() timeouts/cancellations on client
            await ws.send_str(json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": 3, "p": "102"}))
            msg = await ws.receive(timeout=60)
            log["conn2_close"] = (msg.type.name, ws.close_code)
            log["closed_by_client"].set()
        return ws

    app = web.Application()
    app.router.add_get("/ws", handler)
    prices = []
    got_third = asyncio.Event()

    async def on_price(sym, price):
        prices.append((sym, price))
        if price == 102.0:
            got_third.set()

    orig = aiohttp.ClientSession._ws_connect

    async def spy(self, url, **kw):
        if force_deflate:
            kw["compress"] = 15
        ws = await orig(self, url, **kw)
        ws_kwargs.append({"heartbeat": kw.get("heartbeat"), "autoping": kw.get("autoping"),
                          "negotiated_compress": ws.compress,
                          "client_heartbeat_attr": getattr(ws, "_heartbeat", None)})
        return ws

    logger = mock.Mock()
    async with LocalServer(app) as srv:
        stream = BinancePriceStream(symbol_provider=mock.AsyncMock(return_value={"BTCUSDT"}),
                                    on_price=on_price, logger=logger, refresh_seconds=1)
        stream.URL = f"ws://127.0.0.1:{srv.port}/ws"
        with mock.patch.object(aiohttp.ClientSession, "_ws_connect", spy):
            task = asyncio.create_task(stream.run())
            await asyncio.wait_for(got_third.wait(), timeout=25)
            snap = stream.snapshot()
            task.cancel()
            try:
                await task
                raise AssertionError("run() did not propagate cancellation")
            except asyncio.CancelledError:
                pass
            await asyncio.wait_for(log["closed_by_client"].wait(), timeout=5)
    assert log["conns"] == 2, log["conns"]
    for s in log["subs"]:
        assert s == {"method": "SUBSCRIBE", "params": ["btcusdt@aggTrade"], "id": 1}, s
    assert prices == [("BTCUSDT", 100.5), ("BTCUSDT", 101.25), ("BTCUSDT", 102.0)], prices
    assert log["pong"] == b"srv-ping", log["pong"]
    assert all(k["heartbeat"] == 20 and k["autoping"] is True for k in ws_kwargs), ws_kwargs
    if force_deflate:
        assert all(e and "permessage-deflate" in e for e in log["ext_req"]), log["ext_req"]
        assert all(k["negotiated_compress"] == 15 for k in ws_kwargs), ws_kwargs
        assert all(c == 15 for c in log["srv_compress"]), log["srv_compress"]
    else:
        assert log["ext_req"] == [None, None], log["ext_req"]
        assert all(k["negotiated_compress"] == 0 for k in ws_kwargs), ws_kwargs
    assert log["conn2_close"][0] == "CLOSE", log["conn2_close"]
    assert snap["connected"] is True and snap["symbols_cached"] == 1, snap
    assert logger.warning.called  # short outage -> reconnect path
    assert not logger.exception.called and not logger.error.called
    return {"conns": log["conns"], "prices": prices, "pong": log["pong"].decode(),
            "ws_connect": ws_kwargs, "srv_compress": log["srv_compress"],
            "ext_offer": log["ext_req"][0], "conn2_close": log["conn2_close"]}


async def case_ws_heartbeat_equivalent():
    """Equivalent call (same kwargs as production, heartbeat shortened 20->1)."""
    pings = []

    async def handler(request):
        ws = web.WebSocketResponse(autoping=False)
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.PING:
                pings.append(msg.data)
                await ws.pong(msg.data)
                if len(pings) >= 2:
                    break
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/ws", handler)
    async with LocalServer(app) as srv:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(f"ws://127.0.0.1:{srv.port}/ws",
                                          heartbeat=1, autoping=True) as ws:
                t0 = time.monotonic()
                msg = await asyncio.wait_for(ws.receive(), timeout=6)
                el = time.monotonic() - t0
    assert len(pings) >= 2, pings
    assert msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED), msg
    return {"client_pings_seen": len(pings), "seconds": round(el, 2)}


# ------------------------------------------ 3. direct aiohttp call sites
class Redirect:
    """Patch ClientSession._request (class level) so the production code's own
    ClientSession()/get()/post() calls and kwargs are used unchanged, and only
    the hard-coded https://api.binance.com / api.telegram.org URL is rewritten
    to http://127.0.0.1:<port> with identical path + query."""

    HOSTS = {"api.binance.com", "api.telegram.org"}

    def __init__(self, port):
        self.port = port
        self.calls = []
        self._orig = aiohttp.ClientSession._request
        self._patch = None

    def __enter__(self):
        red = self

        def _request(session, method, str_or_url, **kw):
            url = URL(str_or_url)
            red.calls.append({"method": method, "url": str(url),
                              "timeout": kw.get("timeout"), "params": kw.get("params"),
                              "has_json": "json" in kw, "headers": kw.get("headers")})
            if url.host in red.HOSTS:
                url = url.with_scheme("http").with_host("127.0.0.1").with_port(red.port)
            else:
                raise AssertionError(f"unexpected outbound host {url.host}")
            return red._orig(session, method, url, **kw)

        self._patch = mock.patch.object(aiohttp.ClientSession, "_request", _request)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def _direct_app(rec, mode):
    async def ticker(request):
        rec.add(request)
        m = mode["m"]
        if m == "slow":
            await asyncio.sleep(7)
        if m == "err":
            return web.Response(status=503, text="upstream unavailable")
        if m == "noprice":
            return web.json_response({"code": 0})
        return web.json_response({"symbol": request.query["symbol"], "price": "123.45"})

    async def exinfo(request):
        rec.add(request)
        if mode["m"] == "err":
            return web.Response(status=500, text="boom")
        return web.json_response({"symbols": [{"filters": [
            {"filterType": "NOTIONAL", "minNotional": "5.00"},
            {"filterType": "LOT_SIZE", "minQty": "0.1"}]}]})

    async def klines(request):
        rec.add(request)
        if mode["m"] == "err":
            return web.Response(status=429, text="rate")
        now = int(time.time() * 1000)
        return web.json_response([
            [now - 7200000, "1", "1", "1", "9.5", "1", now - 3600001, "1", 1, "1", "1", "0"],
            [now - 3600000, "1", "1", "1", "9.9", "1", now + 3600000, "1", 1, "1", "1", "0"]])

    async def tg_send(request):
        body = await request.json()
        rec.add(request, body)
        m = mode["m"]
        if m == "slow":
            await asyncio.sleep(12)
        if m == "err":
            return web.json_response({"ok": False, "description": "Bad Request"}, status=400)
        return web.json_response({"ok": True, "result": {"message_id": 1}})

    app = web.Application()
    app.router.add_get("/api/v3/ticker/price", ticker)
    app.router.add_get("/api/v3/exchangeInfo", exinfo)
    app.router.add_get("/api/v3/klines", klines)
    app.router.add_post("/bot{token}/sendMessage", tg_send)
    return app


def _check_headers(rec):
    for r in rec.requests:
        bad = _no_ctl(r["raw_headers"])
        assert not bad, bad
        assert r["headers"].get("Host", "").startswith("127.0.0.1:"), r["headers"]


async def case_direct_alerts():
    alerts = _import_shared("alerts")
    rec, mode = Recorder(), {"m": "ok"}
    log = mock.Mock()
    out = {}
    async with LocalServer(_direct_app(rec, mode)) as srv:
        with Redirect(srv.port) as red, \
                mock.patch.object(alerts.config, "TELEGRAM_BOT_TOKEN", "000000:DUMMY-NOT-A-TOKEN"), \
                mock.patch.object(alerts.config, "TELEGRAM_CHAT_ID", "1"), \
                mock.patch.object(alerts, "logger", log):
            await alerts.send_alert("hello", "critical", "compat")
            assert not log.error.called, log.error.call_args
            assert rec.requests[-1]["body"] == {"chat_id": "1", "text": "🚨 [compat] hello"}
            assert rec.requests[-1]["path"] == "/bot000000:DUMMY-NOT-A-TOKEN/sendMessage"
            mode["m"] = "err"
            await alerts.send_alert("x")
            msg = log.error.call_args[0][0]
            assert "HTTP 400" in msg and "Bad Request" in msg, msg
            log.reset_mock()
            mode["m"] = "slow"
            t0 = time.monotonic()
            await alerts.send_alert("y")  # ClientTimeout(total=10)
            el = time.monotonic() - t0
            msg = log.error.call_args[0][0]
            assert "Timeout" in msg and 9 < el < 11.5, (msg, el)
            out["timeout"] = f"{msg[-60:]} after {el:.2f}s"
            t = red.calls[0]["timeout"]
            assert isinstance(t, aiohttp.ClientTimeout) and t.total == 10, t
            assert all(c["headers"] is None and c["has_json"] for c in red.calls)
    _check_headers(rec)
    out["calls"] = len(red.calls)
    return out


async def case_direct_tracker():
    try:
        mod = _load_service_module("trade_tracker", "main", "tt_main_compat")
    except ImportError as exc:
        raise Skip(f"trade_tracker.main not importable here: {exc}")
    rec, mode = Recorder(), {"m": "ok"}
    log = mock.Mock()
    out = {}
    async with LocalServer(_direct_app(rec, mode)) as srv:
        with Redirect(srv.port) as red, mock.patch.object(mod, "logger", log):
            assert await mod.get_current_price("BTCUSDT") == 123.45
            assert rec.requests[-1]["query"] == {"symbol": "BTCUSDT"}
            assert await mod.get_min_notional("BTCUSDT") == 5.0
            assert rec.requests[-1]["query"] == {"symbol": "BTCUSDT"}
            c = await mod.get_last_closed_candle("BTCUSDT", "1h")
            assert c and c["close"] == 9.5, c
            assert rec.requests[-1]["query"] == {"symbol": "BTCUSDT", "interval": "1h", "limit": "2"}
            assert not log.error.called and not log.warning.called
            mode["m"] = "err"
            assert await mod.get_current_price("ETHUSDT") is None
            assert "Binance HTTP 503" in log.error.call_args[0][0]
            mod._min_notional_cache.clear()
            fb = await mod.get_min_notional("ETHUSDT")
            assert fb == mod.config.MIN_ORDER_NOTIONAL_USDT
            assert "HTTP 500" in log.warning.call_args[0][0]
            assert await mod.get_last_closed_candle("ETHUSDT", "1h") is None
            assert "HTTP 429" in log.warning.call_args[0][0]
            mode["m"] = "noprice"
            assert await mod.get_current_price("ETHUSDT") is None
            mode["m"] = "slow"
            t0 = time.monotonic()
            assert await mod.get_current_price("SOLUSDT") is None  # ClientTimeout(total=5)
            el = time.monotonic() - t0
            assert 4.5 < el < 6.5 and "Timeout" in log.error.call_args[0][0], (el, log.error.call_args)
            out["timeout"] = f"{el:.2f}s"
            for c in red.calls:
                assert isinstance(c["timeout"], aiohttp.ClientTimeout) and c["timeout"].total == 5
                assert c["headers"] is None
    _check_headers(rec)
    out["calls"] = len(red.calls)
    return out


async def case_direct_telegram():
    try:
        mod = _load_service_module("telegram", "main", "tg_main_compat")
    except ImportError as exc:
        raise Skip(f"telegram.main not importable here: {exc}")
    wl_path = (Path("/app") if IMAGE_MODE else REPO_ROOT / "telegram") / "whitelist.py"
    src = wl_path.read_text(encoding="utf-8")
    wl_aiohttp_uses = [ln.strip() for ln in src.splitlines()
                       if "aiohttp" in ln and not ln.strip().startswith("import aiohttp")]
    rec, mode = Recorder(), {"m": "ok"}
    log = mock.Mock()
    out = {"whitelist_aiohttp_calls": wl_aiohttp_uses}
    async with LocalServer(_direct_app(rec, mode)) as srv:
        with Redirect(srv.port) as red, mock.patch.object(mod, "logger", log):
            assert await mod.get_current_price("BTCUSDT") == 123.45
            assert rec.requests[-1]["query"] == {"symbol": "BTCUSDT"}
            mode["m"] = "err"
            assert await mod.get_current_price("BTCUSDT") is None
            assert "Binance HTTP 503" in log.warning.call_args[0][0]
            mode["m"] = "slow"
            t0 = time.monotonic()
            assert await mod.get_current_price("BTCUSDT") is None
            el = time.monotonic() - t0
            assert 4.5 < el < 6.5 and "Timeout" in log.warning.call_args[0][0], (el, log.warning.call_args)
            out["timeout"] = f"{el:.2f}s"
            assert all(c["timeout"].total == 5 and c["headers"] is None for c in red.calls)
    wl = sys.modules.get("whitelist")
    assert wl is not None and hasattr(wl, "WhitelistManager")
    assert wl_aiohttp_uses == [], wl_aiohttp_uses  # whitelist lookup is DB-only
    _check_headers(rec)
    out["calls"] = len(red.calls)
    return out


async def case_header_injection_guard():
    """aiohttp must refuse CR/LF in outgoing header values (static headers only)."""
    hits = []

    async def any_(request):
        hits.append(dict(request.headers))
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", any_)
    async with LocalServer(app) as srv:
        async with aiohttp.ClientSession() as s:
            try:
                async with s.get(f"http://127.0.0.1:{srv.port}/",
                                 headers={"X-Test": "a\r\nInjected: 1"}) as r:
                    await r.text()
                refused = False
            except (ValueError, aiohttp.ClientError) as exc:
                refused = type(exc).__name__
    assert refused and not any("Injected" in h for h in hits), (refused, hits)
    return {"refused_with": refused}


GROUPS = {
    "version": [case_version],
    "retry": [case_retry_utils],
    "binance": [case_binance_asyncclient],
    "ws": [case_ws_price_stream, case_ws_price_stream_deflate, case_ws_heartbeat_equivalent],
    "direct_alerts": [case_direct_alerts, case_header_injection_guard],
    "direct_tracker": [case_direct_tracker],
    "direct_telegram": [case_direct_telegram],
    "claude_review": [case_claude_review_import],
}


# --------------------------------------------------------------- pytest glue
def _pytest_case(fn):
    def test():
        import pytest
        res = _run(fn, [], "pytest")
        if res["status"] == "SKIP":
            pytest.skip(res["detail"])
        assert res["status"] == "PASS", res
    test.__name__ = "test_" + fn.__name__[5:]
    return test


if "pytest" in sys.modules:
    test_version = _pytest_case(case_version)
    test_retry_utils = _pytest_case(case_retry_utils)
    test_binance_asyncclient = _pytest_case(case_binance_asyncclient)
    test_ws_price_stream = _pytest_case(case_ws_price_stream)
    test_ws_price_stream_deflate = _pytest_case(case_ws_price_stream_deflate)
    test_ws_heartbeat_equivalent = _pytest_case(case_ws_heartbeat_equivalent)
    test_direct_alerts = _pytest_case(case_direct_alerts)
    test_header_injection_guard = _pytest_case(case_header_injection_guard)
    test_direct_tracker = _pytest_case(case_direct_tracker)
    test_direct_telegram = _pytest_case(case_direct_telegram)
    test_claude_review_import = _pytest_case(case_claude_review_import)


def main(argv):
    groups = argv or list(GROUPS)
    results = []
    for g in groups:
        for fn in GROUPS[g]:
            r = _run(fn, results, g)
            print("RESULT " + json.dumps(r, default=str, ensure_ascii=False), flush=True)
            if r["status"] == "FAIL":
                print("STOP: first failure", flush=True)
                return 1
    print("SUMMARY " + json.dumps({s: sum(r["status"] == s for r in results)
                                   for s in ("PASS", "FAIL", "SKIP")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
