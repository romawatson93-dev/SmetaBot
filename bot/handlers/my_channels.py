import os
import aiosqlite
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputFile
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types.input_file import BufferedInputFile

try:
    import fitz  # PyMuPDF
    _FITZ_OK = True
except Exception:
    _FITZ_OK = False
import base64 as _b64

router = Router()

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))

PAGE_SIZE = 6


async def _fetch_channels(contractor_id: str, *, limit: int | None = None, search: str | None = None) -> list[tuple[int, str, int]]:
    query = "SELECT id, title, channel_id FROM projects WHERE contractor_id=?"
    params: list[object] = [contractor_id]
    if search:
        query += " AND LOWER(title) LIKE ?"
        params.append(f"%{search.lower()}%")
    query += " ORDER BY id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    items: list[tuple[int, str, int]] = []
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(query, tuple(params)) as cur:
            async for row in cur:
                chan_id = int(row[2])
                items.append((int(row[0]), str(row[1]), chan_id))
    return items


async def _show_channels_list(
    m: Message,
    state: FSMContext,
    *,
    caption: str,
    limit: int | None = None,
    search: str | None = None,
) -> None:
    contractor_id = str(m.from_user.id)
    items = await _fetch_channels(contractor_id, limit=limit, search=search)
    if not items:
        if search:
            await m.answer(f"Каналы по запросу «{search}» не найдены.")
        else:
            await m.answer("У вас пока нет каналов. Создайте их через «Новый канал».")
        return

    titles = [title for _, title, _ in items]
    cids = [cid for _, _, cid in items]
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = 0
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    kb = _page_kb(titles[start:end], cids[start:end], page, pages)

    data = await state.get_data()
    mid = data.get("channels_mid")
    try:
        if mid:
            await m.bot.edit_message_text(text=caption, chat_id=m.chat.id, message_id=mid, reply_markup=kb)
            await state.update_data(
                channels_mid=mid,
                channels_titles=titles,
                channels_cids=cids,
                channels_pages=pages,
                channels_caption=caption,
            )
            return
    except Exception:
        pass

    sent = await m.answer(caption, reply_markup=kb)
    await state.update_data(
        channels_mid=sent.message_id,
        channels_titles=titles,
        channels_cids=cids,
        channels_pages=pages,
        channels_caption=caption,
    )


async def show_all_channels(m: Message, state: FSMContext) -> None:
    await _show_channels_list(m, state, caption="Список каналов — выберите запись:")


async def show_recent_channels(m: Message, state: FSMContext) -> None:
    await _show_channels_list(m, state, caption="Последние каналы — выберите запись:", limit=5)


async def start_channels_search(m: Message, state: FSMContext) -> None:
    await state.set_state(ChannelsSearch.waiting_query)
    await m.answer("Введите часть названия канала:")


async def show_channels_stats(m: Message, state: FSMContext) -> None:
    contractor_id = str(m.from_user.id)
    total = 0
    last_titles: list[str] = []
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT COUNT(*) FROM projects WHERE contractor_id=?", (contractor_id,)) as cur:
            row = await cur.fetchone()
            total = int(row[0]) if row and row[0] is not None else 0
        async with conn.execute("SELECT title FROM projects WHERE contractor_id=? ORDER BY id DESC LIMIT 5", (contractor_id,)) as cur:
            async for row in cur:
                last_titles.append(str(row[0]))
    lines = ["Статистика каналов:", f"- Всего каналов: {total}"]
    if last_titles:
        lines.append("- Последние: " + ", ".join(last_titles))
    else:
        lines.append("- Последние: отсутствуют")
    await m.answer("\n".join(lines))


