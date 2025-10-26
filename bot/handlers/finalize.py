import os

import httpx
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import bot.services.channels as channels_service
import bot.services.projects as projects_service

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
INVITES_CACHE: dict[int, str] = {}


async def userbot_post(path: str, json=None):
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{USERBOT_URL}{path}", json=json or {})
        response.raise_for_status()
        return response.json()


@router.callback_query(F.data == "cw:final3")
async def finalize_with_progress(cq: CallbackQuery, bot: Bot):
    uid = cq.from_user.id
    await cq.message.edit_text("⏳ Создаю канал…")

    contractor_id = str(uid)
    title = f"Канал {uid}"
    response = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(response["channel_id"])
    chat_id = int(f"-100{abs(channel_id)}")

    await cq.message.edit_text("✅ Канал создан\n⏳ Добавляю бота админом…")
    me = await bot.get_me()
    bot_username = me.username if me.username.startswith("@") else f"@{me.username}"
    await userbot_post(
        "/rooms/add_bot_admin",
        {"contractor_id": contractor_id, "channel_id": channel_id, "bot_username": bot_username},
    )

    await cq.message.edit_text("✅ Канал создан\n✅ Бот добавлен админом\n⏳ Сохраняю проект…")
    chat = None
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramForbiddenError:
        chat = None
    record = await channels_service.create_project_channel(
        contractor_id=uid,
        title=title,
        channel_id=chat_id,
        username=getattr(chat, "username", None) if chat else None,
        channel_type=getattr(chat, "type", None) if chat else None,
    )
    project = record.get("project") if record else None

    await cq.message.edit_text("✅ Канал создан\n✅ Бот добавлен админом\n✅ Проект сохранён\n⏳ Генерирую ссылку…")
    try:
        link = await bot.create_chat_invite_link(chat_id=chat_id, name=f"Invite for {title}", member_limit=1)
        invite = link.invite_link
        if project:
            await projects_service.create_invite(project["id"], invite, allowed=1)
    except Exception as exc:
        invite = f"Не удалось создать ссылку: {exc}"

    INVITES_CACHE[uid] = invite
    report = f"✅ Канал создан\n\nСсылка (бессрочная, 1 человек):\n{invite}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔗 Скопировать", callback_data="cw:copy_invite"),
                InlineKeyboardButton(text="➡️ Перейти в канал", url=invite if isinstance(invite, str) and invite.startswith("http") else None),
            ]
        ]
    )
    await cq.message.edit_text(report, reply_markup=kb, disable_web_page_preview=True)
    await cq.answer()


@router.callback_query(F.data == "cw:copy_invite")
async def copy_invite(cq: CallbackQuery):
    invite = INVITES_CACHE.get(cq.from_user.id)
    if not invite:
        await cq.answer("Ссылка недоступна", show_alert=True)
        return
    await cq.message.answer(f"Ссылка:\n<code>{invite}</code>", parse_mode="HTML", disable_web_page_preview=True)
    await cq.answer("Ссылка отправлена")
