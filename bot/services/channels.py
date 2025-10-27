from typing import Any, Dict, Optional
from bot.services.db import db, fetchrow, execute, fetch, fetchval, q

# core.channels: id, contractor_id, tg_chat_id UNIQUE, title, username, created_at
# core.publications: id, channel_id, message_id, file_name, file_type, views, posted_at, deleted
# core.invites: id, channel_id, token, expires_at, max_uses, used_count, editable, created_at
# core.clients: id, channel_id, invite_id, tg_user_id, username, full_name, joined_at, blocked

async def record_channel_file(
    channel_id: int,
    message_id: int,
    filename: str,
    file_type: Optional[str] = None,
    caption: Optional[str] = None,
    views: int = 0,
    posted_at: Optional[Any] = None,
    source_document_id: Optional[int] = None,
) -> int:
    """
    Записывает публикацию в core.publications.
    channel_id — это telegram chat_id (не БД id канала).
    """
    # Сначала находим БД ID канала по tg_chat_id
    channel_db = await fetchrow(
        "SELECT id FROM core.channels WHERE tg_chat_id = $1",
        channel_id
    )
    
    if not channel_db:
        raise ValueError(f"Канал с tg_chat_id={channel_id} не найден")
    
    channel_db_id = channel_db["id"]
    
    # Вставляем или обновляем публикацию
    print(f"DEBUG record_channel_file: channel_db_id={channel_db_id}, message_id={message_id}, filename={filename}, file_type={file_type}, views={views}")
    row = await fetchrow(
        """
        INSERT INTO core.publications (channel_id, message_id, file_name, file_type, views, posted_at)
        VALUES ($1, $2, $3, $4, $5, COALESCE($6, now()))
        ON CONFLICT (channel_id, message_id) DO UPDATE
            SET file_name = EXCLUDED.file_name, 
                file_type = COALESCE(EXCLUDED.file_type, core.publications.file_type),
                views = GREATEST(EXCLUDED.views, core.publications.views)
        RETURNING id;
        """,
        (channel_db_id, message_id, filename, file_type, views, posted_at)
    )
    
    return int(row["id"])

async def create_channel(contractor_id: int, tg_channel_id: int, title: str, username: Optional[str] = None) -> int:
    row = await fetchrow(
        f"""
        INSERT INTO core.channels (contractor_id, tg_chat_id, title, username)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (tg_chat_id) DO UPDATE
            SET title = EXCLUDED.title, username = EXCLUDED.username
        RETURNING id;
        """, contractor_id, tg_channel_id, title, username
    )
    return int(row["id"])

# TODO: Переписать под новую схему - таблица channel_members не существует
# async def upsert_member(tg_channel_id: int, user_id: int, role: str, full_name: Optional[str], username: Optional[str]):
#     await execute(
#         f"""
#         INSERT INTO {q("channel_members")} (channel_id, user_id, role, full_name, username)
#         VALUES (
#             (SELECT id FROM {q("channels")} WHERE tg_id = $1),
#             $2, $3, $4, $5
#         )
#         ON CONFLICT (channel_id, user_id) DO UPDATE
#             SET role = EXCLUDED.role, full_name = EXCLUDED.full_name, username = EXCLUDED.username;
#         """,
#         tg_channel_id, user_id, role, full_name, username
#     )

async def list_by_contractor(contractor_id: int) -> list[dict]:
    rows = await fetch("SELECT * FROM core.channels WHERE contractor_id = $1 ORDER BY created_at DESC;", contractor_id)
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

