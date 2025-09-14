import os
import io
import base64
import aiosqlite
import httpx
from aiogram import Router, F, Bot
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.input_file import BufferedInputFile
from aiogram.filters import StateFilter

try:
    import fitz  # PyMuPDF
    _FITZ_OK = True
except Exception:
    _FITZ_OK = False

# Local watermark tiling (copy of worker/tasks/watermark.py logic)
from PIL import Image, ImageDraw, ImageFont

def apply_tiled_watermark(img: Image.Image, text: str, opacity: int = 56, step: int = 300, angle: int = -30) -> Image.Image:
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Prefer Roboto (Cyrillic), fallback to DejaVuSans, else default (font ~ 12% of width)
    font = None
    for path in ("Roboto-Regular.ttf",
                 "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf",
                 "DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            # Reduce to ~0.10 of width (6x smaller than previous 0.60)
            font = ImageFont.truetype(path, max(18, int(W * 0.10)))
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    tile_w, tile_h = int(W * 0.5), int(H * 0.22)
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(tile)
    tw, th = d2.textbbox((0, 0), text, font=font)[2:]
    # Dark semi-transparent fill
    d2.text(((tile_w - tw)//2, (tile_h - th)//2), text, font=font, fill=(0, 0, 0, opacity))
    tile = tile.rotate(angle, expand=True)

    for y in range(-tile.height, H + tile.height, step):
        for x in range(-tile.width, W + tile.width, step):
            overlay.alpha_composite(tile, dest=(x, y))

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

router = Router()
INVITES_CACHE: dict[int, str] = {}
INVITES_CACHE: dict[int, str] = {}

USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))


async def userbot_post(path: str, json=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.post(f"{USERBOT_URL}{path}", json=json or {})
        r.raise_for_status()
        return r.json()


async def userbot_get(path: str, params=None):
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.get(f"{USERBOT_URL}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def has_session(contractor_id: str) -> bool:
    try:
        r = await userbot_get("/session/status", {"contractor_id": contractor_id})
        return bool(r.get("has_session"))
    except Exception:
        return False


class CreateChannel(StatesGroup):
    input_title = State()
    input_avatar = State()
    input_files = State()
    input_wm = State()


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def _card_text(d: dict) -> str:
    title = d.get("title")
    avatar_state = d.get("avatar_state")  # 'added' | 'std' | 'skipped' | None
    files = d.get("files") or []
    # Не считаем шаг 3 выполненным, пока пользователь не нажал "Продолжить" на превью
    if not d.get('files_done'):
        files = []
    wm_text = d.get("wm_text")
    wm_skipped = d.get("wm_skipped")

    def mark(done):
        return "✅" if done else "▫️"

    t1 = f"{mark(bool(title))} 1) Название: {title or 'не задано'}"
    if avatar_state == 'added':
        t2 = "✅ 2) Аватарка: добавлена"
    elif avatar_state == 'std':
        t2 = "✅ 2) Аватарка: стандартная"
    elif avatar_state == 'skipped':
        t2 = "✅ 2) Аватарка: пропущено"
    else:
        t2 = "▫️ 2) Аватарка: не выбрано"
    if files:
        names = ", ".join([f.get('out_name', 'file.png') for f in files])
        t3 = f"✅ 3) Файлы: загружено ({names})"
    else:
        t3 = "▫️ 3) Файлы: не загружено"
    if wm_text:
        t4 = "✅ 4) Водяной знак: добавлен"
    elif wm_skipped:
        t4 = "✅ 4) Водяной знак: пропущен"
    else:
        t4 = "▫️ 4) Водяной знак: не задан"

    header = "Создание канала — чек‑лист"
    extra = "\n⏳ Рендер превью..." if d.get('rendering') else ""
    return f"{header}\n\n{t1}\n{t2}\n{t3}\n{t4}{extra}"


async def _render_card(bot: Bot, chat_id: int, state: FSMContext, hint: str, kb: InlineKeyboardMarkup):
    """Always post a fresh card at the bottom and remove the previous one.

    This keeps the checklist directly above the input field as requested.
    """
    d = await state.get_data()
    text = _card_text(d) + (f"\n\nℹ️ {hint}" if hint else "")
    prev_mid = d.get("card_mid")
    # Send a new message (so it appears at the bottom)
    m = await bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)
    await state.update_data(card_mid=m.message_id)
    # Try to delete the previous card to avoid clutter
    if prev_mid:
        try:
            await bot.delete_message(chat_id, prev_mid)
        except Exception:
            pass


def _kb_step1():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel")]
    )


def _kb_step2():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel")],
        [InlineKeyboardButton(text="⭐ Установить стандартную", callback_data="cw:avatar:std"), InlineKeyboardButton(text="⏭️ Пропустить", callback_data="cw:avatar:skip")],
    )


