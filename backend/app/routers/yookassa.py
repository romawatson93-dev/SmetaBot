# backend/app/routers/yookassa.py
from __future__ import annotations
import os, base64
from typing import Any, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import get_db  # твой DI

router = APIRouter(tags=["webhooks", "yookassa"])

YKASSA_SHOP_ID  = os.getenv("YKASSA_SHOP_ID", "")
YKASSA_SECRET   = os.getenv("YKASSA_SECRET", "")
WEBHOOK_SECRET  = os.getenv("YKASSA_WEBHOOK_SECRET", "")  # ?secret=...

def _yk_headers() -> dict[str, str]:
    auth = base64.b64encode(f"{YKASSA_SHOP_ID}:{YKASSA_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Accept": "application/json"}

async def _yk_get_payment(payment_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as cli:
        r = await cli.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=_yk_headers())
        r.raise_for_status()
        return r.json()

@router.post("/webhooks/yookassa")
async def yookassa_webhook(request: Request, secret: str, session: AsyncSession = Depends(get_db)):
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad secret")

    payload = await request.json()
    obj = payload.get("object") or payload
    payment_id = obj.get("id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="no payment id")

    payment = await _yk_get_payment(payment_id)
    if payment.get("status") != "succeeded":
        return {"ok": True, "ignored": True, "status": payment.get("status")}

    amount = payment["amount"]["value"]
    currency = payment["amount"]["currency"]
    meta = payment.get("metadata") or {}
    try:
        contractor_id = int(meta.get("contractor_id")) if meta.get("contractor_id") is not None else None
    except Exception:
        contractor_id = None
    plan_code = str(meta.get("plan", "PRO")).upper()

    # таблицу лучше вынести в миграцию; оставляю здесь, чтобы не падать на пустой БД
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS billing.payments (
          id BIGSERIAL PRIMARY KEY,
          payment_id TEXT UNIQUE NOT NULL,
          contractor_id BIGINT,
          plan_code TEXT NOT NULL,
          amount NUMERIC(12,2) NOT NULL,
          currency TEXT NOT NULL,
          status TEXT NOT NULL,
          raw JSONB NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          applied_at TIMESTAMPTZ
        );
    """))

    ins = await session.execute(text("""
        INSERT INTO billing.payments (payment_id, contractor_id, plan_code, amount, currency, status, raw)
        VALUES (:pid, :cid, :plan, :amount::numeric, :cur, 'succeeded', CAST(:raw AS JSONB))
        ON CONFLICT (payment_id) DO NOTHING
        RETURNING id;
    """), {"pid": payment_id, "cid": contractor_id, "plan": plan_code, "amount": amount, "cur": currency, "raw": payment})
    if ins.fetchone() is None:
        await session.commit()
        return {"ok": True, "duplicate": True}

    await session.execute(text("""
        INSERT INTO billing.subscriptions (contractor_id, plan, started_at, expires_at, status, source)
        VALUES (:cid, :plan, now(), now() + interval '30 days', 'active', 'yookassa');
    """), {"cid": contractor_id, "plan": plan_code})

    await session.execute(text("""
        INSERT INTO billing.subscription_history (contractor_id, plan, status, source, note)
        VALUES (:cid, :plan, 'active', 'yookassa', :note);
    """), {"cid": contractor_id, "plan": plan_code, "note": f"payment_id={payment_id}"})

    await session.execute(text("UPDATE billing.payments SET applied_at = now() WHERE payment_id = :pid;"),
                          {"pid": payment_id})

    await session.commit()
    return {"ok": True, "payment": payment_id}