async def aggregate_contractor_stats(contractor_id: int) -> Dict[str, Any]:
    """
    Возвращает агрегаты для раздела «Мои каналы».
    Сначала читаем из analytics.profile_overview, при отсутствии — считаем по core.*
    """
    # Сначала получаем внутренний ID подрядчика из БД
    contractor_db_id = await fetchval(
        "SELECT id FROM core.contractors WHERE tg_user_id = $1",
        contractor_id
    )
    
    if not contractor_db_id:
        return {
            "channels_count": 0,
            "files_count": 0,
            "views_total": 0,
            "active_invites": 0,
            "clients_total": 0,
            "blocked_clients": 0,
        }
    
    # 1) пробуем из вьюхи (быстро)
    row = await db.fetchrow(
        "SELECT * FROM analytics.profile_overview WHERE contractor_id = $1",
        (contractor_db_id,),
    )
    if row:
        return {
            "channels_count":  row.get("channels_count", 0),
            "files_count":     row.get("files_count", 0),
            "views_total":     row.get("views_total", 0),
            "active_invites":  row.get("active_invites", 0),
            "clients_total":   row.get("clients_total", 0),
            "blocked_clients": row.get("blocked_clients", 0),
        }

    # 2) запасной путь — считаем напрямую по core.*
    channels_count = await db.fetchval(
        "SELECT COUNT(*) FROM core.channels WHERE contractor_id = $1", (contractor_db_id,)
    ) or 0

    files_count = await db.fetchval(
        """SELECT COUNT(*)
           FROM core.publications p
           JOIN core.channels ch ON ch.id = p.channel_id
          WHERE ch.contractor_id = $1""",
        (contractor_db_id,),
    ) or 0

    views_total = await db.fetchval(
        """SELECT COALESCE(SUM(p.views), 0)
           FROM core.publications p
           JOIN core.channels ch ON ch.id = p.channel_id
          WHERE ch.contractor_id = $1""",
        (contractor_db_id,),
    ) or 0

    active_invites = await db.fetchval(
        """SELECT COUNT(*) 
           FROM core.invites i
           JOIN core.channels ch ON ch.id = i.channel_id
          WHERE ch.contractor_id = $1 
            AND (i.expires_at IS NULL OR i.expires_at > now())
            AND (i.max_uses IS NULL OR i.used_count < i.max_uses)""",
        (contractor_db_id,),
    ) or 0

    clients_total = await db.fetchval(
        """SELECT COUNT(*) 
           FROM core.clients cl
           JOIN core.channels ch ON ch.id = cl.channel_id
          WHERE ch.contractor_id = $1""",
        (contractor_db_id,),
    ) or 0

    blocked_clients = await db.fetchval(
        """SELECT COUNT(*) 
           FROM core.clients cl
           JOIN core.channels ch ON ch.id = cl.channel_id
          WHERE ch.contractor_id = $1 AND cl.blocked = true""",
        (contractor_db_id,),
    ) or 0

    return {
        "channels_count":  channels_count,
        "files_count":     files_count,
        "views_total":     views_total,
        "active_invites":  active_invites,
        "clients_total":   clients_total,
        "blocked_clients": blocked_clients,
    }

async def list_channels(contractor_id: int, limit: int = 100, search: Optional[str] = None) -> list[dict]:
    """Возвращает список каналов подрядчика с поиском по названию."""
    # Сначала получаем внутренний ID подрядчика из БД
    contractor_db_id = await fetchval(
        "SELECT id FROM core.contractors WHERE tg_user_id = $1",
        contractor_id
    )
    
    if not contractor_db_id:
        return []
    
    if search:
        query = """
        SELECT id, contractor_id, tg_chat_id, title, username, created_at,
               id as project_id, id as channel_id
        FROM core.channels 
        WHERE contractor_id = $1 AND title ILIKE $2
        ORDER BY created_at DESC 
        LIMIT $3
        """
        rows = await fetch(query, contractor_db_id, f"%{search}%", limit)
    else:
        query = """
        SELECT id, contractor_id, tg_chat_id, title, username, created_at,
               id as project_id, id as channel_id
        FROM core.channels 
        WHERE contractor_id = $1
        ORDER BY created_at DESC 
        LIMIT $2
        """
        rows = await fetch(query, contractor_db_id, limit)
    
    return [dict(r) for r in rows]

async def get_channel_by_project(project_id: int) -> Optional[dict]:
    """Возвращает канал по project_id (в новой схеме project_id = channel_id)."""
    row = await fetchrow(
        "SELECT id, contractor_id, tg_chat_id, title, username, created_at, id as channel_id FROM core.channels WHERE id = $1",
        project_id
    )
    return dict(row) if row else None

