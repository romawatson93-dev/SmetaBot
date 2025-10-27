import asyncio
from typing import Dict, List, Optional, Tuple
from telethon import TelegramClient
from telethon.tl.types import PeerChannel
from telethon.errors import FloodWaitError
import logging

logger = logging.getLogger(__name__)

async def get_message_views(
    client: TelegramClient, 
    channel_id: int, 
    message_ids: List[int]
) -> Dict[int, int]:
    """
    Получает количество просмотров для сообщений в канале.
    
    Args:
        client: Telethon клиент
        channel_id: ID канала в Telegram
        message_ids: Список ID сообщений
        
    Returns:
        Dict[message_id, views_count]
    """
    views_data = {}
    
    try:
        # Получаем канал
        entity = await client.get_entity(PeerChannel(channel_id))
        
        # Получаем сообщения пакетами по 100 (лимит Telegram API)
        batch_size = 100
        for i in range(0, len(message_ids), batch_size):
            batch = message_ids[i:i + batch_size]
            
            try:
                # Получаем сообщения
                messages = await client.get_messages(entity, ids=batch)
                
                for msg in messages:
                    if msg and hasattr(msg, 'views'):
                        views_data[msg.id] = msg.views or 0
                    else:
                        views_data[msg.id] = 0
                        
            except FloodWaitError as e:
                logger.warning(f"FloodWait {e.seconds}s for channel {channel_id}, batch {i//batch_size + 1}")
                await asyncio.sleep(e.seconds)
                continue
            except Exception as e:
                logger.error(f"Error getting messages for channel {channel_id}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Error accessing channel {channel_id}: {e}")
        
    return views_data

async def get_channel_message_views(
    client: TelegramClient, 
    channel_id: int, 
    limit: int = 100
) -> Dict[int, int]:
    """
    Получает просмотры для последних сообщений в канале.
    
    Args:
        client: Telethon клиент
        channel_id: ID канала в Telegram
        limit: Максимальное количество сообщений
        
    Returns:
        Dict[message_id, views_count]
    """
    views_data = {}
    
    try:
        # Получаем канал
        entity = await client.get_entity(PeerChannel(channel_id))
        
        # Получаем последние сообщения
        messages = await client.get_messages(entity, limit=limit)
        
        for msg in messages:
            if msg and hasattr(msg, 'views'):
                views_data[msg.id] = msg.views or 0
                
    except Exception as e:
        logger.error(f"Error getting channel messages for {channel_id}: {e}")
        
    return views_data