from typing import Optional
import secrets
from .db import fetchrow, fetch, execute, fetchval, q, transaction

# core.contractors: id(bigserial PK), tg_user_id BIGINT UNIQUE, username TEXT, full_name TEXT, status TEXT, created_at

async def get_or_create_by_tg(tg_id: int, username: Optional[str] = None, full_name: Optional[str] = None) -> int:
    """
    Создаёт или получает подрядчика по Telegram ID.
    При создании нового подрядчика автоматически инициализирует:
    - Подписку FREE
    - Счётчики использования (usage_counters)
    - Реферальную ссылку
    """
    # Проверяем, существует ли уже подрядчик
    existing = await fetchrow(
        f"SELECT id FROM {q('contractors')} WHERE tg_user_id = $1",
        tg_id
    )
    
    if existing:
        # Обновляем данные и возвращаем ID
        await execute(
            f"""
            UPDATE {q("contractors")} 
            SET username = COALESCE($2, {q("contractors")}.username),
                full_name = COALESCE($3, {q("contractors")}.full_name)
            WHERE tg_user_id = $1
            """,
            tg_id, username, full_name
        )
        return int(existing["id"])
    
    # Создаём нового подрядчика с инициализацией всех связанных данных
    async with transaction() as tx:
        # 1. Создаём подрядчика
        contractor_row = await tx.fetchrow(
            f"""
            INSERT INTO {q("contractors")} (tg_user_id, username, full_name)
            VALUES ($1, $2, $3)
            RETURNING id;
            """,
            tg_id, username, full_name,
        )
        contractor_id = int(contractor_row["id"])
        
        # 2. Создаём подписку FREE
        free_plan = await tx.fetchrow(
            "SELECT id FROM billing.plans WHERE code = 'FREE'"
        )
        if free_plan:
            await tx.execute(
                """
                INSERT INTO billing.subscriptions (contractor_id, plan_id, status)
                VALUES ($1, $2, 'active')
                """,
                contractor_id, free_plan["id"]
            )
        
        # 3. Создаём счётчики использования
        await tx.execute(
            """
            INSERT INTO billing.usage_counters (contractor_id)
            VALUES ($1)
            """,
            contractor_id
        )
        
        # 4. Создаём реферальную ссылку
        # Генерируем уникальный токен
        token = secrets.token_urlsafe(32)
        await tx.execute(
            """
            INSERT INTO referrals.referral_links (contractor_id, token)
            VALUES ($1, $2)
            """,
            contractor_id, token
        )
        
        # 5. Создаём стартовый цикл реферальной программы
        await tx.execute(
            """
            INSERT INTO referrals.referral_cycles (referrer_id, cycle_no, state)
            VALUES ($1, 1, 'in_progress')
            """,
            contractor_id
        )
        
        # 6. Записываем в историю подписки
        if free_plan:
            await tx.execute(
                """
                INSERT INTO billing.subscription_history 
                    (contractor_id, plan_id, status, starts_at, source)
                VALUES ($1, $2, 'active', now(), 'trial')
                """,
                contractor_id, free_plan["id"]
            )
        
        await tx.commit()
        
        return contractor_id

async def get_by_id(contractor_id: int) -> Optional[dict]:
    row = await fetchrow(f"SELECT * FROM {q('contractors')} WHERE id = $1;", contractor_id)
    return dict(row) if row else None

async def block(contractor_id: int, blocked: bool = True) -> None:
    status = 'blocked' if blocked else 'active'
    await execute(f"UPDATE {q('contractors')} SET status = $2 WHERE id = $1;", contractor_id, status)

# Профиль / обзор — тянем из analytics.profile_overview (VIEW)
async def profile_overview(contractor_id: int) -> Optional[dict]:
    row = await fetchrow(f"SELECT * FROM analytics.profile_overview WHERE contractor_id = $1;", contractor_id)
    return dict(row) if row else None
