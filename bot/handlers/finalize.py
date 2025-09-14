import os
import aiosqlite
import httpx
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.input_file import BufferedInputFile

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))
INVITES_CACHE: dict[int, str] = {}


async def userbot_post(path: str, json=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.post(f"{USERBOT_URL}{path}", json=json or {})
        r.raise_for_status()
        return r.json()


@router.callback_query(F.data == "cw:final3")
async def finalize_with_progress(cq: CallbackQuery, bot: Bot):
    uid = cq.from_user.id
    # Получаем промежуточные данные из другого модуля (FSM уже очищается в старом финале)
    # Здесь делаем полный цикл с прогрессом
    await cq.message.edit_text("⏳ Создаю канал…")
    contractor_id = str(uid)
    title = f"Канал {uid}"
    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(r["channel_id"])  # Telethon id
    chat_id = int(f"-100{abs(channel_id)}")
    await cq.message.edit_text("✅ Канал создан\n⏳ Добавляю бота админом…")
    me = await bot.get_me(); bot_username = me.username if me.username.startswith('@') else f"@{me.username}"
    await userbot_post("/rooms/add_bot_admin", {"contractor_id": contractor_id, "channel_id": channel_id, "bot_username": bot_username})
    await cq.message.edit_text("✅ Канал создан\n✅ Бот добавлен админом\n⏳ Сохраняю проект…")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO projects(contractor_id, title, channel_id) VALUES(?,?,?)", (contractor_id, title, chat_id))
        await conn.commit()
    await cq.message.edit_text("✅ Канал создан\n✅ Бот добавлен админом\n✅ Проект сохранён\n⏳ Генерирую ссылку…")
    try:
        link = await bot.create_chat_invite_link(chat_id=chat_id, name=f"Invite for {title}", member_limit=1)
        invite = link.invite_link
    except Exception as e:
        invite = f"Не удалось создать ссылку: {e}"
    INVITES_CACHE[uid] = invite
    report = f"✅ Канал создан\n\nСсылка (бессрочная, 1 человек):\n{invite}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Скопировать", callback_data="cw:copy_invite"), InlineKeyboardButton(text="➡️ Перейти в канал", url=invite if isinstance(invite, str) and invite.startswith("http") else None)]])
    await cq.message.edit_text(report, reply_markup=kb, disable_web_page_preview=True)
    await cq.answer()


@router.callback_query(F.data == "cw:copy_invite")
async def copy_invite(cq: CallbackQuery):
    invite = INVITES_CACHE.get(cq.from_user.id)
    if not invite:
        await cq.answer("Ссылка недоступна", show_alert=True); return
    await cq.message.answer(f"Ссылка:\n<code>{invite}</code>", parse_mode='HTML', disable_web_page_preview=True)
    await cq.answer("Ссылка отправлена")

