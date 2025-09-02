import os, asyncio, base64
import aiosqlite, httpx
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ChatJoinRequest, WebAppInfo
)
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN not set")

bot = Bot(BOT_TOKEN, parse_mode=None)
dp = Dispatcher(storage=MemoryStorage())
router = Router(); dp.include_router(router)

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# ---------- DB ----------
CREATE_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contractor_id TEXT NOT NULL,
  title TEXT NOT NULL,
  channel_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS invites(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  invite_link TEXT NOT NULL,
  allowed INTEGER NOT NULL DEFAULT 1,
  approved_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(invite_link)
);
"""
async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(CREATE_SQL); await conn.commit()

# ---------- HTTP helpers ----------
async def userbot_post(path: str, json=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.post(f"{USERBOT_URL}{path}", json=json or {}); r.raise_for_status(); return r.json()
async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {}); r.raise_for_status(); return r.json()
async def has_session(contractor_id: str) -> bool:
    try:
        r = await userbot_get("/session/status", {"contractor_id": contractor_id}); return bool(r.get("has_session"))
    except Exception: return False

# ---------- UI helpers ----------
def ik_btn(text, data): return InlineKeyboardButton(text=text, callback_data=data)
def ik_kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
async def main_menu_kb(contractor_id: str) -> InlineKeyboardMarkup:
    # проверим, есть ли активная сессия
    sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
    has = bool(sess.get("has_session"))
    rows = []
    if not has:
        rows.append([InlineKeyboardButton(
            text="🔐 Подключить аккаунт (WebApp)",
            web_app=WebAppInfo(url=os.getenv("WEBAPP_URL", "https://example.com/webapp/login"))
        )])
        rows.append([ik_btn("🔎 Проверить подключение", "check_session")])
    else:
        rows.append([ik_btn("➕ Новый проект (создать канал)", "newproj")])
        rows.append([ik_btn("🎟 Ссылка для клиента (join-request)", "invite")])
    return ik_kb(rows)


# ---------- FSM ----------
class PhoneLogin(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()

class NewProject(StatesGroup):
    waiting_title = State()

# ---------- COMMANDS ----------
@router.message(Command("start"))
async def cmd_start(m: Message):
    await init_db()
    kb = await main_menu_kb(str(m.from_user.id))
    await m.answer("Привет! Это панель подрядчика.\nВыбери действие:", reply_markup=kb)

# ---------- PHONE LOGIN ----------
@router.callback_query(F.data == "conn_phone")
async def conn_phone_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(PhoneLogin.waiting_phone)
    await cq.message.answer("Отправь номер телефона в формате +79991234567:")
    await cq.answer()

@router.callback_query(F.data == "check_session")
async def cb_check_session(cq: CallbackQuery):
    contractor_id = str(cq.from_user.id)
    info = await userbot_get("/session/status", {"contractor_id": contractor_id, "verify": "true"})
    if info.get("has_session") and info.get("authorized"):
        await cq.message.answer("✅ Аккаунт подключён. Функции разблокированы.")
        kb = await main_menu_kb(contractor_id)
        await cq.message.answer("Меню:", reply_markup=kb)
    else:
        await cq.message.answer("⏳ Пока не вижу подключения. Завершите вход в открывшемся окне и нажмите ещё раз.")
    await cq.answer()


@router.message(PhoneLogin.waiting_phone)
async def phone_got_number(m: Message, state: FSMContext):
    phone = m.text.strip()
    if not phone.startswith("+") or len(phone) < 10:
        await m.answer("Похоже, формат неверный. Пример: +79991234567")
        return
    r = await userbot_post("/login/phone/start", {"contractor_id": str(m.from_user.id), "phone": phone})
    await state.update_data(token=r["token"])
    await state.set_state(PhoneLogin.waiting_code)
    await m.answer("Я отправил код в Telegram/SMS. Введи 5–6-значный код:")

@router.message(PhoneLogin.waiting_code)
async def phone_got_code(m: Message, state: FSMContext):
    data = await state.get_data()
    token = data["token"]
    r = await userbot_post("/login/phone/confirm", {"token": token, "code": m.text.strip()})
    if r["status"] == "ready":
        me = r.get("me") or {}
        await m.answer(f"✅ Аккаунт подключён: @{me.get('username') or 'unknown'}")
        await state.clear()
        kb = await main_menu_kb(str(m.from_user.id))
        await m.answer("Готово! Вернись в меню:", reply_markup=kb)
    else:
        await state.set_state(PhoneLogin.waiting_password)
        await m.answer("Включён пароль 2FA. Введи пароль от Telegram:")

@router.message(PhoneLogin.waiting_password)
async def phone_got_password(m: Message, state: FSMContext):
    data = await state.get_data()
    token = data["token"]
    r = await userbot_post("/login/phone/2fa", {"token": token, "password": m.text})
    me = r.get("me") or {}
    await m.answer(f"✅ Аккаунт подключён: @{me.get('username') or 'unknown'}")
    await state.clear()
    kb = await main_menu_kb(str(m.from_user.id))
    await m.answer("Готово! Вернись в меню:", reply_markup=kb)

# ---------- NEW PROJECT ----------
@router.callback_query(F.data == "newproj")
async def cb_newproj(cq: CallbackQuery, state: FSMContext):
    contractor_id = str(cq.from_user.id)
    if not await has_session(contractor_id):
        await cq.message.answer("🔒 Сначала подключи свой аккаунт (вход по номеру).")
        await cq.answer(); return
    await state.set_state(NewProject.waiting_title)
    await cq.message.answer("Введи название проекта одной строкой (пример: «Проект Иванова»).")
    await cq.answer()

@router.message(NewProject.waiting_title)
async def got_project_title(m: Message, state: FSMContext):
    title = m.text.strip()[:64]
    contractor_id = str(m.from_user.id)
    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = r["channel_id"]
    await userbot_post("/rooms/add_bot_admin", {
        "contractor_id": contractor_id,
        "channel_id": channel_id,
        "bot_username": BOT_USERNAME
    })
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO projects(contractor_id, title, channel_id) VALUES(?,?,?)",
                           (contractor_id, title, channel_id))
        await conn.commit()
    await m.answer(f"✅ Канал создан и бот добавлен админом.\nНазвание: {title}\nchannel_id: {channel_id}")
    await state.clear()
    kb = await main_menu_kb(contractor_id)
    await m.answer("Вернуться в меню:", reply_markup=kb)

# ---------- INVITE ----------
@router.callback_query(F.data == "invite")
async def cb_invite(cq: CallbackQuery):
    contractor_id = str(cq.from_user.id)
    if not await has_session(contractor_id):
        await cq.message.answer("🔒 Сначала подключи свой аккаунт (вход по номеру).")
        await cq.answer(); return
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT id, title, channel_id FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 1",
            (contractor_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        await cq.message.answer("Сначала создай проект/канал."); await cq.answer(); return
    project_id, title, channel_id = row
    link = await bot.create_chat_invite_link(
        chat_id=channel_id, name=f"Invite for {title}",
        creates_join_request=True, expire_date=None, member_limit=0
    )
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO invites(project_id, invite_link, allowed) VALUES(?,?,?)",
                           (project_id, link.invite_link, 1))
        await conn.commit()
    await cq.message.answer(f"🎟 Ссылка (join-request):\n{link.invite_link}\n"
                            f"⚙️ Разрешено одобрений: 1")
    await cq.answer()

# ---------- JOIN REQUEST ----------
@router.chat_join_request()
async def on_join_request(evt: ChatJoinRequest):
    user_id = evt.from_user.id
    chat_id = evt.chat.id
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT id FROM projects WHERE channel_id=? LIMIT 1", (chat_id,)) as cur:
            proj = await cur.fetchone()
        if not proj:
            await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id); return
        project_id = proj[0]
        async with conn.execute(
            "SELECT id, allowed, approved_count FROM invites WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,)
        ) as cur:
            inv = await cur.fetchone()
        if not inv:
            await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id); return
        inv_id, allowed, approved = inv
        if approved < allowed:
            await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
            await conn.execute("UPDATE invites SET approved_count=approved_count+1 WHERE id=?", (inv_id,))
            await conn.commit()
        else:
            await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)

# ---------- RUN ----------
async def main():
    await init_db()
    print("Bot is up.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio; asyncio.run(main())
