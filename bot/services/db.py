import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Iterable, Sequence

import asyncpg

# --- Константы и алиасы схем ---
SCHEMAS_DEFAULT = ("core", "billing", "analytics", "referrals", "admin", "public")
SCHEMAS = {
    "core": "core",
    "billing": "billing",
    "analytics": "analytics",
    "referrals": "referrals",
    "admin": "admin",
    "public": "public",
}

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


def _normalize_dsn(url: str) -> str:
    """Нормализуем SQLAlchemy-стиль в обычный DSN для asyncpg."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url.split("://", 1)[1]
    if url.startswith("postgres+asyncpg://"):
        return "postgresql://" + url.split("://", 1)[1]
    return url


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return _normalize_dsn(url)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Выставляем search_path и полезные session-параметры для каждого соединения."""
    # Временная зона — по желанию можно читать из ENV
    tz = os.getenv("PG_TIMEZONE", "UTC")
    # Список схем для search_path (можно переопределить через ENV)
    schemas_env = os.getenv("PG_SEARCH_PATH")
    if schemas_env:
        schemas = [s.strip() for s in schemas_env.split(",") if s.strip()]
    else:
        schemas = list(SCHEMAS_DEFAULT)

    sp = ", ".join(f'"{s}"' for s in schemas)
    await conn.execute(f"SET TIME ZONE '{tz}';")
    await conn.execute(f"SET search_path TO {sp};")


async def init_pool(
    *,
    min_size: int | None = None,
    max_size: int | None = None,
    timeout: int | None = None,
) -> asyncpg.Pool:
    """Инициализируем и кешируем пул asyncpg."""
    global _pool
    if _pool is None:
        async with _lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    dsn=_get_database_url(),
                    min_size=min_size or int(os.getenv("PG_POOL_MIN", "1")),
                    max_size=max_size or int(os.getenv("PG_POOL_MAX", "10")),
                    command_timeout=timeout or int(os.getenv("PG_COMMAND_TIMEOUT", "60")),
                    init=_init_connection,  # <- важное: search_path на каждом соединении
                )
    return _pool


async def get_pool() -> asyncpg.Pool:
    pool = _pool
    if pool is None:
        pool = await init_pool()
    return pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def connection() -> asyncpg.Connection:
    pool = await get_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


@asynccontextmanager
async def transaction():
    async with connection() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            yield conn
        except Exception:
            await tx.rollback()
            raise
        else:
            await tx.commit()


# --- Утилиты запросов ---

async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    async with connection() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    async with connection() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    async with connection() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args: Any) -> str:
    async with connection() as conn:
        return await conn.execute(query, *args)


async def executemany(query: str, param_sets: Iterable[Sequence[Any]]) -> None:
    async with connection() as conn:
        await conn.executemany(query, list(param_sets))


# --- Вспомогательные алиасы ---

def q(table: str, schema: str = "core") -> str:
    """
    Полное имя таблицы с учетом схемы (для статической подстановки).
    Пример: q("channels") -> core.channels
    """
    s = SCHEMAS.get(schema, schema)
    return f'{s}.{table}'
