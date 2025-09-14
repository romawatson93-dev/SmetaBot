# SmetaBot — Session Notes (dev)

## Что сделано
- Auth через Mini App (BotFather), без дублирующей кнопки в чате.
- Меню: Reply‑клавиатура; одно сообщение «Меню» редактируется.
- «Мои каналы»: интерактивная карточка с пагинацией; выбор проекта → действия: Открыть, Инвайт, Новая версия, ← Список, Закрыть.
- «Новый канал»: визард 3 шага — Название → Аватар → Загрузка файлов (в этом же окне).
- Загрузка PDF/XLSX: превью для PDF (150 DPI) → Опубликовать → PNG 300 DPI + водяной знак в канал (Celery/worker).
- Worker переделан на Celery; бот настроен на REDIS_URL из compose.
- WebApp: добавлен маршрут `/webapp/login2` с fallback (deep‑link в бота при отсутствии initData.user).

## Как поднять dev
- Запуск:
  - `make dev-up`
  - или: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
- Проверка origin:
  - `http://localhost:8001/health` → `{ "ok": true }`
  - `http://localhost:8001/webapp/login2` — страница Mini App
- Туннель:
  - `cloudflared tunnel --protocol http2 --edge-ip-version 4 --url http://localhost:8001`
- Обновить Mini App URL (dev):
  - `.env.dev`: `WEBAPP_URL=https://<your>.trycloudflare.com/webapp/login2`
  - В BotFather у дев‑бота Mini App URL — тот же `/webapp/login2`
- Перезапуск бота после смены URL: `make dev-up` (или `docker compose ... up -d bot`)

## Быстрые сценарии
- Вход: /start → «Проверить подключение». Мини‑апп только из BotFather (иконка Mini App).
- Новый канал: «Новый канал» → Название → (опц.) Аватар → шаг загрузки → отправьте PDF → превью → «Опубликовать» → PNG в канале.
- Мои каналы: «Мои каналы» → выберите проект → действия (Открыть/Инвайт/Новая версия). «Закрыть» удаляет карточку.

## Заметки по UX
- Чат «не ползёт»: карточки/меню редактируются на месте. Пользовательские документы бот удалять не может (ограничение Telegram), поэтому файл‑сообщение остаётся в ленте.
- Для приватных каналов «Открыть» даёт временный инвайт; для public можно заменить на t.me/<username> (при наличии).

## Изменённые/ключевые файлы
- Бот: `bot/handlers/reply_menu.py`, `bot/handlers/my_channels.py`, `bot/handlers/channel_wizard.py`, `bot/handlers/webapp.py`
- Юзербот: `userbot/api.py` (маршрут `/webapp/login2`)
- Воркер: `worker.Dockerfile`, `worker/__init__.py`, `worker/tasks/__init__.py`
- Compose/утилиты: `docker-compose.dev.yml`, `docker-compose.yml` (REDIS для бота), `Makefile` (dev‑цели)

## Подсказки
- Логи: `make dev-logs-bot`, `make dev-logs-userbot`, `make dev-ps`
- Проверка публикации: после «Опубликовать» PNG появляются в канале ~за 5 сек (300 DPI, watermark‑pattern).

## TODO / Следующие шаги
- Owner‑меню: реализация пунктов (Подрядчики, Планы/Оплата, Глобальная статистика, Синхронизация ссылок).
- Политика инвайтов: авто‑обработка «чужих» ссылок (revocation/decline) и сторож по chat_member.
- Локализация: убрать «кракозябры» из старых строк (оставшиеся в некоторых хендлерах).
- XLSX: опциональный рендер/превью через LibreOffice headless → PDF → превью.
- «Открыть» для публичных каналов: прямые ссылки вместо инвайтов.

## ENV (dev)
- `WEBAPP_URL=https://<trycloudflare>/webapp/login2`
- `OWNER_IDS=...` (чтобы видеть Owner‑меню)
- Бот в compose говорит с `userbot:8001` и `redis://redis:6379/0`

