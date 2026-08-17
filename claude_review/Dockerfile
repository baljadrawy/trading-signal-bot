# يدعم: linux/amd64 (Hetzner VPS) و linux/arm64 (Raspberry Pi 4)
FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9

ARG APP_VERSION=sb-2026.08
ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$BUILD_REVISION

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=$APP_VERSION

WORKDIR /app

# تثبيت Node.js 20 LTS (ضروري لـ claude CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# تثبيت claude CLI
RUN npm install -g @anthropic-ai/claude-code@2.1.197 \
    && claude --version

COPY claude_review/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.1.* wheel==0.46.* && pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY shared/ ./shared/
COPY claude_review/ ./

# مستخدم غير-root + HOME لأجل اعتمادات claude CLI (.claude مركّبة على /home/appuser)
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/logs \
    && chown -R appuser:appuser /app
ENV HOME=/home/appuser
USER appuser

CMD ["python", "-u", "main.py"]
