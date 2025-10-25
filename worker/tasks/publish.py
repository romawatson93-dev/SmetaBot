from celery import shared_task
import logging
import os
import mimetypes
import time

from worker.metrics import record_publish

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
logger = logging.getLogger(__name__)

@shared_task
def send_document(chat_id: int, file_bytes: bytes, filename: str = "smeta.png", caption: str = "") -> dict[str, object] | None:
    """Send bytes to Telegram as a document (protect_content=True).

    Retries transient errors (e.g., channel not ready, bot rights not yet propagated)
    with small backoff to handle races right after channel creation.
    """
    import io
    import requests

    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    backoff = [1, 2, 3, 5, 8]
    payload_size = len(file_bytes)
    start = time.monotonic()

    for attempt, delay in enumerate([0] + backoff, start=1):
        try:
            files = {"document": (filename, io.BytesIO(file_bytes), mime)}
            data = {"chat_id": chat_id, "caption": caption, "protect_content": True}
            response = requests.post(url, data=data, files=files, timeout=60)
            if response.status_code >= 400:
                logger.warning(
                    "send_document attempt=%d status=%d response=%s",
                    attempt,
                    response.status_code,
                    response.text[:500],
                )
                if attempt < len(backoff) + 1 and response.status_code in (400, 403, 429):
                    time.sleep(delay)
                    continue
                response.raise_for_status()
            duration = time.monotonic() - start
            record_publish("success", duration, attempt - 1, payload_size)
            try:
                payload = response.json()
            except ValueError:
                payload = {"ok": False}
            return payload if isinstance(payload, dict) else {"ok": False}
        except Exception:  # pragma: no cover - network path
            logger.exception("send_document exception attempt=%d", attempt)
            if attempt < len(backoff) + 1:
                time.sleep(delay)
                continue
            duration = time.monotonic() - start
            record_publish("failure", duration, attempt - 1, payload_size)
            return None

    duration = time.monotonic() - start
    record_publish("failure", duration, len(backoff), payload_size)
    return None
