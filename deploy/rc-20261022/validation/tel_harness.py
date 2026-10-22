"""Isolated Stage-B harness: real signal_logic wiring + real run_flusher task; synthetic records; tmpfs only."""
import asyncio, json, os, sys, time
sys.path.insert(0, '/app')
writes = []; _real = os.replace
def _counting_replace(src, dst, *a, **k):
    r = _real(src, dst, *a, **k)
    if str(dst).endswith('_telemetry.json'):
        writes.append((time.monotonic(), os.path.getsize(dst)))
    return r
os.replace = _counting_replace
import signal_logic as sl
from shared.config import config

async def main():
    rec = sl.get_evidence_recorder(); assert rec is not None
    mi = getattr(config, 'EVIDENCE_TELEMETRY_MIN_INTERVAL_S', 'absent')
    task = asyncio.create_task(rec.run_flusher())
    dur = float(os.environ.get('H_DUR', '12')); alarm_at = float(os.environ.get('H_ALARM_AT', '-1'))
    t0 = time.monotonic(); n = 0; stale = []; alarm_lag = None; alarm_fired = False
    while time.monotonic() - t0 < dur:
        rec.capture(symbol=f'SYN{n%5}USDT', timeframe='15m', source='synthetic', n=n); n += 1
        if alarm_at >= 0 and not alarm_fired and time.monotonic() - t0 >= alarm_at:
            rec.dropped += 1; alarm_fired = time.monotonic(); w0 = len(writes)   # synthetic alarm-counter change
        if alarm_fired and alarm_lag is None and len(writes) > w0:
            alarm_lag = round(writes[w0][0] - alarm_fired, 3)
        await asyncio.sleep(0.05)
        if writes: stale.append(time.monotonic() - writes[-1][0])
    wbefore = len(writes)
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    tel = os.path.join(config.EVIDENCE_DIR, '_telemetry.json'); hist = json.load(open(tel))
    print(json.dumps({'min_interval_s': mi, 'dur_s': dur, 'captured': n, 'flushed': rec.flushed,
        'telemetry_writes': len(writes), 'shutdown_write': len(writes) > wbefore,
        'bytes_written': sum(b for _, b in writes), 'max_staleness_s': round(max(stale), 2) if stale else None,
        'history_len': len(hist), 'last_snapshot_flushed_total': hist[-1]['evidence_flushed_total'],
        'alarm_write_lag_s': alarm_lag, 'schema_keys': len(hist[-1])}))
asyncio.run(main())
