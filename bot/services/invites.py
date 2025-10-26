from datetime import datetime
from typing import Optional
from .db import fetchrow, fetch, execute, q

# core.invites: id, channel_id, token, max_uses, used_count, expires_at, active

async def create_invite(channel_id: int, token: str, max_uses: int = 1, expires_at: Optional[datetime] = None) -> int:
    row = await fetchrow(
        f"""
        INSERT INTO {q("invites")} (channel_id, token, max_uses, expires_at, active)
        VALUES ($1, $2, $3, $4, TRUE)
        RETURNING id;
        """, channel_id, token, max_uses, expires_at
    )
    return int(row["id"])

async def list_active(channel_id: int) -> list[dict]:
    rows = await fetch(f"SELECT * FROM {q('invites')} WHERE channel_id = $1 AND active = TRUE ORDER BY id DESC;", channel_id)
    return [dict(r) for r in rows]

async def mark_used(invite_id: int):
    await execute(f"UPDATE {q('invites')} SET used_count = used_count + 1 WHERE id = $1;", invite_id)

async def disable(invite_id: int):
    await execute(f"UPDATE {q('invites')} SET active = FALSE WHERE id = $1;", invite_id)
