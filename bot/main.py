# bot/main.py (фрагмент)
import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties  # <-- добавьте импорт

from config import settings
from handlers import menu_contractor, menu_owner, start, rooms  # rooms вы уже подключили


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Set it in environment or .env")

    # 👇 корректный способ задать parse_mode в v3
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # 🧰 Общие данные для инъекции в хендлеры
    dp["owner_ids"] = settings.owner_ids
    dp["backend_url"] = settings.backend_url

    # Routers
    dp.include_router(start.router)
    dp.include_router(menu_owner.router)
    dp.include_router(menu_contractor.router)
    dp.include_router(rooms.router)

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    with suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
