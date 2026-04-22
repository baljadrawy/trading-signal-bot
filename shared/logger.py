"""
نظام Logging موحد لجميع الـ Containers
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """إعداد Logger موحد — آمن ضد التكرار عند استدعائه أكثر من مرة
    أو على loggers متفرّعة (مثل 'optimizer' و 'optimizer.tuner')."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # منع الانتشار للـ parent logger (يحل مشكلة الطباعة المزدوجة
    # عند وجود handler على parent و child في نفس الوقت)
    logger.propagate = False

    # لو الـ handlers موجودة سابقاً نرجع الـ logger كما هو
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_dir = Path('/app/logs')
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(
        log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
