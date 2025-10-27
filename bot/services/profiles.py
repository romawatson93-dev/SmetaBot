from typing import Optional
from bot.services.db import fetchrow, execute, q

# В новой схеме БД нет отдельной таблицы для профилей
# Будем хранить аватарки в Redis или в отдельной таблице
# Пока создадим простую реализацию с Redis

import redis
import json
import base64
import os

# Подключение к Redis
redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
redis_client = redis.from_url(redis_url, decode_responses=False)

async def upsert_avatar(contractor_id: int, data_bytes: bytes, name: str) -> None:
    """Сохраняет стандартную аватарку подрядчика."""
    # Кодируем данные в base64 для хранения в Redis
    avatar_b64 = base64.b64encode(data_bytes).decode('ascii')
    
    # Сохраняем в Redis с TTL 30 дней
    key = f"profile:avatar:{contractor_id}"
    data = {
        "std_avatar": avatar_b64,
        "std_avatar_name": name,
        "std_avatar_size": len(data_bytes)
    }
    
    redis_client.setex(key, 30 * 24 * 60 * 60, json.dumps(data))

async def get_avatar(contractor_id: int) -> Optional[dict]:
    """Получает стандартную аватарку подрядчика."""
    key = f"profile:avatar:{contractor_id}"
    data_json = redis_client.get(key)
    
    if not data_json:
        return None
    
    try:
        data = json.loads(data_json)
        # Декодируем base64 обратно в bytes
        if "std_avatar" in data:
            data["std_avatar"] = base64.b64decode(data["std_avatar"])
        return data
    except Exception:
        return None

async def delete_avatar(contractor_id: int) -> None:
    """Удаляет стандартную аватарку подрядчика."""
    key = f"profile:avatar:{contractor_id}"
    redis_client.delete(key)
