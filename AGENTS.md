# 🤖 SmetaBot — актуальная архитектура агентов

## 🎯 Назначение
SmetaBot автоматизирует защищённую выдачу смет подрядчиков клиентам в Telegram. Сервис создаёт приватные каналы, конвертирует документы в PNG 300 DPI с обязательным водяным знаком и отслеживает активность. Ниже — актуальное описание ролей агентов и их взаимодействий по состоянию на текущий код.

## 🧩 Компоненты и обязанности
### Telegram Bot (`bot/`)
- aiogram 3.13 (`bot/main.py`) со встроенным хранилищем состояний; агрегирует все роутеры: меню, мастера, обработку документов, профили.
- Управляет пользовательским интерфейсом: стартовое меню, WebApp-авторизация, мастер создания каналов, разделы «Мои каналы»/«Рендер файлов»/«Профиль».
- Общается с userbot по HTTP (`userbot_post`, `userbot_get`), с Celery worker’ом через `bot/celery_client.py`, с Redis для временного хранения бинарей (`bot/storage.py`) и с PostgreSQL через `bot/services/db.py`.
- Ставит фоновые задачи рендера/публикации через Celery (`tasks.render.*`, `tasks.publish.send_document`), а также сохраняет метаданные публикаций в БД (таблицы `projects`, `channels`, `channel_files` и др.).
- Реализует dev-фолбэк для телефонного логина без WebApp (команды `/phone`, callback `conn_phone`).

### Userbot API (`userbot/`)
- FastAPI-приложение (`userbot/api.py`) поверх Telethon. Каждому подрядчику создаётся отдельная MTProto-сессия.
- Сессии сериализуются в StringSession и шифруются Fernet (`SESSION_SECRET`) перед сохранением на диск в `SESSIONS_DIR`.
- Эндпоинты:
  - `GET /session/status` (с опцией `verify=true` реконнектит клиент для проверки авторизации).
  - `POST /login/phone/start`, `/login/phone/confirm`, `/login/phone/2fa` — полный телефонный flow для dev/desktop.
  - `GET /webapp/login`, `GET /webapp/login2` — Mini App-страницы, отправляющие `session_ready` в бота.
  - `POST /rooms/create` — создаёт приватный канал, включает `ToggleNoForwardsRequest`.
  - `POST /rooms/add_bot_admin` — назначает бота администратором (права: постинг, инвайты).
  - `POST /rooms/set_photo` — устанавливает фото канала через Telethon (fallback после создания).
- Обрабатывает FloodWait через `with_floodwait`, дожидается распространения прав и закрывает клиенты после операций.

### Celery worker (`worker/`)
- Конфигурация в `worker/celery_app.py`: очереди `pdf`, `office`, `publish`, `preview`, единый брокер Redis.
- Основные задачи (`worker/tasks/render/__init__.py`):
  - Конвертация PDF (PyMuPDF), DOC/DOCX (LibreOffice → PDF → PNG), XLS/XLSX/ODS (LibreOffice + PyMuPDF) в PNG 300 DPI.
  - Применение тайлового водяного знака (`tasks.watermark.apply_tiled_watermark`, настройки из `common/watermark.py`).
  - Публикация в канал через Telegram Bot API (`tasks.publish.send_document`) с ретраями и `protect_content=True`.
  - Запись метаданных в PostgreSQL (`channels_service.record_channel_file`, снапшоты, учёт просмотров).
- Превью документов (`tasks.preview.generate_preview_task`) использует общую библиотеку `common/preview.py`, складывает превью/фуллрез в Redis с TTL.
- Метрики и агрегированная статистика публикаций — `worker/metrics.py` (Prometheus, автоотчёты в лог).

### Backend (`backend/`)
- Минимальное FastAPI-приложение (`backend/app/main.py`): `GET /health` и демо-страница WebApp логина.
- API для CRUD-процедур (contractors/rooms/documents/invites) планируется, но пока не перенесено из бота — обработчики в `bot/handlers/invite_manage.py` обращаются к незавершённому REST-контракту.

### Общие библиотеки и инфраструктура
- `common/preview.py` — высокоуровневая генерация превью: PyMuPDF, Pillow, LibreOffice, Ghostscript; умеет искать таблицы в Excel.
- `common/watermark.py` — загрузка параметров водяного знака из окружения.
- Redis: хранение исходных файлов (`pdf:<uuid>`, `doc:<uuid>`, `renderpng:<uuid>`), превью (`preview:<uuid>`); TTL управляется `SOURCE_BLOB_TTL`, `FULLRES_BLOB_TTL`.
- PostgreSQL: схема определяется миграциями `infra/migrations/0001_init.sql`, `0002_channels.sql`.
- Docker-файлы и compose-конфигурации лежат в `infra/docker/` и корневых `docker-compose*.yml`.

