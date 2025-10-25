from __future__ import annotations

from typing import Any, Dict, Optional

from . import db


def _as_dict(row: Optional[Any]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


async def upsert_avatar(contractor_id: int, avatar_bytes: bytes, filename: str | None = None) -> Dict[str, Any]:
    row = await db.fetchrow(
        """
        INSERT INTO profiles (contractor_id, std_avatar, std_avatar_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (contractor_id)
        DO UPDATE SET
            std_avatar = EXCLUDED.std_avatar,
            std_avatar_name = COALESCE(EXCLUDED.std_avatar_name, profiles.std_avatar_name),
            updated_at = now()
        RETURNING contractor_id, std_avatar, std_avatar_name, updated_at
        """,
        contractor_id,
        avatar_bytes,
        filename,
    )
    if row is None:
        raise RuntimeError("Failed to store avatar")
    return dict(row)


async def get_avatar(contractor_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        """
        SELECT contractor_id, std_avatar, std_avatar_name, updated_at
        FROM profiles
        WHERE contractor_id = $1
        """,
        contractor_id,
    )
    return _as_dict(row)


async def update_avatar_name(contractor_id: int, filename: str | None) -> None:
    await db.execute(
        "UPDATE profiles SET std_avatar_name = $2, updated_at = now() WHERE contractor_id = $1",
        contractor_id,
        filename,
    )
