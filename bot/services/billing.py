from datetime import datetime, timedelta
from typing import Optional
from .db import fetchrow, fetch, execute

# billing.subscriptions: id, contractor_id, plan, started_at, expires_at, status, source
# billing.plans: code (FREE/PRO/BUSINESS), ...
# billing.gifts_queue: contractor_id, plan_code, reason, applied_at

async def get_active_subscription(contractor_id: int) -> Optional[dict]:
    row = await fetchrow(
        """
        SELECT * FROM billing.subscriptions
        WHERE contractor_id = $1 AND (expires_at IS NULL OR expires_at > NOW()) AND status IN ('active','trial')
        ORDER BY expires_at DESC NULLS LAST
        LIMIT 1;
        """, contractor_id
    )
    return dict(row) if row else None

async def activate_subscription(contractor_id: int, plan_code: str, days: int, source: str = "paid", status: str = "active") -> int:
    row = await fetchrow(
        """
        INSERT INTO billing.subscriptions (contractor_id, plan, started_at, expires_at, source, status)
        VALUES ($1, $2, NOW(), NOW() + ($3 || ' days')::interval, $4, $5)
        RETURNING id;
        """, contractor_id, plan_code, days, source, status
    )
    return int(row["id"])

async def enqueue_gift(contractor_id: int, plan_code: str, reason: str):
    await execute(
        "INSERT INTO billing.gifts_queue (contractor_id, plan_code, reason) VALUES ($1, $2, $3);",
        contractor_id, plan_code, reason
    )

async def apply_gifts_if_no_active(contractor_id: int) -> Optional[int]:
    # берём подарок из очереди, если нет активной подписки
    active = await get_active_subscription(contractor_id)
    if active:
        return None
    gift = await fetchrow(
        "SELECT id, plan_code FROM billing.gifts_queue WHERE contractor_id = $1 AND applied_at IS NULL ORDER BY id LIMIT 1;",
        contractor_id
    )
    if not gift:
        return None
    await execute("UPDATE billing.gifts_queue SET applied_at = NOW() WHERE id = $1;", gift["id"])
    sid = await activate_subscription(contractor_id, gift["plan_code"], days=30, source="gift", status="trial")
    return sid