def _kb_step3():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel"), InlineKeyboardButton(text="⏭️ Пропустить", callback_data="cw:files:skip")]
    )


def _kb_file_preview():
    return _kb(
        [InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:file:remove"), InlineKeyboardButton(text="➕ Добавить", callback_data="cw:file:add"), InlineKeyboardButton(text="▶️ Продолжить", callback_data="cw:files:done")]
    )


def _kb_step4_initial():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel"), InlineKeyboardButton(text="⏭️ Пропустить", callback_data="cw:wm:skip")]
    )


def _kb_wm_preview():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="⛔ Отменить", callback_data="cw:wm:clear"), InlineKeyboardButton(text="⏭️ Пропустить", callback_data="cw:wm:skip"), InlineKeyboardButton(text="▶️ Продолжить", callback_data="cw:wm:done")]
    )


def _kb_final():
    return _kb(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cw:back"), InlineKeyboardButton(text="✖️ Отмена", callback_data="cw:cancel"), InlineKeyboardButton(text="▶️ Продолжить", callback_data="cw:final3")]
    )


async def start_wizard(m: Message, state: FSMContext):
    print("[wizard] start_wizard")
    contractor_id = str(m.from_user.id)
    if not await has_session(contractor_id):
        await m.answer("Сначала подтвердите сессию через Mini App.")
        return
    await state.clear()
    await state.update_data(step=1, title=None, avatar_state=None, avatar_bytes=None, files=[], files_done=False, wm_text=None, wm_skipped=False, card_mid=None)
    await state.set_state(CreateChannel.input_title)
    await _render_card(m.bot, m.chat.id, state, "Напишите название для канала (пример: Иванов проект и смета)", _kb_step1())


@router.message(StateFilter(CreateChannel.input_title))
async def on_title(m: Message, state: FSMContext):
    print("[wizard] on_title")
    title = (m.text or "").strip()[:64]
    if not title:
        await m.answer("Название пустое. Напишите название ещё раз.")
        return
    await state.update_data(title=title, step=2)
    await state.set_state(CreateChannel.input_avatar)
    await _render_card(m.bot, m.chat.id, state, "Добавьте аватарку или нажмите ‘Установить стандартную’ / ‘Пропустить’.", _kb_step2())


@router.message(StateFilter(CreateChannel.input_avatar), F.photo)
async def on_avatar_photo(m: Message, state: FSMContext):
    print("[wizard] on_avatar_photo")
    photo = m.photo[-1]
    f = await m.bot.get_file(photo.file_id)
    data = await m.bot.download_file(f.file_path)
    try:
        # aiogram returns BytesIO; convert to bytes
        if hasattr(data, 'read'):
            data = data.read()
    except Exception:
        pass
    await state.update_data(avatar_state='added', avatar_bytes=data, step=3)
    await state.set_state(CreateChannel.input_files)
    await _render_card(m.bot, m.chat.id, state, "Прикрепите PDF-файлы по очереди, как документ (файлом). Под превью будут кнопки.", _kb_step3())


