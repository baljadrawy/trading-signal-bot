"""Observable dead letters (A38).

Since A38, a dead letter means a genuine failure: deferrals (waiting for a known future state)
no longer consume retry attempts. A dead letter can come from a repeated exception or from an
event whose state could not be resolved by its deadline. DeadLetterWatch makes each new one
visible exactly once:
  * a log line at ERROR for every new dead letter;
  * a heartbeat snapshot (count since boot, the last one, and the dead letters of the 24 h before
    boot, reported but never re-alerted);
  * one alert per poll that found new dead letters. The alert channel is Telegram, so an alert
    can itself fail during a Telegram outage; the log and the heartbeat remain.

Only letters that died after the process started are alerted, so a restart never re-alerts
history. Read-only on the database.
"""
from datetime import datetime, timedelta, timezone

from shared.outbox import dead_letters_since


def _utc_naive(now=None) -> datetime:
    """outbox timestamps are naive UTC (TIMESTAMP DEFAULT NOW() on a UTC server)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


class DeadLetterWatch:
    def __init__(self, service: str, event_types, *, interval_s: float = 60.0,
                 alert=None, logger=None, clock=None):
        self.service = service
        self.event_types = tuple(event_types)
        self.interval_s = interval_s
        self.alert = alert                      # async callable(text) or None
        self.logger = logger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.started = _utc_naive(self.clock())
        self.watermark = (self.started, 0)
        self.new_since_boot = 0
        self.last = None
        self.before_boot_24h = None
        self.errors = 0
        self._next_poll = None

    async def poll(self, force: bool = False) -> list:
        """Return the dead letters that are new since the last poll (at most one query per
        `interval_s`, unless `force`). Never raises: a monitoring failure is counted."""
        now = _utc_naive(self.clock())
        if not force and self._next_poll is not None and now < self._next_poll:
            return []
        self._next_poll = now + timedelta(seconds=self.interval_s)
        try:
            if self.before_boot_24h is None:
                prior = await dead_letters_since(
                    self.event_types, (self.started - timedelta(hours=24), 0), limit=1000)
                self.before_boot_24h = sum(1 for r in prior if r['processed_at'] <= self.started)
            rows = await dead_letters_since(self.event_types, self.watermark, limit=50)
        except Exception as exc:           # monitoring must never break the service loop
            self.errors += 1
            if self.logger:
                self.logger.warning(f'dead-letter watch failed: {type(exc).__name__}: {exc}')
            return []
        if not rows:
            return []
        last = rows[-1]
        self.watermark = (last['processed_at'], int(last['id']))
        self.new_since_boot += len(rows)
        self.last = {'id': int(last['id']), 'event_type': last['event_type'],
                     'aggregate_id': int(last['aggregate_id']),
                     'last_error': (last['last_error'] or '')[:200],
                     'died_at': last['processed_at'].isoformat()}
        for r in rows:
            if self.logger:
                self.logger.error(
                    f"DEAD LETTER {r['event_type']} #{r['id']} {r['aggregate_type']}="
                    f"{r['aggregate_id']} attempts={r['attempts']} deferrals={r['deferrals']}: "
                    f"{(r['last_error'] or '')[:200]}")
        if self.alert:
            kinds = sorted({r['event_type'] for r in rows})
            text = (f"{len(rows)} dead letter(s) in the outbox ({', '.join(kinds)}); "
                    f"last #{last['id']}: {(last['last_error'] or '')[:150]}")
            try:
                await self.alert(text)
            except Exception as exc:
                self.errors += 1
                if self.logger:
                    self.logger.warning(f'dead-letter alert failed: {type(exc).__name__}: {exc}')
        return list(rows)

    def snapshot(self) -> dict:
        return {'event_types': list(self.event_types), 'new_since_boot': self.new_since_boot,
                'last': self.last, 'before_boot_24h': self.before_boot_24h,
                'watch_errors': self.errors}