async def get_channel_stats(channel_id: int) -> dict:
    """Возвращает статистику по каналу."""
    # Получаем основную информацию о канале
    channel = await fetchrow(
        "SELECT id, contractor_id, tg_chat_id, title, username FROM core.channels WHERE id = $1",
        channel_id
    )
    
    if not channel:
        return {}
    
    # Считаем файлы и просмотры
    files_stats = await fetchrow(
        """
        SELECT 
            COUNT(*) as files_count,
            COALESCE(SUM(views), 0) as views_total
        FROM core.publications 
        WHERE channel_id = $1 AND deleted = false
        """,
        channel_id
    )
    
    # Считаем клиентов
    clients_stats = await fetchrow(
        """
        SELECT 
            COUNT(*) as clients_total,
            COUNT(*) FILTER (WHERE blocked = true) as blocked_total
        FROM core.clients 
        WHERE channel_id = $1
        """,
        channel_id
    )
    
    # Считаем активные инвайты
    active_invites = await fetchval(
        """
        SELECT COUNT(*) 
        FROM core.invites 
        WHERE channel_id = $1 
          AND (expires_at IS NULL OR expires_at > now())
          AND (max_uses IS NULL OR used_count < max_uses)
        """,
        channel_id
    ) or 0
    
    return {
        "channel_id": channel_id,
        "project_id": channel_id,  # В новой схеме project_id = channel_id
        "title": channel["title"],
        "username": channel["username"],
        "files_count": files_stats["files_count"] if files_stats else 0,
        "views_total": files_stats["views_total"] if files_stats else 0,
        "clients_total": clients_stats["clients_total"] if clients_stats else 0,
        "blocked_clients": clients_stats["blocked_total"] if clients_stats else 0,
        "active_invites": active_invites,
    }

async def create_project_channel(
    contractor_id: int,
    title: str,
    channel_id: int,
    username: Optional[str] = None,
    channel_type: Optional[str] = None,
    avatar_file: Optional[str] = None,
) -> dict:
    """
    Создает запись о канале в БД с проверкой лимитов.
    В новой схеме project_id = channel_id (канал = проект).
    ВАЖНО: использует транзакцию для согласованности данных.
    """
    from bot.services.contractors import get_or_create_by_tg
    from bot.services.billing import billing
    from bot.services.db import transaction
    
    async with transaction() as conn:
        # Убеждаемся, что подрядчик существует
        contractor_db_id = await get_or_create_by_tg(contractor_id)
        
        # Проверяем лимиты подписки
        can_create, reason = await billing.can_create_channel(contractor_db_id)
        if not can_create:
            raise ValueError(f"Нельзя создать канал: {reason}")
        
        # Создаём запись в core.channels
        # Внутри транзакции используем прямое подключение
        row = await conn.fetchrow(
            """
            INSERT INTO core.channels (contractor_id, tg_chat_id, title, username)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tg_chat_id) DO UPDATE
                SET title = EXCLUDED.title, username = EXCLUDED.username
            RETURNING id;
            """,
            contractor_db_id, channel_id, title, username
        )
        channel_db_id = int(row["id"])
        
        # Инкрементируем счётчик каналов
        await conn.execute(
            """
            INSERT INTO billing.usage_counters (contractor_id, channels_created_total, last_channel_created_at)
            VALUES ($1, 1, now())
            ON CONFLICT (contractor_id) DO UPDATE
            SET channels_created_total = usage_counters.channels_created_total + 1,
                last_channel_created_at = now()
            """,
            contractor_db_id,
        )
    
    # Возвращаем данные в формате, ожидаемом старым кодом
    return {
        "project": {
            "id": channel_db_id,
            "contractor_id": contractor_db_id,
            "title": title,
            "channel_id": channel_id,
            "username": username,
            "channel_type": channel_type,
            "avatar_file": avatar_file,
        },
        "channel": {
            "id": channel_db_id,
            "contractor_id": contractor_db_id,
            "tg_chat_id": channel_id,
            "title": title,
            "username": username,
        }
    }

async def count_channels(contractor_id: int) -> int:
    """Возвращает количество каналов подрядчика по Telegram ID."""
    # Сначала получаем внутренний ID подрядчика из БД
    contractor_db_id = await fetchval(
        "SELECT id FROM core.contractors WHERE tg_user_id = $1",
        contractor_id
    )
    
    if not contractor_db_id:
        return 0
    
    count = await fetchval(
        "SELECT COUNT(*) FROM core.channels WHERE contractor_id = $1",
        contractor_db_id
    )
    return count or 0


