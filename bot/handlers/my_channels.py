from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx
import os

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import bot.services.channels as channels_service

router = Router()

MENU_PREFIX = "chmenu"
CHANNEL_PAGE_SIZE = 6
USERBOT_URL = os.getenv("USERBOT_URL", "http://userbot:8001")


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
        f"• Количество каналов: {stats.get('channels_count', 0)}",
        f"• Опубликованных файлов: {stats.get('files_count', 0)}",
        f"• Суммарные просмотры: {stats.get('views_total', 0)}",
        f"• Активных инвайтов: {stats.get('active_invites', 0)}",
        f"• Всего клиентов: {stats.get('clients_total', 0)}",
        f"• Заблокированных: {stats.get('blocked_clients', 0)}",
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


async def _collect_overview_stats(contractor_id: int, username: str = None, full_name: str = None) -> Dict[str, Any]:
    # Убеждаемся, что подрядчик зарегистрирован в новой схеме
    from bot.services import contractors
    await contractors.get_or_create_by_tg(
        contractor_id,
        username=username,
        full_name=full_name,
    )
    
    aggregate = await channels_service.aggregate_contractor_stats(contractor_id)
    recent = await channels_service.list_channels(contractor_id, limit=5)
    aggregate["recent_titles"] = [row["title"] for row in recent]
    return aggregate


async def show_channels_overview(cq: CallbackQuery, state: FSMContext) -> None:
    contractor_id_int = cq.from_user.id
    stats = await _collect_overview_stats(
        contractor_id_int,
        username=cq.from_user.username,
        full_name=cq.from_user.full_name,
    )
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
    
    # Получаем базовую статистику из БД
    stats = await channels_service.get_channel_stats(int(channel["id"]))
    
    # Получаем актуальные просмотры через userbot API
    try:
        contractor_id = channel["contractor_id"]
        tg_chat_id = channel["tg_chat_id"]
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{USERBOT_URL}/rooms/get_views",
                json={
                    "contractor_id": str(contractor_id),
                    "channel_id": tg_chat_id,
                    "limit": 50
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    views_data = result.get("views", {})
                    # Обновляем статистику актуальными просмотрами
                    total_views = sum(views_data.values())
                    stats["total_views"] = total_views
                    stats["recent_views"] = len(views_data)
                    
    except Exception as e:
        print(f"Error getting real-time views: {e}")
        # Используем статистику из БД как fallback
    
    return stats


async def _format_channel_detail(bot: Bot, info: Dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    from datetime import datetime
    
    project_id = info.get("project_id")
    title = info.get("title") or info.get("project_title") or "Канал"
    # channel_id в info - это tg_chat_id из Telegram
    tg_chat_id = int(info.get("channel_id", 0))

    # Получаем БД ID канала
    channel_row = await channels_service.get_channel_by_project(project_id)
    channel_db_id = channel_row.get("id") if channel_row else None
    
    lines = [
        f"📌 {title}",
        f"ID: {tg_chat_id}",
        "",
    ]
    if info.get("username"):
        lines.append(f"@: @{info['username']}")
    if info.get("created_at"):
        lines.append(f"Создан: {info['created_at']:%Y-%m-%d %H:%M}")
    lines.append("")

    # Статистика файлов
    files_count = info.get("files_count", 0)
    views_total = info.get("views_total", 0)
    lines.append(f"📊 Статистика:")
    lines.append(f"• Файлов: {files_count}")
    lines.append(f"• Просмотров: {views_total}")
    lines.append("")

    # Список файлов с просмотрами
    if channel_db_id:
        publications = await channels_service.get_channel_publications(channel_db_id, limit=10)
        if publications:
            lines.append("📁 Файлы (последние 10):")
            for pub in publications:
                file_name = pub.get("file_name", "без названия")
                views = pub.get("views", 0)
                lines.append(f"  • {file_name} ({views} просмотров)")
            lines.append("")
    
    # Список клиентов (админы + участники)
    lines.append("👥 Участники:")
    
    # Администраторы из Telegram
    try:
        admins = await bot.get_chat_administrators(tg_chat_id)
        lines.append("  🔹 Администраторы:")
        for admin in admins[:10]:  # ограничиваем 10 первыми
            user = admin.user
            username = f"@{user.username}" if user.username else "без username"
            lines.append(f"     • {user.full_name or 'Без имени'}")
            lines.append(f"       {username} (id: {user.id})")
        if len(admins) > 10:
            lines.append(f"     ... и еще {len(admins) - 10}")
    except Exception as e:
        lines.append("  🔹 Администраторы: недоступно")
    
    # Клиенты, присоединившиеся по ссылкам
    if channel_db_id:
        clients = await channels_service.get_channel_clients(channel_db_id)
        if clients:
            active_clients = [c for c in clients if not c.get("blocked")]
            blocked_clients = [c for c in clients if c.get("blocked")]
            
            if active_clients:
                lines.append(f"\n  🔹 Участники ({len(active_clients)}):")
                for client in active_clients[:15]:  # показываем первых 15
                    username = f"@{client['username']}" if client.get("username") else "без username"
                    full_name = client.get("full_name") or "Без имени"
                    user_id = client.get("tg_user_id", "?")
                    lines.append(f"     • {full_name}")
                    lines.append(f"       {username} (id: {user_id})")
                if len(active_clients) > 15:
                    lines.append(f"     ... и еще {len(active_clients) - 15}")
            
            if blocked_clients:
                lines.append(f"\n  🔸 Заблокированные ({len(blocked_clients)}):")
                for client in blocked_clients[:5]:  # показываем первых 5
                    username = f"@{client['username']}" if client.get("username") else "без username"
                    full_name = client.get("full_name") or "Без имени"
                    user_id = client.get("tg_user_id", "?")
                    lines.append(f"     • {full_name} ({username}, id: {user_id})")
                if len(blocked_clients) > 5:
                    lines.append(f"     ... и еще {len(blocked_clients) - 5}")

    # Обрезаем сообщение, если слишком длинное (Telegram имеет лимит 4096 символов)
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "..."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{MENU_PREFIX}:main")],
        ]
    )
    return text, keyboard


