from typing import Optional
from .db import fetch, fetchrow, execute

async def list_contractors(limit: int = 100, offset: int = 0) -> list[dict]:
    rows = await fetch(
        "SELECT * FROM core.contractors ORDER BY id DESC LIMIT $1 OFFSET $2;",
        limit, offset
    )
    return [dict(r) for r in rows]

async def block_contractor(contractor_id: int, blocked: bool = True):
    await execute("UPDATE core.contractors SET blocked = $2 WHERE id = $1;", contractor_id, blocked)

async def grant_subscription(contractor_id: int, plan_code: str, days: int = 30):
    await execute(
        """
        INSERT INTO billing.subscriptions (contractor_id, plan, started_at, expires_at, source, status)
        VALUES ($1, $2, NOW(), NOW() + ($3 || ' days')::interval, 'admin_grant', 'active');
        """, contractor_id, plan_code, days
    )
