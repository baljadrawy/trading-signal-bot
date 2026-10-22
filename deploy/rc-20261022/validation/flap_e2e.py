"""RC isolated validation (synthetic only): continuous Collector run against a fake exchange whose sockets drop
repeatedly for the first FLAP_S seconds. Phase given by argv[1]: 'rc' (flags from env) or 'rollback'
(1.6.0 restarts into the same dataset). Prints one JSON line."""
import json, os, sys, time, gzip, glob
sys.path.insert(0, '/w')
from tests.test_g3_prereqs import FakeWS2
from tests.test_p2cr_continuous import UniverseShiftExchange, VC, lifecycle, run_continuous, setup_calendar
from p2_forward import cal

phase, data, secs = (sys.argv[1:4] + ['x', 'x', '0'])[:3] if len(sys.argv) < 4 else sys.argv[1:4]
secs = float(secs)
FLAP_S = float(os.environ.get('FLAP_S', '25')); T_START = time.time()

class FlappyWS(FakeWS2):
    def __init__(self, url):
        super().__init__(url); self.die_at = time.time() + 1.5 if time.time() - T_START < FLAP_S else None
    async def __anext__(self):
        if self.die_at and time.time() >= self.die_at:
            self.closed = True
        return await super().__anext__()

class FlappyExchange(UniverseShiftExchange):
    def ws_connect(self, url, **kw):
        w = FlappyWS(url); self.ws.append(w); return w

def main():
    global FLAP_S
    over = json.loads(os.environ.get('OVER', '{}'))
    if phase == 'rollback' or os.environ.get('NO_FLAP'):
        FLAP_S = -1
    import datetime as _dt
    from tests.test_p2cr_continuous import HOUR_MS
    h0 = int(os.environ['CAL_H0']) if os.environ.get('CAL_H0') else time.time_ns() // 1_000_000 // HOUR_MS - 14
    cal.configure(HOUR_MS, h0, _dt.datetime(2030, 1, 1, tzinfo=_dt.timezone.utc))
    c, code, s = run_continuous(data, secs, sess=FlappyExchange(), **over)
    ev = {}
    for r in lifecycle(data):
        e = r['payload'].get('event'); ev[e] = ev.get(e, 0) + 1
    kinds = {}
    for r in lifecycle(data, 'ws_session_end'):
        k = r['payload'].get('kind'); kinds[k] = kinds.get(k, 0) + 1
    days = sorted(f[:-5] for f in os.listdir(os.path.join(data, 'days'))) if os.path.isdir(os.path.join(data, 'days')) else []
    rep = {d: VC.verify_day(data, d, allow_test_calendar=True) for d in days}
    vres = {d: {'PASS': r.get('PASS'), 'failures': len(r.get('failures') or {})} for d, r in rep.items()}
    inc = c.incidents
    summ = inc.summary() if inc else {}
    allinc = [{k: i.get(k) for k in ("key", "severity", "active", "resolved_ms", "count", "boot8")} for i in inc.items.values()] if inc else []
    flap_open = {n.name: inc._open_for(f'conn_flapping:{n.name}') is not None for n in c.conns} if inc else None
    print(json.dumps({'phase': phase, 'cal_h0': h0, 'exit_code': code, 'sockets': len(s.ws), 'lifecycle_events': ev,
                      'session_end_kinds': kinds, 'flapping_open_at_end': flap_open, 'days': vres,
                      'conn_session_ends': c.stats.get('conn_session_ends'), 'active_by_severity': summ.get('by_severity'), 'active_keys': [a['key'] for a in summ.get('active', [])], 'incidents_all': allinc}, default=str))


if __name__ == '__main__':
    main()
