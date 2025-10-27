from celery import shared_task
from datetime import datetime, timedelta
from bot.services import db as db_service

@shared_task
def update_views_daily() -> dict:
    """Агрегирует просмотры по публикациям за текущий день."""
    try:
        # Получаем все публикации с просмотрами > 0
        rows = db_service.fetch(
            """
            SELECT id, views, posted_at 
            FROM core.publications 
            WHERE views > 0 AND deleted = false
            ORDER BY id
            """
        )
        
        today = datetime.now().date()
        inserted = 0
        
        for row in rows:
            pub_id = row["id"]
            views = row["views"]
            
            # Вставляем или обновляем запись за сегодня
            db_service.execute(
                """
                INSERT INTO analytics.views_daily (publication_id, collected_at, views)
                VALUES ($1, $2, $3)
                ON CONFLICT (publication_id, collected_at) DO UPDATE
                    SET views = EXCLUDED.views
                """,
                pub_id, today, views
            )
            inserted += 1
        
        return {"status": "ok", "rows_processed": len(rows), "rows_inserted": inserted}
    except Exception as exc:
        print(f"Error in update_views_daily: {exc}")
        return {"status": "error", "error": str(exc)}

@shared_task
def update_channel_stats() -> dict:
    """Обновляет агрегированную статистику по каналам."""
    try:
        # Получаем все каналы
        channels = db_service.fetch(
            "SELECT id FROM core.channels ORDER BY id"
        )
        
        updated = 0
        
        for ch_row in channels:
            channel_id = ch_row["id"]
            
            # Считаем файлы и просмотры
            files_row = db_service.fetchrow(
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
            clients_row = db_service.fetchrow(
                """
                SELECT 
                    COUNT(*) as clients_total,
                    COUNT(*) FILTER (WHERE blocked = true) as blocked_total
                FROM core.clients 
                WHERE channel_id = $1
                """,
                channel_id
            )
            
            # Вставляем или обновляем статистику
            db_service.execute(
                """
                INSERT INTO analytics.channel_stats 
                    (channel_id, files_count, views_total, clients_total, blocked_total, last_updated)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (channel_id) DO UPDATE
                    SET files_count = EXCLUDED.files_count,
                        views_total = EXCLUDED.views_total,
                        clients_total = EXCLUDED.clients_total,
                        blocked_total = EXCLUDED.blocked_total,
                        last_updated = EXCLUDED.last_updated
                """,
                channel_id,
                files_row["files_count"] if files_row else 0,
                files_row["views_total"] if files_row else 0,
                clients_row["clients_total"] if clients_row else 0,
                clients_row["blocked_total"] if clients_row else 0,
            )
            updated += 1
        
        return {"status": "ok", "channels_updated": updated}
    except Exception as exc:
        print(f"Error in update_channel_stats: {exc}")
        return {"status": "error", "error": str(exc)}

@shared_task
def apply_queued_gifts() -> dict:
    """Обрабатывает очередь подарков (gifts_queue)."""
    try:
        # Получаем необработанные подарки
        gifts = db_service.fetch(
            """
            SELECT id, contractor_id, plan_id, days, reason
            FROM billing.gifts_queue
            WHERE applied_at IS NULL
            ORDER BY queued_at ASC
            """
        )
        
        applied = 0
        
        for gift in gifts:
            contractor_id = gift["contractor_id"]
            plan_id = gift["plan_id"]
            days = gift["days"]
            reason = gift["reason"]
            
            # Проверяем, есть ли активная PRO/BUSINESS подписка
            active_sub = db_service.fetchrow(
                """
                SELECT s.id, s.status, p.code
                FROM billing.subscriptions s
                JOIN billing.plans p ON p.id = s.plan_id
                WHERE s.contractor_id = $1 
                  AND p.code IN ('PRO', 'BUSINESS')
                  AND s.status IN ('active', 'trial')
                """,
                contractor_id
            )
            
            if active_sub:
                # Есть активная подписка - пропускаем
                continue
            
            # Применяем подарок
            now = datetime.now()
            expires_at = now + timedelta(days=days)
            
            # Создаём или обновляем подписку
            sub_id = db_service.fetchval(
                """
                INSERT INTO billing.subscriptions 
                    (contractor_id, plan_id, status, starts_at, expires_at, source)
                VALUES ($1, $2, 'active', $3, $4, $5)
                ON CONFLICT (contractor_id) DO UPDATE
                    SET plan_id = EXCLUDED.plan_id,
                        status = 'active',
                        starts_at = EXCLUDED.starts_at,
                        expires_at = EXCLUDED.expires_at,
                        source = EXCLUDED.source
                RETURNING id
                """,
                contractor_id, plan_id, now, expires_at, reason
            )
            
            # Записываем в историю
            db_service.execute(
                """
                INSERT INTO billing.subscription_history
                    (contractor_id, plan_id, status, starts_at, expires_at, source)
                VALUES ($1, $2, 'active', $3, $4, $5)
                """,
                contractor_id, plan_id, now, expires_at, reason
            )
            
            # Помечаем подарок как применённый
            db_service.execute(
                """
                UPDATE billing.gifts_queue
                SET applied_at = now()
                WHERE id = $1
                """,
                gift["id"]
            )
            
            applied += 1
        
        return {
            "status": "ok", 
            "gifts_processed": len(gifts),
            "gifts_applied": applied
        }
    except Exception as exc:
        print(f"Error in apply_queued_gifts: {exc}")
        return {"status": "error", "error": str(exc)}

@shared_task
def refresh_views_periodic() -> dict:
    """Периодически обновляет просмотры для всех активных каналов."""
    try:
        # Получаем все каналы с публикациями
        channels = db_service.fetch(
            """
            SELECT DISTINCT c.id, c.tg_chat_id, c.contractor_id
            FROM core.channels c
            JOIN core.publications p ON p.channel_id = c.id
            WHERE p.deleted = false
            ORDER BY c.id
            """
        )
        
        updated_channels = 0
        total_updated_messages = 0
        errors = []
        
        for channel in channels:
            try:
                result = refresh_views_for_room(channel["id"])
                if result["status"] == "ok":
                    updated_channels += 1
                    total_updated_messages += result.get("updated", 0)
                else:
                    errors.append(f"Channel {channel['id']}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                errors.append(f"Channel {channel['id']}: {str(e)}")
        
        return {
            "status": "ok",
            "channels_processed": len(channels),
            "channels_updated": updated_channels,
            "messages_updated": total_updated_messages,
            "errors": errors
        }
        
    except Exception as exc:
        print(f"Error in refresh_views_periodic: {exc}")
        return {"status": "error", "error": str(exc)}


@shared_task
def refresh_views_for_room(room_id: int) -> dict:
    """Обновляет просмотры для канала через userbot API."""
    import requests
    import os
    
    userbot_url = os.getenv("USERBOT_URL", "http://userbot:8000")
    
    try:
        # Получаем информацию о канале
        channel_info = db_service.fetchrow(
            "SELECT tg_chat_id, contractor_id FROM core.channels WHERE id = $1",
            room_id
        )
        
        if not channel_info:
            return {"room_id": room_id, "status": "error", "error": "Channel not found"}
        
        tg_chat_id = channel_info["tg_chat_id"]
        contractor_id = channel_info["contractor_id"]
        
        # Получаем список сообщений канала
        publications = db_service.fetch(
            """
            SELECT message_id FROM core.publications 
            WHERE channel_id = $1 AND deleted = false
            ORDER BY posted_at DESC
            LIMIT 100
            """,
            room_id
        )
        
        if not publications:
            return {"room_id": room_id, "status": "ok", "updated": 0}
        
        message_ids = [pub["message_id"] for pub in publications]
        
        # Вызываем userbot API
        response = requests.post(
            f"{userbot_url}/rooms/get_views",
            json={
                "contractor_id": str(contractor_id),
                "channel_id": tg_chat_id,
                "message_ids": message_ids
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return {
                "room_id": room_id, 
                "status": "error", 
                "error": f"Userbot API error: {response.status_code}"
            }
        
        data = response.json()
        if not data.get("ok"):
            return {
                "room_id": room_id, 
                "status": "error", 
                "error": data.get("error", "Unknown error")
            }
        
        views_data = data.get("views", {})
        updated_count = 0
        
        # Обновляем просмотры в БД
        for message_id, views in views_data.items():
            db_service.execute(
                """
                UPDATE core.publications 
                SET views = $3 
                WHERE channel_id = $1 AND message_id = $2
                """,
                room_id, message_id, views
            )
            updated_count += 1
        
        return {
            "room_id": room_id, 
            "status": "ok", 
            "updated": updated_count,
            "total_messages": len(message_ids)
        }
        
    except Exception as exc:
        print(f"Error in refresh_views_for_room: {exc}")
        return {"room_id": room_id, "status": "error", "error": str(exc)}
