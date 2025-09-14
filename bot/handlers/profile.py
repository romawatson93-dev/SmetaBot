import os
import aiosqlite
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.handlers.reply_menu import reply_menu_for, userbot_get

router = Router()

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))


class Profile(StatesGroup):
    waiting_avatar = State()


def profile_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🖼 Загрузить аватарку")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(Command("profile"))
async def cmd_profile(m: Message, state: FSMContext):
    await m.answer("Личный кабинет:", reply_markup=profile_kb())


# Open via Reply menu button as well
@router.message(F.text == "👤 Личный кабинет")
@router.message(F.text == "Личный кабинет")
async def open_profile_from_menu(m: Message, state: FSMContext):
    await cmd_profile(m, state)


@router.message(F.text == "🖼 Загрузить аватарку")
async def profile_upload_avatar_start(m: Message, state: FSMContext):
    await state.set_state(Profile.waiting_avatar)
    await m.answer("Отправьте изображение (фото или файл PNG/JPEG), которое будет использоваться как стандартная аватарка для каналов.")


async def _ensure_profiles_table(conn):
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles(
          contractor_id TEXT PRIMARY KEY,
          std_avatar BLOB
        )
        """
    )


@router.message(Profile.waiting_avatar, F.photo | F.document)
async def profile_receive_avatar(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    data_bytes = None
    if m.photo:
        ph = m.photo[-1]
        f = await m.bot.get_file(ph.file_id)
        data_bytes = await m.bot.download_file(f.file_path)
    elif m.document:
        doc = m.document
        name = (doc.file_name or "").lower()
        if not (name.endswith('.png') or name.endswith('.jpg') or name.endswith('.jpeg')):
            await m.answer("Пожалуйста, отправьте PNG или JPEG файл.")
            return
        f = await m.bot.get_file(doc.file_id)
        data_bytes = await m.bot.download_file(f.file_path)
    try:
        if hasattr(data_bytes, 'read'):
            data_bytes = data_bytes.read()
    except Exception:
        pass
    if not data_bytes:
        await m.answer("Не удалось получить файл. Попробуйте ещё раз.")
        return
    async with aiosqlite.connect(DB_PATH) as conn:
        await _ensure_profiles_table(conn)
        await conn.execute(
            "INSERT INTO profiles(contractor_id, std_avatar) VALUES(?, ?) ON CONFLICT(contractor_id) DO UPDATE SET std_avatar=excluded.std_avatar",
            (contractor_id, data_bytes)
        )
        await conn.commit()
    await state.clear()
    await m.answer("Готово. Стандартная аватарка сохранена. Теперь её можно выбирать в мастере создания канала.", reply_markup=profile_kb())


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