@router.callback_query(StateFilter(CreateChannel.input_avatar), F.data == "cw:avatar:std")
async def on_avatar_std(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_avatar_std")
    # Заглушка: стандартная аватарка пока не настроена — помечаем как стандартная без байтов
    await state.update_data(avatar_state='std', avatar_bytes=None, step=3)
    await state.set_state(CreateChannel.input_files)
    await _render_card(cq.bot, cq.message.chat.id, state, "Прикрепите PDF-файлы по очереди, как документ (файлом). Под превью будут кнопки.", _kb_step3())
    await cq.answer()


@router.callback_query(StateFilter(CreateChannel.input_avatar), F.data == "cw:avatar:skip")
async def on_avatar_skip(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_avatar_skip")
    await state.update_data(avatar_state='skipped', avatar_bytes=None, step=3)
    await state.set_state(CreateChannel.input_files)
    await _render_card(cq.bot, cq.message.chat.id, state, "Прикрепите PDF-файлы по очереди, как документ (файлом). Под превью будут кнопки.", _kb_step3())
    await cq.answer()


@router.message(StateFilter(CreateChannel.input_avatar), F.document)
async def on_file_during_avatar(m: Message, state: FSMContext):
    print("[wizard] on_file_during_avatar")
    await m.answer("Это не фотография. Пришлите фото как изображение (не файл) или нажмите ‘Пропустить’.")


def _render_pdf_preview(pdf_bytes: bytes) -> bytes | None:
    if not _FITZ_OK:
        return None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        pix = page.get_pixmap(dpi=180, alpha=False)
        return pix.tobytes("png")
    except Exception:
        return None


@router.message(StateFilter(CreateChannel.input_files), F.document)
async def on_file(m: Message, state: FSMContext):
    print("[wizard] on_file received")
    doc = m.document
    name = doc.file_name or "file.pdf"
    f = await m.bot.get_file(doc.file_id)
    raw = await m.bot.download_file(f.file_path)
    try:
        if hasattr(raw, 'read'):
            raw = raw.read()
    except Exception:
        pass

    if not name.lower().endswith('.pdf'):
        await m.answer("Пришлите, пожалуйста, PDF-файл как документ (файлом).")
        return

    preview = _render_pdf_preview(raw)
    out_name = os.path.splitext(name)[0] + ".png"

    files = (await state.get_data()).get('files') or []
    files.append({
        'filename': name,
        'pdf_b64': base64.b64encode(raw).decode('ascii'),
        'preview_png': preview,
        'out_name': out_name,
    })
    await state.update_data(files=files)

    if preview:
        sent = await m.answer_photo(BufferedInputFile(preview, filename="preview.png"), caption=f"Превью: {name}", reply_markup=_kb_file_preview())
        await state.update_data(last_preview_mid=sent.message_id)
    else:
        sent = await m.answer(f"Файл получен: {name}", reply_markup=_kb_file_preview())
        await state.update_data(last_preview_mid=sent.message_id)

    # Обновляем карточку (ещё остаёмся на шаге 3). Карточка будет внизу.
    await _render_card(m.bot, m.chat.id, state, "Можно добавить ещё файлы, отменить последний или продолжить.", _kb_step3())


@router.callback_query(StateFilter(CreateChannel.input_files), F.data == "cw:file:remove")
async def on_file_remove(cq: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    files = d.get('files') or []
    if files:
        files.pop()
        await state.update_data(files=files)
    # Удалим превью, если можем
    try:
        await cq.message.delete()
    except Exception:
        pass
    await _render_card(cq.bot, cq.message.chat.id, state, "Файл отменён. Прикрепите новый или продолжите.", _kb_step3())
    await cq.answer()


# Fallback: если по какой-то причине фильтр F.document не сработал (клиент прислал иначе)
@router.message(StateFilter(CreateChannel.input_files))
async def on_file_fallback(m: Message, state: FSMContext):
    if m.document:
        return await on_file(m, state)
    await m.answer("Пришлите PDF именно как файл (документ).")


@router.callback_query(StateFilter(CreateChannel.input_files), F.data == "cw:file:add")
async def on_file_add_more(cq: CallbackQuery, state: FSMContext):
    await cq.message.answer("Прикрепите следующий PDF-файл.")
    await cq.answer()


@router.callback_query(StateFilter(CreateChannel.input_files), F.data == "cw:files:done")
async def on_files_done(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_files_done")
    await state.update_data(step=4)
    await state.set_state(CreateChannel.input_wm)
    await _render_card(cq.bot, cq.message.chat.id, state, "Напишите короткий текст для водяного знака или нажмите ‘Пропустить’.", _kb_step4_initial())
    await cq.answer()


@router.callback_query(StateFilter(CreateChannel.input_files), F.data == "cw:files:skip")
async def on_files_skip(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_files_skip")
    await state.update_data(step=4)
    await state.set_state(CreateChannel.input_wm)
    await _render_card(cq.bot, cq.message.chat.id, state, "Шаг с файлами пропущен. Напишите текст водяного знака или ‘Пропустить’.", _kb_step4_initial())
    await cq.answer()


def _overlay_preview(preview_png: bytes, text: str) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(preview_png)).convert('RGB')
    img = apply_tiled_watermark(img, text=text, opacity=32, step=320, angle=-30)
    out = io.BytesIO(); img.save(out, format='PNG', optimize=True); out.seek(0)
    return out.read()


@router.message(StateFilter(CreateChannel.input_wm))
async def on_wm_text(m: Message, state: FSMContext):
    print("[wizard] on_wm_text")
    text = (m.text or '').strip()
    if not text:
        await m.answer("Пустой текст. Напишите текст водяного знака или нажмите ‘Пропустить’.")
        return
    d = await state.get_data()
    files = d.get('files') or []
    if files and files[-1].get('preview_png'):
        try:
            wprev = _overlay_preview(files[-1]['preview_png'], text)
            await m.answer_photo(BufferedInputFile(wprev, filename='wm_preview.png'), caption="Превью с водяным знаком", reply_markup=_kb_wm_preview())
        except Exception:
            await m.answer("Предпросмотр не удалось сгенерировать.", reply_markup=_kb_wm_preview())
    else:
        await m.answer("Текст принят. Предпросмотр доступен после загрузки файла.", reply_markup=_kb_wm_preview())
    await state.update_data(wm_text=text)


@router.callback_query(StateFilter(CreateChannel.input_wm), F.data == "cw:wm:clear")
async def on_wm_clear(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_wm_clear")
    await state.update_data(wm_text=None)
    await _render_card(cq.bot, cq.message.chat.id, state, "Текст водяного знака очищен. Напишите новый или ‘Пропустить’.", _kb_step4_initial())
    await cq.answer()


@router.callback_query(StateFilter(CreateChannel.input_wm), F.data == "cw:wm:skip")
async def on_wm_skip(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_wm_skip")
    await state.update_data(wm_text=None, wm_skipped=True)
    await state.set_state(CreateChannel.input_wm)
    # Все 4 пункта готовы — показываем финальные кнопки
    await _render_card(cq.bot, cq.message.chat.id, state, "Готово. Нажмите ‘Продолжить’ для выполнения задач.", _kb_final())
    await cq.answer()


@router.callback_query(StateFilter(CreateChannel.input_wm), F.data == "cw:wm:done")
async def on_wm_done(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_wm_done")
    await state.update_data(wm_skipped=False)
    await _render_card(cq.bot, cq.message.chat.id, state, "Готово. Нажмите ‘Продолжить’ для выполнения задач.", _kb_final())
    await cq.answer()


@router.callback_query(F.data == "cw:back")
async def on_back(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_back")
    d = await state.get_data(); step = int(d.get('step') or 1)
    step = max(1, step - 1)
    await state.update_data(step=step)
    if step == 1:
        await state.set_state(CreateChannel.input_title)
        await _render_card(cq.bot, cq.message.chat.id, state, "Напишите название для канала (пример: Иванов проект и смета)", _kb_step1())
    elif step == 2:
        await state.set_state(CreateChannel.input_avatar)
        await _render_card(cq.bot, cq.message.chat.id, state, "Добавьте аватарку или нажмите ‘Установить стандартную’ / ‘Пропустить’.", _kb_step2())
    elif step == 3:
        await state.set_state(CreateChannel.input_files)
        await _render_card(cq.bot, cq.message.chat.id, state, "Прикрепите PDF-файлы по очереди, как документ (файлом). Под превью будут кнопки.", _kb_step3())
    else:
        await state.set_state(CreateChannel.input_wm)
        await _render_card(cq.bot, cq.message.chat.id, state, "Напишите короткий текст для водяного знака или ‘Пропустить’.", _kb_step4_initial())
    await cq.answer()


@router.callback_query(F.data == "cw:cancel")
async def on_cancel(cq: CallbackQuery, state: FSMContext):
    print("[wizard] on_cancel")
    await state.clear()
    await cq.message.edit_text("Отменено.")
    await cq.answer()


@router.message(F.document)
async def on_any_document(m: Message, state: FSMContext):
    """Глобальный перехват документов: если мастер активен, маршрутизируем PDF."""
    st = await state.get_state()
    try:
        print(f"[wizard] catch-all document, state={st}")
    except Exception:
        pass
    if st == CreateChannel.input_files.state:
        return await on_file(m, state)
    if st == CreateChannel.input_avatar.state:
        return await on_file_during_avatar(m, state)
    # Иначе — не наш сценарий



async def _execute_job(bot: Bot, user_id: int, d: dict) -> tuple[int | None, str]:
    contractor_id = str(user_id)
    title = d.get('title') or f"Канал {user_id}"
    avatar_bytes = d.get('avatar_bytes') if d.get('avatar_state') == 'added' else None

    # 1) Создать канал от имени userbot и выдать боту права
    r = await userbot_post("/rooms/create", {"contractor_id": contractor_id, "title": title})
    channel_id = int(r["channel_id"])  # Telethon id
    chat_id = int(f"-100{abs(channel_id)}")
    me = await bot.get_me(); bot_username = me.username if me.username.startswith('@') else f"@{me.username}"
    await userbot_post("/rooms/add_bot_admin", {"contractor_id": contractor_id, "channel_id": channel_id, "bot_username": bot_username})

    # 2) Поставить аватарку (если выбрана)
    if avatar_bytes:
        try:
            await bot.set_chat_photo(chat_id=chat_id, photo=BufferedInputFile(avatar_bytes, filename="avatar.jpg"))
        except Exception as e:
            try:
                print(f"[wizard] set_chat_photo failed: {e}")
            except Exception:
                pass

    # 3) Сохранить проект в локальную БД
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO projects(contractor_id, title, channel_id) VALUES(?,?,?)", (contractor_id, title, chat_id))
        await conn.commit()

    # 4) Поставить задачи рендера/публикации для всех файлов
    from celery import Celery
    celery_app = Celery("bot", broker=os.getenv("REDIS_URL", "redis://redis:6379/0"))
    wm_text = d.get('wm_text') if not d.get('wm_skipped') else None
    for f in d.get('files') or []:
        celery_app.send_task("worker.tasks.render.process_and_publish_pdf", args=[chat_id, f['pdf_b64'], wm_text, f.get('out_name') or 'smeta.png'])

    # 5) Одноразовая бессрочная ссылка (1 человек)
    try:
        link = await bot.create_chat_invite_link(chat_id=chat_id, name=f"Invite for {title}", member_limit=1)
        invite = link.invite_link
    except Exception as e:
        invite = f"Не удалось создать ссылку: {e}"

    return chat_id, invite


@router.callback_query(F.data == "cw:final3")
async def on_final_go(cq: CallbackQuery, state: FSMContext, bot: Bot):
    print("[wizard] on_final_go")
    d = await state.get_data()
    chat_id, invite = await _execute_job(bot, cq.from_user.id, d)
    await state.clear()
    report = _card_text(d) + f"\n\nГотово. Канал создан: <code>{chat_id}</code>\nСсылка (1 пользователь):\n{invite}"
    try:
        await cq.message.edit_text(report, parse_mode='HTML', reply_markup=None, disable_web_page_preview=True)
    except Exception:
        await cq.message.answer(report, parse_mode='HTML', disable_web_page_preview=True)
    await cq.answer()




