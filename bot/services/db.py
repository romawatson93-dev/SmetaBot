# bot/services/db.py
from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Iterable, Sequence, Optional

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

_pool: Optional[asyncpg.Pool] = None
_lock = asyncio.Lock()

# bot/services/db.py  (добавь рядом с остальными хелперами)
def _rewrite_params(query: str, params: Iterable[Any] | None) -> tuple[str, list[Any]]:
    if params is None:
        return query, []
    params = list(params)
    if "%s" not in query:
        return query, params
    parts = query.split("%s")
    rebuilt = parts[0]
    for i, tail in enumerate(parts[1:], start=1):
        rebuilt += f"${i}" + tail
    return rebuilt, params

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
        # позволим собирать из DB_* (на случай, если DATABASE_URL не задан)
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "")
        name = os.getenv("DB_NAME", "postgres")
        url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return _normalize_dsn(url)

# bot/services/db.py — в методах facade

async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    q, p = _rewrite_params(query, args if args else None)
    async with connection() as conn:
        if p:
            return await conn.fetch(q, *p)
        else:
            return await conn.fetch(q)

async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    async with connection() as conn:
        if args:
            # Если первый аргумент - это кортеж/список (один элемент), распаковываем его
            if len(args) == 1 and isinstance(args[0], (list, tuple)):
                return await conn.fetchrow(query, *args[0])
            return await conn.fetchrow(query, *args)
        else:
            return await conn.fetchrow(query)

async def fetchval(query: str, *args: Any) -> Any:
    async with connection() as conn:
        if args:
            return await conn.fetchval(query, *args)
        else:
            return await conn.fetchval(query)

async def execute(query: str, *args: Any) -> str:
    async with connection() as conn:
        if args:
            return await conn.execute(query, *args)
        else:
            return await conn.execute(query)

async def executemany(query: str, param_sets: Iterable[Sequence[Any]]) -> None:
    seq = [list(x) for x in param_sets]
    if "%s" in query and seq:
        parts = query.split("%s")
        rebuilt = parts[0]
        for i, tail in enumerate(parts[1:], start=1):
            rebuilt += f"${i}" + tail
        query = rebuilt
    async with connection() as conn:
        await conn.executemany(query, seq)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """search_path и параметры сессии для каждого соединения."""
    tz = os.getenv("PG_TIMEZONE", "UTC")
    schemas_env = os.getenv("PG_SEARCH_PATH")
    if schemas_env:
        schemas = [s.strip() for s in schemas_env.split(",") if s.strip()]
    else:
        schemas = list(SCHEMAS_DEFAULT)

    sp = ", ".join(f'"{s}"' for s in schemas)
    await conn.execute(f"SET TIME ZONE '{tz}';")
    await conn.execute(f"SET search_path TO {sp};")


# ========== НИЖЕ — твой прежний API-функциями ==========
async def init_pool(*, min_size: int | None = None, max_size: int | None = None, timeout: int | None = None) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    dsn=_get_database_url(),
                    min_size=min_size or int(os.getenv("PG_POOL_MIN", "1")),
                    max_size=max_size or int(os.getenv("PG_POOL_MAX", "10")),
                    command_timeout=timeout or int(os.getenv("PG_COMMAND_TIMEOUT", "60")),
                    init=_init_connection,
                )
    return _pool  # type: ignore[return-value]


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


def q(table: str, schema: str = "core") -> str:
    """Полное имя таблицы с учетом схемы (для статической подстановки)."""
    s = SCHEMAS.get(schema, schema)
    return f"{s}.{table}"


# ========== Фасад-объект, которого ждут сервисы: db ==========
class _DBFacade:
    """Фасад над модульными функциями с приведением к dict, где это уместно."""

    async def init_pool(self, **kw: Any) -> asyncpg.Pool:
        return await init_pool(**kw)

    async def close(self) -> None:
        await close_pool()

    @asynccontextmanager
    async def connection(self):
        async with connection() as conn_:
            yield conn_

    @asynccontextmanager
    async def transaction(self):
        async with transaction() as conn_:
            yield conn_

    # ----- helpers c приведением типов -----
    async def fetchrow(self, query: str, params: Iterable[Any] | None = None) -> Optional[dict]:
        row = await fetchrow(query, *(params or []))
        return dict(row) if row is not None else None

    async def fetch(self, query: str, params: Iterable[Any] | None = None) -> list[dict]:
        rows = await fetch(query, *(params or []))
        return [dict(r) for r in rows]

    async def fetchval(self, query: str, params: Iterable[Any] | None = None) -> Any:
        return await fetchval(query, *(params or []))

    async def execute(self, query: str, params: Iterable[Any] | None = None) -> str:
        return await execute(query, *(params or []))

    async def executemany(self, query: str, seq_of_params: Iterable[Iterable[Any]]) -> None:
        await executemany(query, seq_of_params)

    # утилиты
    def q(self, table: str, schema: str = "core") -> str:
        return q(table, schema)


# <<< ВАЖНО: экспортируемый синглтон >>>
db = _DBFacade()

__all__ = [
    # модульные функции (обратная совместимость)
    "init_pool", "get_pool", "close_pool",
    "connection", "transaction",
    "fetch", "fetchrow", "fetchval", "execute", "executemany",
    "q",
    # фасад
    "db",
]
