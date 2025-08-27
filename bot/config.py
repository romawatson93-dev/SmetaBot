import os
from dataclasses import dataclass

def _parse_owner_ids(raw: str) -> set[int]:
    ids = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids

@dataclass(frozen=True)
class Settings:
    bot_token: str
    backend_url: str
    owner_ids: set[int]

    def __init__(self):
        object.__setattr__(self, "bot_token", os.getenv("BOT_TOKEN", ""))
        object.__setattr__(self, "backend_url", os.getenv("BACKEND_URL", "http://backend:8000"))
        object.__setattr__(self, "owner_ids", _parse_owner_ids(os.getenv("OWNER_IDS", "")))

settings = Settings()
