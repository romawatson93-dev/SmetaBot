FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/worker:/app

ENV SAL_USE_VCLPLUGIN=headless

# LibreOffice CLI + fonts for watermarking (use HTTPS mirrors to avoid blocked HTTP)
RUN set -eux; \
    printf 'deb https://deb.debian.org/debian trixie main\n' > /etc/apt/sources.list; \
    printf 'deb https://deb.debian.org/debian trixie-updates main\n' >> /etc/apt/sources.list; \
    printf 'deb https://security.debian.org/debian-security trixie-security main\n' >> /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-calc \
        fonts-roboto \
        fonts-dejavu-core \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fontconfig; \
    fc-cache -fv; \
    rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities (watermark config, etc.)
COPY common/ /app/common/

# Copy package into /app/worker so it is importable as `import worker`
COPY worker/ /app/worker/

# Run from the package directory so local imports `tasks.*` resolve
WORKDIR /app/worker
ENV CELERY_POOL=prefork CELERY_CONCURRENCY=3 CELERY_MAX_TASKS_PER_CHILD=100 CELERY_QUEUES=default PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus METRICS_PORT=9464
CMD ["bash", "-lc", "mkdir -p ${PROMETHEUS_MULTIPROC_DIR}; find ${PROMETHEUS_MULTIPROC_DIR} -type f -delete; celery -A celery_app.celery worker -l info --pool=${CELERY_POOL} -c ${CELERY_CONCURRENCY} --max-tasks-per-child=${CELERY_MAX_TASKS_PER_CHILD} -Q ${CELERY_QUEUES} -Ofair"]

