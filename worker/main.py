import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery("worker", broker=REDIS_URL, backend=REDIS_URL)
app.autodiscover_tasks(["tasks"])

if __name__ == "__main__":
    app.start()
