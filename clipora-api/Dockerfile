FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
ENV DATABASE_PATH=/data/clipora.db
CMD ["sh", "-c", "mkdir -p /data && uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
