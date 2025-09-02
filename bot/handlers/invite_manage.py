from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import httpx, os, time
router = Router()
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

def kb(pid: int, state: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Отозвать", callback_data=f"inv:revoke:{pid}")],
        [InlineKeyboardButton(text="↻ Регенерировать", callback_data=f"inv:regen:{pid}")],
        [
            InlineKeyboardButton(text="TTL 24ч", callback_data=f"inv:ttl:{pid}:24h"),
            InlineKeyboardButton(text="3д",     callback_data=f"inv:ttl:{pid}:3d"),
            InlineKeyboardButton(text="7д",     callback_data=f"inv:ttl:{pid}:7d"),
            InlineKeyboardButton(text="∞",      callback_data=f"inv:ttl:{pid}:inf"),
        ],
        [
            InlineKeyboardButton(text="Лимит 1", callback_data=f"inv:lim:{pid}:1"),
            InlineKeyboardButton(text="2",       callback_data=f"inv:lim:{pid}:2"),
            InlineKeyboardButton(text="5",       callback_data=f"inv:lim:{pid}:5"),
            InlineKeyboardButton(text="10",      callback_data=f"inv:lim:{pid}:10"),
        ],
    ])

@router.message(F.text.startswith("Управление ссылкой "))
async def open_manage(msg: Message):
    project_id = int(msg.text.split()[-1])
    async with httpx.AsyncClient(timeout=10) as x:
        r = await x.get(f"{BACKEND_URL}/projects/{project_id}/invite")
        data = r.json()
    txt = (
        f"Проект #{project_id}\n"
        f"Ссылка: {data.get('invite_link') or '—'}\n"
        f"Статус: {'отозвана' if data.get('revoked') else 'активна'}\n"
        f"Одобрено: {data.get('approved_count',0)} из {data.get('allowed_approvals','∞')}\n"
        f"TTL: {'∞' if not data.get('expire_at') else time.strftime('%Y-%m-%d %H:%M', time.gmtime(data['expire_at']))}"
    )
    await msg.answer(txt, reply_markup=kb(project_id, data))

@router.callback_query(F.data.startswith("inv:"))
async def manage_cb(cb: CallbackQuery):
    _, action, pid, *rest = cb.data.split(":")
    project_id = int(pid)
    async with httpx.AsyncClient(timeout=15) as x:
        if action == "revoke":
            await x.post(f"{BACKEND_URL}/projects/{project_id}/invite/revoke")
        elif action == "regen":
            pr = (await x.get(f"{BACKEND_URL}/projects/{project_id}")).json()
            link = await cb.message.bot.create_chat_invite_link(chat_id=pr["chat_id"], creates_join_request=True, name="primary")
            await x.post(f"{BACKEND_URL}/projects/{project_id}/invite/regenerate", json={"invite_link": link.invite_link})
        elif action == "ttl":
            arg = rest[0]
            expire = None
            if arg != "inf":
                hours = {"24h":24, "3d":72, "7d":168}[arg]
                expire = int(time.time() + hours*3600)
            # обновляем TTL у ТГ-ссылки (если не отозвана)
            inv = (await x.get(f"{BACKEND_URL}/projects/{project_id}/invite")).json()
            if inv.get("invite_link") and not inv.get("revoked"):
                await cb.message.bot.edit_chat_invite_link(
                    chat_id=inv["chat_id"],
                    invite_link=inv["invite_link"],
                    expire_date=expire,
                    # creates_join_request=True  # если хотим закрепить флаг
                )
            await x.put(f"{BACKEND_URL}/projects/{project_id}/invite", json={"expire_at": expire})
        elif action == "lim":
            lim = int(rest[0])
            await x.put(f"{BACKEND_URL}/projects/{project_id}/invite", json={"allowed_approvals": lim})

        # перерисуем карточку
        r = await x.get(f"{BACKEND_URL}/projects/{project_id}/invite")
        data = r.json()
    await cb.message.edit_reply_markup(reply_markup=kb(project_id, data))
    await cb.answer("Готово")
