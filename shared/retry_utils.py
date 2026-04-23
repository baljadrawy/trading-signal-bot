"""
أدوات مساعدة موحدة لمعالجة الأخطاء وإعادة المحاولة.

الهدف: التمييز بين أخطاء الشبكة المؤقتة (عطل DNS، انقطاع Binance/Telegram) وأخطاء
الكود/قاعدة البيانات، لأن أخطاء الشبكة تحصل في datacenter مزود VPS
(Hetzner) لمدد قد تصل 15-20 دقيقة، ولا تحتاج تنبيهات حرجة في كل دورة.
"""
import asyncio
import socket

_NETWORK_EXC = [OSError, asyncio.TimeoutError, ConnectionError, socket.gaierror]

try:
    import aiohttp
    _NETWORK_EXC.extend([
        aiohttp.ClientConnectionError,
        aiohttp.ClientConnectorError,
        aiohttp.ServerDisconnectedError,
        aiohttp.ClientOSError,
    ])
except ImportError:
    pass

try:
    import asyncpg
    _NETWORK_EXC.extend([
        asyncpg.PostgresConnectionError,
        asyncpg.ConnectionDoesNotExistError,
    ])
except ImportError:
    pass

try:
    import anthropic
    _NETWORK_EXC.extend([
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    ])
except (ImportError, AttributeError):
    pass

NETWORK_EXC = tuple(_NETWORK_EXC)


def format_error(e: BaseException) -> str:
    """تمثيل نصي مفيد حتى لو كان str(e) فارغاً."""
    msg = str(e)
    if not msg:
        msg = repr(e)
    return f"{type(e).__name__}: {msg}"


def is_network_error(e: BaseException) -> bool:
    return isinstance(e, NETWORK_EXC)


def compute_backoff(consecutive_errors: int, network: bool) -> int:
    """
    Exponential-ish backoff:
    - أخطاء كود: 60s, 120s, 180s, ... max 300s (5 دقائق)
    - أخطاء شبكة: 60s, 120s, 180s, ... max 600s (10 دقائق) — عطل مزود VPS قد يطول
    """
    step = 60 * consecutive_errors
    cap = 600 if network else 300
    return min(step, cap)


def alert_threshold(network: bool) -> int:
    """
    عتبة إرسال تنبيه Telegram حرج:
    - أخطاء كود: 3 متتالية (يحتاج تدخل سريع)
    - أخطاء شبكة: 10 متتالية (~15 دقيقة) — لا نزعج على عطل مزود VPS عابر
    """
    return 10 if network else 3
