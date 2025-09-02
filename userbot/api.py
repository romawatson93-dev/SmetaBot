import os, asyncio, secrets
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError
)
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest
from telethon.tl.types import ChatAdminRights
from telethon.tl.functions.messages import ToggleNoForwardsRequest

from cryptography.fernet import Fernet

# ---------- ENV ----------
load_dotenv()

_api_id = os.getenv("API_ID") or os.getenv("TG_API_ID") or "0"
API_ID = int(_api_id) if _api_id.isdigit() else 0
API_HASH = os.getenv("API_HASH") or os.getenv("TG_API_HASH") or ""
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
FLOODWAIT_FALLBACK = int(os.getenv("USERBOT_FLOODWAIT_FALLBACK", "5"))
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "/app/sessions")

if not API_ID or not API_HASH:
    raise RuntimeError("API_ID/API_HASH not set")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET not set")

os.makedirs(SESSIONS_DIR, exist_ok=True)
fernet = Fernet(SESSION_SECRET)

# ---------- HELPERS ----------
def _enc(s: str) -> bytes: return fernet.encrypt(s.encode("utf-8"))
def _dec(b: bytes) -> str: return fernet.decrypt(b).decode("utf-8")

def session_path(contractor_id: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{contractor_id}.session.enc")

def save_session(contractor_id: str, session_string: str) -> None:
    with open(session_path(contractor_id), "wb") as f:
        f.write(_enc(session_string))

def load_session(contractor_id: str) -> Optional[str]:
    p = session_path(contractor_id)
    if not os.path.exists(p): return None
    with open(p, "rb") as f: data = f.read()
    return _dec(data)

async def with_floodwait(coro):
    try:
        return await coro
    except FloodWaitError as e:
        await asyncio.sleep(getattr(e, "seconds", FLOODWAIT_FALLBACK))
        return await coro

async def get_client_for_contractor(contractor_id: str) -> TelegramClient:
    sess = load_session(contractor_id)
    if not sess:
        raise HTTPException(400, "Нет сессии подрядчика. Сначала выполните вход по номеру.")
    client = TelegramClient(StringSession(sess), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise HTTPException(401, "Сессия больше не авторизована")
    return client

# ---------- APP ----------
app = FastAPI(title="SmetaBot Userbot (phone only)")

# ----------- MODELS -----------
class SessionStatusResp(BaseModel):
    has_session: bool
    authorized: bool = False

class PhoneStartReq(BaseModel):
    contractor_id: str
    phone: str            # +79991234567

class PhoneStartResp(BaseModel):
    token: str

class PhoneConfirmReq(BaseModel):
    token: str
    code: str             # 5–6 цифр

class PhoneConfirmResp(BaseModel):
    status: str           # "ready" | "2fa_required"
    me: Optional[dict] = None

class PhonePasswordReq(BaseModel):
    token: str
    password: str

class PhonePasswordResp(BaseModel):
    status: str
    me: Optional[dict] = None

class CreateRoomReq(BaseModel):
    contractor_id: str
    title: str
    about: Optional[str] = ""

class CreateRoomResp(BaseModel):
    channel_id: int

class AddBotAdminReq(BaseModel):
    contractor_id: str
    channel_id: int
    bot_username: str

# ---------- SESSION STATUS ----------
@app.get("/session/status", response_model=SessionStatusResp)
async def session_status(contractor_id: str, verify: bool = False):
    sess = load_session(contractor_id)
    if not sess:
        return SessionStatusResp(has_session=False, authorized=False)
    if not verify:
        return SessionStatusResp(has_session=True, authorized=True)
    client = TelegramClient(StringSession(sess), API_ID, API_HASH)
    try:
        await client.connect()
        ok = await client.is_user_authorized()
        return SessionStatusResp(has_session=True, authorized=bool(ok))
    finally:
        await client.disconnect()

# ---------- PHONE LOGIN ----------
_pending_phone: Dict[str, Dict[str, Any]] = {}  # token -> {client, contractor_id, phone}

@app.post("/login/phone/start", response_model=PhoneStartResp)
async def phone_start(req: PhoneStartReq):
    token = secrets.token_urlsafe(24)
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        await with_floodwait(client.send_code_request(req.phone))
    except PhoneNumberInvalidError:
        await client.disconnect()
        raise HTTPException(400, "Неверный номер телефона")
    _pending_phone[token] = {"client": client, "contractor_id": req.contractor_id, "phone": req.phone}
    return PhoneStartResp(token=token)

@app.post("/login/phone/confirm", response_model=PhoneConfirmResp)
async def phone_confirm(req: PhoneConfirmReq):
    info = _pending_phone.get(req.token)
    if not info:
        raise HTTPException(404, "Нет активного логина. Начните заново.")
    client: TelegramClient = info["client"]
    try:
        await with_floodwait(client.sign_in(phone=info["phone"], code=req.code))
        me = await client.get_me()
        sess = client.session.save()
        save_session(info["contractor_id"], sess)
        info["ready"] = True
        info["me"] = dict(id=me.id, username=me.username, phone=me.phone)
        return PhoneConfirmResp(status="ready", me=info["me"])
    except SessionPasswordNeededError:
        return PhoneConfirmResp(status="2fa_required")
    except PhoneCodeInvalidError:
        raise HTTPException(400, "Неверный код")

@app.post("/login/phone/2fa", response_model=PhonePasswordResp)
async def phone_2fa(req: PhonePasswordReq):
    info = _pending_phone.get(req.token)
    if not info:
        raise HTTPException(404, "Нет активного логина. Начните заново.")
    client: TelegramClient = info["client"]
    await with_floodwait(client.sign_in(password=req.password))
    me = await client.get_me()
    sess = client.session.save()
    save_session(info["contractor_id"], sess)
    info["ready"] = True
    info["me"] = dict(id=me.id, username=me.username, phone=me.phone)
    await client.disconnect()
    return PhonePasswordResp(status="ready", me=info["me"])

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/webapp/login", response_class=HTMLResponse)
async def webapp_login():
    # простая страница WebApp — ввод телефона / кода / 2FA
    return HTMLResponse("""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Подключение аккаунта</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin:16px; }
    .card { padding:16px; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.08); }
    input { width:100%; padding:12px; margin:8px 0; border:1px solid #ddd; border-radius:8px; font-size:16px; }
    button { width:100%; padding:12px; border:0; border-radius:10px; font-size:16px; }
    .primary { background:#2ea6ff; color:#fff; }
    .ghost { background:#f3f5f7; }
    .muted { color:#666; font-size:14px; }
    #ok { display:none; }
  </style>
</head>
<body>
  <div class="card">
    <h3>Подключение аккаунта Telegram</h3>
    <p class="muted">Введите номер телефона, затем код (и пароль 2FA, если включён).</p>

    <div id="step1">
      <input id="phone" type="tel" placeholder="+79991234567" />
      <button class="primary" onclick="start()">Получить код</button>
    </div>

    <div id="step2" style="display:none">
      <input id="code" inputmode="numeric" pattern="[0-9]*" placeholder="Код из Telegram / SMS" />
      <button class="primary" onclick="confirmCode()">Подтвердить код</button>
      <p class="muted">Если включён пароль — попросим на следующем шаге.</p>
    </div>

    <div id="step3" style="display:none">
      <input id="password" type="password" placeholder="Пароль 2FA" />
      <button class="primary" onclick="confirmPassword()">Войти</button>
    </div>

    <div id="ok">
      <p>✅ Аккаунт подключён. Можно закрыть это окно и вернуться к боту.</p>
      <button class="ghost" onclick="Telegram.WebApp.close()">Закрыть</button>
    </div>

    <p id="msg" class="muted"></p>
  </div>

<script>
const tg = window.Telegram.WebApp;
tg.expand(); // во всю высоту
let token = null;

function getUserId() {
  const u = tg.initDataUnsafe?.user;
  return u?.id?.toString() || "";
}

async function start() {
  const phone = document.getElementById("phone").value.trim();
  const contractor_id = getUserId();
  if (!phone.startsWith("+") || phone.length < 10) {
    return setMsg("Укажите номер в формате +79991234567");
  }
  if (!contractor_id) return setMsg("Не удалось получить ваш Telegram ID. Откройте мини-приложение из бота.");
  try {
    const r = await fetch("/login/phone/start", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ contractor_id, phone })
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    token = data.token;
    showStep(2);
    setMsg("Код отправлен в Telegram/SMS. Введите его ниже.");
  } catch (e) { setMsg("Ошибка: " + e.message); }
}

async function confirmCode() {
  try {
    const code = document.getElementById("code").value.trim();
    const r = await fetch("/login/phone/confirm", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ token, code })
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    if (data.status === "ready") {
      showOk();
    } else {
      showStep(3);
      setMsg("Введите пароль 2FA.");
    }
  } catch (e) { setMsg("Ошибка: " + e.message); }
}

async function confirmPassword() {
  try {
    const password = document.getElementById("password").value;
    const r = await fetch("/login/phone/2fa", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ token, password })
    });
    if (!r.ok) throw new Error(await r.text());
    showOk();
  } catch (e) { setMsg("Ошибка: " + e.message); }
}

function showStep(n) {
  document.getElementById("step1").style.display = (n===1)?"":"none";
  document.getElementById("step2").style.display = (n===2)?"":"none";
  document.getElementById("step3").style.display = (n===3)?"":"none";
  document.getElementById("ok").style.display = "none";
}
function showOk(){
  document.getElementById("step1").style.display="none";
  document.getElementById("step2").style.display="none";
  document.getElementById("step3").style.display="none";
  document.getElementById("ok").style.display="block";
  setMsg("Готово. Вернитесь в чат с ботом.");
}
function setMsg(t){ document.getElementById("msg").textContent = t; }
</script>
</body>
</html>
    """)


# ---------- ROOMS ----------
@app.post("/rooms/create", response_model=CreateRoomResp)
async def create_room(req: CreateRoomReq):
    client = await get_client_for_contractor(req.contractor_id)
    try:
        r = await with_floodwait(client(CreateChannelRequest(
            title=req.title,
            about=req.about or "",
            megagroup=False,
            for_import=False
        )))
        ch = r.chats[0]
        await asyncio.sleep(1.5)
        await with_floodwait(client(ToggleNoForwardsRequest(channel=ch, enabled=True)))
        await asyncio.sleep(1.0)
        return CreateRoomResp(channel_id=ch.id)
    finally:
        await client.disconnect()

@app.post("/rooms/add_bot_admin")
async def add_bot_admin(req: AddBotAdminReq):
    client = await get_client_for_contractor(req.contractor_id)
    try:
        entity = await client.get_entity(req.channel_id)
        bot = await client.get_entity(req.bot_username)
        rights = ChatAdminRights(
            post_messages=True, invite_users=True,
            add_admins=False, change_info=False,
            ban_users=False, delete_messages=False,
            pin_messages=False, manage_call=False,
            anonymous=False, edit_messages=False
        )
        await with_floodwait(client(EditAdminRequest(
            channel=entity, user_id=bot, admin_rights=rights, rank="bot"
        )))
        await asyncio.sleep(0.5)
        return {"ok": True}
    finally:
        await client.disconnect()


@app.get("/", include_in_schema=False)
async def root_redirect():
    # Перекидываем на веб-приложение логина
    return RedirectResponse(url="/webapp/login", status_code=302)
