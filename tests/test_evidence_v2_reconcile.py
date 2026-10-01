"""Offline reconciliation tool (P1-E) on synthetic event streams with planted defects."""
import sys; sys.path.insert(0, '.')
import json
import re

from shared import evidence_v2 as ev2
from research.evidence_v2 import reconcile as rc
from evidence_v2_fakes import IDENT

H = 3_600_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % 900_000)       # a 15m-aligned synthetic epoch


class Stream:
    def __init__(self, tmp):
        self.tmp, self.recs = tmp, {}

    def rec(self, service, **kw):
        if service not in self.recs:
            clock = {'t': T0}
            r = ev2.RecorderV2(service, ev2.JsonlDailySink(str(self.tmp), service), IDENT,
                               clock_ms=lambda: clock['t'], **kw)
            r.clock = clock
            r.emit('recorder.started', {'service': service}, {}, transition=True, state={'b': r.boot_id})
            self.recs[service] = r
        return self.recs[service]

    def emit(self, service, etype, subject, payload=None, t=T0, **kw):
        r = self.rec(service)
        r.clock['t'] = t
        r.emit(etype, subject, payload or {}, event_time_ms=t, **kw)

    def flush(self, now=None):
        for r in self.recs.values():
            if now is not None:
                r.clock['t'] = now
            r.flush_now()
            r.sink.write_stats(r.stats())


def pit(t_decision, candle_open=T0 - 1_800_000):
    return {'candle_open_time_ms': candle_open, 'candle_close_time_ms': candle_open + 899_999,
            'klines_fetched_at_ms': t_decision - 3000, 'analyzed_at_ms': t_decision - 2000,
            'orderbook_fetched_at_ms': t_decision - 2500}


def lifecycle(s, sid=1, cid='cand_a', t=T0, close=True):
    subj = {'candidate_id': cid, 'candle_id': 'AUSDT|15m|0', 'symbol': 'AUSDT', 'timeframe': '15m'}
    s.emit('analyzer', 'candidate.analyzed', subj, {'pit': pit(t)}, t=t - 1000,
           state={'tt': 'momentum'}, dedup_key=cid)
    s.emit('signal_engine', 'candidate.evaluated', subj, {'pit': pit(t), 'macro': {'macro_age_seconds': 60}},
           t=t, state={'decision': 'selected', 'reason': None}, dedup_key='e' + cid)
    s.emit('signal_engine', 'signal.ready', {'signal_id': sid, 'candidate_id': cid},
           {'pit': pit(t), 'outcome_code': 'POLICY_READY'}, t=t)
    sig = {'signal_id': sid, 'candidate_id': cid, 'symbol': 'AUSDT', 'timeframe': '15m'}
    s.emit('telegram', 'delivery.sent', sig, t=t + 60_000, state={'outcome': 'sent_direct'})
    s.emit('trade_tracker', 'entry.attempt', sig, t=t + 90_000, state={'action': 'market'})
    s.emit('trade_tracker', 'trade.opened', {**sig, 'active_trade_id': sid * 10}, t=t + 90_000)
    if close:
        s.emit('trade_tracker', 'trade.closed', {'active_trade_id': sid * 10, 'signal_id': sid,
                                                 'trade_result_id': sid}, t=t + 5 * H)


def findings(tmp, now):
    return rc.reconcile(str(tmp), now)


def test_complete_lifecycle_is_clean(tmp_path):
    s = Stream(tmp_path)
    lifecycle(s)
    s.flush(now=T0 + 6 * H)
    r = findings(tmp_path, T0 + 6 * H)
    assert r['exit_code'] == 0, r['findings']
    assert r['trade_lifecycle'] == {'opened': 1, 'closed': 1, 'open_within_horizon': 0, 'stale_open': 0,
                                    'dead_letters': {'explained': 0, 'unexplained': 0}}
    assert r['outcome_codes'] == {'signal.ready:POLICY_READY': 1}
    assert r['identity_coverage'] == 1.0


def test_missing_stages_and_stale_open_trade(tmp_path):
    s = Stream(tmp_path)
    lifecycle(s, sid=1, cid='cand_a', close=False)
    s.emit('signal_engine', 'candidate.evaluated', {'candidate_id': 'cand_b', 'symbol': 'B', 'timeframe': '15m'},
           {'pit': pit(T0)}, t=T0, state={'decision': 'selected'}, dedup_key='eb')
    s.emit('signal_engine', 'signal.ready', {'signal_id': 2, 'candidate_id': 'cand_b'}, {'pit': pit(T0)}, t=T0)
    s.flush(now=T0 + 60 * H)
    r = findings(tmp_path, T0 + 60 * H)
    f = r['findings']
    assert f['missing_delivery_stage']['count'] == 1
    assert f['incomplete_trade_lifecycle']['count'] == 1 and r['trade_lifecycle']['stale_open'] == 1
    assert f['signal_without_analysis_event']['count'] == 1
    assert r['exit_code'] == 1


def test_duplicates_conflicts_and_malformed_lines(tmp_path):
    s = Stream(tmp_path)
    lifecycle(s)
    s.flush()
    path = next((tmp_path / 'telegram').glob('events-*.jsonl'))
    lines = path.read_text().splitlines()
    sent = json.loads(lines[-1])
    restated = dict(sent, boot_id='other', seq=1)
    path.write_text('\n'.join(lines + [json.dumps(restated), '{broken']) + '\n')
    tpath = next((tmp_path / 'trade_tracker').glob('events-*.jsonl'))
    entry = json.loads(tpath.read_text().splitlines()[1])
    conflict = dict(entry, boot_id='third', seq=1, subject={**entry['subject'], 'signal_id': 999})
    tpath.write_text(tpath.read_text() + json.dumps(conflict) + '\n')
    f = findings(tmp_path, T0 + 6 * H)['findings']
    assert f['duplicate_event_restated']['severity'] == 'info'
    assert f['conflicting_event_id']['severity'] == 'critical'
    assert f['malformed_line']['count'] == 1