def _page_kb(titles: list[str], cids: list[int], page: int, pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, (t, cid) in enumerate(zip(titles, cids)):
        rows.append([InlineKeyboardButton(text=f"📣 {t}", callback_data=f"ch_sel:{page}:{i}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"ch_page:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"Стр. {page+1}/{pages}", callback_data="noop"))
    if page+1 < pages:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"ch_page:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="Закрыть", callback_data="ch_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _detail_kb(cid: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть", callback_data=f"ch_open:{cid}:{page}")],
        [InlineKeyboardButton(text="Инвайт", callback_data=f"ch_inv:{cid}:{page}"), InlineKeyboardButton(text="Новая версия", callback_data=f"ch_new:{cid}:{page}")],
        [InlineKeyboardButton(text="← Список", callback_data=f"ch_page:{page}"), InlineKeyboardButton(text="Закрыть", callback_data="ch_close")],
    ])


@router.message(Command("channels"))
async def cmd_channels(m: Message, state: FSMContext):
    await show_all_channels(m, state)


@router.message(F.text == "Мои каналы")
async def msg_channels_button(m: Message, state: FSMContext):
    await show_all_channels(m, state)


class UploadNew(StatesGroup):
    waiting_file = State()


class ChannelsSearch(StatesGroup):
    waiting_query = State()


@router.message(ChannelsSearch.waiting_query)
async def channels_search_query(m: Message, state: FSMContext):
    query = (m.text or "").strip()
    if not query:
        await m.answer("Введите часть названия канала для поиска.")
        return
    await state.set_state(None)
    await _show_channels_list(m, state, caption=f"Результаты поиска по «{query}»:", search=query)


@router.callback_query(F.data.startswith("ch_page:"))
async def cb_page(cq: CallbackQuery, state: FSMContext):
    page = int(cq.data.split(":", 1)[1])
    data = await state.get_data()
    titles = data.get("channels_titles", [])
    cids = data.get("channels_cids", [])
    pages = max(1, int(data.get("channels_pages", 1) or 1))
    page = max(0, min(page, pages - 1))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    slice_titles = titles[start:end]
    slice_cids = cids[start:end]
    if not slice_titles and titles:
        page = 0
        start = 0
        end = PAGE_SIZE
        slice_titles = titles[start:end]
        slice_cids = cids[start:end]
    kb = _page_kb(slice_titles, slice_cids, page, pages)
    caption = data.get("channels_caption", "Список каналов — выберите запись:")
    await cq.message.edit_text(caption, reply_markup=kb)
    await cq.answer()


@router.callback_query(F.data.startswith("ch_sel:"))
async def cb_select(cq: CallbackQuery, state: FSMContext):
    _, page, idx = cq.data.split(":")
    page = int(page); idx = int(idx)
    data = await state.get_data()
    titles = data.get("channels_titles", [])
    cids = data.get("channels_cids", [])
    abs_index = page*PAGE_SIZE + idx
    if abs_index >= len(cids):
        await cq.answer("Не найдено", show_alert=True); return
    cid = cids[abs_index]; title = titles[abs_index]
    text = f"Проект: {title}\nВыберите действие:"
    await cq.message.edit_text(text, reply_markup=_detail_kb(cid, page))
    await cq.answer()


@router.callback_query(F.data.startswith("ch_open:"))
async def cb_open(cq: CallbackQuery, bot: Bot):
    parts = cq.data.split(":")
    cid = int(parts[1]); page = int(parts[2]) if len(parts) > 2 else 0
    try:
        link = await bot.create_chat_invite_link(chat_id=cid, name="Open", creates_join_request=False)
        await cq.message.edit_text(f"Ссылка для открытия:\n{link.invite_link}", reply_markup=_detail_kb(cid, page))
    except Exception as e:
        await cq.answer(f"Не удалось получить ссылку: {e}", show_alert=True)


@router.callback_query(F.data.startswith("ch_inv:"))
async def cb_inv(cq: CallbackQuery, bot: Bot):
    parts = cq.data.split(":")
    cid = int(parts[1]); page = int(parts[2]) if len(parts)>2 else 0
    try:
        link = await bot.create_chat_invite_link(chat_id=cid, name="Invite", creates_join_request=True)
        await cq.message.edit_text(f"🔗 Инвайт (join-request):\n{link.invite_link}\n👤 Разрешённых заявок: 1", reply_markup=_detail_kb(cid, page))
    except Exception as e:
        await cq.answer(f"Не удалось создать ссылку: {e}", show_alert=True)


@router.callback_query(F.data.startswith("ch_new:"))
async def cb_new(cq: CallbackQuery, state: FSMContext):
    parts = cq.data.split(":")
    cid = int(parts[1]); page = int(parts[2]) if len(parts)>2 else 0
    await state.set_state(UploadNew.waiting_file)
    await state.update_data(target_chat_id=cid, back_page=page)
    await cq.message.edit_text("Пришлите PDF/XLSX. Мы конвертируем в PNG 300 DPI с водяным знаком и опубликуем в канале.")
    await cq.answer()


@router.message(UploadNew.waiting_file, F.document)
async def on_new_file(m: Message, state: FSMContext):
    data = await state.get_data()
    cid = int(data.get("target_chat_id"))
    back_page = int(data.get("back_page", 0))
    doc = m.document
    filename = doc.file_name or "file.pdf"
    f = await m.bot.get_file(doc.file_id)
    raw = await m.bot.download_file(f.file_path)
    wm_text = (m.from_user.username or str(m.from_user.id))
    out_name = filename.rsplit(".",1)[0] + ".png"

    # Превью для PDF (первая страница, 150 DPI)
    if filename.lower().endswith(".pdf") and _FITZ_OK:
        try:
            doc_pdf = fitz.open(stream=raw, filetype="pdf")
            page = doc_pdf[0]
            zoom = 150/72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            preview = pix.tobytes("png")
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Опубликовать", callback_data="prev_pub"), InlineKeyboardButton(text="Отмена", callback_data="prev_cancel")]])
            sent = await m.answer_photo(BufferedInputFile(preview, filename="preview.png"), caption=f"Превью 1/{doc_pdf.page_count} — Опубликовать?", reply_markup=kb)
            await state.update_data(preview_mid=sent.message_id, file_b64=_b64.b64encode(raw).decode("ascii"), target_chat_id=cid, wm_text=wm_text, out_name=out_name, back_page=back_page)
            return
        except Exception:
            pass

    # Нет превью — сразу предложим публикацию
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Опубликовать", callback_data="prev_pub"), InlineKeyboardButton(text="Отмена", callback_data="prev_cancel")]])
    sent = await m.answer("Превью недоступно. Опубликовать в канал?", reply_markup=kb)
    await state.update_data(preview_mid=sent.message_id, file_b64=_b64.b64encode(raw).decode("ascii"), target_chat_id=cid, wm_text=wm_text, out_name=out_name, back_page=back_page)


@router.callback_query(F.data == "prev_cancel")
async def cb_prev_cancel(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    back_page = int(data.get("back_page", 0))
    cid = int(data.get("target_chat_id"))
    await state.clear()
    await cq.message.edit_text("Отменено.", reply_markup=_detail_kb(cid, back_page))
    await cq.answer()


@router.callback_query(F.data == "prev_pub")
async def cb_prev_pub(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    b64 = data.get("file_b64"); cid = int(data.get("target_chat_id")); wm_text = data.get("wm_text") or ""; out_name = data.get("out_name") or "smeta.png"
    back_page = int(data.get("back_page", 0))
    # Тонкий прогресс
    try:
        await cq.message.edit_caption(caption="⏳ Публикую в канал…", reply_markup=None)
    except Exception:
        try:
            await cq.message.edit_text("⏳ Публикую в канал…", reply_markup=None)
        except Exception:
            pass
    from celery import Celery
    celery_app = Celery("bot", broker=os.getenv("REDIS_URL", "redis://redis:6379/0"))
    celery_app.send_task("tasks.render.process_and_publish_pdf", args=[cid, b64, wm_text, out_name])
    try:
        await cq.message.edit_caption(caption="✅ Отправлено. Готовые PNG появятся в канале через ~5 сек.")
    except Exception:
        try:
            await cq.message.edit_text("✅ Отправлено. Готовые PNG появятся в канале через ~5 сек.")
        except Exception:
            pass
    await state.clear()
    # Вернёмся в карточку канала
    await cq.message.edit_text("Готово.", reply_markup=_detail_kb(cid, back_page))
    await cq.answer()


@router.message(F.document)
async def on_new_file_fallback(m: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("target_chat_id"):
        return
    await on_new_file(m, state)


@router.callback_query(F.data == "ch_close")
async def cb_close(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mid = data.get("channels_mid")
    if mid:
        try:
            await cq.message.delete()
        except Exception:
            pass
    await state.update_data(channels_mid=None)
    await cq.answer()
