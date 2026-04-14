FROM python:3.11-slim
WORKDIR /app
COPY optimizer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY optimizer/ ./optimizer/
CMD ["python", "-u", "optimizer/main.py"]
