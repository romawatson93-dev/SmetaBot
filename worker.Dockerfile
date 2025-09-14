FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/worker

# Install fonts for watermark rendering (Roboto + DejaVu)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-roboto fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ .
# Run worker from the package directory so imports like `celery_app` and `tasks.*` resolve
WORKDIR /app/worker
CMD ["bash", "-lc", "celery -A celery_app.celery worker -l info --pool=solo"]
