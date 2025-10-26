import html
import os

import httpx
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types.input_file import BufferedInputFile

import bot.services.channels as channels_service
import bot.services.profiles as profiles_service
import bot.services.projects as projects_service

router = Router()
INVITES_CACHE: dict[int, str] = {}
INVITES_CACHE: dict[int, str] = {}

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")


async def userbot_post(path: str, json=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.post(f"{USERBOT_URL}{path}", json=json or {})
        r.raise_for_status()
        return r.json()


async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def has_session(contractor_id: str) -> bool:
    try:
        r = await userbot_get("/session/status", {"contractor_id": contractor_id})
        return bool(r.get("has_session"))
    except Exception:
        return False


class CreateChannel(StatesGroup):
    input_title = State()
    input_avatar = State()


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def _is_ready(d: dict) -> bool:
    if not d.get("title"):
        return False
    avatar_state = d.get("avatar_state")
    return avatar_state in {"added", "std", "skipped"}


def _card_text(d: dict, *, include_ready_hint: bool = True) -> str:
    title = d.get("title")
    avatar_state = d.get("avatar_state")

    def mark(done):
        return "✅" if done else "▫️"

    t1 = f"{mark(bool(title))} 1) Название: {title or 'не задано'}"
    if avatar_state == 'added':
        t2 = "✅ 2) Аватарка: добавлена"
    elif avatar_state == 'std':
        t2 = "✅ 2) Аватарка: стандартная"
    elif avatar_state == 'skipped':
        t2 = "✅ 2) Аватарка: пропущено"
    else:
        t2 = "▫️ 2) Аватарка: не выбрано"
    header = "Создание канала — чек‑лист"
    body = f"{header}\n\n{t1}\n{t2}"
    if include_ready_hint and _is_ready(d):
        body += "\n\nГотово. Нажмите ‘Продолжить’ для выполнения задач."
    return body


async def _render_card(bot: Bot, chat_id: int, state: FSMContext, hint: str | None, kb: InlineKeyboardMarkup):
    """Always post a fresh card at the bottom and remove the previous one.

    This keeps the checklist directly above the input field as requested.
    """
    d = await state.get_data()
    text = _card_text(d) + (f"\n\nℹ️ {hint}" if hint else "")
    prev_mid = d.get("card_mid")
    # Send a new message (so it appears at the bottom)
    m = await bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)
    await state.update_data(card_mid=m.message_id)
    # Try to delete the previous card to avoid clutter
    if prev_mid:
        try:
            await bot.delete_message(chat_id, prev_mid)
        except Exception:
            pass


def _kb_step1():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel")]
    )


def _kb_step2():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel")],
        [InlineKeyboardButton(text="⭐ Установить стандартную", callback_data="cw:avatar:std"), InlineKeyboardButton(text="⏭️ Пропустить", callback_data="cw:avatar:skip")],
    )


def _kb_final():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel"), InlineKeyboardButton(text="Продолжить", callback_data="cw:final3")]
    )


async def start_wizard(m: Message, state: FSMContext):
    print("[wizard] start_wizard")
    contractor_id = str(m.from_user.id)
    # Dev-friendly session bootstrap: allow phone login without Mini App in non-prod
    try:
        env = (os.getenv("ENV") or os.getenv("APP_ENV") or "dev").lower()
    except Exception:
        env = "dev"
    if env != "prod":
        try:
            ok = await has_session(contractor_id)
        except Exception:
            ok = False
        if not ok:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="☎️ Подключить по телефону (dev)", callback_data="conn_phone")]]
            )
            await m.answer(
                "Сначала подключите сессию. В dev можно войти по телефону без Mini App.",
                reply_markup=kb,
            )
            return
    if not await has_session(contractor_id):
        await m.answer("Сначала подтвердите сессию через Mini App.")
        return
    await state.clear()
    await state.update_data(step=1, title=None, avatar_state=None, avatar_bytes=None, card_mid=None)
    await state.set_state(CreateChannel.input_title)
    await _render_card(m.bot, m.chat.id, state, "Напишите название для канала (пример: Иванов проект и смета)", _kb_step1())


@router.message(StateFilter(CreateChannel.input_title))
async def on_title(m: Message, state: FSMContext):
    print("[wizard] on_title")
    title = (m.text or "").strip()[:64]
    if not title:
        await m.answer("Название пустое. Напишите название ещё раз.")
        return
    await state.update_data(title=title, step=2)
    await state.set_state(CreateChannel.input_avatar)
    await _render_card(m.bot, m.chat.id, state, "Добавьте аватарку или выберите ‘Установить стандартную’ / ‘Пропустить’.", _kb_step2())


@router.message(StateFilter(CreateChannel.input_avatar), F.photo)
async def on_avatar_photo(m: Message, state: FSMContext):
    print("[wizard] on_avatar_photo")
    photo = m.photo[-1]
    f = await m.bot.get_file(photo.file_id)
    data = await m.bot.download_file(f.file_path)
    try:
        # aiogram returns BytesIO; convert to bytes
        if hasattr(data, 'read'):
            data = data.read()
    except Exception:
        pass
    await state.update_data(avatar_state='added', avatar_bytes=data, step=2)
    await _render_card(m.bot, m.chat.id, state, None, _kb_final())


