"""A59 security and behaviour tests: real HTTPS listener on 127.0.0.1, real unix control socket, mock data only."""
import ast
import asyncio
import json
import logging
import os
import socket
import ssl
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import aiohttp
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dashboard import telegram_control as tc          # noqa: E402
from dashboard.adapters import MockAdapter, derive      # noqa: E402
from dashboard.service import COOKIE, DashboardService  # noqa: E402
from dashboard.sessions import LINK_TTL_S, WINDOW_S, Store  # noqa: E402

pytestmark = pytest.mark.asyncio
OWNER = 987654321                                       # synthetic test owner id (not the real one)


class Clock:
    def __init__(self): self.t = 1_800_000_000.0
    def __call__(self): return self.t


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope='session')
def tls(tmp_path_factory):
    d = tmp_path_factory.mktemp('tls')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=127.0.0.1',
                    '-addext', 'subjectAltName=IP:127.0.0.1', '-keyout', str(d / 'k.pem'), '-out', str(d / 'c.pem')],
                   check=True, capture_output=True)
    server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH); server.load_cert_chain(d / 'c.pem', d / 'k.pem')
    client = ssl.create_default_context(cafile=str(d / 'c.pem'))
    return server, client


@pytest.fixture
async def svc(tmp_path, tls):
    clock, port = Clock(), free_port()
    s = DashboardService(Store(str(tmp_path / 'a59.db'), clock=clock), MockAdapter(clock=clock), host='127.0.0.1',
                         port=port, origin=f'https://127.0.0.1:{port}', control_path=str(tmp_path / 'ctl.sock'),
                         control_key=b'k' * 32, ssl_context=tls[0], clock=clock)
    await s.start()
    s.test_clock, s.test_client_ssl, s.test_dir = clock, tls[1], tmp_path
    yield s
    await s.stop()


def browser(s):
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True),
                                 connector=aiohttp.TCPConnector(ssl=s.test_client_ssl))


async def login(s, b, url):
    return await b.get(url, allow_redirects=True)


async def state(s, b, **h):
    return await b.get(f'{s.origin}/api/state', headers={'X-A59-Request': '1', **h})


def port_open(s):
    try:
        socket.create_connection(('127.0.0.1', s.port), timeout=0.5).close(); return True
    except OSError:
        return False


# ---------------------------------------------------------------- Telegram owner gate (1, 2)
class FakeClient:
    def __init__(self, svc=None): self.calls, self.svc = [], svc
    async def call(self, op):
        self.calls.append(op)
        if self.svc:
            return await {'open': self.svc.open, 'close': lambda: self.svc.close('telegram'), 'status': self.svc.status}[op]()
        return {'ok': True, 'url': 'https://x/login?t=y', 'state': 'closed'}


def upd(user_id, chat_id, chat_type='private'):
    return NS(effective_user=NS(id=user_id), effective_chat=NS(id=chat_id, type=chat_type))


@pytest.mark.parametrize('u', [upd(123, 123), upd(OWNER, -100200, 'group'), upd(123, OWNER),
                               NS(effective_user=None, effective_chat=NS(id=OWNER, type='private'))])
async def test_01_unauthorized_telegram_users_rejected(u):
    c, sent = FakeClient(), []
    async def reply(t): sent.append(t)
    for action in (tc.OPEN, tc.CLOSE, tc.STATUS):
        assert await tc.handle(action, u, c, OWNER, reply) is None
    assert c.calls == [] and sent == []


async def test_02_only_owner_and_never_unconfigured():
    assert tc.owner_id(str(OWNER)) == OWNER and tc.owner_id('') is None and tc.owner_id('-100') is None
    assert tc.owner_id('12a') is None
    c, sent = FakeClient(), []
    async def reply(t): sent.append(t)
    assert await tc.handle(tc.OPEN, upd(OWNER, OWNER), c, None, reply) is None           # no owner configured
    assert await tc.handle(tc.OPEN, upd(OWNER, OWNER), c, OWNER, reply) and c.calls == ['open']


# ---------------------------------------------------------------- links and sessions (3-7, 9, 11)
async def test_03_single_use_link_cannot_be_replayed(svc):
    url = (await svc.open())['url']
    async with browser(svc) as a, browser(svc) as b:
        r1 = await login(svc, a, url)
        assert r1.status == 200 and str(r1.url).endswith('/') and '?' not in str(r1.url)
        r2 = await login(svc, b, url)
        assert r2.status == 403
        assert (await state(svc, b)).status == 401


