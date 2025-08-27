FROM python:3.11-slim

RUN pip install --upgrade pip

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy asyncpg pydantic

COPY backend /app

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
