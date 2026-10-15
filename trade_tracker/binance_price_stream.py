"""Resilient Binance aggregate-trade stream with dynamic subscriptions."""
import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp


class BinancePriceStream:
    URL = 'wss://stream.binance.com:9443/ws'

    def __init__(self, *, symbol_provider: Callable[[], Awaitable[set[str]]],
                 on_price: Callable[[str, float], Awaitable[None]], logger,
                 refresh_seconds: int = 5, alert_after_seconds: int = 60,
                 on_status: Callable[[str, dict], Awaitable[None]] | None = None):
        self.symbol_provider = symbol_provider
        self.on_price = on_price
        self.logger = logger
        self.refresh_seconds = max(1, refresh_seconds)
        self.alert_after_seconds = max(1, alert_after_seconds)
        self.on_status = on_status
        self.prices: dict[str, tuple[float, datetime]] = {}
        self.last_aggregate_id: dict[str, int] = {}
        self.connected = False
        self.last_message_at: datetime | None = None
        self.disconnected_since: datetime | None = None
        self.outage_alerted = False
        self._queue: asyncio.Queue[tuple[str, float]] = asyncio.Queue(maxsize=1000)

    def snapshot(self) -> dict:
        now = datetime.now(timezone.utc)
        age = ((now - self.last_message_at).total_seconds()
               if self.last_message_at else None)
        return {
            'connected': self.connected,
            'symbols_cached': len(self.prices),
            'last_message_age_seconds': round(age, 1) if age is not None else None,
            'queue_size': self._queue.qsize(),
        }

    async def run(self):
        consumer = asyncio.create_task(self._consume(), name='price-stream-consumer')
        try:
            backoff = 5
            while True:
                try:
                    await self._connection()
                    backoff = 5
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    now = datetime.now(timezone.utc)
                    self.connected = False
                    if self.disconnected_since is None:
                        self.disconnected_since = now
                    outage = (now - self.disconnected_since).total_seconds()
                    if outage >= self.alert_after_seconds:
                        self.logger.error(
                            'WebSocket متوقف %.0fث؛ REST backup ما زال فعالاً: %s',
                            outage, exc)
                        if not self.outage_alerted and self.on_status:
                            self.outage_alerted = True
                            await self.on_status('down', {
                                'outage_seconds': round(outage),
                                'error': str(exc)[:300],
                            })
                    else:
                        self.logger.warning(
                            'انقطاع WebSocket قصير؛ إعادة الاتصال خلال %sث: %s',
                            backoff, exc)
                    await asyncio.sleep(backoff)
                    backoff = min(60, backoff * 2)
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)

    async def _connection(self):
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(self.URL, heartbeat=20, autoping=True) as ws:
                self.connected = True
                if self.outage_alerted and self.on_status:
                    await self.on_status('restored', {})
                self.outage_alerted = False
                self.disconnected_since = None
                subscribed: set[str] = set()
                request_id = 1
                self.logger.info('✅ WebSocket Binance متصل')
                while True:
                    wanted = {s.lower() for s in await self.symbol_provider()}
                    add, remove = wanted - subscribed, subscribed - wanted
                    if add:
                        await ws.send_json({
                            'method': 'SUBSCRIBE',
                            'params': [f'{s}@aggTrade' for s in sorted(add)],
                            'id': request_id,
                        })
                        request_id += 1
                    if remove:
                        await ws.send_json({
                            'method': 'UNSUBSCRIBE',
                            'params': [f'{s}@aggTrade' for s in sorted(remove)],
                            'id': request_id,
                        })
                        request_id += 1
                    subscribed = wanted

                    try:
                        msg = await asyncio.wait_for(
                            ws.receive(), timeout=self.refresh_seconds)
                    except asyncio.TimeoutError:
                        continue
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle(msg.data, subscribed)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                     aiohttp.WSMsgType.CLOSE,
                                     aiohttp.WSMsgType.ERROR):
                        raise ConnectionError(f'websocket state={msg.type}')

    async def _handle(self, raw: str, subscribed: set[str]):
        data = json.loads(raw)
        if data.get('e') != 'aggTrade':
            return
        symbol = str(data.get('s') or '').upper()
        if symbol.lower() not in subscribed:
            return
        aggregate_id = int(data['a'])
        if aggregate_id <= self.last_aggregate_id.get(symbol, -1):
            return
        price = float(data['p'])
        if not math.isfinite(price) or price <= 0:       # never advance the watermark on it
            return
        self.last_aggregate_id[symbol] = aggregate_id
        now = datetime.now(timezone.utc)
        self.last_message_at = now
        self.prices[symbol] = (price, now)
        try:
            self._queue.put_nowait((symbol, price))
        except asyncio.QueueFull:
            # Preserve the newest observation; REST backup remains authoritative.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait((symbol, price))

    async def _consume(self):
        while True:
            symbol, price = await self._queue.get()
            try:
                await self.on_price(symbol, price)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.exception('فشل معالجة tick لـ %s: %s', symbol, exc)
            finally:
                self._queue.task_done()
