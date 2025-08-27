# /app/api.py
import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import ChatPrivileges  # <-- важное добавление

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

pyro = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    workdir=SESSION_DIR,
    proxy=PROXY,
)

app = FastAPI(title="Userbot API")

# ===== СТАРТ/СТОП =====
@app.on_event("startup")
async def _startup():
    await pyro.start()
    # прогрев кэша диалогов (фикс 'Peer id invalid')
    try:
        async for _ in pyro.get_dialogs(limit=100):
            pass
        log.info("dialogs warm-up done")
    except Exception as e:
        log.warning("dialogs warm-up failed: %s", e)

    me = await pyro.get_me()
    if getattr(me, "is_bot", False):
        raise RuntimeError("Userbot залогинен как БОТ. Удалите /sessions/*.session и залогиньтесь телефоном.")
    log.info("pyrogram started as %s (%s)", me.username, me.id)

@app.on_event("shutdown")
async def _shutdown():
    await pyro.stop()
    log.info("pyrogram stopped")

# ===== МОДЕЛИ =====
class CreateRoomReq(BaseModel):
    title: str
    bot_username: str  # например "@OrbitSend_bot"

class CreateRoomResp(BaseModel):
    chat_id: int
    title: str

# ===== ЭНДПОИНТЫ =====
@app.get("/health")
async def health():
    me = await pyro.get_me()
    return {"ok": True, "user": me.username, "id": me.id, "is_bot": getattr(me, "is_bot", None)}

@app.post("/selftest")
async def selftest():
    me = await pyro.get_me()
    await pyro.send_message("me", "✅ Userbot online")
    return {"ok": True, "user_id": me.id}

@app.post("/create_room", response_model=CreateRoomResp)
async def create_room(req: CreateRoomReq):
    """
    1) создаём приватный канал
    2) включаем защиту контента (restrict saving)
    3) бота сразу назначаем администратором (без приглашения участником)
    """
    try:
        # 1) создать канал
        chat = await pyro.create_channel(req.title, description="Личная комната клиента")
        chat_id = chat.id

        # 2) защитить контент (если метод доступен)
        try:
            await pyro.set_chat_protected_content(chat_id, True)  # type: ignore[attr-defined]
        except Exception as e:
            log.warning("set_chat_protected_content not applied: %s", e)

        # 3) назначить бота администратором
        bot = await pyro.get_users(req.bot_username)
        target = getattr(bot, "id", req.bot_username)

        privileges = ChatPrivileges(
            can_change_info=True,
            can_post_messages=True,      # для каналов
            can_edit_messages=True,      # для каналов
            can_delete_messages=True,
            can_invite_users=True,
            can_restrict_members=False,
            can_pin_messages=True,
            can_promote_members=False,
            can_manage_video_chats=False,
            is_anonymous=False,
            # can_manage_topics=True,    # при необходимости, если доступно
        )

        await pyro.promote_chat_member(chat_id, target, privileges=privileges)

        return CreateRoomResp(chat_id=chat_id, title=req.title)

    except RPCError as e:
        raise HTTPException(status_code=400, detail=f"Telegram error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
