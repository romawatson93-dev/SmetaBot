from typing import Optional
from .db import fetchrow, fetch

# analytics.profile_overview (VIEW) — агрегат для "Мой профиль"
async def profile_overview(contractor_id: int) -> Optional[dict]:
    row = await fetchrow("SELECT * FROM analytics.profile_overview WHERE contractor_id = $1;", contractor_id)
    return dict(row) if row else None

# Пример: последние события (если используете analytics.events)
async def recent_events(channel_id: int, limit: int = 50) -> list[dict]:
    rows = await fetch(
        "SELECT * FROM analytics.events WHERE channel_id = $1 ORDER BY created_at DESC LIMIT $2;",
        channel_id, limit
    )
    return [dict(r) for r in rows]
