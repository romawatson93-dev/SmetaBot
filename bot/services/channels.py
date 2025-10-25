from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import db


def _as_dict(row: Optional[Any]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


async def create_project_channel(
    *,
    contractor_id: int,
    title: str,
    channel_id: int,
    username: str | None = None,
    channel_type: str | None = None,
    avatar_file: str | None = None,
) -> Dict[str, Dict[str, Any]]:
    async with db.transaction() as conn:
        project_row = await conn.fetchrow(
            """
            INSERT INTO projects (contractor_id, title, status)
            VALUES ($1, $2, 'active')
            ON CONFLICT (contractor_id, title)
            DO UPDATE SET title = EXCLUDED.title
            RETURNING id, contractor_id, title, status, created_at
            """,
            contractor_id,
            title,
        )
        if project_row is None:
            raise RuntimeError("Failed to upsert project while creating channel")

        channel_row = await conn.fetchrow(
            """
            INSERT INTO channels (
                project_id,
                contractor_id,
                channel_id,
                title,
                username,
                type,
                avatar_file
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (channel_id)
            DO UPDATE SET
                project_id = EXCLUDED.project_id,
                contractor_id = EXCLUDED.contractor_id,
                title = EXCLUDED.title,
                username = EXCLUDED.username,
                type = EXCLUDED.type,
                avatar_file = COALESCE(EXCLUDED.avatar_file, channels.avatar_file)
            RETURNING id, project_id, contractor_id, channel_id, title, username, type, avatar_file, created_at
            """,
            project_row["id"],
            contractor_id,
            channel_id,
            title,
            username,
            channel_type,
            avatar_file,
        )
        if channel_row is None:
            raise RuntimeError("Failed to upsert channel record")

    return {"project": dict(project_row), "channel": dict(channel_row)}


async def update_channel_first_message(channel_id: int, timestamp: datetime) -> None:
    await db.execute(
        "UPDATE channels SET first_message_at = $2 WHERE channel_id = $1",
        channel_id,
        timestamp,
    )


async def get_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        """
        SELECT
            c.id,
            c.project_id,
            c.contractor_id,
            c.channel_id,
            c.title,
            c.username,
            c.type,
            c.created_at,
            c.first_message_at,
            c.avatar_file,
            p.title AS project_title,
            p.status AS project_status
        FROM channels c
        JOIN projects p ON p.id = c.project_id
        WHERE c.channel_id = $1
        """,
        channel_id,
    )
    return _as_dict(row)


async def get_channel_by_project(project_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        """
        SELECT
            c.id,
            c.project_id,
            c.contractor_id,
            c.channel_id,
            c.title,
            c.username,
            c.type,
            c.created_at,
            c.first_message_at,
            c.avatar_file
        FROM channels c
        WHERE c.project_id = $1
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
        """,
        project_id,
    )
    return _as_dict(row)


async def get_latest_channel(contractor_id: int) -> Optional[Dict[str, Any]]:
    row = await db.fetchrow(
        """
        SELECT
            c.channel_id,
            c.project_id,
            c.title,
            c.username,
            c.type,
            c.created_at
        FROM channels c
        WHERE c.contractor_id = $1
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
        """,
        contractor_id,
    )
    return _as_dict(row)


