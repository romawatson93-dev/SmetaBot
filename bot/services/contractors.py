from typing import Optional
from .db import fetchrow, fetch, execute, fetchval, q

# core.contractors: id(bigserial PK), tg_id BIGINT UNIQUE, username TEXT, created_at, blocked BOOL

async def get_or_create_by_tg(tg_id: int, username: Optional[str] = None) -> int:
    row = await fetchrow(
        f"""
        INSERT INTO {q("contractors")} (tg_id, username)
        VALUES ($1, $2)
        ON CONFLICT (tg_id) DO UPDATE SET username = COALESCE(EXCLUDED.username, {q("contractors")}.username)
        RETURNING id;
        """,
        tg_id, username,
    )
    return int(row["id"])

async def get_by_id(contractor_id: int) -> Optional[dict]:
    row = await fetchrow(f"SELECT * FROM {q('contractors')} WHERE id = $1;", contractor_id)
    return dict(row) if row else None

async def block(contractor_id: int, blocked: bool = True) -> None:
    await execute(f"UPDATE {q('contractors')} SET blocked = $2 WHERE id = $1;", contractor_id, blocked)

# Профиль / обзор — тянем из analytics.profile_overview (VIEW)
async def profile_overview(contractor_id: int) -> Optional[dict]:
    row = await fetchrow(f"SELECT * FROM analytics.profile_overview WHERE contractor_id = $1;", contractor_id)
    return dict(row) if row else None
