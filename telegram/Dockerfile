# يدعم: linux/amd64 (Hetzner VPS) و linux/arm64 (Raspberry Pi 4)
FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9

ARG APP_VERSION=sb-2026.08
# Provenance (WP-A06, R5.b): no defaults. A release build passes the values that
# ops/provenance/build_preflight.py proves from a clean checkout; the guard refuses others.
ARG BUILD_REVISION
ARG BUILD_TREE_CLEAN
ARG STRATEGY_SOURCE_HASHES
LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$BUILD_REVISION \
      tsb.build.tree_clean=$BUILD_TREE_CLEAN \
      tsb.strategy.source_hashes=$STRATEGY_SOURCE_HASHES
RUN case "$BUILD_REVISION" in *[!0-9a-f]*|"") exit 64;; esac; [ "${#BUILD_REVISION}" -eq 40 ] && [ "$BUILD_TREE_CLEAN" = true ] && [ -n "$STRATEGY_SOURCE_HASHES" ]

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=$APP_VERSION

WORKDIR /app

COPY telegram/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.1.* wheel==0.46.* && pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY shared/ ./shared/
COPY telegram/ ./

# مستخدم غير-root (uid 1000 يطابق tradmin على المضيف لصلاحيات الـ bind mounts)
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/logs /app/models \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-u", "main.py"]
