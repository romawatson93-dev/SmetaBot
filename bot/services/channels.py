from typing import Optional, Sequence
from .db import fetch, fetchrow, execute, q

# core.channels: id, contractor_id, tg_id UNIQUE, title, username, created_at
# core.channel_members: channel_id, user_id, role, full_name, username

async def create_channel(contractor_id: int, tg_channel_id: int, title: str, username: Optional[str] = None) -> int:
    row = await fetchrow(
        f"""
        INSERT INTO {q("channels")} (contractor_id, tg_id, title, username)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (tg_id) DO UPDATE
            SET title = EXCLUDED.title, username = EXCLUDED.username
        RETURNING id;
        """, contractor_id, tg_channel_id, title, username
    )
    return int(row["id"])

async def upsert_member(tg_channel_id: int, user_id: int, role: str, full_name: Optional[str], username: Optional[str]):
    await execute(
        f"""
        INSERT INTO {q("channel_members")} (channel_id, user_id, role, full_name, username)
        VALUES (
            (SELECT id FROM {q("channels")} WHERE tg_id = $1),
            $2, $3, $4, $5
        )
        ON CONFLICT (channel_id, user_id) DO UPDATE
            SET role = EXCLUDED.role, full_name = EXCLUDED.full_name, username = EXCLUDED.username;
        """,
        tg_channel_id, user_id, role, full_name, username
    )

async def list_by_contractor(contractor_id: int) -> list[dict]:
    rows = await fetch(f"SELECT * FROM {q('channels')} WHERE contractor_id = $1 ORDER BY created_at DESC;", contractor_id)
    return [dict(r) for r in rows]

async def recent_stats(contractor_id: int) -> dict:
    row = await fetchrow(
        """
        SELECT
          COUNT(*)::int AS channels_count,
          COALESCE(SUM(pub.cnt),0)::int AS files_count,
          COALESCE(SUM(pub.views),0)::int AS views_total
        FROM core.channels ch
        LEFT JOIN (
           SELECT channel_id, COUNT(*) AS cnt, SUM(views)::bigint AS views
           FROM core.publications
           GROUP BY channel_id
        ) pub ON pub.channel_id = ch.id
        WHERE ch.contractor_id = $1;
        """, contractor_id
    )
    return dict(row) if row else {"channels_count":0, "files_count":0, "views_total":0}
