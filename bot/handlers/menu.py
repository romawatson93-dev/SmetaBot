import os
import httpx
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext

from bot.handlers.channel_wizard import start_wizard
from bot.handlers.my_channels import (
    show_all_channels,
    show_recent_channels,
    start_channels_search,
    show_channels_stats,
)
from bot.handlers.menu_common import (
    build_main_menu_keyboard,
    build_render_menu_keyboard,
    build_channels_menu_keyboard,
    BTN_NEW_CHANNEL,
    BTN_MY_CHANNELS,
    BTN_MY_LINKS,
    BTN_RENDER,
    BTN_RENDER_BACK,
    BTN_RENDER_DOC,
    BTN_RENDER_PDF,
    BTN_RENDER_PNG,
    BTN_RENDER_XLSX,
    BTN_PROFILE,
    BTN_HELP,
    BTN_CHANNELS_RECENT,
    BTN_CHANNELS_ALL,
    BTN_CHANNELS_SEARCH,
    BTN_CHANNELS_STATS,
    BTN_CHANNELS_BACK,
)
from bot.handlers.render_pdf import reset_render_state

router = Router()

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com/webapp/login")
ENV = os.getenv("ENV", "dev").lower()
REQUIRE_INIT_DATA = os.getenv("REQUIRE_INIT_DATA", "true" if ENV == "prod" else "false").lower() in ("1", "true", "yes")


async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


def reply_menu_for(user_id: int, has_session: bool):
    return build_main_menu_keyboard()


def webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть вход (WebApp)", web_app=WebAppInfo(url=WEBAPP_URL))]]
    )


async def _ensure_main_menu(m: Message, state: FSMContext, has_session: bool) -> None:
    data = await state.get_data()
    mid = data.get("menu_mid")
    try:
        if mid:
            await m.bot.edit_message_text(
                "Меню:",
                chat_id=m.chat.id,
                message_id=mid,
                reply_markup=reply_menu_for(m.from_user.id, has_session),
            )
            return
    except Exception:
        pass
    sent = await m.answer("Меню:", reply_markup=reply_menu_for(m.from_user.id, has_session))
    await state.update_data(menu_mid=sent.message_id)


async def _ensure_render_menu(m: Message, state: FSMContext) -> None:
    sent = await m.answer(
        "Для защиты вашего контента в канале, файлы нужно переконвертировать в PNG. "
        "Выберите нужный формат. Если у вас уже готов файл PNG, можете сразу загрузить его в созданный канал, "
        "выбрав «PNG в канал».",
        reply_markup=build_render_menu_keyboard(),
    )
    await state.update_data(menu_mid=sent.message_id)


CHANNELS_TRIGGERS = {BTN_MY_CHANNELS, "Мои каналы"}

@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    init_ok = bool((await state.get_data()).get("init_ok"))
    if REQUIRE_INIT_DATA and not init_ok:
        await m.answer("Для продолжения авторизуйтесь через WebApp:", reply_markup=webapp_kb())
        return
    await _ensure_main_menu(m, state, has)


@router.message(Command("menu"))
async def cmd_menu(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    init_ok = bool((await state.get_data()).get("init_ok"))
    if REQUIRE_INIT_DATA and not init_ok:
        await m.answer("Для продолжения авторизуйтесь через WebApp:", reply_markup=webapp_kb())
        return
    await _ensure_main_menu(m, state, has)


@router.message(F.text == BTN_NEW_CHANNEL)
async def act_new_channel(m: Message, state: FSMContext):
    await start_wizard(m, state)


@router.message(F.text.in_(CHANNELS_TRIGGERS))
async def act_my_channels(m: Message, state: FSMContext):
    sent = await m.answer("Раздел «Мои каналы». Выберите действие:", reply_markup=build_channels_menu_keyboard())
    await state.update_data(channels_menu_mid=sent.message_id)


@router.message(F.text == BTN_CHANNELS_BACK)
async def act_channels_back(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    await _ensure_main_menu(m, state, has)


@router.message(F.text == BTN_CHANNELS_ALL)
async def act_channels_all(m: Message, state: FSMContext):
    await show_all_channels(m, state)


@router.message(F.text == BTN_CHANNELS_RECENT)
async def act_channels_recent(m: Message, state: FSMContext):
    await show_recent_channels(m, state)


@router.message(F.text == BTN_CHANNELS_SEARCH)
async def act_channels_search(m: Message, state: FSMContext):
    await start_channels_search(m, state)


@router.message(F.text == BTN_CHANNELS_STATS)
async def act_channels_stats(m: Message, state: FSMContext):
    await show_channels_stats(m, state)


@router.message(F.text == BTN_MY_LINKS)
async def act_my_links(m: Message):
    await m.answer(
        "🔗 Ссылки: приглашение формата join-request появится после того, как вы создадите канал через «🆕 Новый канал»."
    )


@router.message(F.text == BTN_RENDER)
async def act_render_menu(m: Message, state: FSMContext):
    await _ensure_render_menu(m, state)


@router.message(F.text == BTN_RENDER_BACK)
async def act_render_back(m: Message, state: FSMContext):
    await reset_render_state(state)
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    await _ensure_main_menu(m, state, has)


@router.message(F.text == BTN_RENDER_PNG)
async def act_render_png_direct(m: Message):
    await m.answer("🖼️ Если PNG уже готов, прикрепите его как документ прямо в созданном канале.")


@router.message(F.text == BTN_PROFILE)
async def act_profile(m: Message):
    await m.answer("👤 Личный кабинет: управление настройками профиля появится здесь позже.")


@router.message(F.text == BTN_HELP)
async def act_help(m: Message):
    await m.answer(
        "❓ Помощь:\n"
        "- 🆕 Новый канал — мастер создания защищённого канала.\n"
        "- 📢 Мои каналы — список проектов.\n"
        "- 🔗 Мои ссылки — генерация приглашений подрядчиков.\n"
        "- 🖼️ Рендер файлов — выбор формата для конвертации в PNG.\n"
        "- 👤 Личный кабинет — настройки профиля (в разработке).\n"
        "- В prod сначала авторизуйтесь через WebApp."
    )


@router.message(F.text == "??????")
async def legacy_invite(m: Message):
    await m.answer("Используйте «🔗 Мои ссылки» или «📢 Мои каналы» для управления приглашениями.")