## 🔄 Ключевые процессы

### Онбординг подрядчика
1. Пользователь стартует бота (`/start` или кнопка «Открыть вход (WebApp)»). В prod требуется WebApp init data (`REQUIRE_INIT_DATA=true`).
2. Мини-приложение (`WEBAPP_URL` → `userbot/api.py::webapp_login`) проверяет существующую сессию, при необходимости запускает телефонный flow и отправляет `session_ready` обратно в чат.
3. Бот помечает состояние `init_ok` (`bot/handlers/webapp_gate.py`), повторно проверяет `/session/status?verify=true` и разблокирует остальное меню.
4. В dev-средах доступен прямой телефонный login (`/phone`, callback `conn_phone`), который проходит через `/login/phone/*` и обновляет меню без WebApp.

### Мастер создания защищённого канала
1. Раздел «🆕 Новый канал» (`bot/handlers/channel_wizard.py`) собирает название и аватарку (варианты: кастом, стандартная из профиля, пропустить).
2. Проверяется наличие авторизованной сессии. В dev при отсутствии предлагается кнопка «☎️ Подключить по телефону».
3. Userbot создаёт канал (`/rooms/create`), включает `noforwards/protected_content`, бот приглашает себя администратора (`/rooms/add_bot_admin`).
4. Если нужно, фото канала устанавливается через API бота либо `rooms/set_photo`.
5. Метаданные канала и проекта сохраняются в PostgreSQL (`channels_service.create_project_channel`).
6. Создаётся одноразовая ссылка (`Bot.create_chat_invite_link(member_limit=1)`), результат фиксируется в `project_invites`.
7. Пользователь получает чек-лист и ссылку на дальнейшие действия (рендер, ссылки).

### Меню и управление
- Главное меню (`bot/handlers/menu.py`) включает «Мои каналы», «Мои ссылки», «Рендер файлов», «Личный кабинет», «Помощь».
- «📢 Мои каналы» (`bot/handlers/my_channels.py`) агрегирует статистику: суммарные файлы/просмотры, последние проекты, поиск по названию, карточки каналов с выгрузкой списка администраторов через Telegram API.
- «👤 Личный кабинет» (`bot/handlers/profile.py`) позволяет загрузить стандартную аватарку для будущих каналов и проверить состояние сессии.
- Раздел «🔗 Мои ссылки» планируется завершить после появления REST эндпоинтов в backend; сейчас выдано текстовое объяснение/заглушка.

### Обработка и публикация документов
1. Подрядчик выбирает формат («📄 PDF → PNG», «📊 Excel → PNG», «📝 Word → PNG», «🖼️ PNG в канал») в `bot/handlers/render_pdf.py`.
2. Исходник загружается в чат; бот сохраняет файл в Redis (`store_blob`, префиксы `pdf`, `doc`, `xls`, `png`).
3. Для PDF/DOC/XLS вызывается превью (`tasks.preview.generate_preview_task`), пользователь может выбрать страницы/лист/таблицу, указать текст водяного знака (по умолчанию username подрядчика). Внутри задействованы per-user `asyncio.Lock`, чтобы не запускать несколько рендеров одновременно.
4. Выбранные страницы ставятся в очередь Celery:
   - `tasks.render.process_and_publish_pdf|doc|excel` извлекают файл (однократное чтение с удалением), рендерят PNG 300 DPI, накладывают watermark.
   - `tasks.render.process_and_publish_png` работает с готовыми PNG, при необходимости дополнительно нормализует DPI и водяной знак.
5. `tasks.publish.send_document` отправляет PNG в канал как `document` с `protect_content=True`, автоматически ретрая ошибки Telegram (403/429/400) и логируя метрики.
6. `worker/tasks/render._record_publication` заносит запись о сообщении (файл, caption, views) в таблицу `channel_files`; далее данные доступны в разделе «Мои каналы».

### Инвайты и защита доступа
- Создаваемые userbot’ом каналы всегда содержат `ToggleNoForwardsRequest` и `protected_content`.
- Все выдаваемые ссылки через `create_chat_invite_link` ограничены `member_limit=1`.
- `bot/services/projects.create_invite` хранит истину по одноразовым приглашениям; `bot/handlers/invite_manage.py` готов к управлению TTL/лимитами через backend (эндпоинты добавятся вместе с реализацией в FastAPI).
- В боте подчёркивается отправка файлов исключительно как `document`; `render`-пайплайн не допускает прямых форвардов.

