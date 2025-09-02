# userbot.Dockerfile
FROM python:3.11-slim

# healthcheck через curl
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория — внутри папки userbot
WORKDIR /app/userbot

# Зависимости
COPY userbot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходники
COPY userbot/ .

# Каталог для зашифрованных сессий подрядчиков
RUN mkdir -p /app/sessions
ENV PYTHONUNBUFFERED=1

EXPOSE 8001
# Запускаем FastAPI: в userbot/api.py объект приложения называется "app"
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]
