FROM python:3.11-slim
WORKDIR /app/userbot

# Устанавливаем python-зависимости
COPY userbot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY userbot/ .

# Папка для сессий
RUN mkdir -p /app/sessions
ENV PYTHONUNBUFFERED=1

EXPOSE 8001
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]