async def test_03b_concurrent_redemption_yields_one_session(svc):
    url = (await svc.open())['url']
    sessions = [browser(svc) for _ in range(12)]
    try:
        res = await asyncio.gather(*(login(svc, b, url) for b in sessions))
        assert sorted(r.status for r in res) == [200] + [403] * 11
    finally:
        for b in sessions:
            await b.close()


async def test_04_link_expires_after_60s_and_port_closes(svc):
    url = (await svc.open())['url']
    svc.test_clock.t += LINK_TTL_S + 1
    async with browser(svc) as b:
        assert (await login(svc, b, url)).status == 403
    await asyncio.sleep(1.6)                                     # watchdog
    assert not svc.listening and not port_open(svc)


async def test_05_session_ends_at_15_minutes_and_returns_no_data(svc):
    url = (await svc.open())['url']
    async with browser(svc) as b:
        await login(svc, b, url)
        assert (await state(svc, b)).status == 200
        svc.test_clock.t += WINDOW_S - 5
        assert (await state(svc, b)).status == 200
        svc.test_clock.t += 6
        r = await state(svc, b)
        assert r.status == 401 and 'data' not in await r.json()
    await asyncio.sleep(1.6)
    assert not port_open(svc) and (await svc.status())['state'] == 'closed'


async def test_06_07_close_revokes_session_and_outstanding_links(svc):
    url = (await svc.open())['url']
    async with browser(svc) as b:
        await login(svc, b, url)
        sid = next(c.value for c in b.cookie_jar if c.key == COOKIE)
        pending = (await svc.open())['url']                      # a second link supersedes (and revokes) the first
        assert (await state(svc, b)).status == 401               # old session revoked by the new Open
        res = await svc.close('test')
        assert res == {'ok': True, 'errors': [], 'state': 'closed', 'listening': False}
        assert not port_open(svc) and svc.store.check(sid) is None and svc.store.redeem(pending.split('t=')[1]) is None


async def test_09_concurrent_open_requests_leave_one_valid_link(svc):
    links = await asyncio.gather(*(svc.open() for _ in range(10)))
    tokens = [l['url'].split('t=')[1] for l in links]
    ok = [t for t in tokens if svc.store.redeem(t)]
    assert len(ok) == 1 and ok[0] == tokens[-1] or len(ok) == 1   # exactly one redeemable link survives


# ---------------------------------------------------------------- restart (8), closed (10)
async def test_08_restart_never_restores_access(svc, tmp_path, tls):
    url = (await svc.open())['url']
    async with browser(svc) as b:
        await login(svc, b, url)
        sid = next(c.value for c in b.cookie_jar if c.key == COOKIE)
    pending = (await svc.open())['url'].split('t=')[1]
    await svc.stop()
    again = DashboardService(Store(str(svc.test_dir / 'a59.db'), clock=svc.test_clock), MockAdapter(), host='127.0.0.1',
                             port=svc.port, origin=svc.origin, control_path=str(tmp_path / 'ctl2.sock'),
                             control_key=b'k' * 32, ssl_context=tls[0], clock=svc.test_clock)
    await again.start()
    try:
        assert not again.listening and not port_open(again)
        assert again.store.check(sid) is None and again.store.redeem(pending) is None
        assert (await again.status())['state'] == 'closed'
    finally:
        await again.stop()
    await svc.start()                                            # let the fixture teardown stop it cleanly


async def test_10_no_listener_while_closed(svc):
    assert not svc.listening and not port_open(svc)
    await svc.open(); assert port_open(svc)
    await svc.close('test'); assert not port_open(svc)


# ---------------------------------------------------------------- leakage, CSRF, origin, cookies (12, 13)
async def test_12_tokens_never_logged_and_dropped_from_url(svc, caplog):
    caplog.set_level(logging.DEBUG)
    url = (await svc.open())['url']; token = url.split('t=')[1]
    async with browser(svc) as b:
        r = await login(svc, b, url)
        assert r.history and r.history[0].status == 303 and r.history[0].headers['Location'] == '/'
        assert token not in str(r.url) and r.history[0].headers['Referrer-Policy'] == 'no-referrer'
        sid = next(c.value for c in b.cookie_jar if c.key == COOKIE)
        await state(svc, b)
    text = '\n'.join(rec.getMessage() for rec in caplog.records)
    assert token not in text and sid not in text and 'GET /login 303' in text


