import os, asyncio, base64
import aiosqlite, httpx
from dotenv import load_dotenv
from bot.handlers.webapp_gate import router as webapp_gate_router
from bot.handlers.webapp import router as webapp_router
from bot.handlers.reply_menu import router as reply_menu_router
from bot.handlers.channel_wizard import router as channel_wizard_router
from bot.handlers.finalize import router as finalize_router
from bot.handlers.my_channels import router as my_channels_router
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ChatJoinRequest, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.types.input_file import BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com/webapp/login")
if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN not set")

_proxy = os.getenv("TG_PROXY_URL")
if _proxy:
    session = AiohttpSession(proxy=_proxy)
    bot = Bot(BOT_TOKEN, session=session, parse_mode=None)
else:
    bot = Bot(BOT_TOKEN, parse_mode=None)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(webapp_gate_router)
dp.include_router(webapp_router)
dp.include_router(reply_menu_router)
dp.include_router(channel_wizard_router)
dp.include_router(finalize_router)
dp.include_router(my_channels_router)
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
CREATE TABLE IF NOT EXISTS profiles(
  contractor_id TEXT PRIMARY KEY,
  std_avatar BLOB
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


async def reply_menu_kb(contractor_id: str) -> ReplyKeyboardMarkup:
    # Reply-клавиатура под полем ввода
    try:
        sess = await userbot_get("/session/status", {"contractor_id": contractor_id})
        has = bool(sess.get("has_session"))
    except Exception:
        has = False
    if not has:
        rows = [
            [KeyboardButton(text="Подключить аккаунт (WebApp)", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="Проверить подключение")],
        ]
    else:
        rows = [
            [KeyboardButton(text="Создать канал быстро")],
            [KeyboardButton(text="Мои каналы"), KeyboardButton(text="Инвайт")],
            [KeyboardButton(text="Загрузить PDF"), KeyboardButton(text="Статистика")],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


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

# Quick fallback: start phone login via command (no WebApp/HTTPS)
@router.message(Command("phone"))
async def cmd_phone(m: Message, state: FSMContext):
    await state.set_state(PhoneLogin.waiting_phone)
    await m.answer(
        "Введите номер телефона в формате +79991234567:"
    )

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

@router.callback_query(F.data == "newproj_quick")
async def cb_newproj_quick(cq: CallbackQuery):
    contractor_id = str(cq.from_user.id)
    if not await has_session(contractor_id):
        await cq.message.answer("⚠️ Сначала подключите сессию через WebApp.")
        await cq.answer(); return
    title = f"Проект {cq.from_user.first_name or ''}".strip()
    # 1) создать канал через userbot (с noforwards)
    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(r["channel_id"])  # Telethon id
    chat_id = int(f"-100{abs(channel_id)}")
    # 2) добавить бота админом
    me = await bot.get_me()
    bot_username = me.username if me.username.startswith("@") else f"@{me.username}"
    await userbot_post("/rooms/add_bot_admin", {
        "contractor_id": contractor_id,
        "channel_id": channel_id,
        "bot_username": bot_username,
    })
    # 3) сохранить проект
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO projects(contractor_id, title, channel_id) VALUES(?,?,?)",
            (contractor_id, title, chat_id),
        )
        await conn.commit()
    # 4) создать ссылку join-request
    try:
        link = await bot.create_chat_invite_link(
            chat_id=chat_id, name=f"Invite for {title}", creates_join_request=True
        )
        invite_text = f"\n🔗 Ссылка (join-request): {link.invite_link}"
    except Exception as e:
        invite_text = f"\n⚠️ Не удалось создать ссылку: {e}"
    await cq.message.answer(
        f"✅ Канал создан\n• Название: <b>{title}</b>\n• chat_id: <code>{chat_id}</code> (channel_id: <code>{channel_id}</code>){invite_text}",
        parse_mode="HTML",
    )
    await cq.answer()

@router.message(NewProject.waiting_title)
async def got_project_title(m: Message, state: FSMContext):
    title = m.text.strip()[:64]
    contractor_id = str(m.from_user.id)
    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(r["channel_id"])  # Telethon channel id
    # Convert to Bot API chat_id (-100 prefix)
    chat_id = int(f"-100{abs(channel_id)}")
    # Resolve bot username dynamically to avoid relying on BOT_USERNAME env
    me = await bot.get_me()
    bot_username = me.username if me.username.startswith("@") else f"@{me.username}"
    await userbot_post("/rooms/add_bot_admin", {
        "contractor_id": contractor_id,
        "channel_id": channel_id,
        "bot_username": bot_username
    })
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO projects(contractor_id, title, channel_id) VALUES(?,?,?)",
                           (contractor_id, title, chat_id))
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

@router.message(Command("menu"))
async def cmd_menu(m: Message):
    kb = await main_menu_kb(str(m.from_user.id))
    await m.answer("Меню обновлено:", reply_markup=kb)

# --------- NEW WIZARD COMMANDS ---------
class NewChannel(StatesGroup):
    waiting_title = State()
    waiting_avatar = State()

@router.message(Command("new"))
async def cmd_new(m: Message, state: FSMContext):
    await state.set_state(NewChannel.waiting_title)
    await m.answer("Введите название канала (например: Дом • Проект А).")

@router.message(NewChannel.waiting_title)
async def new_channel_title(m: Message, state: FSMContext):
    title = m.text.strip()[:64]
    await state.update_data(title=title)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="skip_avatar2")]])
    await state.set_state(NewChannel.waiting_avatar)
    await m.answer("Пришлите фото для аватарки или нажмите Пропустить.", reply_markup=kb)

