"""Screenshot the REAL dashboard (served by run_preview.py) in WebKit (Safari engine) iPhone viewports and a Chromium
desktop viewport. Internal Docker network only; the self-signed preview certificate is accepted for this host only.
Usage: capture.py <scenario> ; writes /shared/shots/<scenario>__<device>.png and /shared/checks/<scenario>.json"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

SCEN = sys.argv[1]
DEVICES = [('iphone13', 'webkit', 'iPhone 13', 'light'), ('iphoneSE', 'webkit', 'iPhone SE', 'light'),
           ('iphone14ProMax', 'webkit', 'iPhone 14 Pro Max', 'light'), ('iphone13-dark', 'webkit', 'iPhone 13', 'dark'),
           ('desktop', 'chromium', None, 'light')]
if SCEN in ('expiry', 'closed'):
    DEVICES = DEVICES[:1]


def new_link():
    before = os.path.getmtime('/shared/url.txt') if os.path.exists('/shared/url.txt') else 0
    open('/shared/req', 'w').close()
    for _ in range(100):
        if os.path.exists('/shared/url.txt') and os.path.getmtime('/shared/url.txt') > before:
            return open('/shared/url.txt').read().strip()
        time.sleep(0.1)
    raise RuntimeError('no link')


checks = []
os.makedirs('/shared/shots', exist_ok=True); os.makedirs('/shared/checks', exist_ok=True)
with sync_playwright() as p:
    for name, engine, dev, scheme in DEVICES:
        browser = getattr(p, engine).launch()
        opts = dict(p.devices[dev]) if dev else {'viewport': {'width': 1366, 'height': 900}}
        opts.pop('default_browser_type', None)
        ctx = browser.new_context(**opts, color_scheme=scheme, ignore_https_errors=True, locale='ar')
        page = ctx.new_page()
        url = new_link()
        page.goto(url, wait_until='networkidle')
        page.wait_for_timeout(1200)
        if SCEN == 'expiry':
            page.screenshot(path=f'/shared/shots/{SCEN}-countdown__{name}.png', full_page=True)
            page.wait_for_timeout(27000)
        if SCEN == 'closed':
            page.click('#close'); page.wait_for_timeout(1200)
        page.screenshot(path=f'/shared/shots/{SCEN}__{name}.png', full_page=True)
        token = url.split('t=')[1]
        checks.append({'device': name, 'final_url_has_token': token in page.url, 'final_path': page.url.split('8443')[1],
                       'document_cookie': page.evaluate('document.cookie'), 'token_in_html': token in page.content(),
                       'close_button_box': page.locator('#close').bounding_box(),
                       'overall_class': page.get_attribute('#overall', 'class'),
                       'banner': page.locator('#banner').inner_text() if page.locator('#banner').is_visible() else '',
                       'synthetic_badge': page.locator('#synthetic').is_visible(),
                       'scroll_width': page.evaluate('document.documentElement.scrollWidth'),
                       'viewport_width': page.viewport_size['width'], 'dir': page.get_attribute('html', 'dir')})
        browser.close()
open(f'/shared/checks/{SCEN}.json', 'w').write(json.dumps(checks, ensure_ascii=False, indent=1))
print(SCEN, 'ok', len(checks))
