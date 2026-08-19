import asyncio

from analyzer.orderbook_analyzer import OrderBookAnalyzer


class Client:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def get_order_book(self, **kwargs):
        if self.error:
            raise self.error
        return self.result


def test_empty_orderbook_is_invalid_not_zero_spread():
    result = asyncio.run(OrderBookAnalyzer(Client({'bids': [], 'asks': []})).analyze('XUSDT'))
    assert result['valid'] is False
    assert result['spread_pct'] is None


def test_valid_orderbook_has_explicit_validity():
    book = {'bids': [['99', '2']], 'asks': [['100', '1']]}
    result = asyncio.run(OrderBookAnalyzer(Client(book)).analyze('XUSDT'))
    assert result['valid'] is True
    assert result['spread_pct'] > 0
