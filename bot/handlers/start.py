# bot/handlers/start.py
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

router = Router()


def owner_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая комната")],
            # при желании добавьте другие кнопки для владельца
        ],
        resize_keyboard=True,
    )


def contractor_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мои проекты")],
        ],
        resize_keyboard=True,
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    owner_ids: set[int] | list[int] | tuple[int, ...] = (),  # <-- ИНЪЕКЦИЯ из dp["owner_ids"]
):
    """
    В aiogram v3 данные из dp[...] попадают в параметры хендлера по имени.
    Мы кладём dp["owner_ids"] в main.py и получаем тут через параметр owner_ids.
    НИКАКИХ message.bot.dispatcher в v3 не существует.
    """
    uid = message.from_user.id if message.from_user else 0
    is_owner = uid in set(owner_ids)

    if is_owner:
        await message.answer("Привет, владелец! Выбери действие:", reply_markup=owner_kb())
    else:
        await message.answer("Привет! Здесь будут ваши проекты.", reply_markup=contractor_kb())
