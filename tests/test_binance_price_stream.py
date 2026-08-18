import json
from unittest.mock import AsyncMock, Mock

import pytest

from trade_tracker.binance_price_stream import BinancePriceStream


@pytest.mark.asyncio
async def test_stream_caches_price_and_discards_duplicate_aggregate_id():
    callback = AsyncMock()
    stream = BinancePriceStream(symbol_provider=AsyncMock(return_value={'BTCUSDT'}),
                                on_price=callback, logger=Mock())
    payload = json.dumps({'e': 'aggTrade', 's': 'BTCUSDT', 'a': 10, 'p': '101.5'})
    await stream._handle(payload, {'btcusdt'})
    await stream._handle(payload, {'btcusdt'})
    assert stream.prices['BTCUSDT'][0] == 101.5
    assert stream._queue.qsize() == 1


@pytest.mark.asyncio
async def test_stream_ignores_unsubscribed_symbol():
    stream = BinancePriceStream(symbol_provider=AsyncMock(return_value=set()),
                                on_price=AsyncMock(), logger=Mock())
    payload = json.dumps({'e': 'aggTrade', 's': 'ETHUSDT', 'a': 1, 'p': '10'})
    await stream._handle(payload, {'btcusdt'})
    assert not stream.prices
