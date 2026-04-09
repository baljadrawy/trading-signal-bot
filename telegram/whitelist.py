"""
نظام Whitelist + الموافقة اليدوية عبر Telegram
- العملات في الـ Whitelist تُرسل مباشرة للبوت المنفذ
- العملات الجديدة تحتاج موافقة يدوية خلال 30 دقيقة
- كل موافقة تُضيف العملة للـ Whitelist تلقائياً
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
import aiohttp
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger

logger = setup_logger('whitelist')


class WhitelistManager:

    async def is_whitelisted(self, symbol: str) -> bool:
        """هل العملة في الـ Whitelist؟"""
        result = await Database.fetchval(
            "SELECT COUNT(*) FROM symbol_whitelist WHERE symbol = $1",
            symbol
        )
        return result > 0

    async def add_to_whitelist(self, symbol: str, notes: str = ""):
        """إضافة عملة للـ Whitelist بعد الموافقة"""
        await Database.execute("""
            INSERT INTO symbol_whitelist (symbol, approved_by, notes)
            VALUES ($1, 'user_telegram', $2)
            ON CONFLICT (symbol) DO UPDATE
            SET approved_at = NOW(), notes = $2
        """, symbol, notes)
        logger.info(f"✅ تمت إضافة {symbol} للـ Whitelist")

    async def get_all(self) -> list:
        """جلب كل العملات المعتمدة"""
        rows = await Database.fetch(
            "SELECT symbol, approved_at FROM symbol_whitelist ORDER BY approved_at DESC"
        )
        return [dict(r) for r in rows]

    async def remove(self, symbol: str):
        """إزالة عملة من الـ Whitelist"""
        await Database.execute(
            "DELETE FROM symbol_whitelist WHERE symbol = $1", symbol
        )
        logger.info(f"🗑️ تمت إزالة {symbol} من الـ Whitelist")


class BlacklistManager:
    """إدارة القائمة السوداء - العملات المرفوضة نهائياً"""

    async def add_to_blacklist(self, symbol: str, reason: str = "رفض يدوي من Telegram"):
        """إضافة عملة للقائمة السوداء"""
        await Database.execute("""
            INSERT INTO symbol_blacklist (symbol, reason)
            VALUES ($1, $2)
            ON CONFLICT (symbol) DO UPDATE
            SET rejected_at = NOW(), reason = $2
        """, symbol, reason)
        logger.info(f"🚫 تمت إضافة {symbol} للقائمة السوداء")

    async def is_blacklisted(self, symbol: str) -> bool:
        """هل العملة في القائمة السوداء؟"""
        result = await Database.fetchval(
            "SELECT COUNT(*) FROM symbol_blacklist WHERE symbol = $1", symbol
        )
        return result > 0

    async def remove_from_blacklist(self, symbol: str):
        """إزالة عملة من القائمة السوداء"""
        await Database.execute(
            "DELETE FROM symbol_blacklist WHERE symbol = $1", symbol
        )
        logger.info(f"✅ تمت إزالة {symbol} من القائمة السوداء")

    async def get_all(self) -> list:
        """جلب كل العملات المحظورة"""
        rows = await Database.fetch(
            "SELECT symbol, rejected_at, reason FROM symbol_blacklist ORDER BY rejected_at DESC"
        )
        return [dict(r) for r in rows]


class ApprovalManager:

    def __init__(self):
        self.whitelist = WhitelistManager()
        self.blacklist = BlacklistManager()
        self.timeout_minutes = config.APPROVAL_TIMEOUT_MINUTES
        self.max_price_change_pct = config.APPROVAL_MAX_PRICE_CHANGE_PCT

    async def process_signal(self, signal: dict) -> str:
        """
        معالجة الإشارة:
        - إذا العملة في Whitelist → أرسل مباشرة
        - إذا جديدة → اطلب موافقة
        يرجع: 'sent_direct' / 'awaiting_approval' / 'rejected'
        """
        symbol = signal['symbol']

        # تحقق من الـ Whitelist
        if await self.whitelist.is_whitelisted(symbol):
            logger.info(f"✅ {symbol} في الـ Whitelist - إرسال مباشر")
            return 'sent_direct'

        # عملة جديدة - اطلب موافقة
        logger.info(f"🆕 {symbol} غير موجودة في الـ Whitelist - طلب موافقة")
        await self._create_approval_request(signal)
        return 'awaiting_approval'

    async def _create_approval_request(self, signal: dict):
        """إنشاء طلب موافقة في قاعدة البيانات"""
        expires_at = datetime.now() + timedelta(minutes=self.timeout_minutes)

        await Database.execute("""
            INSERT INTO approval_requests
            (signal_id, symbol, expires_at, entry_price_at_request)
            VALUES ($1, $2, $3, $4)
        """,
            signal['id'],
            signal['symbol'],
            expires_at,
            float(signal['entry_price'])
        )

    async def handle_approval(self, signal_id: int, approved: bool, current_price: float) -> dict:
        """
        معالجة رد المستخدم على طلب الموافقة
        يرجع: {'action': 'send'/'reject'/'expired'/'price_changed', 'reason': '...'}
        """
        # جلب طلب الموافقة
        request = await Database.fetchrow("""
            SELECT ar.*, s.symbol, s.entry_price
            FROM approval_requests ar
            JOIN signals s ON ar.signal_id = s.id
            WHERE ar.signal_id = $1 AND ar.status = 'pending'
        """, signal_id)

        if not request:
            return {'action': 'reject', 'reason': 'الطلب غير موجود أو انتهت صلاحيته'}

        # تحقق من انتهاء الوقت
        if datetime.now() > request['expires_at']:
            await self._update_request(signal_id, 'expired', current_price)
            return {'action': 'expired', 'reason': f'انتهت الصلاحية (30 دقيقة)'}

        # إذا رفض المستخدم → أضف للقائمة السوداء فوراً
        if not approved:
            await self._update_request(signal_id, 'rejected', current_price)
            await self.blacklist.add_to_blacklist(
                request['symbol'],
                reason="رفض يدوي من Telegram"
            )
            return {'action': 'reject', 'reason': 'تم الرفض وإضافة العملة للقائمة السوداء'}

        # تحقق من تغير السعر
        entry_price = float(request['entry_price_at_request'])
        price_change_pct = abs((current_price - entry_price) / entry_price * 100)

        if price_change_pct > self.max_price_change_pct:
            await self._update_request(signal_id, 'expired', current_price, price_change_pct)
            return {
                'action': 'price_changed',
                'reason': f'السعر تغير {price_change_pct:.2f}% (الحد الأقصى {self.max_price_change_pct}%)'
            }

        # موافقة ناجحة → أضف للـ Whitelist وأزل من السوداء إن وُجدت
        await self._update_request(signal_id, 'approved', current_price, price_change_pct)
        await self.whitelist.add_to_whitelist(request['symbol'])
        await self.blacklist.remove_from_blacklist(request['symbol'])

        return {'action': 'send', 'reason': 'تمت الموافقة وإضافة العملة للـ Whitelist'}

    async def _update_request(self, signal_id: int, status: str,
                               current_price: float, price_change_pct: float = 0):
        await Database.execute("""
            UPDATE approval_requests
            SET status = $1,
                responded_at = NOW(),
                current_price_at_approval = $2,
                price_change_pct = $3
            WHERE signal_id = $4
        """, status, current_price, price_change_pct, signal_id)

    async def expire_old_requests(self):
        """تنظيف الطلبات المنتهية تلقائياً"""
        expired = await Database.fetch("""
            UPDATE approval_requests
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at < NOW()
            RETURNING signal_id, symbol
        """)
        for req in expired:
            logger.info(f"⏰ انتهت صلاحية طلب الموافقة على {req['symbol']}")
        return expired
