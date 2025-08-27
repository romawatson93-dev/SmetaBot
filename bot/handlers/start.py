from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name=__name__)

@router.message(CommandStart())
async def cmd_start(message: Message):
    owner_ids: set[int] = message.bot.dispatcher["owner_ids"]
    if message.from_user and message.from_user.id in owner_ids:
        await message.answer("👑 Привет, Владелец!\n/menu_owner — открыть панель")
    else:
        await message.answer("🧾 Привет, Подрядчик!\n/menu — открыть меню")
