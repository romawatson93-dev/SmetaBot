FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/worker

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
        fontconfig \
        ghostscript; \
    fc-cache -fv; \
    rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy package into /app/worker so it is importable as `import worker`
COPY worker/ /app/worker/

# Run from the package directory so local imports `tasks.*` resolve
WORKDIR /app/worker
CMD ["bash", "-lc", "celery -A celery_app.celery worker -l info --pool=solo"]

