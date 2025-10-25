from __future__ import annotations

from typing import Any, Dict, List, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services import channels as channels_service

router = Router()

MENU_PREFIX = "chmenu"
CHANNEL_PAGE_SIZE = 6


class ChannelsSearch(StatesGroup):
    waiting_query = State()


def _overview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗂 Последние 5 каналов", callback_data=f"{MENU_PREFIX}:recent")],
            [InlineKeyboardButton(text="📋 Все каналы", callback_data=f"{MENU_PREFIX}:all:0")],
            [InlineKeyboardButton(text="🔍 Поиск по названию", callback_data=f"{MENU_PREFIX}:search")],
        ]
    )


def _format_overview_text(stats: Dict[str, Any]) -> str:
    lines = [
        "📊 Статистика каналов:",
        f"• Количество каналов: {stats.get('total_channels', 0)}",
        f"• Опубликованных файлов: {stats.get('total_files', 0)}",
        f"• Суммарные просмотры: {stats.get('total_views', 0)}",
    ]
    recent = stats.get("recent_titles") or []
    if recent:
        lines.append("")
        lines.append("🗂 Последние каналы:")
        for title in recent:
            lines.append(f"  • {title}")
    return "\n".join(lines)


async def _ensure_card(
    *,
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
    message: Optional[Message] = None,
) -> None:
    data = await state.get_data()
    current_mid = data.get("channels_card_mid")

    if message and current_mid == message.message_id:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            await state.update_data(channels_card_mid=message.message_id)
            return
        except TelegramBadRequest:
            pass

    if current_mid:
        try:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=current_mid, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            try:
                await bot.delete_message(chat_id, current_mid)
            except Exception:
                pass

    sent = await bot.send_message(chat_id, text, reply_markup=keyboard)
    await state.update_data(channels_card_mid=sent.message_id)


async def _fetch_channels(
    contractor_id: int,
    *,
    limit: Optional[int] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows = await channels_service.list_channels(
        contractor_id,
        limit=limit or 100,
        search=search,
    )
    return [
        {
            "project_id": row["project_id"],
            "title": row["title"],
            "channel_id": int(row["channel_id"]),
        }
        for row in rows
    ]


async def _collect_overview_stats(contractor_id: int) -> Dict[str, Any]:
    aggregate = await channels_service.aggregate_contractor_stats(contractor_id)
    recent = await channels_service.list_channels(contractor_id, limit=5)
    aggregate["recent_titles"] = [row["title"] for row in recent]
    return aggregate


async def show_channels_overview(cq: CallbackQuery, state: FSMContext) -> None:
    contractor_id_int = cq.from_user.id
    stats = await _collect_overview_stats(contractor_id_int)
    text = _format_overview_text(stats)
    keyboard = _overview_keyboard()
    await _ensure_card(
        bot=cq.message.bot,
        state=state,
        chat_id=cq.message.chat.id,
        text=text,
        keyboard=keyboard,
        message=cq.message,
    )
    await state.update_data(channels_view={"type": "overview"})
    await cq.answer()


async def show_recent_channels_view(cq: CallbackQuery, state: FSMContext) -> None:
    contractor_id_int = cq.from_user.id
    items = await _fetch_channels(contractor_id_int, limit=5)
    if not items:
        text = "Каналы отсутствуют."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")]])
    else:
        text_lines = ["🗂 Последние каналы:", ""]
        for item in items:
            text_lines.append(f"• {item['title']}")
        text = "\n".join(text_lines)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"📂 {item['title']}", callback_data=f"{MENU_PREFIX}:detail:{item['project_id']}:recent:0")]
                for item in items
            ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")]]
        )
    await _ensure_card(
        bot=cq.message.bot,
        state=state,
        chat_id=cq.message.chat.id,
        text=text,
        keyboard=keyboard,
        message=cq.message,
    )
    await state.update_data(channels_view={"type": "recent"})
    await cq.answer()


async def show_all_channels_view(cq: CallbackQuery, state: FSMContext, page: int = 0) -> None:
    contractor_id_int = cq.from_user.id
    items = await _fetch_channels(contractor_id_int, limit=500)
    if not items:
        text = "Каналы отсутствуют."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")]])
    else:
        total_pages = max(1, (len(items) + CHANNEL_PAGE_SIZE - 1) // CHANNEL_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * CHANNEL_PAGE_SIZE
        subset = items[start : start + CHANNEL_PAGE_SIZE]

        text_lines = [f"📋 Все каналы — страница {page + 1}/{total_pages}", ""]
        text_lines.extend(f"• {item['title']}" for item in subset)
        text = "\n".join(text_lines)

        rows: List[List[InlineKeyboardButton]] = [
            [InlineKeyboardButton(text=f"📂 {item['title']}", callback_data=f"{MENU_PREFIX}:detail:{item['project_id']}:all:{page}")]
            for item in subset
        ]
        if total_pages > 1:
            nav_row: List[InlineKeyboardButton] = []
            if page > 0:
                nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"{MENU_PREFIX}:all:{page - 1}"))
            nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=f"{MENU_PREFIX}:noop"))
            if page + 1 < total_pages:
                nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"{MENU_PREFIX}:all:{page + 1}"))
            rows.append(nav_row)
        rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data=f"{MENU_PREFIX}:main")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    await _ensure_card(
        bot=cq.message.bot,
        state=state,
        chat_id=cq.message.chat.id,
        text=text,
        keyboard=keyboard,
        message=cq.message,
    )
    await state.update_data(channels_view={"type": "all", "page": page})
    await cq.answer()


