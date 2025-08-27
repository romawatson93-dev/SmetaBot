from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import httpx
import os

router = Router()
USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8080")


# --- клавиатура ---
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая комната")],
        ],
        resize_keyboard=True,
    )


# --- FSM ---
class NewRoom(StatesGroup):
    waiting_for_title = State()


# --- handlers ---
@router.message(F.text == "/start")
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "Привет! Нажми «➕ Новая комната», чтобы выдать доступ клиенту.",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "➕ Новая комната")
async def ask_title(msg: Message, state: FSMContext):
    await state.set_state(NewRoom.waiting_for_title)
    await msg.answer("Введи название комнаты/проекта (например: «Смета • Иван Петров»).")


@router.message(NewRoom.waiting_for_title, F.text.len() >= 3)
async def create_room_flow(msg: Message, state: FSMContext):
    title = msg.text.strip()
    await msg.answer("⏳ Создаю комнату…")

    # username бота для назначения админом
    me = await msg.bot.get_me()
    bot_username = me.username if me.username.startswith("@") else f"@{me.username}"

    # 1) userbot: создать приватный канал и включить protected content
    try:
        async with httpx.AsyncClient(timeout=40) as x:
            r = await x.post(f"{USERBOT_URL}/create_room",
                             json={"title": title, "bot_username": bot_username})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        await msg.answer(f"❌ Не удалось создать комнату через userbot: {e}")
        await state.clear()
        return

    chat_id = data["chat_id"]

    # 2) Bot API: одноразовая ссылка
    try:
        link = await msg.bot.create_chat_invite_link(
            chat_id=chat_id,
            member_limit=1,
            name="one-time",
        )
    except TelegramBadRequest as e:
        await msg.answer(
            f"⚠️ Комната создана (<code>{chat_id}</code>), "
            f"но ссылку сделать не удалось: <b>{e}</b>\n"
            f"Проверь, что бот админ канала.",
            parse_mode="HTML",
        )
        await state.clear()
        return

    await msg.answer(
        "✅ Комната создана\n"
        f"• Название: <b>{title}</b>\n"
        f"• Chat ID: <code>{chat_id}</code>\n"
        f"• Одноразовая ссылка: {link.invite_link}",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


@router.message(NewRoom.waiting_for_title)
async def title_too_short(msg: Message, state: FSMContext):
    await msg.answer("Название слишком короткое. Введи не менее 3 символов или /start.")
