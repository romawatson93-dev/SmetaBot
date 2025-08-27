import os
from pydantic import BaseModel

class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "dev")
    db_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://app:app@db:5432/estimates")

settings = Settings()
