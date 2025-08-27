from aiogram import Router, F
from aiogram.types import Message

router = Router(name=__name__)

@router.message(F.text == "/menu")
async def menu_contractor(message: Message):
    await message.answer("📚 Мои комнаты | ➕ Новая комната | 📈 Статистика")
