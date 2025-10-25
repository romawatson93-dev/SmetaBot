from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db


def _as_dict(row: Optional[Any]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


async def upsert_project(
    contractor_id: int,
    title: str,
    *,
    status: str = "active",
) -> Dict[str, Any]:
    row = await db.fetchrow(
        """
        INSERT INTO projects (contractor_id, title, status)
        VALUES ($1, $2, $3)
        ON CONFLICT (contractor_id, title)
        DO UPDATE SET
            title = EXCLUDED.title,
            status = EXCLUDED.status
        RETURNING id, contractor_id, title, status, created_at
        """,
        contractor_id,
        title,
        status,
    )
    if row is None:
        raise RuntimeError("Failed to upsert project record")
    return dict(row)


async def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        "SELECT id, contractor_id, title, status, created_at FROM projects WHERE id = $1",
        project_id,
    )
    return _as_dict(row)


async def get_project_by_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        """
        SELECT p.id, p.contractor_id, p.title, p.status, p.created_at
        FROM channels c
        JOIN projects p ON p.id = c.project_id
        WHERE c.channel_id = $1
        """,
        channel_id,
    )
    return _as_dict(row)


async def list_projects(contractor_id: int, *, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    rows = await db.fetch(
        """
        SELECT id, contractor_id, title, status, created_at
        FROM projects
        WHERE contractor_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT $2 OFFSET $3
        """,
        contractor_id,
        limit,
        offset,
    )
    return [dict(r) for r in rows]


async def count_projects(contractor_id: int) -> int:
    total = await db.fetchval(
        "SELECT COUNT(*) FROM projects WHERE contractor_id = $1",
        contractor_id,
    )
    return int(total or 0)


async def create_invite(project_id: int, invite_link: str, *, allowed: int = 1) -> Dict[str, Any]:
    row = await db.fetchrow(
        """
        INSERT INTO project_invites (project_id, invite_link, allowed)
        VALUES ($1, $2, $3)
        RETURNING id, project_id, invite_link, allowed, approved_count, created_at
        """,
        project_id,
        invite_link,
        allowed,
    )
    if row is None:
        raise RuntimeError("Failed to create invite")
    return dict(row)


async def get_latest_invite(project_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        """
        SELECT id, project_id, invite_link, allowed, approved_count, created_at
        FROM project_invites
        WHERE project_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        project_id,
    )
    return _as_dict(row)


async def increment_invite_approved(invite_id: int) -> None:
    await db.execute(
        "UPDATE project_invites SET approved_count = approved_count + 1 WHERE id = $1",
        invite_id,
    )
