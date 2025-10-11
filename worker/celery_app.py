import os
from celery import Celery

broker = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Running from /app/worker; register tasks via local package path
celery = Celery(
    "smetabot-worker",
    broker=broker,
    include=["tasks.render"],
)

# Ensure tasks modules are imported so @shared_task registers
import tasks.render  # noqa: F401
