import os
from celery import Celery

broker = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery = Celery("smetabot-worker", broker=broker)

# Ensure tasks modules are imported so @shared_task registers
import tasks.render  # noqa: F401