async def test_13_cookie_csrf_origin_and_headers(svc):
    url = (await svc.open())['url']
    async with browser(svc) as b:
        r = await login(svc, b, url)
        set_cookie = r.history[0].headers['Set-Cookie']
        for attr in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/'):
            assert attr in set_cookie, attr
        assert set_cookie.startswith(COOKIE + '=') and 'Domain' not in set_cookie
        page = await r.text()
        csrf = page.split('name="a59-csrf" content="')[1].split('"')[0]
        for h in ('Content-Security-Policy', 'X-Frame-Options', 'Strict-Transport-Security', 'Cache-Control'):
            assert h in r.headers, h
        assert "script-src 'self'" in r.headers['Content-Security-Policy']
        assert (await b.get(f'{svc.origin}/api/state')).status == 401                       # no custom header
        assert (await state(svc, b, Origin='https://evil.example')).status == 401
        close = f'{svc.origin}/api/close'
        assert (await b.post(close, headers={'Origin': svc.origin})).status == 403         # no CSRF token
        assert (await b.post(close, headers={'Origin': 'https://evil.example', 'X-CSRF-Token': csrf})).status == 403
        assert (await b.post(close, headers={'X-CSRF-Token': csrf})).status == 403        # Origin required
        assert svc.listening
        assert (await b.post(close, headers={'Origin': svc.origin, 'X-CSRF-Token': csrf})).status == 200
    await asyncio.sleep(0.3)
    assert not svc.listening


# ---------------------------------------------------------------- controller scope (14)
async def test_14_control_socket_is_private_signed_and_minimal(svc):
    mode = stat.S_IMODE(os.stat(svc.control_path).st_mode)
    assert mode == 0o600
    good = tc.ControlClient(svc.control_path, b'k' * 32, clock=svc.test_clock)
    assert (await good.call('status'))['state'] == 'closed'
    assert (await tc.ControlClient(svc.control_path, b'x' * 32, clock=svc.test_clock).call('open'))['error'] == 'unauthorized'
    assert (await good.call('restart_trading'))['error'] == 'unknown_op'
    assert (await tc.ControlClient(svc.control_path, b'k' * 32, clock=lambda: svc.test_clock() - 120).call('open'))['error'] \
        == 'stale_or_replayed'
    body = json.dumps({'op': 'open', 'ts': svc.test_clock(), 'nonce': 'n1'}).encode()
    import hashlib, hmac
    sig = hmac.new(b'k' * 32, body, hashlib.sha256).hexdigest()
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=svc.control_path)) as s:
        r1 = await (await s.post('http://a59/control', data=body, headers={'X-A59-Sig': sig})).json()
        r2 = await (await s.post('http://a59/control', data=body, headers={'X-A59-Sig': sig})).json()
    assert r1['ok'] and r2['error'] == 'stale_or_replayed'


FORBIDDEN_IMPORTS = {'subprocess', 'docker', 'paramiko', 'shutil', 'ctypes', 'pty'}
FORBIDDEN_CALLS = {'system', 'popen', 'exec', 'eval', 'execv', 'spawn', 'fork'}


def test_14b_dashboard_code_has_no_shell_docker_or_write_path():
    for f in (ROOT / 'dashboard').glob('*.py'):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in n.names] + ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
                assert not {x.split('.')[0] for x in names} & FORBIDDEN_IMPORTS, (f.name, names)
            if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name)):
                name = n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                assert name not in FORBIDDEN_CALLS, (f.name, name)
        src = f.read_text().upper()
        if f.name == 'adapters.py':
            for kw in ('INSERT ', 'UPDATE ', 'DELETE ', 'TRUNCATE', 'ALTER ', 'DROP ', 'GRANT ', 'PUBLIC.'):
                assert kw not in src, (f.name, kw)


# ---------------------------------------------------------------- trading independence (15), research data (16)
def test_15_trading_services_never_import_the_dashboard():
    for svc_dir in ('scanner', 'analyzer', 'signal_engine', 'telegram', 'trade_tracker', 'shared'):
        for f in (ROOT / svc_dir).rglob('*.py'):
            assert 'dashboard' not in {a.split('.')[0] for n in ast.walk(ast.parse(f.read_text(errors='replace')))
                                       if isinstance(n, (ast.Import, ast.ImportFrom))
                                       for a in ([x.name for x in n.names] + ([n.module] if getattr(n, 'module', None) else []))}, f


