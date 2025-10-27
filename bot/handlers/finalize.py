import os

import httpx
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import bot.services.channels as channels_service
import bot.services.contractors as contractors_service
import bot.services.invites as invites_service

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")


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
    channel_db = record.get("channel") if record else None

    await cq.message.edit_text("✅ Канал создан\n✅ Бот добавлен админом\n✅ Проект сохранён\n⏳ Генерирую ссылку…")
    try:
        link = await bot.create_chat_invite_link(chat_id=chat_id, name=f"Invite for {title}", member_limit=1)
        invite = link.invite_link
        if channel_db:
            # Извлекаем только токен из полной ссылки
            token = invite.split('/')[-1] if '/' in invite else invite
            await invites_service.create_invite(channel_id=int(channel_db['id']), token=token, max_uses=1)
    except Exception as exc:
        invite = f"Не удалось создать ссылку: {exc}"

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
    # Получаем последний канал и ищем активную ссылку
    contractor_id_int = cq.from_user.id
    latest = await channels_service.get_latest_channel(contractor_id_int)
    if not latest:
        await cq.answer("Канал не найден", show_alert=True)
        return
    
    channel_id = int(latest["channel_id"])
    # Здесь можно добавить логику получения ссылки из БД или создания новой
    await cq.answer("Используйте раздел '🔗 Мои ссылки' для управления приглашениями")
