from aiogram import Router, F
from aiogram.types import Message

router = Router(name=__name__)

@router.message(F.text == "/menu_owner")
async def menu_owner(message: Message):
    owner_ids: set[int] = message.bot.dispatcher["owner_ids"]
    if message.from_user.id not in owner_ids:
        return await message.answer("❌ Недостаточно прав.")
    await message.answer("👑 Панель владельца:\n- 🔍 Подрядчики\n- 💳 Планы/квоты\n- 🚫 Заморозить/разморозить")
