# tsb P2 forward collector — public market data only, zero trading authority.
# Base: local python:3.12-slim (sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9, arm64)
FROM python@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-deps --only-binary=:all: -r /tmp/requirements.txt && pip check && rm /tmp/requirements.txt
COPY p2_forward /app/p2_forward
WORKDIR /app
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=2 \
  CMD python -c "import json,time,sys;h=json.load(open('/data/health/collector_health.json'));sys.exit(0 if time.time()*1000-h['ts_ms']<60000 else 1)"
ENTRYPOINT ["python", "-m", "p2_forward"]