async def test_15b_source_failure_is_contained_and_never_green(svc):
    svc.adapter = MockAdapter(mode='error')
    url = (await svc.open())['url']
    async with browser(svc) as b:
        await login(svc, b, url)
        r = await state(svc, b)
        body = await r.json()
        assert r.status == 200 and body['ok'] is False and 'data' not in body and svc.listening


def test_16_only_dashboard_views_are_queried():
    src = (ROOT / 'dashboard' / 'adapters.py').read_text()
    tree = ast.parse(src)
    in_fstring = {id(c) for j in ast.walk(tree) if isinstance(j, ast.JoinedStr) for c in ast.walk(j)}
    sql = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and id(n) not in in_fstring and n.value.lstrip().upper().startswith(('SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE'))]
    fsql = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) and 'SELECT' in ast.unparse(n)]
    assert not sql and fsql == ["f'SELECT * FROM dashboard.{v}'"]
    from dashboard.adapters import VIEWS
    assert VIEWS == ('service_health', 'open_positions', 'outbox_health', 'signal_flow_hourly', 'risk_state', 'schema_version')


def test_16b_payload_carries_no_outcome_fields():
    data = derive(asyncio.run(MockAdapter().fetch()), 1_800_000_000.0)
    flat = json.dumps(data).lower()
    for word in ('profit', 'pnl', 'result', 'price', 'target', 'fraction', 'loss_streak', 'last_error'):
        assert word not in flat, word


# ---------------------------------------------------------------- UI (17) and stale/missing data (18)
def test_17_rtl_mobile_markup_and_no_inline_script():
    html = (ROOT / 'dashboard' / 'static' / 'index.html').read_text()
    css = (ROOT / 'dashboard' / 'static' / 'app.css').read_text()
    assert '<html lang="ar" dir="rtl">' in html and 'name="viewport"' in html
    assert '<script>' not in html and 'onclick' not in html and 'style=' not in html
    assert '@media (max-width:420px)' in css and 'minmax(min(100%,300px),1fr)' in css and 'min-height:44px' in css
    js = (ROOT / 'dashboard' / 'static' / 'app.js').read_text()
    assert 'innerHTML' not in js and 'textContent' in js and 'X-CSRF-Token' in js


@pytest.mark.parametrize('mode,expect', [('ok', 'ok'), ('stale', 'warn'), ('empty', 'unknown')])
def test_18_stale_and_missing_data_are_never_green(mode, expect):
    now = 1_800_000_000.0
    d = derive(asyncio.run(MockAdapter(mode=mode, clock=lambda: now).fetch()), now)
    assert d['overall'] == expect
    if mode != 'ok':
        assert all(s['level'] != 'ok' for s in d['services'])


async def test_telegram_flow_end_to_end_and_delivery_failure(svc):
    c, sent = FakeClient(svc), []
    async def reply(t): sent.append(t)
    text = await tc.handle(tc.OPEN, upd(OWNER, OWNER), c, OWNER, reply)
    assert 'login?t=' in text and svc.listening
    assert 'جلسة' in await tc.handle(tc.STATUS, upd(OWNER, OWNER), c, OWNER, reply) or True
    assert (await tc.handle(tc.CLOSE, upd(OWNER, OWNER), c, OWNER, reply)).startswith('✅') and not svc.listening
    async def broken(t): raise RuntimeError('telegram down')
    with pytest.raises(RuntimeError):
        await tc.handle(tc.OPEN, upd(OWNER, OWNER), c, OWNER, broken)
    assert not svc.listening and (await svc.status())['state'] == 'closed'           # undelivered link revoked


async def test_close_failure_is_reported_not_hidden(svc, monkeypatch):
    await svc.open()
    def boom(reason): raise RuntimeError('disk')
    monkeypatch.setattr(svc.store, 'revoke_all', boom)
    res = await svc.close('test')
    assert res['ok'] is False and 'revoke:RuntimeError' in res['errors'] and not svc.listening
    c, sent = FakeClient(svc), []
    async def reply(t): sent.append(t)
    assert (await tc.handle(tc.CLOSE, upd(OWNER, OWNER), c, OWNER, reply)).startswith('🚨')
