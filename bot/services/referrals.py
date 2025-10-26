from typing import Optional
from .db import fetchrow, fetch, execute

# referrals.referrals: id, referrer_id, referred_contractor_id, created_at
# referrals.referral_links: id, referrer_id, client_id, created_at
# referrals.referral_progress (VIEW): referral_id, referrer_id, referred_contractor_id, channels_created, qualified

async def register_referral(referrer_id: int, referred_contractor_id: int) -> int:
    row = await fetchrow(
        """
        INSERT INTO referrals.referrals (referrer_id, referred_contractor_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        RETURNING id;
        """, referrer_id, referred_contractor_id
    )
    return int(row["id"]) if row else 0

async def create_referral_link_click(referrer_id: int, client_id: int) -> int:
    row = await fetchrow(
        "INSERT INTO referrals.referral_links (referrer_id, client_id) VALUES ($1, $2) RETURNING id;",
        referrer_id, client_id
    )
    return int(row["id"])

async def get_progress_for_referrer(referrer_id: int) -> list[dict]:
    rows = await fetch(
        """
        SELECT *
        FROM referrals.referral_progress
        WHERE referrer_id = $1
        ORDER BY referral_id DESC;
        """, referrer_id
    )
    return [dict(r) for r in rows]
