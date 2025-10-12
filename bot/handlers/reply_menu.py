import os
import httpx
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import aiosqlite

from bot.handlers.menu_common import (
    build_main_menu_keyboard,
    build_render_menu_keyboard,
    BTN_NEW_CHANNEL,
    BTN_MY_CHANNELS,
    BTN_MY_LINKS,
    BTN_RENDER,
    BTN_RENDER_BACK,
    BTN_RENDER_DOC,
    BTN_RENDER_PNG,
    BTN_RENDER_PDF,
    BTN_RENDER_XLSX,
    BTN_PROFILE,
    BTN_HELP,
)
from bot.handlers.render_pdf import reset_render_state, render_png_start

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))


async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


def reply_menu_for(user_id: int, has_session: bool):
    return build_main_menu_keyboard()


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


@router.message(F.text == BTN_NEW_CHANNEL)
async def msg_new_channel(m: Message, state: FSMContext):
    from bot.handlers.channel_wizard import start_wizard

    await start_wizard(m, state)


@router.message(F.text == BTN_MY_CHANNELS)
async def msg_channels_redirect(m: Message, state: FSMContext):
    from bot.handlers.my_channels import cmd_channels

    await cmd_channels(m, state)


@router.message(F.text == BTN_MY_LINKS)
async def msg_invite(m: Message, bot: Bot):
    contractor_id = str(m.from_user.id)
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT id, title, channel_id FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 1",
            (contractor_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        await m.answer("Сначала создайте канал через «🆕 Новый канал».")
        return
    project_id, title, channel_id = row
    try:
        link = await bot.create_chat_invite_link(
            chat_id=channel_id,
            name=f"Invite for {title}",
            creates_join_request=True,
            expire_date=None,
            member_limit=0,
        )
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT INTO invites(project_id, invite_link, allowed) VALUES(?,?,?)",
                (project_id, link.invite_link, 1),
            )
            await conn.commit()
        await m.answer(f"🔗 Приглашение (join-request):\n{link.invite_link}\n✅ Ограничение: 1 заявка.")
    except Exception as e:
        await m.answer(f"⚠️ Не удалось создать приглашение: {e}")


@router.message(F.text == BTN_RENDER)
async def msg_render_menu(m: Message, state: FSMContext):
    sent = await m.answer(
        "Для защиты вашего контента в канале, файлы нужно переконвертировать в PNG. "
        "Выберите нужный формат. Если у вас уже готов файл PNG, можете сразу загрузить его в созданный канал, "
        "выбрав «PNG в канал».",
        reply_markup=build_render_menu_keyboard(),
    )
    await state.update_data(menu_mid=sent.message_id)


@router.message(F.text == BTN_RENDER_BACK)
async def msg_render_back(m: Message, state: FSMContext):
    await reset_render_state(state)
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    sent = await m.answer("Меню:", reply_markup=reply_menu_for(m.from_user.id, has))
    await state.update_data(menu_mid=sent.message_id)


@router.message(F.text == BTN_RENDER_PNG)
async def msg_render_png_direct(m: Message, state: FSMContext):
    await render_png_start(m, state)


@router.message(F.text == BTN_PROFILE)
async def msg_profile(m: Message):
    await m.answer("👤 Личный кабинет: настройки профиля появятся здесь позже.")


@router.message(F.text == BTN_HELP)
async def msg_help(m: Message):
    await m.answer(
        "Помощь:\n"
        "- 🆕 Новый канал — мастер создания защищённого канала.\n"
        "- 📢 Мои каналы — список проектов и статусов.\n"
        "- 🔗 Мои ссылки — управление приглашениями подрядчиков.\n"
        "- 🖼️ Рендер файлов — выбор формата для конвертации в PNG.\n"
        "- 👤 Личный кабинет — настройки профиля (в разработке).\n"
        "- В dev WebApp не обязателен, в prod сначала авторизуйтесь через WebApp."
    )
