import os
import uuid
from typing import Iterable, Optional

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SOURCE_BLOB_TTL = int(os.getenv("SOURCE_BLOB_TTL", "3600"))
FULLRES_BLOB_PREFIX = os.getenv("FULLRES_BLOB_PREFIX", "renderpng")
FULLRES_BLOB_TTL = int(os.getenv("FULLRES_BLOB_TTL", str(SOURCE_BLOB_TTL)))

_redis_client: Optional[Redis] = None


def _get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(REDIS_URL)
    return _redis_client


def _resolve_ttl(prefix: str, ttl: Optional[int]) -> int:
    if ttl is not None:
        return ttl
    if prefix == FULLRES_BLOB_PREFIX:
        return FULLRES_BLOB_TTL
    return SOURCE_BLOB_TTL


async def store_blob(prefix: str, payload: bytes, *, ttl: Optional[int] = None) -> str:
    """Persist binary payload in Redis under `<prefix>:<uuid>` key."""
    key = f"{prefix}:{uuid.uuid4().hex}"
    client = _get_redis()
    await client.set(key, payload, ex=_resolve_ttl(prefix, ttl))
    return key


async def load_blob(key: str, *, delete: bool = False) -> bytes:
    """Load a payload from Redis. Deletes it when requested."""
    client = _get_redis()
    if delete:
        value = await client.getdel(key)
    else:
        value = await client.get(key)
    if value is None:
        raise RuntimeError(f"������ ��ꥪ� �� ����� {key} �� ������.")
    return value


async def delete_blob(key: Optional[str]) -> None:
    """Remove a payload from Redis."""
    if not key:
        return
    client = _get_redis()
    await client.delete(key)


async def delete_many(keys: Iterable[Optional[str]]) -> None:
    """Remove several payloads at once."""
    filtered = [key for key in keys if key]
    if not filtered:
        return
    client = _get_redis()
    await client.delete(*filtered)


__all__ = [
    "store_blob",
    "load_blob",
    "delete_blob",
    "delete_many",
    "SOURCE_BLOB_TTL",
    "FULLRES_BLOB_TTL",
    "FULLRES_BLOB_PREFIX",
]
