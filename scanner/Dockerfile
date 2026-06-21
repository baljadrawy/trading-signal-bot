# يدعم: linux/amd64 (Hetzner VPS) و linux/arm64 (Raspberry Pi 4)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY scanner/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.1.* wheel==0.46.* && pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY shared/ ./shared/
COPY scanner/ ./

# مستخدم غير-root (uid 1000 يطابق tradmin على المضيف لصلاحيات الـ bind mounts)
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/logs /app/models \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-u", "main.py"]
