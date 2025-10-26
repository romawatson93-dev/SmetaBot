from __future__ import annotations
import os, uuid, base64, httpx
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.handlers.menu_common import BTN_SUBSCRIPTION
from bot.services.billing import billing  # твой сервис биллинга (заглушку можно оставить)
from bot.services.db import db

router = Router(name="subscription")

# ---------- UI helpers ----------
def ik_btn(text, data): return InlineKeyboardButton(text=text, callback_data=data)
def ik_kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)

# ---------- ЮKassa простая обёртка (без SDK) ----------
YKASSA_SHOP_ID  = os.getenv("YKASSA_SHOP_ID", "")
YKASSA_SECRET   = os.getenv("YKASSA_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://example.com")  # для возврата после оплаты

def _yk_headers(idempotence_key: str) -> dict:
    auth = base64.b64encode(f"{YKASSA_SHOP_ID}:{YKASSA_SECRET}".encode()).decode()
    return {
        "Authorization": f"Basic {auth}",
        "Idempotence-Key": idempotence_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

async def yk_create_payment(amount_rub: int, description: str, return_path: str, metadata: dict) -> dict:
    """
    Создаёт платёж и возвращает JSON ЮKassa.
    """
    body = {
        "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
        "capture": True,
        "description": description,
        "confirmation": {
            "type": "redirect",
            "return_url": f"{PUBLIC_BASE_URL.rstrip('/')}{return_path}",
        },
        "metadata": metadata,
    }
    key = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post("https://api.yookassa.ru/v3/payments", headers=_yk_headers(key), json=body)
        r.raise_for_status()
        return r.json()

async def yk_get_payment(payment_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=_yk_headers(str(uuid.uuid4())))
        r.raise_for_status()
        return r.json()

# ---------- UI рендер ----------
async def _subscription_card_text(user_id: int) -> str:
    # Получаем активную подписку (если её пока нет — ок, покажем FREE)
    sub = await billing.get_subscription(user_id)
    if not sub:
        plan = "FREE"
        ends = "—"
    else:
        plan = sub.get("plan_code", "UNKNOWN")
        ends = sub.get("valid_until", "—")

    # Дополнительно: счётчики (если есть в analytics).
    overview = await db.fetchrow(
        "SELECT * FROM analytics.profile_overview WHERE contractor_id = %s",
        (user_id,)
    )
    channels_total = overview.get("channels_total") if overview else None
    files_total    = overview.get("files_total") if overview else None
    views_total    = overview.get("views_total") if overview else None
    gifts_queue    = overview.get("gifts_queue") if overview else None
    ref_progress   = overview.get("ref_progress") if overview else None

    lines = [
        "<b>Моя подписка</b>",
        f"• План: <b>{plan}</b>",
        f"• Действует до: {ends}",
        "",
        "<b>Статистика</b>",
        f"• Каналов: {channels_total or 'н/д'}",
        f"• Файлов: {files_total or 'н/д'}",
        f"• Просмотров: {views_total or 'н/д'}",
        f"• Подарки в очереди: {gifts_queue or 0}",
        f"• Реферал-прогресс: {ref_progress or 'н/д'}",
    ]
    return "\n".join(lines)

def _subscription_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [ik_btn("💳 Продлить PRO — 590 ₽/мес", "sub:buy:pro")],
        [ik_btn("💼 Business — 1490 ₽/мес", "sub:buy:biz")],
        [ik_btn("📜 Тарифы", "sub:tariffs"), ik_btn("🔄 Проверить оплату", "sub:check")],
        [ik_btn("⬅️ Назад", "sub:back")],
    ]
    return ik_kb(rows)

# ---------- Handlers ----------
@router.message(F.text == BTN_SUBSCRIPTION)
async def open_subscription_card(m: types.Message, state: FSMContext):
    text = await _subscription_card_text(m.from_user.id)
    await m.answer(text, parse_mode="HTML", reply_markup=_subscription_keyboard())

@router.callback_query(F.data == "sub:tariffs")
async def show_tariffs(cq: types.CallbackQuery):
    text = (
        "<b>Тарифы</b>\n"
        "• FREE — 5 каналов, без редактирования каналов из бота\n"
        "• PRO — 590 ₽/мес: безлимит, все функции\n"
        "• Business — 1490 ₽/мес: всё из PRO + команда до 4 пользователей, CRM-интеграция\n"
    )
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=_subscription_keyboard())
    await cq.answer()

@router.callback_query(F.data.in_(["sub:buy:pro", "sub:buy:biz"]))
async def start_payment(cq: types.CallbackQuery):
    plan = "PRO" if cq.data.endswith("pro") else "BUSINESS"
    amount = 590 if plan == "PRO" else 1490

    # Мета на будущее (чтобы в webhook/проверке понять, что это за платёж)
    metadata = {
        "contractor_id": cq.from_user.id,
        "plan": plan,
        "period": "1m",
        "source": "bot",
    }
    try:
        data = await yk_create_payment(
            amount_rub=amount,
            description=f"{plan} — подписка на 1 месяц",
            return_path="/payments/return",  # можешь потом сделать страницу «Спасибо»
            metadata=metadata,
        )
        confirmation_url = data["confirmation"]["confirmation_url"]
        payment_id = data["id"]

        # При желании — сохранить в свою таблицу платежей (если уже есть)
        # await billing.save_payment(payment_id, cq.from_user.id, plan, amount)

        await cq.message.answer(f"Ссылка на оплату ({plan}):\n{confirmation_url}")
        await cq.answer("Открываю ссылку на оплату", show_alert=False)
    except httpx.HTTPError as e:
        await cq.answer("Не удалось создать платёж. Попробуйте позже.", show_alert=True)

@router.callback_query(F.data == "sub:check")
async def check_payment(cq: types.CallbackQuery):
    # Если сохраняешь payment_id — возьми последний незакрытый платёж из своей БД.
    # Здесь — просто текст с инструкцией.
    await cq.answer("После оплаты вернитесь в бот и нажмите 'Проверить оплату'. Автоприменение подарков/оплат выполняется раз в день.", show_alert=True)

@router.callback_query(F.data == "sub:back")
async def back_to_menu(cq: types.CallbackQuery):
    await cq.message.delete()
    await cq.answer()
