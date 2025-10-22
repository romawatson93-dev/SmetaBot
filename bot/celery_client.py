import os
from typing import Optional

from celery import Celery

_celery_app: Optional[Celery] = None


def _make_celery() -> Celery:
    broker_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    backend_url = os.getenv("CELERY_RESULT_BACKEND", broker_url)
    app = Celery("bot", broker=broker_url, backend=backend_url)

    default_queue = os.getenv("CELERY_DEFAULT_QUEUE", "default")
    pdf_queue = os.getenv("CELERY_PDF_QUEUE", "pdf")
    publish_queue = os.getenv("CELERY_PUBLISH_QUEUE", "publish")
    office_queue = os.getenv("CELERY_OFFICE_QUEUE", "office")
    preview_queue = os.getenv("CELERY_PREVIEW_QUEUE", "preview")

    app.conf.update(
        task_default_queue=default_queue,
        task_routes={
            "tasks.render.render_pdf_to_png_300dpi": {"queue": pdf_queue},
            "tasks.render.render_pdf_to_jpeg_300dpi": {"queue": pdf_queue},
            "tasks.render.process_and_publish_pdf": {"queue": pdf_queue},
            "tasks.render.process_and_publish_png": {"queue": publish_queue},
            "tasks.render.process_and_publish_doc": {"queue": office_queue},
            "tasks.render.process_and_publish_excel": {"queue": office_queue},
            "tasks.preview.generate_preview_task": {"queue": preview_queue},
            "tasks.publish.send_document": {"queue": publish_queue},
        },
    )
    return app


def get_celery() -> Celery:
    global _celery_app
    if _celery_app is None:
        _celery_app = _make_celery()
    return _celery_app