@router.callback_query(StateFilter(CreateChannel.input_avatar), F.data == "cw:avatar:std")
async def on_avatar_std(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_avatar_std")
    await state.update_data(avatar_state='std', avatar_bytes=None, step=2)
    await _render_card(cq.bot, cq.message.chat.id, state, None, _kb_final())
    await cq.answer()

@router.callback_query(StateFilter(CreateChannel.input_avatar), F.data == "cw:avatar:skip")
async def on_avatar_skip(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_avatar_skip")
    await state.update_data(avatar_state='skipped', avatar_bytes=None, step=2)
    await _render_card(cq.bot, cq.message.chat.id, state, None, _kb_final())
    await cq.answer()


@router.message(StateFilter(CreateChannel.input_avatar), F.document)
async def on_file_during_avatar(m: Message, state: FSMContext):
    print("[wizard] on_file_during_avatar")
    await m.answer("Сейчас можно загрузить только аватарку. Отправьте изображение фотографией или выберите ‘Пропустить’.")

@router.callback_query(F.data == "cw:back")
async def on_back(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_back")
    d = await state.get_data(); step = int(d.get('step') or 1)
    step = max(1, step - 1)
    await state.update_data(step=step)
    if step == 1:
        await state.set_state(CreateChannel.input_title)
        await _render_card(cq.bot, cq.message.chat.id, state, "Напишите название для канала (пример: Иванов проект и смета)", _kb_step1())
    else:
        await state.set_state(CreateChannel.input_avatar)
        await _render_card(cq.bot, cq.message.chat.id, state, "Добавьте аватарку или выберите ‘Установить стандартную’ / ‘Пропустить’.", _kb_step2())
    await cq.answer()


@router.callback_query(F.data == "cw:cancel")
async def on_cancel(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_cancel")
    await state.clear()
    await cq.message.edit_text("Отменено.")
    await cq.answer()


@router.message(F.document)
async def on_any_document(m: Message, state: FSMContext):
    """Перехватываем документы во время шага аватарки, чтобы подсказать формат."""
    st = await state.get_state()
    try:
        print(f"[wizard] catch-all document, state={st}")
    except Exception:
        pass
    if st == CreateChannel.input_avatar.state:
        return await on_file_during_avatar(m, state)
    # Иначе — не наш сценарий



async def _execute_job(bot: Bot, user_id: int, d: dict) -> tuple[int | None, str]:
    contractor_id = str(user_id)
    contractor_id_int = user_id
    title = d.get('title') or f"Канал {user_id}"
    avatar_state = d.get('avatar_state')
    avatar_bytes = d.get('avatar_bytes') if avatar_state == 'added' else None
    if (not avatar_bytes) and avatar_state == 'std':
        try:
            profile = await profiles_service.get_avatar(contractor_id_int)
            if profile and profile.get('std_avatar'):
                avatar_bytes = profile['std_avatar']
        except Exception:
            avatar_bytes = None

    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(r["channel_id"])
    chat_id = int(f"-100{abs(channel_id)}")
    me = await bot.get_me()
    bot_username = me.username if me.username.startswith('@') else f"@{me.username}"
    await userbot_post("/rooms/add_bot_admin", {"contractor_id": contractor_id, "channel_id": channel_id, "bot_username": bot_username})

    if avatar_bytes:
        import asyncio
        await asyncio.sleep(1.5)
        try:
            await bot.set_chat_photo(chat_id=chat_id, photo=BufferedInputFile(avatar_bytes, filename="avatar.jpg"))
            avatar_tag = "custom"
        except Exception as e:
            try:
                print(f"[wizard] set_chat_photo failed: {e}")
            except Exception:
                pass
            try:
                import asyncio, base64 as _b64
                await asyncio.sleep(2.0)
                await userbot_post("/rooms/set_photo", {
                    "contractor_id": contractor_id,
                    "channel_id": channel_id,
                    "photo_b64": _b64.b64encode(avatar_bytes).decode("ascii"),
                })
                avatar_tag = "custom"
            except Exception as e2:
                try:
                    print(f"[wizard] userbot set_photo failed: {e2}")
                except Exception:
                    pass
                avatar_tag = None
    else:
        avatar_tag = None

    chat = None
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramForbiddenError:
        chat = None
    record = await channels_service.create_project_channel(
        contractor_id=contractor_id_int,
        title=title,
        channel_id=chat_id,
        username=getattr(chat, 'username', None) if chat else None,
        channel_type=getattr(chat, 'type', None) if chat else None,
        avatar_file=avatar_tag,
    )
    project = record.get('project') if record else None

    try:
        link = await bot.create_chat_invite_link(chat_id=chat_id, name=f"Invite for {title}", member_limit=1)
        invite = link.invite_link
        if project:
            await projects_service.create_invite(project['id'], invite, allowed=1)
    except Exception as e:
        invite = f"Не удалось создать ссылку: {e}"

    return chat_id, invite


@router.callback_query(F.data == "cw:final3")
async def on_final_go(cq: CallbackQuery, state: FSMContext, bot: Bot):
    print("[wizard] on_final_go")
    d = await state.get_data()
    chat_id, invite = await _execute_job(bot, cq.from_user.id, d)
    await state.clear()
    title = d.get('title') or f"Канал {cq.from_user.id}"
    channel_note = f"Создан канал \"{html.escape(title)}\" с защитой контента. Для загрузки файлов перейдите в раздел меню Рендер файлов."
    report = (
        _card_text(d, include_ready_hint=False)
        + f"\n\n{channel_note}"
    )
    try:
        await cq.message.edit_text(report, parse_mode='HTML', reply_markup=None, disable_web_page_preview=True)
    except Exception:
        await cq.message.answer(report, parse_mode='HTML', disable_web_page_preview=True)
    await cq.answer()





