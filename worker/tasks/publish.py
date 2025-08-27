from celery import shared_task
from aiogram import Bot
import os, tempfile

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

@shared_task
def send_document(chat_id: int, jpeg_bytes: bytes, filename: str = "smeta.jpg", caption: str = "") -> bool:
    # aiogram синхронно не работает — используем простой HTTP к Bot API или aio под-runner.
    # Для MVP — Bot API через requests (синхронно), но здесь оставим заглушку.
    try:
        import requests, io
        files = {"document": (filename, io.BytesIO(jpeg_bytes), "image/jpeg")}
        data = {"chat_id": chat_id, "caption": caption, "protect_content": True}
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        r = requests.post(url, data=data, files=files, timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:
        print("send_document error:", e)
        return False
