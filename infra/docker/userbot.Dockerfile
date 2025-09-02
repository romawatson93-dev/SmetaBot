FROM python:3.11-slim

# Ставим системные утилиты, чтобы healthcheck мог использовать curl
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем зависимости
COPY userbot/requirements.txt /app/userbot/requirements.txt
RUN pip install --no-cache-dir -r /app/userbot/requirements.txt

# Копируем исходники
COPY userbot /app/userbot

# Папка для зашифрованных сессий (монтируется томом)
RUN mkdir -p /app/sessions
ENV PYTHONUNBUFFERED=1

EXPOSE 8001
CMD ["python", "-m", "userbot"]
