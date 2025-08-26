```markdown
# 🤖 AGENTS.md — Инструкции для AI-ассистентов (Codex, Copilot и др.)

## 📜 Общая концепция
Этот проект — Telegram SaaS-сервис.  
Цель: автоматизация защищённой выдачи смет в формате PDF (рендер в JPEG 300 DPI с водяным знаком) через приватные каналы Telegram.

## 📂 Основные модули
- `backend/` — FastAPI (REST API, авторизация, квоты, статистика).
- `bot/` — aiogram бот, интерфейс для владельца и подрядчиков.
- `userbot/` — Telethon/Pyrogram userbot, создаёт/настраивает приватные каналы, управляет инвайтами и защитой.
- `worker/` — Celery задачи: рендер PDF→JPEG, watermark, публикация, сбор статистики.
- `infra/` — Dockerfiles и миграции базы.
- `ci/` — CI/CD конфиги (GitHub Actions).

## ⚙️ Технологии
- Python 3.11+, aiogram, Telethon/Pyrogram, FastAPI, Celery, Redis, PostgreSQL, Docker Compose.
- Рендер PDF: PyMuPDF (fitz).
- Водяной знак: Pillow.

## 📑 Бизнес-правила
1. **PDF не хранить** — только JPEG версии.
2. **Рендер только в JPEG 300 DPI** (по умолчанию одна страница).
3. **Водяной знак обязателен** — тайловый паттерн с текстом подрядчика.
4. **Отправка только как файл (document)** + `protect_content=True`.
5. **Канал с noforwards/protected_content** — создаётся userbot-ом.
6. **Инвайт-ссылки одноразовые** (`member_limit=1`).
7. **Владелец** управляет подрядчиками, подписками, квотами, доступом.
8. **Статистика** = просмотры постов (`message.views`) + вступления/выходы.

## 🔧 Стиль кода
- PEP8, async/await (FastAPI, aiogram, Telethon).
- Каждое действие подрядчика/владельца должно быть логировано (`audits`).
- Конфиги через `.env`.

## 📌 Задачи для AI
- Генерация кода эндпоинтов FastAPI (CRUD для contractors/rooms/documents).
- Хендлеры aiogram (меню владельца, меню подрядчика, генерация invite links).
- Задачи Celery (рендер PDF→JPEG, watermark, отправка в Telegram).
- SQLAlchemy модели для схемы БД.
- Юнит-тесты (pytest, httpx).