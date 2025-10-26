from typing import Optional
from .db import fetchrow, fetch, execute, executemany, q

# core.publications: id, channel_id, message_id, filename, file_type, caption, views, posted_at

async def add_publication(channel_id: int, message_id: int, filename: str, file_type: str, caption: Optional[str], views: int = 0) -> int:
    row = await fetchrow(
        f"""
        INSERT INTO {q("publications")} (channel_id, message_id, filename, file_type, caption, views)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (channel_id, message_id) DO UPDATE
            SET filename = EXCLUDED.filename, file_type = EXCLUDED.file_type, caption = EXCLUDED.caption
        RETURNING id;
        """,
        channel_id, message_id, filename, file_type, caption, views
    )
    return int(row["id"])

async def update_views_bulk(pairs: list[tuple[int,int]]):
    # pairs: [(channel_id, message_id, views), ...]
    await executemany(
        f"UPDATE {q('publications')} SET views = $3 WHERE channel_id = $1 AND message_id = $2;",
        pairs
    )

async def list_recent(channel_id: int, limit: int = 20) -> list[dict]:
    rows = await fetch(
        f"SELECT * FROM {q('publications')} WHERE channel_id = $1 ORDER BY posted_at DESC LIMIT $2;",
        channel_id, limit
    )
    return [dict(r) for r in rows]
