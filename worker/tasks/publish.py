from celery import shared_task
import os, mimetypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

@shared_task
def send_document(chat_id: int, file_bytes: bytes, filename: str = "smeta.png", caption: str = "") -> bool:
    """Send bytes to Telegram as a document (protect_content=True)."""
    try:
        import requests, io
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {"document": (filename, io.BytesIO(file_bytes), mime)}
        data = {"chat_id": chat_id, "caption": caption, "protect_content": True}
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        r = requests.post(url, data=data, files=files, timeout=60)
        r.raise_for_status()
        return True
    except Exception as e:
        print("send_document error:", e)
        return False