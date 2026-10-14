"""Public market-data transports: WebSocket streams and REST (aiohttp). Market-data-only hosts; allow-listed paths.

No API key, no signing, no order/account/user-data endpoint exists in this module (enforced by tests).
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
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
        self.last_body_sha256 = {}  # path -> SHA-256 of the last 200 body (universe input provenance, R04)
        self.keep_body = {"/api/v3/exchangeInfo", "/api/v3/ticker/24hr"}
        self.last_body = {}         # path -> raw bytes of the last 200 body (universe paths only; persisted, M2)

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
                    self.stats["rest_malformed"] = self.stats.get("rest_malformed", 0) + 1     # m2: REST-specific
                    self._failed(path); return "malformed", None, recv_ns, t0, t1
                self.fail[path] = 0
                self.last_body_sha256[path] = hashlib.sha256(body).hexdigest()
                if path in self.keep_body:
                    self.last_body[path] = body
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
    to end; force_reconnect() is the recovery path for data stalls, ack timeouts and handler-error bursts.

    P2F 1.6.0 (A34 recovery hardening). Each WebSocket session runs in its own task (`_session`) owned by run(); a
    session is ended ONLY through `_end_session()`, which is BOUNDED and never relies on the peer:
      1. graceful close (aiohttp close(): CLOSE frame, wait for the peer's CLOSE) for at most `close_grace_s`;
      2. then the TCP transport is aborted, and the session task gets `abort_wait_s` to finish;
      3. then the session task is cancelled, with another `abort_wait_s`;
      4. if it still has not finished the connection is reported WEDGED (on_recovery outcome "wedged"): the owner
         (Collector) retires this object and starts a new one; a retired object never delivers another message.
    aiohttp 3.14.3 bounds its close wait per received frame, so a peer that keeps sending frames but never answers
    CLOSE kept close() - and with it every earlier recovery path - waiting indefinitely (A33 D1, 2026-10-10).
    Concurrent end requests share one termination (no double abort, no duplicate sessions). Sessions carry a
    generation number; a message from any other generation, or from a retired object, is dropped and counted
    (`stale_dropped`), never delivered. Reconnects keep the existing Backoff (exponential, rate-limited)."""

    SUB_CHUNK = 100

    def __init__(self, name: str, streams: list, session, on_message, on_shutdown, on_state,
                 base: str = C.WS_BASE, backoff: Backoff | None = None, guard: RateGuard | None = None,
                 on_error=None, on_sub_sent=None, on_sub_result=None, on_recovery=None,
                 close_grace_s: float = 3.0, abort_wait_s: float = 2.0):
        self.name, self.streams, self.session = name, list(streams), session
        self.on_message, self.on_shutdown, self.on_state = on_message, on_shutdown, on_state
        self.on_error, self.on_sub_sent, self.on_sub_result = on_error, on_sub_sent, on_sub_result
        self.on_recovery = on_recovery
        self.base, self.backoff, self.guard = base, backoff or Backoff(), guard
        self.close_grace_s, self.abort_wait_s = float(close_grace_s), float(abort_wait_s)
        self.connected = False
        self.first_msg = asyncio.Event()
        self.reconnects = 0
        self.last_msg_ns = None
        self.sub_requests = {}                 # id -> {"streams", "sent_ms", "resolved"} (current session)
        self.handler_errors = 0
        self.gen = 0                           # session generation (incremented on every successful connect)
        self.stale_dropped = 0                 # messages of an obsolete generation / retired object, never delivered
        self.recovering = False
        self.wedged = False
        self.retired = False
        self.recoveries = collections.deque(maxlen=20)
        self._closing = False
        self._ws = None
        self._session = None                   # current session task
        self._ending = None                    # (session task, future) of the termination in progress
        self._was_connected = False

    def url(self) -> str:
        u = f"{self.base}?streams={self.streams[0]}"
        _check_url(u)
        return u

    async def run(self) -> None:
        while not self._closing and not self.retired:
            if self.guard is not None and self.guard.banned():
                await asyncio.sleep(1); continue
            self.backoff.attempt()
            self._was_connected = False
            st = self._session = asyncio.create_task(self._session_once(), name=f"{self.name}-session")
            try:
                await asyncio.wait({st})
            except asyncio.CancelledError:              # run() itself cancelled (stop / replacement): bounded cleanup
                if self._ws is not None:
                    self._abort(self._ws)               # else aiohttp's __aexit__ close() could wait on the peer again
                await self._cancel_bounded(st)
                self.connected = False; self._ws = None
                raise
            err = None
            if not st.cancelled():
                kind, err = st.result()
                if kind == "banned":
                    continue
            was = self._was_connected
            self.connected = False; self._ws = None
            if self._closing or self.retired:
                break
            if err is not None:
                self._report(err)
            self.on_state(self, "disconnected" if was else "connect_failed")
            self.backoff.failed(); self.reconnects += 1
            await asyncio.sleep(self.backoff.next_delay())

    async def _session_once(self):
        """One WebSocket session. Returns ("ended" | "banned", unexpected exception or None)."""
        err = None
        try:
            async with self.session.ws_connect(self.url(), autoping=True, heartbeat=30.0, max_msg_size=8 * 2**20,
                                               timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
                self._ws = ws
                if self.guard is not None and self.guard.banned():
                    await self._close_bounded(ws)
                    return "banned", None
                self.gen += 1
                gen = self.gen
                self.connected = self._was_connected = True
                self.on_state(self, "connected")
                await self._subscribe(ws)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._handle_text(msg.data, gen)
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE):
                        break
        except asyncio.CancelledError:
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
        finally:
            self.connected = False
        return "ended", err

    async def _close_bounded(self, ws) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(ws.close()), timeout=self.close_grace_s)
        except Exception:                                        # noqa: BLE001 - timeout or close error: abort
            self._abort(ws)

    @staticmethod
    def _abort(ws) -> bool:
        """Hard-close the TCP transport under a WebSocket (aiohttp 3.14.3 attribute paths; best effort)."""
        for holder in (getattr(ws, "_writer", None), getattr(getattr(ws, "_response", None), "connection", None)):
            tr = getattr(holder, "transport", None)
            if tr is not None:
                try:
                    tr.abort()
                    return True
                except Exception:                                # noqa: BLE001
                    continue
        return False

    async def _end_session(self, reason: str) -> dict:
        """Bounded termination of the current session (see class doc). Never waits longer than
        close_grace_s + 2 * abort_wait_s. Concurrent callers for the same session share one termination."""
        st = self._session
        if st is None or st.done():
            return {"reason": reason, "outcome": "no_session", "gen": self.gen, "ms": 0}
        if self._ending is not None and self._ending[0] is st:
            res = dict(await asyncio.shield(self._ending[1]))
            res["deduplicated"] = True
            return res
        fut = asyncio.get_running_loop().create_future()
        self._ending = (st, fut)
        t0, ws, gen = time.monotonic(), self._ws, self.gen
        self.recovering = True
        closer = None
        res = {"reason": reason, "outcome": "interrupted", "gen": gen, "ms": None}
        try:
            if ws is not None and not ws.closed:
                closer = asyncio.create_task(ws.close(), name=f"{self.name}-close")
            if ws is None:                                   # still connecting: nothing to close gracefully
                outcome, done = "cancelled", set()
            else:
                outcome = "graceful"
                done, _ = await asyncio.wait({st}, timeout=self.close_grace_s)
                if not done:
                    outcome = "aborted" if self._abort(ws) else "abort_unavailable"
                    done, _ = await asyncio.wait({st}, timeout=self.abort_wait_s)
            if not done:
                outcome = "cancelled"
                done = await self._cancel_bounded(st)
            if not done:
                outcome = "wedged"
                self.wedged = True
            res = {"reason": reason, "outcome": outcome, "gen": gen, "ms": round((time.monotonic() - t0) * 1000)}
        finally:
            if closer is not None and not closer.done():
                closer.cancel()
            self.recovering = False
            self.recoveries.append(res)
            if not fut.done():
                fut.set_result(res)                          # deduplicated waiters never hang, even if interrupted
            if self._ending is not None and self._ending[1] is fut:
                self._ending = None
        if self.on_recovery is not None:
            try:
                self.on_recovery(self, res)
            except Exception:                                    # noqa: BLE001 - reporting never breaks recovery
                pass
        return res

    async def _cancel_bounded(self, st) -> bool:
        """Cancel REPEATEDLY until the task ends or abort_wait_s elapses. One cancel can be consumed at an await that
        the task then leaves for another (e.g. aiohttp's __aexit__ close() after a cancelled receive()); repeating it
        interrupts the next await too. Returns True if the task ended."""
        loop = asyncio.get_running_loop()
        end = loop.time() + self.abort_wait_s
        while not st.done():
            left = end - loop.time()
            if left <= 0:
                break
            st.cancel()
            await asyncio.wait({st}, timeout=min(0.25, left))
        return st.done()

    def retire(self) -> None:
        """Owner gave up on this object (wedged): it must never deliver another message or reconnect."""
        self.retired = True
        self._closing = True

    def _report(self, err: BaseException) -> None:
        self.handler_errors += 1
        if self.on_error is not None:
            try:
                self.on_error(self, err)
            except Exception:                                        # noqa: BLE001
                pass

    def _handle_text(self, raw, gen: int | None = None) -> None:
        if self.retired or (gen is not None and gen != self.gen):
            self.stale_dropped += 1                                  # obsolete session: never delivered
            return
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

    async def suspend(self) -> dict:
        """End the current session (418 ban), bounded; run() stays alive and waits until the ban ends."""
        return await self._end_session("ban_418")

    async def force_reconnect(self, reason: str = "") -> dict:
        """Bounded recovery: end the current session (graceful -> abort -> cancel); run() reconnects with backoff."""
        if self._closing:
            return {"reason": reason, "outcome": "closing", "gen": self.gen, "ms": 0}
        return await self._end_session(reason or "forced")

    async def close(self) -> dict:
        self._closing = True
        return await self._end_session("close")
