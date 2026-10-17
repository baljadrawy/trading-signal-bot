"""A59 data adapters. Read-only by construction: the only SQL is a fixed SELECT on the six R-5 dashboard views.

MockAdapter serves synthetic data for development and tests (no database). PostgresAdapter is the future interface
for the R-5 role tsb_dashboard_ro, which can read the dashboard.* views and nothing else (it has no usage on public).
Status levels are computed here, server-side, so the UI can never show green for missing or stale data.
"""
import datetime as _dt
import time

VIEWS = ('service_health', 'open_positions', 'outbox_health', 'signal_flow_hourly', 'risk_state', 'schema_version')
HEARTBEAT_STALE_S = 600            # a heartbeat older than this is stale, never "ok"
DATA_STALE_S = 120                 # a snapshot older than this is shown as stale


class DataUnavailable(Exception):
    """The source could not be read. The UI shows an explicit error state, never cached green."""


def _ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, _dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=_dt.timezone.utc)).timestamp()
    return None


def derive(raw: dict, now: float) -> dict:
    """Add a level (ok / warn / error / unknown) to each card from raw view rows."""
    services = []
    for s in raw.get('service_health') or []:
        last = _ts(s.get('last_success_at'))
        age = None if last is None else max(0, now - last)
        if last is None:
            level = 'unknown'
        elif (s.get('consecutive_errors') or 0) > 0:
            level = 'error'
        elif age > HEARTBEAT_STALE_S:
            level = 'warn'
        else:
            level = 'ok'
        services.append({'name': s.get('service_name'), 'level': level, 'age_s': None if age is None else int(age),
                         'consecutive_errors': s.get('consecutive_errors') or 0})
    outbox = [{'event_type': r.get('event_type'), 'status': r.get('status'), 'events': r.get('events'),
               'level': 'error' if r.get('status') == 'dead' else ('warn' if r.get('status') in ('pending', 'processing')
                                                                   and (now - (_ts(r.get('oldest_available_at')) or now)) > 900
                                                                   else 'ok')}
              for r in raw.get('outbox_health') or []]
    risk_rows = sorted(raw.get('risk_state') or [], key=lambda r: str(r.get('date')))
    latest = risk_rows[-1] if risk_rows else None
    risk = ({'paused': bool(latest.get('is_trading_paused')), 'reason': latest.get('pause_reason'),
             'level': 'warn' if latest.get('is_trading_paused') else 'ok'} if latest else
            {'paused': None, 'reason': None, 'level': 'unknown'})
    positions = [{'symbol': p.get('symbol'), 'timeframe': p.get('timeframe'), 'opened_age_s':
                  None if _ts(p.get('opened_at')) is None else int(now - _ts(p.get('opened_at'))),
                  'entry_order_type': p.get('entry_order_type'), 'stop_policy': p.get('stop_policy')}
                 for p in raw.get('open_positions') or []]
    hourly = [{'hour': (_ts(r.get('hour')) or 0), 'timeframe': r.get('timeframe'), 'signals': r.get('signals')}
              for r in raw.get('signal_flow_hourly') or []]
    sv = (raw.get('schema_version') or [{}])[0].get('version')
    worst = [c['level'] for c in services + outbox] + [risk['level']]
    overall = ('error' if 'error' in worst else 'warn' if 'warn' in worst else
               'unknown' if (not services or 'unknown' in worst) else 'ok')
    return {'overall': overall, 'services': services, 'positions': positions, 'outbox': outbox,
            'signals_hourly': hourly, 'risk': risk, 'schema_version': sv}


class MockAdapter:
    """Synthetic operational data. `mode` = 'ok' | 'stale' | 'error' | 'empty' for tests and UI review."""
    def __init__(self, mode='ok', clock=time.time):
        self.mode, self.clock = mode, clock

    async def fetch(self) -> dict:
        now = self.clock()
        if self.mode == 'error':
            raise DataUnavailable('mock source unavailable')
        if self.mode == 'empty':
            return {v: [] for v in VIEWS}
        age = 4000 if self.mode == 'stale' else 20
        svc = ['scanner', 'analyzer', 'signal_engine', 'telegram', 'trade_tracker']
        return {
            'service_health': [{'service_name': s, 'last_success_at': now - age - i * 5, 'consecutive_errors': 0}
                               for i, s in enumerate(svc)],
            'open_positions': [{'symbol': 'SYNAUSDT', 'timeframe': '15m', 'opened_at': now - 1800,
                                'entry_order_type': 'market', 'stop_policy': 'reversion_structure'}],
            'outbox_health': [{'event_type': 'trade.opened', 'status': 'completed', 'events': 12,
                               'oldest_available_at': now - 3600},
                              {'event_type': 'signal.delivered', 'status': 'pending', 'events': 1,
                               'oldest_available_at': now - 60}],
            'signal_flow_hourly': [{'hour': now - h * 3600, 'timeframe': '15m', 'signals': (h * 7) % 4}
                                   for h in range(12)],
            'risk_state': [{'date': '2026-10-17', 'is_trading_paused': False, 'pause_reason': None}],
            'schema_version': [{'version': 11}],
        }


class PostgresAdapter:
    """Future: reads ONLY dashboard.<view> as tsb_dashboard_ro, in a read-only transaction with timeouts."""
    def __init__(self, dsn: str, timeout_s: float = 5.0):
        self.dsn, self.timeout_s = dsn, timeout_s

    async def fetch(self) -> dict:
        import asyncpg                                       # optional dependency, only for the real adapter
        try:
            conn = await asyncpg.connect(self.dsn, timeout=self.timeout_s,
                                         server_settings={'application_name': 'a59_dashboard',
                                                          'default_transaction_read_only': 'on',
                                                          'statement_timeout': '3000'})
        except Exception as exc:
            raise DataUnavailable(type(exc).__name__) from None
        try:
            out = {}
            async with conn.transaction(readonly=True):
                for v in VIEWS:                              # fixed allowlist; no user input reaches SQL
                    out[v] = [dict(r) for r in await conn.fetch(f'SELECT * FROM dashboard.{v}')]
            return out
        except Exception as exc:
            raise DataUnavailable(type(exc).__name__) from None
        finally:
            await conn.close()
