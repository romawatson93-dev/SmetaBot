import os
from celery import Celery
from kombu import Queue

broker = os.getenv("REDIS_URL", "redis://redis:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", broker)

# Running from /app/worker; register tasks via local package path
celery = Celery(
    "smetabot-worker",
    broker=broker,
    backend=result_backend,
    include=["tasks.render", "tasks.publish", "tasks.preview"],
)

default_queue = os.getenv("CELERY_DEFAULT_QUEUE", "default")
pdf_queue = os.getenv("CELERY_PDF_QUEUE", "pdf")
publish_queue = os.getenv("CELERY_PUBLISH_QUEUE", "publish")
office_queue = os.getenv("CELERY_OFFICE_QUEUE", "office")
preview_queue = os.getenv("CELERY_PREVIEW_QUEUE", "preview")

queues = []
seen = set()
for name in (
    default_queue,
    pdf_queue,
    publish_queue,
    office_queue,
    preview_queue,
):
    if name in seen:
        continue
    queues.append(Queue(name))
    seen.add(name)

# Tune worker defaults for better throughput under load.
celery.conf.update(
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "1")),
    task_acks_late=True,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "240")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "180")),
    broker_connection_retry_on_startup=True,
    task_default_queue=default_queue,
    task_queues=queues,
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

# Ensure tasks modules are imported so @shared_task registers.
import tasks.render  # noqa: F401
import tasks.publish  # noqa: F401
import tasks.preview  # noqa: F401

from worker.metrics import setup_celery_signal_handlers  # noqa: E402

setup_celery_signal_handlers()
