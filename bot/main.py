"""Entry point for running the Telegram bot.

- aiogram v3
- centralized settings (config.settings)
- routers split by areas
- graceful logging & startup checks
"""

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from config import settings
from handlers import menu_contractor, menu_owner, start


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Set it in environment or .env")

    bot = Bot(settings.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # shared context
    dp["owner_ids"] = settings.owner_ids
    dp["backend_url"] = settings.backend_url

    # routers
    dp.include_router(start.router)
    dp.include_router(menu_owner.router)
    dp.include_router(menu_contractor.router)

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    with suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
