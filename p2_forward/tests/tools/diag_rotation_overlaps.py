"""Reproduce the TEST_CORRECTIONS.md §2 measurement: per-overlap stale market components in the lagging-rotation e2e.

Run from p2_forward/ (synthetic only): python tests/tools/diag_rotation_overlaps.py  -> one JSON line per run.
Not collected by pytest (no test_ prefix). Instruments the fake exchange and MarketTrack; collector code is unchanged.
"""
import json
import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import tests.test_p2f_rotation_e2e as T
from tests.test_p2cr_continuous import run_continuous, setup_calendar
from p2_forward import tracks

SOCKS, STALE = [], []
_orig_close = T.LagWS2.close
async def _close(self):
    if getattr(self, 'closed_at', None) is None: self.closed_at = time.time()
    return await _orig_close(self)
T.LagWS2.close = _close
_orig_aexit = T.LagWS2.__aexit__
async def _aexit(self, *a):
    if getattr(self, 'closed_at', None) is None: self.closed_at = time.time()
    return await _orig_aexit(self, *a)
T.LagWS2.__aexit__ = _aexit
_orig_init = T.LagWS2.__init__
def _init(self, url, lag):
    _orig_init(self, url, lag); self.opened_at = time.time(); self.closed_at = None; SOCKS.append(self)
T.LagWS2.__init__ = _init
_orig_on_array = tracks.MarketTrack.on_array
def _on_array(self, recv_ns, arr, stale_guard_ns=None):
    b = self.stale_components; r = _orig_on_array(self, recv_ns, arr, stale_guard_ns)
    if self.stale_components > b: STALE.append((time.time(), self.stale_components - b))
    return r
tracks.MarketTrack.on_array = _on_array

def main():
    d = os.path.join(tempfile.mkdtemp(), 'data'); setup_calendar()
    c, code, s = run_continuous(d, 100, sess=T.LagExchange())
    t0 = min(x.opened_at for x in SOCKS)
    mk = [x for x in SOCKS if '!miniTicker@arr' in x.streams]
    socks = [(round(x.opened_at - t0, 2), round((x.closed_at or time.time()) - t0, 2), x.lag) for x in mk]
    ov = []
    for i in range(len(socks) - 1):
        a, b = socks[i], socks[i + 1]
        lo, hi = b[0], min(a[1], b[1])
        n = sum(k for t, k in STALE if lo <= t - t0 <= hi + 0.5)
        ov.append({'overlap_s': round(hi - lo, 2), 'lags': (a[2], b[2]), 'stale': n})
    print(json.dumps({'exit': code, 'market_component_stale': c.counters()['market_component_stale'], 'market_sockets': socks, 'overlaps': ov}))
if __name__ == '__main__':
    main()
