# /app/api.py
import os
import re
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pyrogram import Client, filters
from pyrogram.errors import RPCError

# ===== ЛОГИ =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("userbot")
logging.getLogger("pyrogram").setLevel(logging.INFO)

# ===== НАСТРОЙКИ =====
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_NAME = os.getenv("TG_SESSION_NAME", "userbot")
SESSION_DIR = "/sessions"

# Если нужен прокси — раскомментируйте и задайте TG_PROXY_URL в .env
# from urllib.parse import urlparse
# def build_proxy(url: str | None):
#     if not url:
#         return None
#     u = urlparse(url)
#     return {
#         "scheme": u.scheme, "hostname": u.hostname, "port": u.port,
#         "username": u.username, "password": u.password
#     }
# PROXY = build_proxy(os.getenv("TG_PROXY_URL"))
PROXY = None

# ваш числовой id подхватим на старте
MY_ID: int | None = None

pyro = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    workdir=SESSION_DIR,
    proxy=PROXY,
)

app = FastAPI(title="Userbot API")

# ===== ХУКИ СТАРТА/ОСТАНОВА =====
@app.on_event("startup")
async def _startup():
    await pyro.start()

    # 🔥 Прогреваем кэш пиров, чтобы не было 'Peer id invalid'
    try:
        async for _ in pyro.get_dialogs(limit=100):
            pass
        log.info("dialogs warm-up done")
    except Exception as e:
        log.warning("dialogs warm-up failed: %s", e)

    me = await pyro.get_me()

    # ⬇️ запомним ваш числовой user id (например, 370759938)
    global MY_ID
    MY_ID = me.id

    if getattr(me, "is_bot", False):
        raise RuntimeError(
            "Userbot залогинен как БОТ. Удалите /sessions/*.session и залогиньтесь телефоном."
        )
    log.info("pyrogram started as %s (%s)", me.username, me.id)

@app.on_event("shutdown")
async def _shutdown():
    await pyro.stop()
    log.info("pyrogram stopped")

# ===== УТИЛИТЫ =====
def _is_me(msg) -> bool:
    """
    Считаем сообщение «моим», если оно исходящее (outgoing=True)
    ИЛИ явно от моего user_id.
    """
    return bool(
        getattr(msg, "outgoing", False)
        or (getattr(msg, "from_user", None) and msg.from_user.id == MY_ID)
    )

# ===== СЕРВИСНЫЕ ЭНДПОИНТЫ =====
@app.get("/health")
async def health():
    me = await pyro.get_me()
    return {"ok": True, "user": me.username, "id": me.id, "is_bot": getattr(me, "is_bot", None)}

@app.post("/selftest")
async def selftest():
    me = await pyro.get_me()
    await pyro.send_message("me", "✅ Userbot online")
    return {"ok": True, "user_id": me.id}

# ===== ДИАГНОСТИКА АПДЕЙТОВ (временный логгер) =====
@pyro.on_message(filters.text)
async def _dbg_me(client, message):
    # логируем КАЖДОЕ текстовое сообщение и помечаем, «моё» ли оно
    log.info(
        "TXT chat=%s from=%s outgoing=%s is_me=%s text=%r",
        getattr(message.chat, "id", None),
        getattr(getattr(message, "from_user", None), "id", None),
        getattr(message, "outgoing", None),
        _is_me(message),
        message.text,
    )

# ===== ПИНГ-ХЕНДЛЕР (со слэшем и без; ru/en) =====
@pyro.on_message(
    filters.text & filters.regex(r"^/?(?:ping|pong|пинг|понг)$", flags=re.IGNORECASE)
)
async def ping_me(client, message):
    if not _is_me(message):
        return
    log.info("PING matched text=%r chat=%s", message.text, getattr(message.chat, "id", None))
    await message.reply_text("pong")

# ===== МИНИ-API: создание канала + защита + добавить бота админом =====
class CreateRoomReq(BaseModel):
    title: str
    bot_username: str  # например "@YourBot"

class CreateRoomResp(BaseModel):
    chat_id: int
    title: str

@app.post("/create_room", response_model=CreateRoomResp)
async def create_room(req: CreateRoomReq):
    try:
        chat = await pyro.create_channel(req.title, description="Личная комната клиента")
        chat_id = chat.id

        # Включить protected content (если доступно в вашей версии клиента/аккаунта)
        try:
            # в разных версиях может называться по-разному — ловим любые ошибки
            await pyro.set_chat_protected_content(chat_id, True)  # type: ignore[attr-defined]
        except Exception as e:
            log.warning("set_chat_protected_content not applied: %s", e)

        # Добавить бота и выдать базовые админ-права
        await pyro.add_chat_members(chat_id, [req.bot_username])
        await pyro.promote_chat_member(
            chat_id,
            req.bot_username,
            can_manage_chat=True,
            can_post_messages=True,
            can_edit_messages=True,
            can_delete_messages=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_video_chats=False,
            can_promote_members=False,
        )

        return CreateRoomResp(chat_id=chat_id, title=req.title)
    except RPCError as e:
        raise HTTPException(status_code=400, detail=f"Telegram error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