@router.callback_query(F.data == "skip_avatar2")
async def skip_avatar2(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await create_channel_pipeline(cq.message, title=data.get("title", "Проект"), avatar_bytes=None)
    await state.clear(); await cq.answer()

@router.message(NewChannel.waiting_avatar, F.photo)
async def new_channel_avatar(m: Message, state: FSMContext):
    data = await state.get_data()
    photo = m.photo[-1]
    f = await bot.get_file(photo.file_id)
    b = await bot.download_file(f.file_path)
    await create_channel_pipeline(m, title=data.get("title", "Проект"), avatar_bytes=b)
    await state.clear()

async def create_channel_pipeline(msg: Message, title: str, avatar_bytes: bytes | None):
    contractor_id = str(msg.from_user.id)
    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(r["channel_id"])  # Telethon id
    chat_id = int(f"-100{abs(channel_id)}")
    me = await bot.get_me()
    bot_username = me.username if me.username.startswith("@") else f"@{me.username}"
    await userbot_post("/rooms/add_bot_admin", {
        "contractor_id": contractor_id,
        "channel_id": channel_id,
        "bot_username": bot_username
    })
    if avatar_bytes:
        try:
            await bot.set_chat_photo(chat_id=chat_id, photo=BufferedInputFile(avatar_bytes, filename="avatar.jpg"))
        except Exception:
            pass
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO projects(contractor_id, title, channel_id) VALUES(?,?,?)",
                           (contractor_id, title, chat_id))
        await conn.commit()
    try:
        link = await bot.create_chat_invite_link(
            chat_id=chat_id, name=f"Invite for {title}", creates_join_request=True
        )
        invite_text = f"\n🔗 Ссылка (join-request): {link.invite_link}"
    except Exception as e:
        invite_text = f"\n⚠️ Не удалось создать ссылку: {e}"
    await msg.answer(
        f"✅ Канал создан\n• Название: <b>{title}</b>\n• chat_id: <code>{chat_id}</code> (channel_id: <code>{channel_id}</code>){invite_text}",
        parse_mode="HTML",
    )

@router.message(Command("channels"))
async def cmd_channels(m: Message):
    contractor_id = str(m.from_user.id)
    async with aiosqlite.connect(DB_PATH) as conn:
        rows = []
        async with conn.execute("SELECT id, title, channel_id FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 10", (contractor_id,)) as cur:
            async for r in cur:
                rows.append(r)
    if not rows:
        await m.answer("Пока нет каналов. Используйте /new для создания.")
        return
    text = "Ваши каналы:\n" + "\n".join([f"• {t} — <code>{cid}</code>" for _, t, cid in rows])
    await m.answer(text, parse_mode="HTML")

# --------- EXTRA MENU AND UPLOAD ---------
class UploadFile(StatesGroup):
    waiting_pdf = State()

def _get_celery():
    from celery import Celery
    return Celery("bot", broker=os.getenv("REDIS_URL", "redis://redis:6379/0"))

@router.callback_query(F.data == "newproj_wizard")
async def cb_newproj_wizard(cq: CallbackQuery, state: FSMContext):
    await cb_newproj(cq, state)

@router.callback_query(F.data == "channels")
async def cb_channels(cq: CallbackQuery):
    contractor_id = str(cq.from_user.id)
    async with aiosqlite.connect(DB_PATH) as conn:
        rows = []
        async with conn.execute(
            "SELECT id, title, channel_id FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 10",
            (contractor_id,)
        ) as cur:
            async for r in cur:
                rows.append(r)
    if not rows:
        await cq.message.answer("Пока нет каналов. Нажмите ‘Создать канал’.")
    else:
        text = "Ваши каналы:\n" + "\n".join([f"• {t} — <code>{cid}</code>" for _, t, cid in rows])
        await cq.message.answer(text, parse_mode="HTML")
    await cq.answer()

@router.callback_query(F.data == "upload")
async def cb_upload(cq: CallbackQuery, state: FSMContext):
    await state.set_state(UploadFile.waiting_pdf)
    await cq.message.answer("Пришлите PDF-файл. Мы отрендерим первую страницу в PNG 300 DPI с водяным знаком и опубликуем в последний канал.")
    await cq.answer()

@router.message(UploadFile.waiting_pdf, F.document)
async def on_pdf(m: Message, state: FSMContext):
    doc = m.document
    filename = doc.file_name or "smeta.pdf"
    if not filename.lower().endswith(".pdf"):
        await m.answer("Пожалуйста, пришлите PDF-файл.")
        return
    f = await bot.get_file(doc.file_id)
    data = await bot.download_file(f.file_path)
    pdf_b64 = base64.b64encode(data).decode("ascii")
    contractor_id = str(m.from_user.id)
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT channel_id FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 1",
            (contractor_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        await m.answer("Сначала создайте канал (/new).")
        return
    chat_id = int(row[0])
    wm_text = m.from_user.username or str(m.from_user.id)
    out_name = os.path.splitext(filename)[0] + ".png"
    celery_app = _get_celery()
    celery_app.send_task(
        "worker.tasks.render.process_and_publish_pdf",
        args=[chat_id, pdf_b64, wm_text, out_name],
    )
    await m.answer("✅ Файл принят. PNG будет опубликован в канале после обработки.")
    await state.clear()

@router.callback_query(F.data == "stats")
async def cb_stats(cq: CallbackQuery):
    await cq.message.answer("Статистика: в разработке (просмотры/вступления/выходы).")
    await cq.answer()

# ---------- RUN ----------
async def main():
    await init_db()
    print("Bot is up.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio; asyncio.run(main())