async def list_channels(
    contractor_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> List[Dict[str, Any]]:
    search_term = f"%{search.lower()}%" if search else None
    rows = await db.fetch(
        """
        SELECT
            c.channel_id,
            c.project_id,
            c.title,
            c.username,
            c.type,
            c.created_at,
            p.title AS project_title
        FROM channels c
        JOIN projects p ON p.id = c.project_id
        WHERE c.contractor_id = $1
          AND (
            $2::text IS NULL
            OR LOWER(c.title) LIKE $2
            OR LOWER(p.title) LIKE $2
          )
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT $3 OFFSET $4
        """,
        contractor_id,
        search_term,
        limit,
        offset,
    )
    return [dict(r) for r in rows]


async def count_channels(contractor_id: int) -> int:
    total = await db.fetchval(
        "SELECT COUNT(*) FROM channels WHERE contractor_id = $1",
        contractor_id,
    )
    return int(total or 0)


async def upsert_member(
    channel_id: int,
    *,
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
    role: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO channel_members (channel_id, user_id, username, full_name, role)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (channel_id, user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            role = EXCLUDED.role,
            collected_at = now()
        """,
        channel_id,
        user_id,
        username,
        full_name,
        role,
    )


async def bulk_upsert_members(
    channel_id: int,
    members: Iterable[Tuple[int, Optional[str], Optional[str], Optional[str]]],
) -> None:
    params = [
        (channel_id, user_id, username, full_name, role)
        for user_id, username, full_name, role in members
    ]
    if not params:
        return
    await db.executemany(
        """
        INSERT INTO channel_members (channel_id, user_id, username, full_name, role)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (channel_id, user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            role = EXCLUDED.role,
            collected_at = now()
        """,
        params,
    )


async def record_channel_file(
    channel_id: int,
    *,
    message_id: int,
    filename: str | None = None,
    file_type: str | None = None,
    caption: str | None = None,
    views: int = 0,
    posted_at: datetime | None = None,
    source_document_id: int | None = None,
) -> Dict[str, Any]:
    row = await db.fetchrow(
        """
        INSERT INTO channel_files (
            channel_id,
            message_id,
            filename,
            file_type,
            caption,
            views,
            posted_at,
            source_document_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (channel_id, message_id)
        DO UPDATE SET
            filename = COALESCE(EXCLUDED.filename, channel_files.filename),
            file_type = COALESCE(EXCLUDED.file_type, channel_files.file_type),
            caption = EXCLUDED.caption,
            views = EXCLUDED.views,
            posted_at = COALESCE(EXCLUDED.posted_at, channel_files.posted_at),
            source_document_id = COALESCE(EXCLUDED.source_document_id, channel_files.source_document_id)
        RETURNING id, channel_id, message_id, filename, file_type, caption, views, posted_at, source_document_id
        """,
        channel_id,
        message_id,
        filename,
        file_type,
        caption,
        views,
        posted_at,
        source_document_id,
    )
    if row is None:
        raise RuntimeError("Failed to record channel file")
    return dict(row)


async def update_channel_file_views(channel_id: int, message_id: int, views: int) -> None:
    await db.execute(
        """
        UPDATE channel_files
        SET views = $3
        WHERE channel_id = $1 AND message_id = $2
        """,
        channel_id,
        message_id,
        views,
    )


async def add_file_views_datapoint(channel_file_id: int, views: int, collected_at: datetime | None = None) -> None:
    await db.execute(
        """
        INSERT INTO channel_file_views (channel_file_id, views, collected_at)
        VALUES ($1, $2, COALESCE($3, now()))
        """,
        channel_file_id,
        views,
        collected_at,
    )


async def create_snapshot(
    channel_id: int,
    *,
    snapshot_date: datetime,
    files_count: int,
    views_total: int,
    members_total: int | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO channel_snapshots (channel_id, snapshot_date, files_count, views_total, members_total)
        VALUES ($1, $2::date, $3, $4, $5)
        ON CONFLICT (channel_id, snapshot_date)
        DO UPDATE SET
            files_count = EXCLUDED.files_count,
            views_total = EXCLUDED.views_total,
            members_total = EXCLUDED.members_total,
            created_at = now()
        """,
        channel_id,
        snapshot_date,
        files_count,
        views_total,
        members_total,
    )


async def get_channel_stats(channel_id: int) -> Dict[str, Any]:
    channel = await get_channel(channel_id)
    if channel is None:
        raise LookupError(f"Channel {channel_id} not found")

    counts = await db.fetchrow(
        """
        SELECT
            COUNT(*) AS files_count,
            COALESCE(SUM(views), 0) AS views_total,
            MAX(posted_at) AS last_posted_at
        FROM channel_files
        WHERE channel_id = $1
        """,
        channel_id,
    ) or {"files_count": 0, "views_total": 0, "last_posted_at": None}

    members_total = await db.fetchval(
        "SELECT COUNT(*) FROM channel_members WHERE channel_id = $1",
        channel_id,
    )

    channel["files_count"] = int(counts["files_count"] or 0)
    channel["views_total"] = int(counts["views_total"] or 0)
    channel["last_posted_at"] = counts.get("last_posted_at")
    channel["members_total"] = int(members_total or 0)
    return channel


async def get_recent_channels_with_stats(contractor_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    channels = await list_channels(contractor_id, limit=limit)
    result: List[Dict[str, Any]] = []
    for item in channels:
        stats = await db.fetchrow(
            """
            SELECT
                COUNT(*) AS files_count,
                COALESCE(SUM(views), 0) AS views_total
            FROM channel_files
            WHERE channel_id = $1
            """,
            item["channel_id"],
        ) or {"files_count": 0, "views_total": 0}
        result.append(
            {
                **item,
                "files_count": int(stats["files_count"] or 0),
                "views_total": int(stats["views_total"] or 0),
            }
        )
    return result


async def aggregate_contractor_stats(contractor_id: int) -> Dict[str, int]:
    row = await db.fetchrow(
        """
        SELECT
            COUNT(DISTINCT c.channel_id) AS total_channels,
            COUNT(cf.id) AS total_files,
            COALESCE(SUM(cf.views), 0) AS total_views
        FROM channels c
        LEFT JOIN channel_files cf ON cf.channel_id = c.channel_id
        WHERE c.contractor_id = $1
        """,
        contractor_id,
    ) or {"total_channels": 0, "total_files": 0, "total_views": 0}
    return {
        "total_channels": int(row["total_channels"] or 0),
        "total_files": int(row["total_files"] or 0),
        "total_views": int(row["total_views"] or 0),
    }
