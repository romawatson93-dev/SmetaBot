from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import Any, Dict, List, Optional
import httpx
import os
import redis

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
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CHANNEL_VIEWS_CACHE_TTL = int(os.getenv("CHANNEL_VIEWS_CACHE_TTL", "60"))

try:
    _views_cache = redis.from_url(REDIS_URL, decode_responses=True)
except Exception:
    _views_cache = None


async def _cache_get(key: str) -> Optional[str]:
    if _views_cache is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    try:
        return await loop.run_in_executor(None, partial(_views_cache.get, key))
    except Exception:
        return None


async def _cache_set(key: str, value: str, ttl: int) -> None:
    if _views_cache is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        await loop.run_in_executor(None, partial(_views_cache.setex, key, ttl, value))
    except Exception:
        return


def _normalize_views_dict(data: Dict[Any, Any]) -> Dict[int, int]:
    normalized: Dict[int, int] = {}
    for raw_key, raw_val in data.items():
        try:
            message_id = int(raw_key)
            normalized[message_id] = int(raw_val)
        except (TypeError, ValueError):
            continue
    return normalized


def _serialize_views_dict(data: Dict[int, int]) -> str:
    return json.dumps({str(k): int(v) for k, v in data.items()})


async def _cache_get_views(cache_key: str) -> Optional[Dict[int, int]]:
    raw = await _cache_get(cache_key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_views_dict(payload)


async def _refresh_channel_views(
    contractor_id: int,
    tg_chat_id: int,
    limit: int,
    cache_key: str,
) -> tuple[Dict[int, int], Optional[str]]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{USERBOT_URL}/rooms/get_views",
                json={
                    "contractor_id": str(contractor_id),
                    "channel_id": tg_chat_id,
                    "limit": limit,
                },
            )
    except Exception as exc:
        return {}, f"userbot request failed: {exc}"

    if response.status_code != 200:
        return {}, f"userbot HTTP {response.status_code}"

    try:
        payload = response.json()
    except ValueError as exc:
        return {}, f"userbot invalid JSON: {exc}"

    if not isinstance(payload, dict):
        return {}, "userbot response format error"

    if not payload.get("ok", False):
        return {}, payload.get("error") or "userbot error"

    views_raw = payload.get("views") or {}
    if not isinstance(views_raw, dict):
        views_raw = {}

    views = _normalize_views_dict(views_raw)
    if views:
        await _cache_set(cache_key, _serialize_views_dict(views), CHANNEL_VIEWS_CACHE_TTL)
    return views, None


def _schedule_views_refresh(contractor_id: int, tg_chat_id: int, limit: int, cache_key: str) -> None:
    async def _runner() -> None:
        await _refresh_channel_views(contractor_id, tg_chat_id, limit, cache_key)

    try:
        asyncio.create_task(_runner())
    except RuntimeError:
        pass


async def _fetch_channel_views(
    contractor_id: int,
    tg_chat_id: int,
    *,
    limit: int = 50,
    force_refresh: bool = False,
) -> tuple[Dict[int, int], Optional[str], bool]:
    cache_key = f"channel:views:{tg_chat_id}:{limit}"

    if not force_refresh:
        cached = await _cache_get_views(cache_key)
        if cached is not None:
            _schedule_views_refresh(contractor_id, tg_chat_id, limit, cache_key)
            return cached, None, True

    views, error = await _refresh_channel_views(contractor_id, tg_chat_id, limit, cache_key)
    return views, error, False


async def _fetch_channel_admins_userbot(
    contractor_id: int,
    tg_chat_id: int,
    *,
    limit: int = 50,
) -> tuple[list[dict], int, Optional[str]]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{USERBOT_URL}/rooms/get_admins",
                json={
                    "contractor_id": str(contractor_id),
                    "channel_id": abs(int(tg_chat_id)),
                    "limit": limit,
                },
            )
        if response.status_code != 200:
            return [], 0, f"userbot HTTP {response.status_code}"
        payload = response.json()
        if not isinstance(payload, dict):
            return [], 0, "userbot invalid payload"
        if not payload.get("ok"):
            return [], 0, payload.get("error") or "userbot error"
        admins = payload.get("admins") or []
        normalized: list[dict] = []
        for admin in admins:
            try:
                admin_id = int(admin.get("id"))
            except (TypeError, ValueError):
                continue
            normalized.append(
                {
                    "id": admin_id,
                    "username": admin.get("username"),
                    "full_name": admin.get("full_name"),
                }
            )
        return normalized, len(admins), None
    except Exception as exc:
        return [], 0, str(exc)


