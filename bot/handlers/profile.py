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
        [KeyboardButton(text="👤 Мой профиль")],
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
          std_avatar BLOB,
          std_avatar_name TEXT
        )
        """
    )
    # Try add missing column if table existed before
    try:
        await conn.execute("ALTER TABLE profiles ADD COLUMN std_avatar_name TEXT")
    except Exception:
        pass


@router.message(Profile.waiting_avatar, F.photo | F.document)
async def profile_receive_avatar(m: Message, state: FSMContext):
    contractor_id = str(m.from_user.id)
    data_bytes = None
    name_hint = None
    if m.photo:
        ph = m.photo[-1]
        f = await m.bot.get_file(ph.file_id)
        data_bytes = await m.bot.download_file(f.file_path)
        name_hint = "photo.jpg"
    elif m.document:
        doc = m.document
        name = (doc.file_name or "").lower()
        if not (name.endswith('.png') or name.endswith('.jpg') or name.endswith('.jpeg')):
            await m.answer("Пожалуйста, отправьте PNG или JPEG файл.")
            return
        f = await m.bot.get_file(doc.file_id)
        data_bytes = await m.bot.download_file(f.file_path)
        name_hint = doc.file_name or "avatar.png"
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
            "INSERT INTO profiles(contractor_id, std_avatar, std_avatar_name) VALUES(?, ?, ?) ON CONFLICT(contractor_id) DO UPDATE SET std_avatar=excluded.std_avatar, std_avatar_name=excluded.std_avatar_name",
            (contractor_id, data_bytes, name_hint or "avatar.png")
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


@router.message(F.text == "👤 Мой профиль")
@router.message(F.text == "Мой профиль")
async def profile_stats(m: Message):
    contractor_id = str(m.from_user.id)
    # Session status
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id, "verify": "true"})
        sess_txt = "активна" if (sess.get("has_session") and sess.get("authorized")) else "нет"
    except Exception:
        sess_txt = "—"
    # Channels count
    channels = 0
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            async with conn.execute("SELECT COUNT(*) FROM projects WHERE contractor_id=?", (contractor_id,)) as cur:
                row = await cur.fetchone()
                channels = int(row[0] if row else 0)
        except Exception:
            channels = 0
        # Avatar filename
        try:
            await _ensure_profiles_table(conn)
            async with conn.execute("SELECT std_avatar_name FROM profiles WHERE contractor_id=?", (contractor_id,)) as cur:
                row = await cur.fetchone()
                avatar_name = row[0] if row and row[0] else "—"
        except Exception:
            avatar_name = "—"
    # Subscription stub
    sub_txt = "—"
    text = (
        "Мой профиль:\n"
        f"- Мой ID: <code>{contractor_id}</code>\n"
        f"- Бот-сессия: {sess_txt}\n"
        f"- Подписка: {sub_txt}\n"
        f"- Стандартная аватарка: {avatar_name}\n"
        f"- Количество каналов: {channels}\n"
        f"- Статистика: в разработке"
    )
    await m.answer(text, parse_mode="HTML", reply_markup=profile_kb())
