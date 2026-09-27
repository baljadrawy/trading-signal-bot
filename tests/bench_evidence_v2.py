"""Evidence v2 overhead benchmark (P1-F): emit latency, decision-cycle CPU/wall overhead, flush
throughput with fsync, memory at full queue/state cache, analyzer PIT overhead.
    python tests/bench_evidence_v2.py <output_dir_on_real_disk> <result.json>
Synthetic inputs only; no network, no database."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests'); sys.path.insert(0, 'signal_engine')
import asyncio
import json
import os
import resource
import statistics
import time
import tracemalloc

from shared import evidence_v2 as ev2
from shared.config import config
from shared.database import Database
from evidence_v2_fakes import IDENT, FakeMacro, analysis_row

OUT_DIR, RESULT = sys.argv[1], sys.argv[2]


def pct(values, p):
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p * len(s)))], 4)


def payload():
    row = analysis_row('BENCHUSDT')['analysis_data']
    return {'geometry': {k: row[k] for k in ('entry_price', 'target_1', 'target_2', 'target_3', 'stop_loss')},
            'pit': row['pit'], 'features': {f'f{i}': i * 1.5 for i in range(30)},
            'order_book': row['order_book'], 'macro': {'macro_state': 'usdtd_flat', 'macro_age_seconds': 60}}


def bench_emit(n=20000):
    rec = ev2.RecorderV2('bench', ev2.ListSink(), IDENT, max_queue=n + 10, state_cache_size=n + 10)
    p = payload()
    new, rep = [], []
    for i in range(n):
        t = time.perf_counter()
        rec.emit('candidate.evaluated', {'candidate_id': f'c{i}'}, p, state={'d': 'rejected'}, dedup_key=f'c{i}')
        new.append((time.perf_counter() - t) * 1000)
    for i in range(n):
        t = time.perf_counter()
        rec.emit('candidate.evaluated', {'candidate_id': f'c{i}'}, p, state={'d': 'rejected'}, dedup_key=f'c{i}')
        rep.append((time.perf_counter() - t) * 1000)
    size = statistics.mean(len(line) for _, line in list(rec._q)[:1000])
    return {'new_state_ms': {'p50': pct(new, .5), 'p95': pct(new, .95), 'p99': pct(new, .99), 'max': round(max(new), 3)},
            'suppressed_repeat_ms': {'p50': pct(rep, .5), 'p95': pct(rep, .95), 'p99': pct(rep, .99)},
            'avg_event_bytes': round(size)}


def bench_cycle(reps=30):
    import signal_logic

    async def fetch(sql, *a):
        return []
    Database.fetch = fetch
    engine = signal_logic.SignalEngine()

    async def cooldown():
        return set()

    async def volume(s):
        return 1e6
    engine._get_symbol_cooldown_set, engine._get_volume_usdt = cooldown, volume
    rows = [analysis_row(f'S{i:03d}USDT', ['15m', '4h', '1d'][i % 3], ['momentum', 'reversion', None][i % 3],
                         spread=0.01 + (i % 20) / 100) for i in range(200)]

    def timed(mode):
        wall, cpu = [], []
        for r in range(reps):
            if mode == 'on_new':
                ev2.reset_for_tests()
                ev2._RECORDERS['signal_engine'] = ev2.RecorderV2('signal_engine', ev2.ListSink(), IDENT)
            t0, c0 = time.perf_counter(), time.process_time()
            asyncio.run(engine.find_best_signal_live(rows, FakeMacro()))
            wall.append((time.perf_counter() - t0) * 1000)
            cpu.append((time.process_time() - c0) * 1000)
        return {'wall_ms_p50': pct(wall, .5), 'wall_ms_p95': pct(wall, .95), 'cpu_ms_p50': pct(cpu, .5)}
    config.EVIDENCE_V2_ENABLED = False
    ev2.reset_for_tests()
    off = timed('off')
    config.EVIDENCE_V2_ENABLED = True
    on_new = timed('on_new')                        # every candidate is a new state (worst case)
    ev2.reset_for_tests()
    ev2._RECORDERS['signal_engine'] = ev2.RecorderV2('signal_engine', ev2.ListSink(), IDENT)
    asyncio.run(engine.find_best_signal_live(rows, FakeMacro()))
    on_repeat = timed('on_repeat')                  # steady state: identical decisions suppressed
    config.EVIDENCE_V2_ENABLED = False
    return {'candidates_per_cycle': 200, 'recorder_off': off, 'recorder_on_all_new_states': on_new,
            'recorder_on_steady_state': on_repeat}


def bench_flush(n=20000):
    sink = ev2.JsonlDailySink(OUT_DIR, 'bench', fsync=True)
    rec = ev2.RecorderV2('bench', sink, IDENT, max_queue=n + 10, batch_size=500)
    p = payload()
    for i in range(n):
        rec.emit('candidate.evaluated', {'candidate_id': f'c{i}'}, p)
    t0 = time.perf_counter()
    rec.flush_now()
    dt = time.perf_counter() - t0
    return {'events': n, 'seconds': round(dt, 3), 'events_per_s': round(n / dt),
            'batch_500_fsync_ms': round(dt / (n / 500) * 1000, 2)}


class DiscardSink:
    def write(self, batch):
        pass


def bench_memory():
    tracemalloc.start()
    rec = ev2.RecorderV2('bench', DiscardSink(), IDENT, max_queue=10000, state_cache_size=50000)
    p = payload()
    base = tracemalloc.get_traced_memory()[0]
    for i in range(10000):
        rec.emit('candidate.evaluated', {'candidate_id': f'q{i}'}, p)
    full_queue = tracemalloc.get_traced_memory()[0] - base
    rec.flush_now()
    base = tracemalloc.get_traced_memory()[0]
    for i in range(50000):
        rec.emit('x', {'i': i}, {}, state={'s': 1}, dedup_key=f'candidate:cand_{i:024d}')
        if i % 500 == 0:
            rec.flush_now()
    rec.flush_now()
    cache = tracemalloc.get_traced_memory()[0] - base
    tracemalloc.stop()
    return {'full_queue_10000_events_mb': round(full_queue / 2**20, 1),
            'state_cache_50000_keys_mb': round(cache / 2**20, 1),
            'process_maxrss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}


def bench_pit(n=2000):
    import pandas as pd
    import numpy as np
    idx = pd.date_range('2026-01-01', periods=200, freq='15min', tz='UTC', name='open_time')
    df = pd.DataFrame({'close': np.ones(200), 'close_time': (idx.asi8 // 10**6) + 899_999}, index=idx)
    ev2.compute_code_sha()
    t = []
    for _ in range(n):
        t0 = time.perf_counter()
        pit = ev2.candle_pit(df, '15m', ev2.now_ms())
        ev2.candidate_pit(pit, 'BENCHUSDT', '15m', 'momentum', config, {'rsi': 1.0})
        t.append((time.perf_counter() - t0) * 1000)
    return {'per_analysis_ms_p50': pct(t, .5), 'per_analysis_ms_p99': pct(t, .99)}


if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    result = {'emit': bench_emit(), 'decision_cycle': bench_cycle(), 'flush_fsync_disk': bench_flush(),
              'memory': bench_memory(), 'analyzer_pit': bench_pit(),
              'python': sys.version.split()[0], 'cpu_count': os.cpu_count()}
    with open(RESULT, 'w') as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps(result, indent=1))