def test_sequence_gaps_and_recorder_health(tmp_path):
    s = Stream(tmp_path)
    r = s.rec('signal_engine', max_queue=3)
    for i in range(8):
        s.emit('signal_engine', 'cycle.outcome', {'stream': 'c'}, t=T0 + i, state={'o': i},
               dedup_key='c', transition=True)
    s.flush()
    rep = findings(tmp_path, T0 + 60_000)
    gap = rep['findings']['sequence_gap_lost_events']['examples'][0]
    assert gap['lost'] == r.dropped == 6
    assert rep['findings']['recorder_dropped']['count'] == 1
    assert rep['recorder_health']['signal_engine']['dropped'] == 6
    later = findings(tmp_path, T0 + 2 * H)                              # nothing flushed for 2h
    assert later['findings']['recorder_stale_flush']['count'] >= 1


def test_point_in_time_violations_and_staleness(tmp_path):
    s = Stream(tmp_path)
    subj = {'candidate_id': 'cand_x', 'symbol': 'X', 'timeframe': '15m'}
    bad = pit(T0)
    bad['candle_close_time_ms'] = bad['klines_fetched_at_ms'] + 10    # candle not closed at fetch
    s.emit('signal_engine', 'candidate.evaluated', subj, {'pit': bad}, t=T0, state={'decision': 'rejected'},
           dedup_key='x1')
    old = pit(T0 + 3 * H)                                              # analysed 3h before decision
    s.emit('signal_engine', 'candidate.evaluated', {**subj, 'candidate_id': 'cand_y'},
           {'pit': {**old, 'analyzed_at_ms': T0}, 'macro': {'macro_age_seconds': 9000}},
           t=T0 + 3 * H, state={'decision': 'rejected', 'reason': 'spread'}, dedup_key='y1')
    s.flush()
    f = findings(tmp_path, T0 + 4 * H)['findings']
    assert f['pit_violation']['severity'] == 'critical'
    assert f['stale_analysis']['count'] == 1 and f['stale_macro_used']['severity'] == 'critical'


def test_cli_exit_code_and_json(tmp_path, capsys):
    s = Stream(tmp_path)
    lifecycle(s)
    s.flush(now=T0 + 6 * H)
    out = tmp_path / 'report.json'
    code = rc.main(['--dir', str(tmp_path), '--now', ev2.ms_to_iso(T0 + 6 * H), '--json', str(out)])
    assert code == 0 and json.loads(out.read_text())['exit_code'] == 0
    assert 'exit_code=0' in capsys.readouterr().out


def test_tool_is_outcome_blind_by_construction():
    src = open(rc.__file__, encoding='utf-8').read()
    code = src.split('"""', 2)[2]                                       # ignore the module docstring
    assert not re.search(r"['\"](gross_profit|net_profit|profit_pct|pnl|result_label|"
                         r"weighted_exit_price|trigger_price|profit_usdt)['\"]", code)


def _sent(s, sid, t):
    sig = {'signal_id': sid, 'candidate_id': f'cand_{sid}', 'symbol': 'NUSDT', 'timeframe': '15m'}
    s.emit('signal_engine', 'signal.ready', {'signal_id': sid, 'candidate_id': f'cand_{sid}'},
           {'pit': pit(t), 'outcome_code': 'POLICY_READY'}, t=t)
    s.emit('telegram', 'delivery.sent', sig, {'outcome_code': 'DELIVERED',
                                             'claimed_event_type': 'signal.ready'},
           t=t + 30_000, state={'outcome': 'sent_direct'})
    return sig


def test_no_fill_dead_letter_is_explained_unobserved_is_flagged(tmp_path):
    """P1-R: a delivery event that exhausts its outbox attempts (runtime dead letter) is explained
    by evidence when an outcome was observed (limit wait -> NO_FILL); only an unobserved one warns."""
    s = Stream(tmp_path)
    sig = _sent(s, 7, T0)
    s.emit('trade_tracker', 'entry.attempt', sig, {'outcome_code': 'AWAITING_FILL'}, t=T0 + 60_000,
           state={'action': 'limit_wait'}, dedup_key='entry:7')
    s.emit('trade_tracker', 'delivery.consumed', {'signal_id': 7, 'outbox_event_id': 70},
           {'outcome_code': 'AWAITING_FILL', 'final_attempt': True, 'outbox_event_id': 70},
           t=T0 + 40 * 60_000, state={'kind': 'deferred'})
    s.emit('trade_tracker', 'entry.expired', sig, {'outcome_code': 'NO_FILL',
                                                  'last_outcome_code': 'AWAITING_FILL'},
           t=T0 + 2 * H + 30_000, state={'outcome_code': 'NO_FILL'})
    sig8 = _sent(s, 8, T0)
    s.emit('trade_tracker', 'delivery.consumed', {'signal_id': 8, 'outbox_event_id': 80},
           {'outcome_code': 'DEFERRED_UNOBSERVED', 'final_attempt': True, 'outbox_event_id': 80},
           t=T0 + 40 * 60_000, state={'kind': 'deferred'})
    s.flush(now=T0 + 3 * H)
    r = findings(tmp_path, T0 + 3 * H)
    assert r['trade_lifecycle']['dead_letters'] == {'explained': 1, 'unexplained': 1}
    codes = set(r['findings'])
    assert 'unexplained_dead_letter' in codes
    assert r['outcome_codes']['entry.expired:NO_FILL'] == 1
    assert 'missing_admission_stage' not in codes          # expiry/consumed count as tracker stage
