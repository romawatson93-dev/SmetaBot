FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install fonts and LibreOffice CLI (convert DOC/DOCX/XLSX). Force HTTPS mirrors to avoid HTTP blocks.
RUN set -eux; \
    printf 'deb https://deb.debian.org/debian trixie main\n' > /etc/apt/sources.list; \
    printf 'deb https://deb.debian.org/debian trixie-updates main\n' >> /etc/apt/sources.list; \
    printf 'deb https://security.debian.org/debian-security trixie-security main\n' >> /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends fonts-roboto fonts-dejavu-core libreoffice-writer libreoffice-calc; \
    rm -rf /var/lib/apt/lists/*

COPY bot/requirements.txt /app/bot/requirements.txt
RUN pip install --no-cache-dir -r /app/bot/requirements.txt

# Copy source under package path
COPY bot/ /app/bot/

# Run as a module to keep imports like `from bot...`
CMD ["python", "-m", "bot.main"]

