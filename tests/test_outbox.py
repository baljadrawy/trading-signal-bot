import asyncio
import re

from shared import outbox


def test_worker_id_is_scoped_and_unique():
    first = outbox.worker_id('telegram')
    second = outbox.worker_id('telegram')
    assert first != second
    assert re.match(r'^telegram:[^:]+:[0-9a-f]{12}$', first)


def test_enqueue_serializes_payload(monkeypatch):
    seen = {}

    class Conn:
        async def fetchval(self, query, *args):
            seen['args'] = args
            return 7

    result = asyncio.run(outbox.enqueue(
        Conn(), 'signal.created', 'signal', 42, {'signal_id': 42}))
    assert result == 7
    assert '"signal_id": 42' in seen['args'][3]
