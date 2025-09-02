# bot/handlers/join_requests.py
from contextlib import suppress
import logging
import os

from aiogram import Router, Bot            # ← Bot импортируем отсюда
from aiogram.types import ChatJoinRequest  # ← событие из aiogram.types
import httpx

router = Router()
log = logging.getLogger("join-requests")

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")


@router.chat_join_request()
async def on_join_request(e: ChatJoinRequest, bot: Bot):
    """
    Авто-апрув первого и отклонение остальных согласно политике в backend.
    Ссылку НЕ ревокаем автоматически (по твоей текущей модели «одна ссылка»).
    """
    inv = getattr(e, "invite_link", None)
    link = getattr(inv, "invite_link", None)

    # 1) Получаем политику для проекта/чата
    try:
        async with httpx.AsyncClient(timeout=10) as x:
            r = await x.get(
                f"{BACKEND_URL}/projects/by_chat/{e.chat.id}/invite",
                params={"invite_link": link},
            )
            r.raise_for_status()
            policy = r.json()  # {allowed_approvals, approved_count, revoked, expire_at, ...}
    except Exception as ex:
        log.warning("Invite policy fetch failed: %s", ex)
        policy = {"allowed_approvals": 1, "approved_count": 0, "revoked": False, "expire_at": None}

    # 2) Пускаем первого, остальных отклоняем
    if policy.get("approved_count", 0) < policy.get("allowed_approvals", 1):
        await bot.approve_chat_join_request(e.chat.id, e.from_user.id)
        with suppress(Exception):
            async with httpx.AsyncClient(timeout=10) as x:
                await x.post(
                    f"{BACKEND_URL}/projects/by_chat/{e.chat.id}/invite/increment",
                    json={"invite_link": link, "user_id": e.from_user.id},
                )
        log.info("Approved join: chat=%s user=%s link=%s", e.chat.id, e.from_user.id, link)
    else:
        await bot.decline_chat_join_request(e.chat.id, e.from_user.id)
        log.info("Declined extra join: chat=%s user=%s link=%s", e.chat.id, e.from_user.id, link)
