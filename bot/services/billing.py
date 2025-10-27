# bot/services/billing.py
from __future__ import annotations

from bot.services.db import db


class BillingService:
    async def get_subscription(self, contractor_id: int) -> dict | None:
        row = await db.fetchrow(
            """
            SELECT
                s.id,
                s.contractor_id,
                s.status,
                s.source,
                s.starts_at,
                s.expires_at,
                COALESCE(p.code, 'FREE') AS plan_code
            FROM billing.subscriptions s
            LEFT JOIN billing.plans p ON p.id = s.plan_id
            WHERE s.contractor_id = $1
              AND s.status IN ('active','trial','grace')
            ORDER BY s.expires_at DESC
            LIMIT 1
            """,
            (contractor_id,),
        )
        return row
    
    async def upsert_active_subscription(
        self,
        contractor_id: int,
        plan_code: str,
        months: int = 1,
        source: str = "paid",
        note: str | None = None,
    ) -> None:
        """
        Апсерт активной подписки (удобно для вебхука).
        Если в схеме есть plan_id — берём его, иначе пишем в s.plan.
        """
        # берём plan_id, если есть таблица billing.plans
        plan_rec = await db.fetchrow(
            "SELECT id FROM billing.plans WHERE code = $1",
            (plan_code,),
        )
        if plan_rec and ("id" in plan_rec or hasattr(plan_rec, "get")):
            plan_id = plan_rec.get("id") if hasattr(plan_rec, "get") else plan_rec["id"]
        else:
            plan_id = None

        if plan_id is not None:
            # вариант со столбцом plan_id
            await db.execute(
                """
                INSERT INTO billing.subscriptions (contractor_id, plan_id, status, source, starts_at, expires_at)
                VALUES ($1, $2, 'active', $3, now(), now() + ($4 || ' months')::interval)
                ON CONFLICT (contractor_id) DO UPDATE
                SET plan_id = EXCLUDED.plan_id,
                    status = 'active',
                    source = EXCLUDED.source,
                    starts_at = now(),
                    expires_at = now() + ($4 || ' months')::interval
                """,
                (contractor_id, plan_id, source, months, months),
            )
            await db.execute(
                """
                INSERT INTO billing.subscription_history (contractor_id, plan_id, status, source, note)
                VALUES ($1, $2, 'active', $3, $4)
                """,
                (contractor_id, plan_id, source, note),
            )
        else:
            # совместимость с вариантом, где в subscriptions есть текстовый s.plan
            await db.execute(
                """
                INSERT INTO billing.subscriptions (contractor_id, plan, status, source, starts_at, expires_at)
                VALUES ($1, $2, 'active', $3, now(), now() + ($4 || ' months')::interval)
                ON CONFLICT (contractor_id) DO UPDATE
                SET plan = EXCLUDED.plan,
                    status = 'active',
                    source = EXCLUDED.source,
                    starts_at = now(),
                    expires_at = now() + ($4 || ' months')::interval
                """,
                (contractor_id, plan_code, source, months, months),
            )
            await db.execute(
                """
                INSERT INTO billing.subscription_history (contractor_id, plan, status, source, note)
                VALUES ($1, $2, 'active', $3, $4)
                """,
                (contractor_id, plan_code, source, note),
            )

    async def record_payment(
        self,
        payment_id: str,
        contractor_id: int | None,
        plan_code: str,
        amount: str,
        currency: str,
        status: str,
        raw: dict,
    ) -> bool:
        """
        Фиксирует платёж (идемпотентно). Возвращает True, если вставили новую запись, False — если уже была.
        """
        inserted = await db.fetchrow(
            """
            INSERT INTO billing.payments (payment_id, contractor_id, plan_code, amount, currency, status, raw)
            VALUES ($1, $2, $3, $4::numeric, $5, $6, $7::jsonb)
            ON CONFLICT (payment_id) DO NOTHING
            RETURNING id
            """,
            (payment_id, contractor_id, plan_code, amount, currency, status, raw),
        )
        return bool(inserted)

    async def mark_payment_applied(self, payment_id: str) -> None:
        await db.execute(
            "UPDATE billing.payments SET applied_at = now() WHERE payment_id = $1",
            (payment_id,),
        )

    async def ensure_subscription(self, contractor_id: int) -> dict:
        """
        Гарантирует наличие подписки. Если нет — создаёт FREE.
        Возвращает данные подписки.
        """
        # Проверяем существующую активную подписку
        sub = await self.get_subscription(contractor_id)
        if sub:
            return sub
        
        # Нет подписки — создаём FREE
        free_plan = await db.fetchrow("SELECT id FROM billing.plans WHERE code = 'FREE'")
        if not free_plan:
            raise RuntimeError("FREE plan not found in database")
        
        plan_id = free_plan["id"]
        
        # Вставляем подписку FREE без expires_at
        await db.execute(
            """
            INSERT INTO billing.subscriptions (contractor_id, plan_id, status, source, expires_at)
            VALUES ($1, $2, 'active', 'admin_grant', NULL)
            ON CONFLICT (contractor_id) DO NOTHING
            """,
            (contractor_id, plan_id),
        )
        
        # Обновляем историю
        await db.execute(
            """
            INSERT INTO billing.subscription_history (contractor_id, plan_id, status, source)
            VALUES ($1, $2, 'active', 'admin_grant')
            """,
            (contractor_id, plan_id),
        )
        
        return await self.get_subscription(contractor_id)

    async def can_create_channel(self, contractor_id: int) -> tuple[bool, str]:
        """
        Проверяет, может ли подрядчик создать канал.
        Возвращает (can_create, reason).
        """
        # Гарантируем наличие подписки
        sub = await self.ensure_subscription(contractor_id)
        plan_code = sub.get("plan_code", "FREE")
        
        # PRO и BUSINESS — безлимитные каналы
        if plan_code in ("PRO", "BUSINESS"):
            return True, ""
        
        # FREE — проверяем лимит
        usage = await db.fetchrow(
            "SELECT channels_created_total FROM billing.usage_counters WHERE contractor_id = $1",
            (contractor_id,),
        )
        
        if not usage:
            # Создаём счётчик
            await db.execute(
                "INSERT INTO billing.usage_counters (contractor_id) VALUES ($1)",
                (contractor_id,),
            )
            return True, ""
        
        used = usage.get("channels_created_total", 0) or 0
        limit = sub.get("channels_limit_one_off", 5)  # По умолчанию 5 для FREE
        
        if used >= limit:
            return False, f"Достигнут лимит каналов для тарифа FREE ({limit})"
        
        return True, ""

    async def increment_channels(self, contractor_id: int) -> None:
        """
        Увеличивает счётчик созданных каналов.
        Создаёт запись в usage_counters, если её нет.
        """
        await db.execute(
            """
            INSERT INTO billing.usage_counters (contractor_id, channels_created_total, last_channel_created_at)
            VALUES ($1, 1, now())
            ON CONFLICT (contractor_id) DO UPDATE
            SET channels_created_total = usage_counters.channels_created_total + 1,
                last_channel_created_at = now()
            """,
            (contractor_id,),
        )


# Экспортируем ИНСТАНС, который и ждёт твой импорт:
billing = BillingService()

__all__ = ["billing", "BillingService"]
