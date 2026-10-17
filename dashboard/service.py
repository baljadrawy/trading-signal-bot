"""A59 on-demand dashboard service: a private control socket (for the Telegram bot) plus a web listener that exists
ONLY while a login link or a session is valid. When the dashboard is closed the HTTPS port is not bound at all.

Control channel: a unix socket (mode 0600) accepting exactly three HMAC-signed operations: open, close, status.
It has no shell, Docker, database-admin or trading capability. Web: /login (single use), / (page), /api/state (read),
/api/close (CSRF + Origin). Tokens never appear in logs; the login URL is replaced by a 303 to "/".
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

from .adapters import DATA_STALE_S, DataUnavailable, derive
from .sessions import Store

log = logging.getLogger('a59')
COOKIE = '__Host-a59'                       # __Host-: Secure, Path=/, no Domain (browser-enforced)
STATIC = Path(__file__).parent / 'static'
CONTROL_SKEW_S = 30
SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
                               "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store', 'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'Strict-Transport-Security': 'max-age=31536000',
}


class ScrubbedAccessLogger(AbstractAccessLogger):
    """Method, path WITHOUT query string, status. A login token can never reach a log line."""
    def log(self, request, response, time_):
        self.logger.info('%s %s %s', request.method, request.rel_url.path, response.status)


class DashboardService:
    def __init__(self, store: Store, adapter, *, host: str, port: int, origin: str, control_path: str,
                 control_key: bytes, ssl_context=None, clock=time.time):
        self.store, self.adapter, self.host, self.port, self.origin = store, adapter, host, port, origin.rstrip('/')
        self.control_path, self.control_key, self.ssl, self.clock = control_path, control_key, ssl_context, clock
        self._web_runner = self._ctl_runner = self._watchdog = None
        self._nonces: dict[str, float] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    async def start(self):
        self.store.revoke_all('service_start')                 # a restart never restores any access
        app = web.Application(client_max_size=4096)
        app.router.add_post('/control', self._control)
        self._ctl_runner = web.AppRunner(app, access_log=None)
        await self._ctl_runner.setup()
        if os.path.exists(self.control_path):
            os.unlink(self.control_path)
        old = os.umask(0o177)
        try:
            await web.UnixSite(self._ctl_runner, self.control_path).start()
        finally:
            os.umask(old)
        os.chmod(self.control_path, 0o600)
        self._watchdog = asyncio.create_task(self._watch())

    async def stop(self):
        if self._watchdog:
            self._watchdog.cancel()
        await self._stop_listener()
        if self._ctl_runner:
            await self._ctl_runner.cleanup()

    @property
    def listening(self) -> bool:
        return self._web_runner is not None

    async def _start_listener(self):
        if self._web_runner:
            return
        app = web.Application(middlewares=[self._headers], client_max_size=4096)
        app.router.add_get('/login', self._login)
        app.router.add_get('/', self._index)
        app.router.add_get('/static/{name}', self._static)
        app.router.add_get('/api/state', self._state)
        app.router.add_post('/api/close', self._web_close)
        runner = web.AppRunner(app, access_log_class=ScrubbedAccessLogger, access_log=logging.getLogger('a59.access'))
        await runner.setup()
        await web.TCPSite(runner, self.host, self.port, ssl_context=self.ssl).start()
        self._web_runner = runner

    async def _stop_listener(self):
        runner, self._web_runner = self._web_runner, None
        if runner:
            await runner.cleanup()

    async def _watch(self):
        while True:
            await asyncio.sleep(1)
            try:
                if self.listening and self.store.status()['state'] == 'closed':
                    await self.close('expired')
            except Exception:                                    # never let the watchdog die silently
                log.exception('a59 watchdog')

    # ------------------------------------------------------------------ owner operations
    async def open(self) -> dict:
        async with self._lock:
            token, window_end = self.store.issue_link()
            await self._start_listener()
            return {'ok': True, 'url': f'{self.origin}/login?t={token}', 'window_end': window_end}

    async def close(self, reason: str) -> dict:
        """Stop the listener FIRST (no request can be served), then revoke, then verify both. Fail loudly."""
        async with self._lock:
            errors = []
            try:
                await self._stop_listener()
            except Exception as exc:
                errors.append(f'listener:{type(exc).__name__}')
            try:
                self.store.revoke_all(reason)
            except Exception as exc:
                errors.append(f'revoke:{type(exc).__name__}')
            st = self.store.status()
            if self.listening or st['state'] != 'closed':
                errors.append('verify')
            return {'ok': not errors, 'errors': errors, 'state': st['state'], 'listening': self.listening}

    async def status(self) -> dict:
        return {**self.store.status(), 'listening': self.listening}

    # ------------------------------------------------------------------ control channel
    def _signed(self, body: bytes, sig: str | None) -> bool:
        want = hmac.new(self.control_key, body, hashlib.sha256).hexdigest()
        return bool(sig) and hmac.compare_digest(want, sig)

    async def _control(self, request):
        body = await request.read()
        if not self._signed(body, request.headers.get('X-A59-Sig')):
            return web.json_response({'ok': False, 'error': 'unauthorized'}, status=403)
        try:
            msg = json.loads(body)
            ts, nonce, op = float(msg['ts']), str(msg['nonce']), msg['op']
        except Exception:
            return web.json_response({'ok': False, 'error': 'bad_request'}, status=400)
        now = self.clock()
        self._nonces = {n: t for n, t in self._nonces.items() if now - t < 2 * CONTROL_SKEW_S}
        if abs(now - ts) > CONTROL_SKEW_S or nonce in self._nonces:
            return web.json_response({'ok': False, 'error': 'stale_or_replayed'}, status=403)
        self._nonces[nonce] = now
        ops = {'open': self.open, 'close': lambda: self.close('telegram'), 'status': self.status}
        if op not in ops:
            return web.json_response({'ok': False, 'error': 'unknown_op'}, status=400)
        return web.json_response(await ops[op]())

    # ------------------------------------------------------------------ web
    @web.middleware
    async def _headers(self, request, handler):
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc
        except Exception:
            log.error('a59 handler error on %s', request.rel_url.path)
            resp = web.Response(status=500, text='error')
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp

    def _session(self, request):
        return self.store.check(request.cookies.get(COOKIE, ''))

    def _same_origin(self, request, required: bool) -> bool:
        origin = request.headers.get('Origin')
        if origin is None:
            return not required
        return origin == self.origin

    async def _login(self, request):
        res = self.store.redeem(request.query.get('t', ''))
        if not res:
            return web.Response(status=403, text='الرابط غير صالح أو منتهي. اطلب رابطاً جديداً من تيليجرام.',
                                content_type='text/plain', charset='utf-8')
        sid, _, expires = res
        resp = web.HTTPSeeOther('/')                           # drop the token from the address bar
        resp.set_cookie(COOKIE, sid, path='/', secure=True, httponly=True, samesite='Strict',
                        max_age=max(1, int(expires - self.clock())))
        return resp

    async def _index(self, request):
        sess = self._session(request)
        if not sess:
            return web.Response(status=401, text='الجلسة غير موجودة أو انتهت.', content_type='text/plain',
                                charset='utf-8')
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        html = html.replace('__CSRF__', sess['csrf']).replace('__EXPIRES__', str(int(sess['expires'])))
        return web.Response(text=html, content_type='text/html', charset='utf-8')

    async def _static(self, request):
        name = request.match_info['name']
        if name not in ('app.js', 'app.css'):
            raise web.HTTPNotFound()
        ctype = 'application/javascript' if name.endswith('.js') else 'text/css'
        return web.Response(body=(STATIC / name).read_bytes(), content_type=ctype)

    async def _state(self, request):
        sess = self._session(request)
        if not sess or request.headers.get('X-A59-Request') != '1' or not self._same_origin(request, False):
            return web.json_response({'error': 'unauthorized'}, status=401)
        now = self.clock()
        base = {'session_expires_at': sess['expires'], 'server_time': now, 'stale_after_s': DATA_STALE_S}
        try:
            raw = await asyncio.wait_for(self.adapter.fetch(), timeout=8)
            return web.json_response({**base, 'ok': True, 'fetched_at': now, 'data': derive(raw, now)})
        except (DataUnavailable, asyncio.TimeoutError):
            return web.json_response({**base, 'ok': False, 'error': 'data_unavailable'})

    async def _web_close(self, request):
        sess = self._session(request)
        if not sess or not self._same_origin(request, True) or \
                not Store.csrf_ok(sess['csrf'], request.headers.get('X-CSRF-Token')):
            return web.json_response({'error': 'forbidden'}, status=403)
        asyncio.get_running_loop().call_later(0.05, lambda: asyncio.ensure_future(self.close('web')))
        return web.json_response({'ok': True})
