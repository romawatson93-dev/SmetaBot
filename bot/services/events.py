# bot/services/events.py
from typing import Optional, Any
from bot.services.db import db

# analytics.events: id, channel_id, client_id, event_type, details (JSONB), created_at

async def log_event(
    event_type: str,
    channel_id: Optional[int] = None,
    client_id: Optional[int] = None,
    details: Optional[dict] = None,
) -> int:
    """
    Записывает событие в analytics.events.
    Типы: 'client_join', 'client_leave', 'invite_used', 'file_posted', 'file_deleted', 'sync_run'
    """
    row = await db.fetchrow(
        """
        INSERT INTO analytics.events (event_type, channel_id, client_id, details)
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id;
        """,
        (event_type, channel_id, client_id, details),
    )
    return int(row["id"]) if row else 0

async def log_client_join(channel_id: int, client_id: int, invite_id: Optional[int] = None):
    """Клиент присоединился к каналу."""
    await log_event(
        event_type="client_join",
        channel_id=channel_id,
        client_id=client_id,
        details={"invite_id": invite_id} if invite_id else None,
    )

async def log_invite_used(channel_id: int, invite_id: int):
    """Инвайт использован."""
    await log_event(
        event_type="invite_used",
        channel_id=channel_id,
        details={"invite_id": invite_id},
    )

async def log_file_posted(channel_id: int, message_id: int, file_name: str, file_type: str):
    """Файл опубликован в канале."""
    await log_event(
        event_type="file_posted",
        channel_id=channel_id,
        details={"message_id": message_id, "file_name": file_name, "file_type": file_type},
    )

async def log_file_deleted(channel_id: int, publication_id: int):
    """Файл удалён из канала."""
    await log_event(
        event_type="file_deleted",
        channel_id=channel_id,
        details={"publication_id": publication_id},
    )

async def log_sync_run(channel_id: int, stats: dict):
    """Запущена синхронизация канала."""
    await log_event(
        event_type="sync_run",
        channel_id=channel_id,
        details=stats,
    )