async def start_channels_search_inline(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ChannelsSearch.waiting_query)
    text = "🔍 Поиск по названию. Отправьте часть названия канала."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")]])
    await _ensure_card(
        bot=cq.message.bot,
        state=state,
        chat_id=cq.message.chat.id,
        text=text,
        keyboard=keyboard,
        message=cq.message,
    )
    await state.update_data(channels_view={"type": "search"})
    await cq.answer("Введите поисковый запрос в чат")


async def _get_channel_detail(project_id: int) -> Optional[Dict[str, Any]]:
    channel = await channels_service.get_channel_by_project(project_id)
    if not channel:
        return None
    stats = await channels_service.get_channel_stats(int(channel["channel_id"]))
    return stats


async def _format_channel_detail(bot: Bot, info: Dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    project_id = info.get("project_id")
    title = info.get("title") or info.get("project_title") or "Канал"
    channel_id = int(info["channel_id"])

    lines = [
        "📌 Информация о канале:",
        f"• Название: {title}",
        f"• ID: {channel_id}",
    ]
    if info.get("username"):
        lines.append(f"• Username: @{info['username']}")
    if info.get("type"):
        lines.append(f"• Тип: {info['type']}")
    if info.get("created_at"):
        lines.append(f"• Создан: {info['created_at']:%Y-%m-%d %H:%M:%S}")
    if info.get("first_message_at"):
        lines.append(f"• Первый пост: {info['first_message_at']:%Y-%m-%d %H:%M:%S}")

    lines.append(f"• Опубликованных файлов: {info.get('files_count', 0)}")
    lines.append(f"• Суммарные просмотры: {info.get('views_total', 0)}")

    lines.append("")
    lines.append("Участники (администраторы):")
    try:
        admins = await bot.get_chat_administrators(channel_id)
        for admin in admins:
            user = admin.user
            username = f"@{user.username}" if user.username else "без username"
            lines.append(f"  • {user.full_name} ({username}, id={user.id})")
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound):
        lines.append("  • недоступно")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Перейти в канал", callback_data=f"{MENU_PREFIX}:goto:{project_id}")],
            [InlineKeyboardButton(text="✏️ Редактировать канал", callback_data=f"{MENU_PREFIX}:edit:{project_id}")],
            [InlineKeyboardButton(text="📎 Добавить/удалить файлы", callback_data=f"{MENU_PREFIX}:files:{project_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")],
        ]
    )
    return "\n".join(lines), keyboard


async def show_channel_detail_view(cq: CallbackQuery, state: FSMContext, project_id: int) -> None:
    info = await _get_channel_detail(project_id)
    if not info:
        await cq.answer("Канал не найден", show_alert=True)
        return
    text, keyboard = await _format_channel_detail(cq.message.bot, info)
    await _ensure_card(
        bot=cq.message.bot,
        state=state,
        chat_id=cq.message.chat.id,
        text=text,
        keyboard=keyboard,
        message=cq.message,
    )
    await state.update_data(channels_view={"type": "detail", "project_id": project_id})
    await cq.answer()


@router.message(ChannelsSearch.waiting_query)
async def handle_search_query(m: Message, state: FSMContext) -> None:
    query = (m.text or "").strip()
    if not query:
        await m.answer("Введите непустой запрос.")
        return
    await state.set_state(None)
    contractor_id_int = m.from_user.id
    items = await _fetch_channels(contractor_id_int, search=query, limit=50)
    if not items:
        text = f"Результаты поиска по «{query}» отсутствуют."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")]])
    else:
        text_lines = [f"🔍 Результаты поиска по «{query}»:"] + [f"• {item['title']}" for item in items]
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"📂 {item['title']}", callback_data=f"{MENU_PREFIX}:detail:{item['project_id']}:search:0")]
                for item in items
            ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")]]
        )
        text = "\n".join(text_lines)
    await _ensure_card(
        bot=m.bot,
        state=state,
        chat_id=m.chat.id,
        text=text,
        keyboard=keyboard,
    )
    await state.update_data(channels_view={"type": "search_results", "query": query})


@router.callback_query(F.data.startswith(f"{MENU_PREFIX}:"))
async def channels_menu_callback(cq: CallbackQuery, state: FSMContext) -> None:
    parts = cq.data.split(":")
    action = parts[1]
    if action == "main":
        await show_channels_overview(cq, state)
    elif action == "recent":
        await show_recent_channels_view(cq, state)
    elif action == "all":
        page = int(parts[2]) if len(parts) > 2 else 0
        await show_all_channels_view(cq, state, page)
    elif action == "search":
        await start_channels_search_inline(cq, state)
    elif action == "detail":
        project_id = int(parts[2])
        await show_channel_detail_view(cq, state, project_id)
    elif action == "goto":
        project_id = int(parts[2])
        channel = await channels_service.get_channel_by_project(project_id)
        if not channel:
            await cq.answer("Канал недоступен", show_alert=True)
            return
        channel_id = int(channel["channel_id"])
        title = channel.get("title") or "Канал"
        try:
            chat = await cq.bot.get_chat(channel_id)
            if chat.username:
                url = f"https://t.me/{chat.username}"
            else:
                url = await cq.bot.export_chat_invite_link(channel_id)
            await cq.message.answer(f"Ссылка на канал {title}:\n{url}")
            await cq.answer()
        except Exception as exc:
            await cq.answer(f"Не удалось получить ссылку: {exc}", show_alert=True)
    elif action in {"edit", "files"}:
        await cq.answer("Функция находится в разработке", show_alert=True)
    elif action == "noop":
        await cq.answer()
    else:
        await cq.answer("Неизвестное действие", show_alert=True)
