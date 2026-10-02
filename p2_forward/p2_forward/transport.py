"""Public market-data transports: WebSocket streams and REST (aiohttp). Market-data-only hosts; allow-listed paths.

No API key, no signing, no order/account/user-data endpoint exists in this module (enforced by tests).
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.parse

import aiohttp

from . import config as C
from .guards import Backoff, RateGuard


class EndpointNotAllowed(Exception):
    pass


def _check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if u.hostname not in C.ALLOWED_HOSTS:
        raise EndpointNotAllowed(u.hostname)
    if u.scheme == "https" and u.path not in C.ALLOWED_REST_PATHS:
        raise EndpointNotAllowed(u.path)
    if u.scheme == "wss" and u.path != "/stream":
        raise EndpointNotAllowed(u.path)


class RestClient:
    """GET-only REST client with own budget, IP-weight yielding, 429/418 handling and per-path circuit breaker."""

    def __init__(self, session, guard: RateGuard, stats: dict, base: str = C.REST_BASE):
        self.session, self.guard, self.stats, self.base = session, guard, stats, base
        self.fail = {}             # path -> consecutive failures
        self.open_until = {}       # path -> monotonic time
        self.weight_used_total = 0

    async def get(self, path: str, params: dict | None = None, urgent: bool = False, timeout: float = 15.0):
        """Return (status, json|None, recv_ns, t0_ms, t1_ms) or (reason_str, None, ...) when not sent."""
        url = self.base + path
        _check_url(url)
        weight = C.ALLOWED_REST_PATHS[path]
        if time.monotonic() < self.open_until.get(path, 0):
            return "circuit_open", None, None, None, None
        ok, why = self.guard.allow(weight, urgent=urgent)
        if not ok:
            return why, None, None, None, None
        t0 = time.time() * 1000
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                body = await r.read()
                recv_ns = time.time_ns(); t1 = time.time() * 1000
                self.guard.observe_header(r.headers.get("x-mbx-used-weight-1m") or r.headers.get("X-MBX-USED-WEIGHT-1M"))
                self.weight_used_total += weight
                if r.status == 429:
                    self.guard.on_429(r.headers.get("Retry-After")); self._failed(path); return 429, None, recv_ns, t0, t1
                if r.status == 418:
                    self.guard.on_418(r.headers.get("Retry-After")); self._failed(path); return 418, None, recv_ns, t0, t1
                if r.status != 200:
                    self._failed(path); return r.status, None, recv_ns, t0, t1
                try:
                    data = json.loads(body)
                except ValueError:
                    self.stats["malformed"] += 1; self._failed(path); return "malformed", None, recv_ns, t0, t1
                self.fail[path] = 0
                return 200, data, recv_ns, t0, t1
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self._failed(path)
            return "network_error", None, None, None, None

    def _failed(self, path: str) -> None:
        if path == "/api/v3/time":                      # clock probes never trip the breaker (M4): weight 1
            return
        self.fail[path] = self.fail.get(path, 0) + 1
        if self.fail[path] >= 3:
            self.open_until[path] = time.monotonic() + 600
            self.fail[path] = 0


class WSConnection:
    """One combined-stream connection. Subscribes via SUBSCRIBE messages (<= 2 msgs/s, < 5 incoming limit).
    Server pings are answered by aiohttp autoping (payload echoed). `serverShutdown` triggers on_shutdown.

    G2-Repeat: every SUBSCRIBE id is tracked and its ack/error routed to on_sub_result (F22 / F37); a handler
    exception never kills the connection (counted via on_error, F20); any unexpected exception in the run loop
    leads to reconnect with backoff; suspend() closes the socket on a 418 ban (F23) and run() waits for the ban
    to end; force_reconnect() is the recovery path for ack timeouts and handler-error bursts."""

    SUB_CHUNK = 100

    def __init__(self, name: str, streams: list, session, on_message, on_shutdown, on_state,
                 base: str = C.WS_BASE, backoff: Backoff | None = None, guard: RateGuard | None = None,
                 on_error=None, on_sub_sent=None, on_sub_result=None):
        self.name, self.streams, self.session = name, list(streams), session
        self.on_message, self.on_shutdown, self.on_state = on_message, on_shutdown, on_state
        self.on_error, self.on_sub_sent, self.on_sub_result = on_error, on_sub_sent, on_sub_result
        self.base, self.backoff, self.guard = base, backoff or Backoff(), guard
        self.connected = False
        self.first_msg = asyncio.Event()
        self.reconnects = 0
        self.last_msg_ns = None
        self.sub_requests = {}                 # id -> {"streams", "sent_ms", "resolved"} (current session)
        self.handler_errors = 0
        self._closing = False
        self._ws = None

    def url(self) -> str:
        u = f"{self.base}?streams={self.streams[0]}"
        _check_url(u)
        return u

    async def run(self) -> None:
        while not self._closing:
            if self.guard is not None and self.guard.banned():
                await asyncio.sleep(1); continue
            self.backoff.attempt()
            err = None
            try:
                async with self.session.ws_connect(self.url(), autoping=True, heartbeat=30.0, max_msg_size=8 * 2**20,
                                                   timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
                    self._ws = ws
                    if self.guard is not None and self.guard.banned():
                        await ws.close(); continue
                    self.connected = True; self.on_state(self, "connected")
                    await self._subscribe(ws)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_text(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE):
                            break
            except asyncio.CancelledError:
                self.connected = False; self._ws = None
                raise
            except aiohttp.WSServerHandshakeError as e:          # 418 / 429 at the handshake reach the guard (F23)
                if self.guard is not None and e.status == 418:
                    self.guard.on_418(e.headers.get("Retry-After") if e.headers else None)
                elif self.guard is not None and e.status == 429:
                    self.guard.on_429(e.headers.get("Retry-After") if e.headers else None)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                pass
            except Exception as e:                                   # noqa: BLE001 - never die silently (F20)
                err = e
            was = self.connected
            self.connected = False; self._ws = None
            if self._closing:
                break
            if err is not None:
                self._report(err)
            self.on_state(self, "disconnected" if was else "connect_failed")
            self.backoff.failed(); self.reconnects += 1
            await asyncio.sleep(self.backoff.next_delay())

    def _report(self, err: BaseException) -> None:
        self.handler_errors += 1
        if self.on_error is not None:
            try:
                self.on_error(self, err)
            except Exception:                                        # noqa: BLE001
                pass

    def _handle_text(self, raw) -> None:
        recv_ns = time.time_ns()
        self.last_msg_ns = recv_ns
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
        try:
            if isinstance(obj, dict) and (obj.get("stream") == "!serverShutdown" or
                                          (isinstance(obj.get("data"), dict) and obj["data"].get("e") == "serverShutdown")):
                self.on_shutdown(self, obj, recv_ns); return
            if isinstance(obj, dict) and "id" in obj and ("result" in obj or "error" in obj) and "stream" not in obj:
                if self.on_sub_result is not None:
                    self.on_sub_result(self, obj)
                return
            if obj is not None:
                self.first_msg.set()
                self.backoff.succeeded()
            self.on_message(self, obj, recv_ns)
        except Exception as e:                                       # noqa: BLE001 - one bad message never kills the stream
            self._report(e)

    async def _subscribe(self, ws) -> None:
        self.sub_requests = {}
        rest = self.streams[1:]
        for i in range(0, len(rest), self.SUB_CHUNK):
            rid = i // self.SUB_CHUNK + 1
            chunk = rest[i:i + self.SUB_CHUNK]
            sent_ms = time.time_ns() // 1_000_000
            self.sub_requests[rid] = {"streams": chunk, "sent_ms": sent_ms, "resolved": False}
            await ws.send_str(json.dumps({"method": "SUBSCRIBE", "params": chunk, "id": rid}))
            if self.on_sub_sent is not None:
                self.on_sub_sent(self, rid, chunk, sent_ms)
            await asyncio.sleep(0.5)

    async def suspend(self) -> None:
        """Close the current socket (418 ban); run() stays alive and waits until the ban ends."""
        ws = self._ws
        if ws is not None and not ws.closed:
            await ws.close()

    async def force_reconnect(self, reason: str = "") -> None:
        ws = self._ws
        if ws is not None and not ws.closed and not self._closing:
            await ws.close()

    async def close(self) -> None:
        self._closing = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
