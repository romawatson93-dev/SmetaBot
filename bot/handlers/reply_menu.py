import os
import httpx
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
import aiosqlite
from aiogram.fsm.state import StatesGroup, State

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))


async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


def reply_menu_for(user_id: int, has_session: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🆕 Новый канал")],
        [KeyboardButton(text="📚 Мои каналы"), KeyboardButton(text="🔗 Мои ссылки")],
        [KeyboardButton(text="🖼️ Рендер в PNG"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    data = await state.get_data()
    mid = data.get("menu_mid")
    try:
        if mid:
            await m.bot.edit_message_text("Меню:", chat_id=m.chat.id, message_id=mid, reply_markup=reply_menu_for(m.from_user.id, has))
            return
    except Exception:
        pass
    sent = await m.answer("Меню:", reply_markup=reply_menu_for(m.from_user.id, has))
    await state.update_data(menu_mid=sent.message_id)


@router.message(Command("menu"))
async def cmd_menu(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    data = await state.get_data()
    mid = data.get("menu_mid")
    try:
        if mid:
            await m.bot.edit_message_text("Меню:", chat_id=m.chat.id, message_id=mid, reply_markup=reply_menu_for(m.from_user.id, has))
            return
    except Exception:
        pass
    sent = await m.answer("Меню:", reply_markup=reply_menu_for(m.from_user.id, has))
    await state.update_data(menu_mid=sent.message_id)


@router.message(F.text == "🆕 Новый канал")
async def msg_new_channel(m: Message, state: FSMContext):
    from bot.handlers.channel_wizard import start_wizard
    await start_wizard(m, state)


@router.message(F.text == "📚 Мои каналы")
async def msg_channels_redirect(m: Message, state: FSMContext):
    from bot.handlers.my_channels import cmd_channels
    await cmd_channels(m, state)


@router.message(F.text == "🔗 Мои ссылки")
async def msg_invite(m: Message, bot: Bot):
    contractor_id = str(m.from_user.id)
    async with aiosqlite.connect(os.path.join(os.path.dirname(__file__), "..", "data.db")) as conn:
        async with conn.execute(
            "SELECT id, title, channel_id FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 1",
            (contractor_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        await m.answer("Сначала создайте канал (‘Новый канал’).")
        return
    project_id, title, channel_id = row
    try:
        link = await bot.create_chat_invite_link(
            chat_id=channel_id, name=f"Invite for {title}",
            creates_join_request=True, expire_date=None, member_limit=0
        )
        async with aiosqlite.connect(os.path.join(os.path.dirname(__file__), "..", "data.db")) as conn:
            await conn.execute(
                "INSERT INTO invites(project_id, invite_link, allowed) VALUES(?,?,?)",
                (project_id, link.invite_link, 1)
            )
            await conn.commit()
        await m.answer(f"🔗 Ссылка (join-request):\n{link.invite_link}\n👤 Разрешено: 1")
    except Exception as e:
        await m.answer(f"⚠️ Не удалось создать ссылку: {e}")


@router.message(F.text == "🖼️ Рендер в PNG")
async def msg_upload(m: Message):
    await m.answer("Пришлите PDF‑файл как документ. Я поставлю задачу на конвертацию в PNG с водяным знаком.")


@router.message(F.text == "👤 Личный кабинет")
async def msg_profile(m: Message):
    await m.answer("Личный кабинет: скоро здесь будут настройки, квоты и подписки.")


@router.message(F.text == "❓ Помощь")
async def msg_help(m: Message):
    await m.answer("Помощь:\n- 🆕 Новый канал — создать закрытый канал и выдать права боту.\n- 📚 Мои каналы — список ваших каналов.\n- 🔗 Мои ссылки — сгенерировать приглашение (join-request).\n- 🖼️ Рендер в PNG — отправьте PDF как документ для конвертации.\n- 👤 Личный кабинет — настройки (в разработке).")