async def _collect_channel_admins(
    bot: Bot,
    contractor_id: Optional[int],
    tg_chat_id: int,
    *,
    display_limit: int = 10,
) -> tuple[list[dict], int, Optional[str]]:
    entries: list[dict] = []
    extra = 0
    error_text: Optional[str] = None

    try:
        admins = await asyncio.wait_for(bot.get_chat_administrators(tg_chat_id), timeout=3.0)
        total = len(admins)
        for admin in admins[:display_limit]:
            user = admin.user
            entries.append(
                {
                    "name": user.full_name or "Без имени",
                    "username": user.username,
                    "id": user.id,
                }
            )
        extra = max(0, total - display_limit)
        if entries:
            return entries, extra, None
    except Exception as exc:
        error_text = str(exc)

    if contractor_id is not None:
        fallback, total, fallback_error = await _fetch_channel_admins_userbot(contractor_id, tg_chat_id, limit=max(display_limit, 30))
        if fallback:
            for admin in fallback[:display_limit]:
                entries.append(
                    {
                        "name": admin.get("full_name") or "Без имени",
                        "username": admin.get("username"),
                        "id": admin.get("id"),
                    }
                )
            extra = max(0, total - display_limit)
            return entries, extra, None
        if fallback_error:
            error_text = fallback_error if not error_text else error_text

    return [], 0, error_text


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


async def _get_channel_detail(bot: Bot, project_id: int) -> Optional[Dict[str, Any]]:
    channel = await channels_service.get_channel_by_project(project_id)
    if not channel:
        return None

    channel_db_id = int(channel["id"])
    contractor_id = channel["contractor_id"]
    tg_chat_id = channel["tg_chat_id"]

    stats_task = asyncio.create_task(channels_service.get_channel_stats(channel_db_id))
    views_task = asyncio.create_task(_fetch_channel_views(contractor_id, tg_chat_id, limit=50))
    admins_task = asyncio.create_task(_collect_channel_admins(bot, contractor_id, tg_chat_id))

    views_data, error, _ = await views_task
    stats = await stats_task
    admin_entries, admins_extra, admin_error = await admins_task

    if error:
        print(f"Warning: failed to refresh channel views for {tg_chat_id}: {error}")

    if views_data:
        total_views = sum(views_data.values())
        merged_views = max(stats.get("views_total", 0), total_views)
        stats["views_total"] = merged_views
        stats["total_views"] = merged_views
        stats["recent_views"] = len(views_data)

    stats["views_map"] = views_data or {}
    stats["admins_entries"] = admin_entries
    stats["admins_extra"] = admins_extra
    stats["admins_error"] = admin_error

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

    

    raw_views_map = info.get("views_map") or {}

    views_map: Dict[int, int] = {}

    for key, value in raw_views_map.items():

        try:

            views_map[int(key)] = int(value)

        except (TypeError, ValueError):

            continue

    

    lines = [
        f"📌 {title}",
        f"ID: {tg_chat_id}",
        "",
    ]
    if info.get("username"):
        lines.append(f"@{info['username']}")
    if info.get("created_at"):
        lines.append(f"Создан: {info['created_at']:%Y-%m-%d %H:%M}")
    lines.append("")

    files_count = info.get("files_count", 0)
    views_total = info.get("views_total", 0)
    lines.append("📊 Статистика:")
    lines.append(f"• Файлов: {files_count}")
    lines.append(f"• Просмотров: {views_total}")
    if info.get("recent_views") is not None:
        lines.append(f"• Live: {info['recent_views']} сообщений (последние 50)")
    lines.append("")

    if channel_db_id:
        publications = await channels_service.get_channel_publications(channel_db_id, limit=10)
        if publications:
            lines.append("📂 Файлы (последние 10):")
            for pub in publications:
                file_name = pub.get("file_name", "Без названия")
                stored_views = int(pub.get("views") or 0)
                message_id = pub.get("message_id")
                live_views = views_map.get(int(message_id), 0) if message_id is not None else 0
                total_views = max(stored_views, live_views)
                posted_at = pub.get("posted_at")
                posted_suffix = f" ({posted_at:%Y-%m-%d})" if isinstance(posted_at, datetime) else ""
                lines.append(f"  • {file_name} ({total_views} просмотров){posted_suffix}")
            lines.append("")

    lines.append("👥 Участники:")

    admin_entries = info.get("admins_entries") or []
    extra_admins = int(info.get("admins_extra") or 0)
    admin_error = info.get("admins_error")

    if admin_entries:
        lines.append("  👮 Администраторы:")
        for entry in admin_entries:
            username = entry.get("username")
            username_display = f"@{username}" if username else "без username"
            lines.append(f"    • {entry.get('name') or 'Без имени'}")
            lines.append(f"      {username_display} (id: {entry.get('id')})")
        if extra_admins > 0:
            lines.append(f"    … и ещё {extra_admins}")
    else:
        message = "  👮 Администраторы: не удалось получить список"
        if admin_error:
            message += ""
        lines.append(message)

    if channel_db_id:
        clients = await channels_service.get_channel_clients(channel_db_id)
        if clients:
            active_clients = [c for c in clients if not c.get("blocked")]
            blocked_clients = [c for c in clients if c.get("blocked")]

            if active_clients:
                lines.append(f"\n  ✅ Активные ({len(active_clients)}):")
                for client in active_clients[:15]:
                    user_id = client.get("tg_user_id", "?")
                    username = client.get("username")
                    full_name = client.get("full_name")
                    if user_id not in (None, "?"):
                        try:
                            member = await bot.get_chat_member(tg_chat_id, int(user_id))
                            full_name = full_name or member.user.full_name
                            if not username and member.user.username:
                                username = member.user.username
                        except Exception:
                            pass
                    display_name = full_name or "Без имени"
                    username_display = f"@{username}" if username else "без username"
                    lines.append(f"    • {display_name}")
                    lines.append(f"      {username_display} (id: {user_id})")
                if len(active_clients) > 15:
                    lines.append(f"    … и ещё {len(active_clients) - 15}")

            if blocked_clients:
                lines.append(f"\n  🚫 Заблокированные ({len(blocked_clients)}):")
                for client in blocked_clients[:5]:
                    user_id = client.get("tg_user_id", "?")
                    username = client.get("username")
                    full_name = client.get("full_name")
                    username_display = f"@{username}" if username else "без username"
                    display_name = full_name or "Без имени"
                    lines.append(f"    • {display_name} ({username_display}, id: {user_id})")
                if len(blocked_clients) > 5:
                    lines.append(f"    … и ещё {len(blocked_clients) - 5}")
        else:
            lines.append("  • Клиентов пока нет")

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
        channel_info = await channels_service.get_channel_by_project(project_id)
        if not channel_info:
            return

        contractor_id = channel_info["contractor_id"]
        tg_chat_id = channel_info["tg_chat_id"]

        await _fetch_channel_views(contractor_id, tg_chat_id, force_refresh=True)

    except Exception as e:
        print(f"Error refreshing stats for channel {project_id}: {e}")


