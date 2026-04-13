"""
نظام تنبيهات Telegram للأخطاء الحرجة
يُستخدم من جميع الـ containers لإرسال تنبيهات للمستخدم
"""
import aiohttp
import logging
from shared.config import config

logger = logging.getLogger(__name__)

ALERT_LEVELS = {
    'info':     'ℹ️',
    'warning':  '⚠️',
    'critical': '🚨',
}


async def send_alert(message: str, level: str = 'warning', component: str = ''):
    """
    إرسال تنبيه لـ Telegram
    level: 'info' | 'warning' | 'critical'
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return

    icon = ALERT_LEVELS.get(level, '⚠️')
    comp = f"[{component}] " if component else ""
    text = f"{icon} {comp}{message}"

    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={'chat_id': config.TELEGRAM_CHAT_ID, 'text': text},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"فشل إرسال التنبيه: {resp.status}")
    except Exception as e:
        logger.error(f"خطأ في إرسال التنبيه: {e}")
