# يدعم: linux/amd64 (Hetzner VPS) و linux/arm64 (Raspberry Pi 4)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# تثبيت Node.js 20 LTS (ضروري لـ claude CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# تثبيت claude CLI
RUN npm install -g @anthropic-ai/claude-code \
    && claude --version

COPY claude_review/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.1.* wheel==0.46.* && pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY shared/ ./shared/
COPY claude_review/ ./

CMD ["python", "-u", "main.py"]
