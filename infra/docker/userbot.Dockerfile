FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY userbot/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

VOLUME ["/sessions"]
ENV TG_SESSION_NAME=userbot

COPY userbot /app
EXPOSE 8080
CMD ["python", "main.py"]
