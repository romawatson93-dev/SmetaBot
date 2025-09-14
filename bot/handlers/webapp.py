import os, json, httpx, traceback
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from bot.handlers.menu import reply_menu_for

router = Router()

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com/webapp/login")


def webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть WebApp", web_app=WebAppInfo(url=WEBAPP_URL))]])


@router.message(Command("webapp"))
async def cmd_webapp(message: Message):
    await message.answer("Откройте WebApp для подключения сессии:", reply_markup=webapp_kb())


@router.message(F.web_app_data)
async def on_webapp_data(message: Message):
    raw = message.web_app_data.data if message.web_app_data else ""
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {"raw": raw}

    if isinstance(payload, dict) and payload.get("action") == "session_ready":
        contractor_id = str(message.from_user.id)
        userbot_url = os.getenv("USERBOT_URL", "http://userbot:8001")
        info = {"has_session": False, "authorized": False}
        try:
            async with httpx.AsyncClient(timeout=20) as cl:
                r = await cl.get(f"{userbot_url}/session/status", params={"contractor_id": contractor_id, "verify": "true"})
                info = r.json()
        except Exception:
            traceback.print_exc()

        await message.answer(
            "✅ Сессия подтверждена. Меню обновлено." if (info.get("has_session") and info.get("authorized")) else "⚠️ Сессия не подтверждена. Откройте WebApp и завершите вход.",
            reply_markup=reply_menu_for(message.from_user.id, bool(info.get("has_session") and info.get("authorized")))
        )
        return

    preview = raw if len(raw) <= 500 else raw[:500] + " …"
    await message.answer(f"Получены данные из WebApp:\n{preview}")
