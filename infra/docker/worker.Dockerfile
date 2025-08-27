FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev zlib1g-dev gcc && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY worker /app
CMD ["python", "main.py"]
