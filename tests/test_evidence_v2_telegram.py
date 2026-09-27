"""Telegram instrumentation (P1-D): delivery refusals and owner risk controls are recorded without
changing replies or database writes. Runs where python-telegram-bot is installed (the telegram image);
skipped elsewhere, like the other telegram tests."""
import sys; sys.path.insert(0, '.')
import asyncio
import json
from types import SimpleNamespace

import pytest

main = pytest.importorskip('main', reason='production-parity env only (module lives at /app/main.py)')
pytest.importorskip('telegram.ext', reason='python-telegram-bot not installed')
if not hasattr(main, 'cmd_recover_risk'):
    pytest.skip('main.py is not the Telegram service', allow_module_level=True)

from shared import evidence_v2 as ev2          # noqa: E402
from shared.config import config               # noqa: E402

OWNER = '424242'
IDENT = {'strategy_version': 'sb-test', 'code_sha': 'c' * 64, 'config_hash': 'h' * 64,
         'build_revision': 'unknown', 'phase_id': None}


class Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def owner_update():
    return SimpleNamespace(effective_chat=SimpleNamespace(id=int(OWNER)),
                           effective_user=SimpleNamespace(username='owner', id=1), message=Msg())


def enable(monkeypatch):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', True)
    ev2.reset_for_tests()
    sink = ev2.ListSink()
    rec = ev2.RecorderV2('telegram', sink, IDENT)
    ev2._RECORDERS['telegram'] = rec
    return rec, sink


SIGNAL = {'id': 41, 'symbol': 'AAAUSDT', 'timeframe': '15m', 'telegram_sent': True,
          'claude_approved': True,
          'features_snapshot': json.dumps({'identity': {'candidate_id': 'cand_abc'}})}


def test_delivery_events_carry_lineage_and_reason(monkeypatch):
    rec, sink = enable(monkeypatch)
    main._v2_delivery('delivery.refused', SIGNAL, 'refused', 'risk:loss_streak_halt', 7)
    main._v2_delivery('delivery.skipped', SIGNAL, 'skipped', None, 8)          # reason derived inside
    main._v2_delivery('delivery.skipped', None, 'skipped', None, 9)            # missing signal row
    rec.flush_now()
    refused, skipped, missing = sink.records()
    assert refused['subject'] == {'signal_id': 41, 'candidate_id': 'cand_abc', 'symbol': 'AAAUSDT',
                                  'timeframe': '15m'}
    assert refused['state'] == {'outcome': 'refused', 'reason': 'risk:loss_streak_halt'}
    assert skipped['state']['reason'] == 'already_sent' and missing['state']['reason'] == 'signal_missing'
    ev2.reset_for_tests()


def test_control_hook_reads_partial_objects_without_raising(monkeypatch):
    rec, sink = enable(monkeypatch)
    main._v2_control('resume', 'resumed', streak=SimpleNamespace(halt_active=True))
    main._v2_control('recover_risk', 'recovered', recovery={'id': 3, 'reason': 'reviewed'}, still_paused=True)
    rec.flush_now()
    resume, recovered = sink.records()
    assert resume['payload']['halt_active'] is True and resume['payload']['consecutive_losses'] is None
    assert recovered['payload']['id'] == 3 and recovered['payload']['still_paused'] is True
    assert not any('chat' in k for e in sink.records() for k in e['payload'])
    ev2.reset_for_tests()


def _pause(monkeypatch):
    executed = []

    async def execute(sql, *args):
        executed.append(' '.join(sql.split()))
    monkeypatch.setattr(main.Database, 'execute', execute)
    monkeypatch.setattr(config, 'TELEGRAM_CHAT_ID', OWNER)
    update = owner_update()
    asyncio.run(main.cmd_pause(update, SimpleNamespace(args=[])))
    return executed, update.message.replies


def test_pause_command_behaviour_is_unchanged_by_recording(monkeypatch):
    monkeypatch.setattr(config, 'EVIDENCE_V2_ENABLED', False)
    ev2.reset_for_tests()
    off = _pause(monkeypatch)
    rec, sink = enable(monkeypatch)
    on = _pause(monkeypatch)
    assert on == off and off[0] and off[1]
    rec.flush_now()
    [event] = sink.records()
    assert event['event_type'] == 'control.command'
    assert event['state'] == {'command': 'pause', 'outcome': 'paused'}
    ev2.reset_for_tests()
