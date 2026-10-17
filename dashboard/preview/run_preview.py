"""Isolated preview runner (disposable container on an internal network only). Runs the REAL DashboardService with
the MockAdapter (synthetic data). A new single-use link is issued each time /shared/req appears (the capture script
asks for one per device); the URL is written to /shared/url.txt. Env: A59_MODE, A59_WINDOW_S (preview of expiry)."""
import asyncio, os, ssl, subprocess, sys, tempfile
sys.path.insert(0, '/src')
import dashboard.sessions as sessions
from dashboard.adapters import MockAdapter
from dashboard.service import DashboardService

async def main():
    if os.environ.get('A59_WINDOW_S'):
        sessions.WINDOW_S = int(os.environ['A59_WINDOW_S'])
    d = tempfile.mkdtemp()
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=a59-preview',
                    '-addext', 'subjectAltName=DNS:a59-preview', '-keyout', f'{d}/k.pem', '-out', f'{d}/c.pem'],
                   check=True, capture_output=True)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH); ctx.load_cert_chain(f'{d}/c.pem', f'{d}/k.pem')
    svc = DashboardService(sessions.Store(f'{d}/a59.db'), MockAdapter(mode=os.environ.get('A59_MODE', 'ok')),
                           host='0.0.0.0', port=8443, origin='https://a59-preview:8443', control_path=f'{d}/ctl.sock',
                           control_key=os.urandom(32), ssl_context=ctx)
    await svc.start()
    while True:
        if os.path.exists('/shared/req'):
            os.remove('/shared/req')
            res = await svc.open()
            tmp = '/shared/url.tmp'; open(tmp, 'w').write(res['url']); os.replace(tmp, '/shared/url.txt')
        if os.path.exists('/shared/status_req'):
            os.remove('/shared/status_req'); open('/shared/status.txt', 'w').write(str(await svc.status()))
        await asyncio.sleep(0.2)

asyncio.run(main())