async def refresh_channel_stats_silent(project_id: int) -> None:
    """Тихо обновляет статистику канала через userbot API."""
    try:
        # Получаем информацию о канале
        channel_info = await channels_service.get_channel_by_project(project_id)
        if not channel_info:
            return
        
        contractor_id = channel_info["contractor_id"]
        tg_chat_id = channel_info["tg_chat_id"]
        
        # Вызываем userbot API для обновления статистики
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{USERBOT_URL}/rooms/refresh_stats",
                json={
                    "contractor_id": str(contractor_id),
                    "channel_id": tg_chat_id
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "ok":
                    # Статистика обновлена успешно
                    pass
            
    except Exception as e:
        # Логируем ошибку, но не показываем пользователю
        print(f"Error refreshing stats for channel {project_id}: {e}")

async def refresh_channel_stats(cq: CallbackQuery, state: FSMContext, project_id: int) -> None:
    """Обновляет статистику канала через userbot API с уведомлением пользователя."""
    try:
        await cq.answer("🔄 Обновляю статистику...")
        
        # Получаем информацию о канале
        channel_info = await channels_service.get_channel_by_project(project_id)
        if not channel_info:
            await cq.answer("❌ Канал не найден", show_alert=True)
            return
        
        contractor_id = channel_info["contractor_id"]
        tg_chat_id = channel_info["tg_chat_id"]
        
        # Вызываем userbot API для обновления статистики
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{USERBOT_URL}/rooms/refresh_stats",
                json={
                    "contractor_id": str(contractor_id),
                    "channel_id": tg_chat_id
                }
            )
            
            if response.status_code != 200:
                await cq.answer(f"❌ Ошибка API: {response.status_code}", show_alert=True)
                return
            
            result = response.json()
            
            if result.get("status") == "ok":
                updated_count = result.get("updated", 0)
                await cq.answer(f"✅ Обновлено {updated_count} сообщений", show_alert=True)
                
                # Обновляем отображение канала
                await show_channel_detail_view(cq, state, project_id)
            else:
                error = result.get("error", "Неизвестная ошибка")
                await cq.answer(f"❌ Ошибка: {error}", show_alert=True)
            
    except Exception as e:
        await cq.answer(f"❌ Ошибка обновления: {str(e)}", show_alert=True)


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


async def show_channels_overview_inline(bot: Bot, chat_id: int, state: FSMContext, contractor_id: int) -> None:
    """Вспомогательная функция для обновления карточки каналов."""
    stats = await _collect_overview_stats(
        contractor_id,
        username=None,
        full_name=None,
    )
    text = _format_overview_text(stats)
    keyboard = _overview_keyboard()
    await _ensure_card(
        bot=bot,
        state=state,
        chat_id=chat_id,
        text=text,
        keyboard=keyboard,
    )
    await state.update_data(channels_view={"type": "overview"})



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
        # Автоматически обновляем статистику при выборе канала
        await refresh_channel_stats_silent(project_id)
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
