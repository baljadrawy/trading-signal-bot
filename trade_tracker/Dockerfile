FROM python:3.12-slim
WORKDIR /app
COPY trade_tracker/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.1.* wheel==0.46.* && pip install --no-cache-dir -r requirements.txt
COPY shared/ shared/
COPY trade_tracker/ .

# مستخدم غير-root (uid 1000 يطابق tradmin على المضيف لصلاحيات الـ bind mounts)
RUN useradd -u 1000 -m appuser \
    && mkdir -p /app/logs /app/models \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-u", "main.py"]
