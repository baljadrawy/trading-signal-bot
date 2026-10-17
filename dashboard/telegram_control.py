"""A59 Telegram control PROTOTYPE (not wired into the live bot). Owner-only Open / Close / Status.

Owner identity = the existing approved configuration value (TELEGRAM_CHAT_ID), parsed as a numeric id and required to
match BOTH the sender's user id and a private chat with that same id. It is never hard-coded. Non-owners get no reply.
The handlers talk only to the dashboard's control socket (three signed operations); they have no other capability.
"""
import hashlib
import hmac
import json
import logging
import secrets
import time

import aiohttp

log = logging.getLogger('a59.telegram')
OPEN, CLOSE, STATUS = 'a59:open', 'a59:close', 'a59:status'
BUTTONS = [('🟢 فتح لوحة المتابعة', OPEN), ('🔴 إغلاق لوحة المتابعة', CLOSE), ('ℹ️ حالة اللوحة', STATUS)]


def owner_id(configured) -> int | None:
    s = str(configured or '').strip()
    return int(s) if s.isdigit() and int(s) > 0 else None   # private chats have positive ids; groups are negative


def is_owner(update, owner: int | None) -> bool:
    user, chat = getattr(update, 'effective_user', None), getattr(update, 'effective_chat', None)
    return bool(owner and user and chat and getattr(user, 'id', None) == owner
                and getattr(chat, 'type', None) == 'private' and getattr(chat, 'id', None) == owner)


class ControlClient:
    """Signed requests to the dashboard control socket. The key is shared only by the bot and the dashboard."""
    def __init__(self, socket_path: str, key: bytes, clock=time.time):
        self.socket_path, self.key, self.clock = socket_path, key, clock

    async def call(self, op: str) -> dict:
        body = json.dumps({'op': op, 'ts': self.clock(), 'nonce': secrets.token_hex(16)}).encode()
        sig = hmac.new(self.key, body, hashlib.sha256).hexdigest()
        async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=self.socket_path)) as s:
            async with s.post('http://a59/control', data=body, headers={'X-A59-Sig': sig},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()


def _mins(s):
    return f'{max(0, int(s or 0)) // 60}:{max(0, int(s or 0)) % 60:02d}'


async def handle(action: str, update, client: ControlClient, owner: int | None, reply) -> str | None:
    """Run one owner action. `reply(text)` sends a Telegram message. Returns the text sent (None for non-owners)."""
    if not is_owner(update, owner):
        log.warning('a59: unauthorized dashboard control attempt (ignored)')   # no ids, no details
        return None
    if action == OPEN:
        res = await client.call('open')
        if not res.get('ok'):
            text = '⚠️ تعذّر فتح اللوحة. لم يُفتح أي وصول.'
        else:
            text = ('🔐 رابط دخول لمرة واحدة (صالح 60 ثانية):\n' + res['url'] +
                    '\n\nتُغلق اللوحة تلقائياً بعد 15 دقيقة كحد أقصى. أي رابط سابق أُلغي.')
        try:
            await reply(text)
        except Exception:                                        # undelivered link: revoke it, fail closed
            await client.call('close')
            raise
        return text
    if action == CLOSE:
        res = await client.call('close')
        text = ('✅ أُغلقت اللوحة: أُلغيت كل الجلسات والروابط وتوقّف المنفذ.' if res.get('ok') else
                '🚨 فشل الإغلاق! اعتبره حادثاً أمنياً: ' + ','.join(res.get('errors') or ['unknown']))
        await reply(text)
        return text
    if action == STATUS:
        st = await client.call('status')
        label = {'closed': 'مغلقة 🔒', 'link_pending': 'بانتظار استخدام الرابط ⏳',
                 'session_active': 'جلسة نشطة 🟢'}.get(st.get('state'), 'غير معروفة ⚠️')
        extra = (f"\nتنتهي الجلسة خلال {_mins(st['session_expires_in_s'])}" if st.get('session_expires_in_s') else
                 f"\nينتهي الرابط خلال {st['link_expires_in_s']} ث" if st.get('link_expires_in_s') else '')
        text = f"حالة لوحة المتابعة: {label}{extra}\nالمنفذ: {'مفتوح' if st.get('listening') else 'مغلق'}"
        await reply(text)
        return text
    return None
