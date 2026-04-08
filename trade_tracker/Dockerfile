FROM python:3.11-slim
WORKDIR /app
COPY trade_tracker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ shared/
COPY trade_tracker/ .
CMD ["python", "-u", "main.py"]
