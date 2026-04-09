# يدعم: linux/amd64 (Hetzner VPS) و linux/arm64 (Raspberry Pi 4)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY scanner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY shared/ ./shared/
COPY scanner/ ./

CMD ["python", "-u", "main.py"]
