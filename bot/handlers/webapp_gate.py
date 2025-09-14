import os, json
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

router = Router()


@router.message(F.web_app_data)
async def mark_init_from_webapp(message: Message, state: FSMContext):
    raw = message.web_app_data.data if message.web_app_data else ""
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    if isinstance(payload, dict) and payload.get("action") == "session_ready":
        await state.update_data(init_ok=True)
        # Do not swallow the update; let other handlers run too.

