from typing import Optional
from .db import fetchrow, fetch, execute, q

# core.clients: id, channel_id, invite_id, tg_user_id, username, full_name, joined_at, blocked

async def register_client(channel_id: int, invite_id: Optional[int], tg_id: int, full_name: Optional[str], username: Optional[str]) -> int:
    row = await fetchrow(
        f"""
        INSERT INTO {q("clients")} (channel_id, invite_id, tg_user_id, full_name, username)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (channel_id, tg_user_id) DO UPDATE
            SET username = COALESCE(EXCLUDED.username, {q("clients")}.username),
                full_name = COALESCE(EXCLUDED.full_name, {q("clients")}.full_name)
        RETURNING id;
        """, channel_id, invite_id, tg_id, full_name, username
    )
    return int(row["id"]) if row else 0

async def block_client(client_id: int, blocked: bool = True):
    await execute(f"UPDATE {q('clients')} SET blocked = $2 WHERE id = $1;", client_id, blocked)

async def counts_for_channel(channel_id: int) -> dict:
    row = await fetchrow(
        f"""
        SELECT
          COUNT(*)::int AS clients_total,
          COUNT(*) FILTER (WHERE blocked) ::int AS blocked_total
        FROM {q('clients')}
        WHERE channel_id = $1;
        """, channel_id
    )
    return dict(row) if row else {"clients_total": 0, "blocked_total": 0}
