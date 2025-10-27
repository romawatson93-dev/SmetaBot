from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from bot.handlers.menu import reply_menu_for, userbot_get
from bot.handlers.menu_common import BTN_PROFILE
import bot.services.channels as channels_service
import bot.services.contractors as contractors_service
import bot.services.profiles as profiles_service

router = Router()


class Profile(StatesGroup):
    waiting_avatar = State()


def profile_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🖼 Загрузить аватарку")],
        [KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(Command("profile"))
async def cmd_profile(m: Message, state: FSMContext):
    await m.answer("Личный кабинет:", reply_markup=profile_kb())


@router.message(F.text == BTN_PROFILE)
async def open_profile_from_menu(m: Message, state: FSMContext):
    await cmd_profile(m, state)


@router.message(F.text == "🖼 Загрузить аватарку")
async def profile_upload_avatar_start(m: Message, state: FSMContext):
    await state.set_state(Profile.waiting_avatar)
    await m.answer(
        "Отправьте изображение (фото или файл PNG/JPEG), которое будет использоваться как стандартная аватарка для каналов."
    )


@router.message(Profile.waiting_avatar, F.photo | F.document)
async def profile_receive_avatar(m: Message, state: FSMContext):
    contractor_id_int = m.from_user.id
    data_bytes: bytes | None = None
    name_hint: str | None = None

    if m.photo:
        photo = m.photo[-1]
        file = await m.bot.get_file(photo.file_id)
        data_bytes = await m.bot.download_file(file.file_path)
        name_hint = "photo.jpg"
    elif m.document:
        doc = m.document
        name = (doc.file_name or "").lower()
        if not (name.endswith(".png") or name.endswith(".jpg") or name.endswith(".jpeg")):
            await m.answer("Пожалуйста, отправьте PNG или JPEG файл.")
            return
        file = await m.bot.get_file(doc.file_id)
        data_bytes = await m.bot.download_file(file.file_path)
        name_hint = doc.file_name or "avatar.png"

    try:
        if hasattr(data_bytes, "read"):
            data_bytes = data_bytes.read()
    except Exception:
        pass

    if not data_bytes:
        await m.answer("Не удалось получить файл. Попробуйте ещё раз.")
        return

    await profiles_service.upsert_avatar(contractor_id_int, data_bytes, name_hint or "avatar.png")
    await state.clear()
    await m.answer(
        "Готово. Стандартная аватарка сохранена. Теперь её можно выбирать в мастере создания канала.",
        reply_markup=profile_kb(),
    )


@router.message(F.text == "⬅️ Назад")
async def profile_back_to_menu(m: Message, state: FSMContext):
    await state.clear()
    contractor_id = str(m.from_user.id)
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    await m.answer("Меню:", reply_markup=reply_menu_for(m.from_user.id, has))


@router.message(F.text == "👤 Мой профиль")
async def profile_stats(m: Message):
    contractor_id = str(m.from_user.id)
    contractor_id_int = m.from_user.id

    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id, "verify": "true"})
        sess_txt = "активна" if (sess.get("has_session") and sess.get("authorized")) else "нет"
    except Exception:
        sess_txt = "—"

    channels_count = await channels_service.count_channels(contractor_id_int)

    try:
        avatar = await profiles_service.get_avatar(contractor_id_int)
        avatar_name = avatar.get("std_avatar_name") if avatar else "—"
    except Exception:
        avatar_name = "—"

    sub_txt = "—"
    text = (
        "Мой профиль:\n"
        f"- Мой ID: <code>{contractor_id}</code>\n"
        f"- Бот-сессия: {sess_txt}\n"
        f"- Подписка: {sub_txt}\n"
        f"- Стандартная аватарка: {avatar_name or '—'}\n"
        f"- Количество каналов: {channels_count}\n"
        f"- Статистика: в разработке"
    )
    await m.answer(text, parse_mode="HTML", reply_markup=profile_kb())
