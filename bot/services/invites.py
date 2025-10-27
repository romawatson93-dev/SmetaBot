from datetime import datetime
from typing import Optional
from .db import fetchrow, fetch, execute, q

# core.invites: id, channel_id, token, expires_at, max_uses, used_count, editable, created_at

async def create_invite(channel_id: int, token: str, max_uses: int = 1, expires_at: Optional[datetime] = None) -> int:
    """Создаёт новый инвайт. По умолчанию max_uses=1 (одноразовый)."""
    row = await fetchrow(
        f"""
        INSERT INTO {q("invites")} (channel_id, token, max_uses, expires_at)
        VALUES ($1, $2, $3, $4)
        RETURNING id;
        """, channel_id, token, max_uses, expires_at
    )
    return int(row["id"])

async def list_active(channel_id: int) -> list[dict]:
    """
    Возвращает активные инвайты канала.
    Активен = не исчерпал лимит И не истёк срок действия.
    """
    rows = await fetch(
        f"""
        SELECT * FROM {q('invites')}
        WHERE channel_id = $1
          AND (used_count < max_uses OR max_uses IS NULL)
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY created_at DESC;
        """, channel_id
    )
    return [dict(r) for r in rows]

async def list_all(channel_id: int) -> list[dict]:
    """Возвращает все инвайты канала (включая использованные/истёкшие)."""
    rows = await fetch(
        f"SELECT * FROM {q('invites')} WHERE channel_id = $1 ORDER BY created_at DESC;",
        channel_id
    )
    return [dict(r) for r in rows]

async def increment_used(invite_id: int):
    """Увеличивает счётчик использования инвайта."""
    await execute(f"UPDATE {q('invites')} SET used_count = used_count + 1 WHERE id = $1;", invite_id)

async def mark_used(invite_id: int):
    """Алиас для backward compatibility."""
    await increment_used(invite_id)

async def is_usable(invite_id: int) -> bool:
    """Проверяет, можно ли ещё использовать инвайт."""
    row = await fetchrow(
        f"""
        SELECT (used_count < max_uses OR max_uses IS NULL)
           AND (expires_at IS NULL OR expires_at > now()) AS usable
        FROM {q('invites')}
        WHERE id = $1;
        """, invite_id
    )
    return bool(row["usable"]) if row else False

async def get_by_token(token: str) -> Optional[dict]:
    """Находит инвайт по токену."""
    row = await fetchrow(f"SELECT * FROM {q('invites')} WHERE token = $1;", token)
    return dict(row) if row else None

async def disable(invite_id: int):
    """
    ОТКЛЮЧАЕТ инвайт путём установки used_count = max_uses.
    ВАЖНО: в новой схеме нет поля 'active', используем эту логику.
    """
    await execute(
        f"""
        UPDATE {q('invites')}
        SET used_count = GREATEST(max_uses, COALESCE(used_count, 0))
        WHERE id = $1;
        """, invite_id
    )
