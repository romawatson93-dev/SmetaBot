from celery import shared_task
import os, mimetypes, time

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

@shared_task
def send_document(chat_id: int, file_bytes: bytes, filename: str = "smeta.png", caption: str = "") -> bool:
    """Send bytes to Telegram as a document (protect_content=True).

    Retries transient errors (e.g., channel not ready, bot rights not yet propagated)
    with small backoff to handle races right after channel creation.
    """
    import requests, io
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    backoff = [1, 2, 3, 5, 8]
    for attempt, delay in enumerate([0] + backoff, start=1):
        try:
            files = {"document": (filename, io.BytesIO(file_bytes), mime)}
            data = {"chat_id": chat_id, "caption": caption, "protect_content": True}
            r = requests.post(url, data=data, files=files, timeout=60)
            if r.status_code >= 400:
                # Log text for diagnostics
                print(f"send_document attempt {attempt} failed: {r.status_code} {r.text}")
                if attempt < len(backoff) + 1 and r.status_code in (400, 403, 429):
                    time.sleep(delay)
                    continue
                r.raise_for_status()
            return True
        except Exception as e:
            print(f"send_document exception on attempt {attempt}: {e}")
            if attempt < len(backoff) + 1:
                time.sleep(delay)
                continue
            return False
    return False
