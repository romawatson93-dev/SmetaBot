import os
import httpx
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
import aiosqlite
from bot.handlers.channel_wizard import start_wizard
from bot.handlers.my_channels import cmd_channels

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com/webapp/login")
ENV = os.getenv("ENV", "dev").lower()
REQUIRE_INIT_DATA = os.getenv("REQUIRE_INIT_DATA", "true" if ENV == "prod" else "false").lower() in ("1","true","yes")


async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


def _menu_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🆕 Новый канал")],
        [KeyboardButton(text="📢 Мои каналы"), KeyboardButton(text="🔗 Мои ссылки")],
        [KeyboardButton(text="🖼️ Рендер в PNG"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def reply_menu_for(user_id: int, has_session: bool) -> ReplyKeyboardMarkup:
    return _menu_keyboard()


def webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть вход (WebApp)", web_app=WebAppInfo(url=WEBAPP_URL))]])


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
    init_ok = bool(data.get("init_ok"))
    if REQUIRE_INIT_DATA and not init_ok:
        await m.answer("Для доступа к меню выполните вход через WebApp:", reply_markup=webapp_kb())
        return
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
    init_ok = bool(data.get("init_ok"))
    if REQUIRE_INIT_DATA and not init_ok:
        await m.answer("Для доступа к меню выполните вход через WebApp:", reply_markup=webapp_kb())
        return
    try:
        if mid:
            await m.bot.edit_message_text("Меню:", chat_id=m.chat.id, message_id=mid, reply_markup=reply_menu_for(m.from_user.id, has))
            return
    except Exception:
        pass
    sent = await m.answer("Меню:", reply_markup=reply_menu_for(m.from_user.id, has))
    await state.update_data(menu_mid=sent.message_id)


@router.message(F.text == "🆕 Новый канал")
async def act_new_channel(m: Message, state: FSMContext):
    await start_wizard(m, state)


@router.message(F.text == "📢 Мои каналы")
async def act_my_channels(m: Message, state: FSMContext):
    await cmd_channels(m, state)


@router.message(F.text == "🔗 Мои ссылки")
async def act_my_links(m: Message):
    await m.answer("🔗 Скоро: управление ссылками приглашений. Пока используйте раздел ‘📢 Мои каналы’.")


@router.message(F.text == "🖼️ Рендер в PNG")
async def act_render_png(m: Message):
    await m.answer("🖼️ Пришлите PDF-файл в этот чат — подготовим рендер в PNG c водяным знаком.")


@router.message(F.text == "👤 Личный кабинет")
async def act_profile(m: Message):
    await m.answer("👤 Личный кабинет: скоро тут будут настройки аккаунта, тариф и квоты.")


@router.message(F.text == "❓ Помощь")
async def act_help(m: Message):
    await m.answer("❓ Помощь:\n- Создайте ‘🆕 Новый канал’ или откройте ‘📢 Мои каналы’.\n- В dev-режиме WebApp не обязателен. В prod — сначала ‘Открыть вход (WebApp)’.")


# Legacy shortcuts from the previous menu
@router.message(F.text == "������")
async def legacy_invite(m: Message):
    await m.answer("Используйте пункт ‘🔗 Мои ссылки’ или ‘📢 Мои каналы’ для управления приглашениями.")