### Статистика и наблюдаемость
- `channels_service.aggregate_contractor_stats` агрегирует количество каналов/файлов/просмотров для карточек.
- `channel_file_views` и `channel_snapshots` предназначены для накопления данных; `worker/tasks/stats.py` пока содержит заглушку `refresh_views_for_room`, которую нужно подключить к userbot для чтения `message.views`.
- Рабочее приложение экспонирует Prometheus-метрики (порт `METRICS_PORT`, по умолчанию 9464) для публикаций и ретраев.
- Redis TTL по умолчанию (`SOURCE_BLOB_TTL`/`FULLRES_BLOB_TTL`) защищает от накопления временных файлов.

## 🗃️ Хранилища и данные
- **PostgreSQL** (`infra/migrations`):
  - `projects`, `channels`, `project_invites`, `profiles` — управление объектами подрядчика.
  - `channel_files`, `channel_file_views`, `channel_snapshots`, `channel_members` — публикации и статистика.
  - Наследованные таблицы из ранних версий (`rooms`, `documents`, `messages`, `invites`, `audits`, `plans`) сохраняются для обратной совместимости и аудита.
- **Redis**:
  - Исходные файлы: `pdf:*`, `doc:*`, `xls:*`, `png:*`.
  - Полные PNG: `renderpng:*`.
  - Превью: `preview:*`.
  - Ключи удаляются после обработки (`_pop_storage_blob`, `delete_many`), удержание регулируется TTL.
- **Диск (`SESSIONS_DIR`)**: зашифрованные Telethon-сессии `<contractor_id>.session.enc`.
- **Prometheus multiprocess dir** — опционально (`PROMETHEUS_MULTIPROC_DIR`) для корректной работы метрик в нескольких воркерах.

## 🔐 Инварианты безопасности
- PDF не хранятся долговременно: после конвертации остаются только PNG и временные превью с ограниченным TTL.
- Все изображения публикуются с DPI 300 и водяным знаком (если текст пустой, watermark пропускается только явно).
- Публикации осуществляются как `document` + `protect_content=True`; каналы создаются с выключенным форвардингом.
- Каждому подрядчику соответствует отдельная MTProto-сессия; ключи шифрования задаются `SESSION_SECRET`, ротация возможна на уровне переменной окружения.
- Секреты и соединения настраиваются через `.env*`; логирование избегает чувствительных данных (код проверяет ошибки, но не сохраняет payload’ы).
- Все действия подрядчика/владельца планируется писать в `audits` (инфраструктура таблицы уже существует).

## ⚙️ Конфигурация и зависимости
- **Bot**: `BOT_TOKEN`, `BOT_USERNAME`, `DATABASE_URL`, `REDIS_URL`, `USERBOT_URL`, `WEBAPP_URL`, `CELERY_*`, `ENABLE_CELERY_PUBLISH`, `PREVIEW_TASK_TIMEOUT`, `SOURCE_BLOB_TTL`, `FULLRES_BLOB_TTL`, `ENV`/`APP_ENV`, `REQUIRE_INIT_DATA`, `TG_PROXY_URL`.
- **Worker**: использует те же `REDIS_URL`/`CELERY_*`, плюс `WATERMARK_*`, `PREVIEW_BLOB_TTL`, `FULLRES_BLOB_PREFIX`, `METRICS_PORT`, `PUBLISH_STATS_INTERVAL`/`PUBLISH_STATS_SAMPLE`.
- **Userbot**: `API_ID`, `API_HASH`, `SESSION_SECRET`, `SESSIONS_DIR`, `BOT_USERNAME`, `USERBOT_FLOODWAIT_FALLBACK`.
- **Backend**: `WEBAPP_URL`, `BOT_TOKEN` (для встраиваемого скрипта) — остальные эндпоинты добавятся позже.
- **Внешние бинарные зависимости**: LibreOffice (`libreoffice`/`soffice`), Ghostscript (`gs`/`gswin64c`), а также Python-пакеты PyMuPDF, Pillow, openpyxl, redis, asyncpg (см. `bot/requirements.txt`, `worker/requirements.txt`).
- Docker-компоуз (`docker-compose.yml` + overrides) поднимает PostgreSQL, Redis, backend, bot, userbot, worker.

## 🚧 Известные ограничения и TODO
- Backend пока предоставляет только health-check и демо WebApp; REST-контракт (contractors/projects/documents/invites) нужно перенести из бота.
- Статистика просмотров (`worker/tasks/stats.refresh_views_for_room`) ещё не интегрирована с реальными вызовами userbot’a.
- Раздел «🔗 Мои ссылки» и `bot/handlers/invite_manage.py` ожидают backend-эндпоинтов и доработки UI.
- Не реализованы квоты/тарифы (`plans`, `audits`, лимиты по подпискам) — таблицы есть, но бизнес-логика отложена.
- Требуется доработать массовое удаление временных ключей и мониторинг LibreOffice/Ghostscript ошибок в production.