async def refresh_channel_stats(cq: CallbackQuery, state: FSMContext, project_id: int) -> None:
    """Обновляет статистику канала через userbot API с уведомлением пользователя."""
    try:
        await cq.answer("🔄 Обновляю статистику...")

        channel_info = await channels_service.get_channel_by_project(project_id)
        if not channel_info:
            await cq.answer("❌ Канал не найден", show_alert=True)
            return

        contractor_id = channel_info["contractor_id"]
        tg_chat_id = channel_info["tg_chat_id"]

        views, error, _ = await _fetch_channel_views(contractor_id, tg_chat_id, force_refresh=True)

        if error:
            await cq.answer(f"⚠️ {error}", show_alert=True)
            return

        await cq.answer(f"✅ Обновлено {len(views)} сообщений", show_alert=True)
        await show_channel_detail_view(cq, state, project_id, acknowledge=False)
    except Exception as e:
        await cq.answer(f"❌ Ошибка: {e}", show_alert=True)


async def show_channel_detail_view(
    cq: CallbackQuery,
    state: FSMContext,
    project_id: int,
    *,
    acknowledge: bool = True,
) -> None:
    info = await _get_channel_detail(cq.message.bot, project_id)
    if not info:
        await cq.answer("❌ Канал не найден", show_alert=True)
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
    if acknowledge:
        await cq.answer()


async def show_channels_overview_inline(bot: Bot, chat_id: int, state: FSMContext, contractor_id: int) -> None:
    """Служебная функция для обновления карточки каналов."""
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
    action = parts[1] if len(parts) > 1 else ""

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
        if len(parts) < 3:
            await cq.answer("Некорректные данные", show_alert=True)
            return
        project_id = int(parts[2])
        try:
            asyncio.create_task(refresh_channel_stats_silent(project_id))
        except RuntimeError:
            await refresh_channel_stats_silent(project_id)
        await show_channel_detail_view(cq, state, project_id)
    elif action == "goto":
        if len(parts) < 3:
            await cq.answer("Некорректные данные", show_alert=True)
            return
        project_id = int(parts[2])
        channel = await channels_service.get_channel_by_project(project_id)
        if not channel:
            await cq.answer("Канал не найден", show_alert=True)
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
        except Exception as exc:
            await cq.answer(f"Не удалось получить ссылку: {exc}", show_alert=True)
            return
    elif action == "refresh":
        if len(parts) < 3:
            await cq.answer("Некорректные данные", show_alert=True)
            return
        project_id = int(parts[2])
        await refresh_channel_stats(cq, state, project_id)
        return
    elif action == "noop":
        await cq.answer()
        return
    else:
        await cq.answer("Неизвестная команда", show_alert=True)
        return

    await cq.answer()