async def get_channel_by_tg_chat_id(tg_chat_id: int) -> Optional[dict]:
    """Возвращает канал по Telegram chat_id."""
    row = await fetchrow(
        "SELECT id, contractor_id, tg_chat_id, title, username, created_at FROM core.channels WHERE tg_chat_id = $1",
        tg_chat_id
    )
    return dict(row) if row else None


async def get_channel_clients(channel_db_id: int) -> list[dict]:
    """Возвращает список клиентов канала."""
    rows = await fetch(
        """
        SELECT tg_user_id, username, full_name, joined_at, blocked
        FROM core.clients
        WHERE channel_id = $1
        ORDER BY joined_at DESC
        """,
        channel_db_id
    )
    return [dict(r) for r in rows]


async def get_channel_publications(channel_db_id: int, limit: int = 50) -> list[dict]:
    """Возвращает список публикаций канала с просмотрами."""
    rows = await fetch(
        """
        SELECT id, file_name, file_type, views, posted_at
        FROM core.publications
        WHERE channel_id = $1 AND deleted = false
        ORDER BY posted_at DESC
        LIMIT $2
        """,
        channel_db_id, limit
    )
    return [dict(r) for r in rows]


async def sync_channels_from_telegram(contractor_id: int, bot, known_channel_ids: Optional[list] = None) -> dict:
    """
    Синхронизирует каналы из Telegram для подрядчика.
    Проверяет список известных каналов и добавляет те, где бот является администратором.
    
    Args:
        contractor_id: ID подрядчика в Telegram
        bot: объект бота
        known_channel_ids: список ID каналов для проверки (опционально)
    
    Returns:
        dict: {found, added, channels, errors}
    """
    # Получаем внутренний ID подрядчика
    contractor_db_id = await fetchval(
        "SELECT id FROM core.contractors WHERE tg_user_id = $1",
        contractor_id
    )
    
    if not contractor_db_id:
        raise ValueError("Подрядчик не найден в БД")
    
    # Получаем ID бота
    bot_info = await bot.get_me()
    bot_id = bot_info.id
    
    synced_channels = []
    added_count = 0
    errors = []
    
    # Если не передан список каналов, получаем все каналы подрядчика из БД
    if not known_channel_ids:
        # Получаем все каналы подрядчика
        rows = await fetch(
            "SELECT tg_chat_id FROM core.channels WHERE contractor_id = $1",
            contractor_db_id
        )
        known_channel_ids = [int(row["tg_chat_id"]) for row in rows]
    
    # Проверяем каждый канал
    for channel_id in known_channel_ids:
        try:
            # Получаем информацию о канале
            chat = await bot.get_chat(channel_id)
            
            # Проверяем, является ли бот администратором
            admins = await bot.get_chat_administrators(chat.id)
            is_bot_admin = any(admin.user.id == bot_id for admin in admins)
            
            if not is_bot_admin:
                continue
            
            # Проверяем, есть ли канал уже в БД
            existing = await fetchrow(
                "SELECT id, contractor_id FROM core.channels WHERE tg_chat_id = $1",
                chat.id
            )
            
            if existing:
                # Если канал уже принадлежит этому подрядчику, пропускаем
                if existing["contractor_id"] == contractor_db_id:
                    continue
                # Иначе обновляем владельца
                await execute(
                    "UPDATE core.channels SET contractor_id = $1 WHERE tg_chat_id = $2",
                    contractor_db_id, chat.id
                )
                added_count += 1
                synced_channels.append({
                    "id": chat.id,
                    "title": chat.title or f"Канал {chat.id}",
                    "username": chat.username
                })
            else:
                # Добавляем новый канал в БД
                await create_channel(
                    contractor_db_id,
                    chat.id,
                    chat.title or f"Канал {chat.id}",
                    chat.username
                )
                
                added_count += 1
                synced_channels.append({
                    "id": chat.id,
                    "title": chat.title or f"Канал {chat.id}",
                    "username": chat.username
                })
            
        except Exception as e:
            # Ошибка при проверке/добавлении канала
            errors.append(f"Channel {channel_id}: {str(e)}")
            continue
    
    return {
        "found": len(synced_channels),
        "added": added_count,
        "channels": synced_channels,
        "errors": errors
    }