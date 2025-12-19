# 📊 SmetaBot — Схемы проекта и сценарии

## 📑 Содержание

1. [Архитектура системы](#1-архитектура-системы)
2. [Схема авторизации через QR-код](#2-схема-авторизации-через-qr-код)
3. [Сценарий: Первый запуск подрядчика](#3-сценарий-первый-запуск-подрядчика)
4. [Сценарий: Создание канала](#4-сценарий-создание-канала)
5. [Сценарий: Публикация документа](#5-сценарий-публикация-документа)
6. [Сценарий: Клиент получает доступ](#6-сценарий-клиент-получает-доступ)
7. [Поток данных: Обработка документа](#7-поток-данных-обработка-документа)
8. [Схема базы данных](#8-схема-базы-данных)
9. [Инфраструктура развёртывания](#9-инфраструктура-развёртывания)
10. [Схема взаимодействия компонентов](#10-схема-взаимодействия-компонентов)

---

## 1. Архитектура системы

### 1.1. Общая архитектура

```mermaid
graph TB
    subgraph "Пользователи"
        Contractor[Подрядчик<br/>Telegram]
        Client[Клиент<br/>Telegram]
    end

    subgraph "Frontend Layer"
        Bot[Telegram Bot<br/>aiogram]
        WebApp[WebApp<br/>HTML/JS]
    end

    subgraph "API Layer"
        UserbotAPI[Userbot API<br/>FastAPI + Telethon]
        BackendAPI[Backend API<br/>FastAPI]
    end

    subgraph "Processing Layer"
        WorkerPDF[Celery Worker<br/>PDF Queue]
        WorkerOffice[Celery Worker<br/>Office Queue]
        WorkerPublish[Celery Worker<br/>Publish Queue]
        WorkerPreview[Celery Worker<br/>Preview Queue]
    end

    subgraph "Storage Layer"
        Redis[(Redis<br/>Queue + Cache)]
        PostgreSQL[(PostgreSQL<br/>Database)]
        Sessions[File System<br/>Encrypted Sessions]
    end

    subgraph "External Services"
        TelegramAPI[Telegram API<br/>Bot + MTProto]
        LibreOffice[LibreOffice<br/>Document Converter]
    end

    Contractor -->|Команды| Bot
    Client -->|Join Request| Bot
    Contractor -->|WebApp| WebApp
    WebApp -->|HTTP| UserbotAPI
    Bot -->|HTTP| UserbotAPI
    Bot -->|HTTP| BackendAPI
    Bot -->|Tasks| Redis
    Bot -->|Queries| PostgreSQL

    UserbotAPI -->|MTProto| TelegramAPI
    UserbotAPI -->|Read/Write| Sessions
    UserbotAPI -->|Queries| PostgreSQL

    WorkerPDF -->|Read| Redis
    WorkerPDF -->|Write| PostgreSQL
    WorkerPDF -->|Publish| TelegramAPI
    WorkerOffice -->|Read| Redis
    WorkerOffice -->|Write| PostgreSQL
    WorkerOffice -->|Convert| LibreOffice
    WorkerOffice -->|Publish| TelegramAPI
    WorkerPublish -->|Read| Redis
    WorkerPublish -->|Write| PostgreSQL
    WorkerPublish -->|Publish| TelegramAPI
    WorkerPreview -->|Read| Redis
    WorkerPreview -->|Write| Redis

    Redis -->|Tasks| WorkerPDF
    Redis -->|Tasks| WorkerOffice
    Redis -->|Tasks| WorkerPublish
    Redis -->|Tasks| WorkerPreview

    style Bot fill:#2ea6ff,color:#fff
    style UserbotAPI fill:#00d4aa,color:#fff
    style BackendAPI fill:#00d4aa,color:#fff
    style Redis fill:#dc382d,color:#fff
    style PostgreSQL fill:#336791,color:#fff
```

### 1.2. Компоненты и их взаимодействие

```mermaid
graph LR
    subgraph "Bot Service"
        BotMain[main.py]
        Handlers[handlers/]
        Services[services/]
        Storage[storage.py]
    end

    subgraph "Userbot Service"
        UserbotAPI[api.py]
        Login[login.py]
        TGOps[tg_ops/]
    end

    subgraph "Worker Service"
        CeleryApp[celery_app.py]
        RenderTasks[tasks/render/]
        PublishTasks[tasks/publish.py]
        PreviewTasks[tasks/preview.py]
        StatsTasks[tasks/stats.py]
    end

    subgraph "Common Libraries"
        PreviewLib[common/preview.py]
        WatermarkLib[common/watermark.py]
    end

    BotMain --> Handlers
    Handlers --> Services
    Services --> Storage
    Handlers -->|HTTP| UserbotAPI
    Handlers -->|Tasks| CeleryApp

    UserbotAPI --> Login
    UserbotAPI --> TGOps

    CeleryApp --> RenderTasks
    CeleryApp --> PublishTasks
    CeleryApp --> PreviewTasks
    CeleryApp --> StatsTasks

    RenderTasks --> PreviewLib
    RenderTasks --> WatermarkLib
    PreviewTasks --> PreviewLib
```

---

## 2. Схема авторизации через QR-код

### 2.1. Процесс авторизации

```mermaid
sequenceDiagram
    participant U as Подрядчик
    participant B as Telegram Bot
    participant W as WebApp
    participant UA as Userbot API
    participant T as Telegram API
    participant S as Sessions Storage

    U->>B: /start или кнопка "Подключить аккаунт"
    B->>UA: GET /session/status?contractor_id=X
    UA-->>B: {has_session: false}
    B->>U: Показать кнопку "Открыть WebApp"
    
    U->>W: Открыть WebApp
    W->>UA: GET /session/status?contractor_id=X&verify=true
    UA-->>W: {has_session: false}
    
    W->>UA: POST /login/qr/start {contractor_id: X}
    UA->>T: client.qr_login()
    T-->>UA: QR-код (base64)
    UA-->>W: {token: "xxx", qr_code: "base64_image"}
    
    W->>W: Отобразить QR-код
    Note over U,T: Пользователь сканирует QR-код<br/>в Telegram Desktop/Web
    
    W->>UA: POST /login/qr/check {token: "xxx"}
    UA->>T: Проверка статуса QR-логина
    alt QR-код не отсканирован
        T-->>UA: waiting
        UA-->>W: {status: "waiting"}
        W->>W: Повторить проверку через 2 сек
    else QR-код отсканирован, ожидается подтверждение
        T-->>UA: waiting_for_password (2FA)
        UA-->>W: {status: "2fa_required"}
        W->>U: Запросить пароль 2FA
        U->>W: Ввести пароль
        W->>UA: POST /login/qr/2fa {token: "xxx", password: "***"}
        UA->>T: client.sign_in(password)
    else QR-код подтверждён
        T-->>UA: authorized
        UA->>UA: Сохранить сессию (StringSession)
        UA->>S: Зашифровать и сохранить сессию
        UA-->>W: {status: "ready", me: {...}}
        W->>B: tg.sendData({action: "session_ready"})
        B->>UA: GET /session/status?contractor_id=X&verify=true
        UA-->>B: {has_session: true, authorized: true}
        B->>U: ✅ Аккаунт подключён. Меню разблокировано.
    end
```

### 2.2. Схема WebApp для QR-авторизации

```mermaid
stateDiagram-v2
    [*] --> ПроверкаСессии
    
    ПроверкаСессии --> ПоказQR: Сессии нет
    ПроверкаСессии --> Успех: Сессия есть
    
    ПоказQR --> ОжиданиеСканирования: QR-код получен
    ОжиданиеСканирования --> ПроверкаСтатуса: Каждые 2 сек
    
    ПроверкаСтатуса --> ОжиданиеСканирования: waiting
    ПроверкаСтатуса --> ЗапросПароля: waiting_for_password
    ПроверкаСтатуса --> Успех: authorized
    
    ЗапросПароля --> ВводПароля: Пользователь вводит пароль
    ВводПароля --> ПроверкаСтатуса: Пароль отправлен
    
    Успех --> [*]: Сессия сохранена
    
    note right of ПоказQR
        Отображение QR-кода
        Инструкция: "Откройте Telegram Desktop/Web
        и отсканируйте QR-код"
    end note
    
    note right of ЗапросПароля
        Если включён 2FA,
        запрашивается пароль
    end note
```

### 2.3. API эндпоинты для QR-авторизации

```mermaid
graph TB
    subgraph "QR Login Endpoints"
        Start[POST /login/qr/start<br/>Начать QR-логин]
        Check[POST /login/qr/check<br/>Проверить статус]
        TwoFA[POST /login/qr/2fa<br/>Ввести пароль 2FA]
    end

    subgraph "Telethon Methods"
        QRLogin[client.qr_login<br/>Получить QR-код]
        QRCheck[client.qr_login<br/>Проверить статус]
        SignIn[client.sign_in<br/>Подтвердить с паролем]
    end

    subgraph "Storage"
        Pending[_pending_qr<br/>Временное хранилище]
        Session[Encrypted Session<br/>Файл .session.enc]
    end

    Start --> QRLogin
    QRLogin --> Pending
    QRLogin --> Start
    
    Check --> QRCheck
    QRCheck --> Pending
    QRCheck --> Check
    
    TwoFA --> SignIn
    SignIn --> Session
    SignIn --> TwoFA
    
    style Start fill:#2ea6ff,color:#fff
    style Check fill:#2ea6ff,color:#fff
    style TwoFA fill:#2ea6ff,color:#fff
```

---

## 3. Сценарий: Первый запуск подрядчика

### 3.1. Диаграмма последовательности

```mermaid
sequenceDiagram
    participant U as Подрядчик
    participant B as Telegram Bot
    participant W as WebApp
    participant UA as Userbot API
    participant DB as PostgreSQL
    participant T as Telegram API

    U->>B: /start
    B->>UA: GET /session/status?contractor_id=123
    UA-->>B: {has_session: false}
    
    B->>U: Привет! Подключите аккаунт через WebApp
    B->>U: [Кнопка: "🔐 Подключить аккаунт (WebApp)"]
    
    U->>W: Открыть WebApp
    W->>UA: GET /session/status?contractor_id=123&verify=true
    UA-->>W: {has_session: false}
    
    W->>UA: POST /login/qr/start {contractor_id: "123"}
    UA->>T: client.qr_login()
    T-->>UA: QR-код (base64)
    UA-->>W: {token: "abc123", qr_code: "data:image/png;base64,..."}
    
    W->>U: Отобразить QR-код + инструкция
    
    loop Каждые 2 секунды
        W->>UA: POST /login/qr/check {token: "abc123"}
        UA->>T: Проверка статуса
        T-->>UA: waiting
        UA-->>W: {status: "waiting"}
    end
    
    Note over U,T: Пользователь сканирует QR-код<br/>в Telegram Desktop/Web
    
    W->>UA: POST /login/qr/check {token: "abc123"}
    UA->>T: Проверка статуса
    T-->>UA: authorized
    UA->>UA: Сохранить StringSession
    UA->>UA: Зашифровать Fernet
    UA->>UA: Сохранить в файл 123.session.enc
    UA-->>W: {status: "ready", me: {id: 123, username: "user"}}
    
    W->>B: tg.sendData({action: "session_ready"})
    B->>UA: GET /session/status?contractor_id=123&verify=true
    UA->>UA: Загрузить и проверить сессию
    UA-->>B: {has_session: true, authorized: true}
    
    B->>DB: INSERT INTO core.contractors (tg_user_id, ...)
    DB-->>B: contractor_id
    
    B->>U: ✅ Аккаунт подключён! Меню разблокировано.
    B->>U: [Главное меню с функциями]
```

### 3.2. Блок-схема процесса

```mermaid
flowchart TD
    Start([Пользователь запускает /start]) --> CheckSession{Сессия<br/>есть?}
    
    CheckSession -->|Нет| ShowWebApp[Показать кнопку<br/>"Подключить аккаунт"]
    CheckSession -->|Да| ShowMenu[Показать главное меню]
    
    ShowWebApp --> OpenWebApp[Пользователь открывает WebApp]
    OpenWebApp --> RequestQR[POST /login/qr/start]
    
    RequestQR --> GetQR[Получить QR-код от Telegram]
    GetQR --> DisplayQR[Отобразить QR-код в WebApp]
    
    DisplayQR --> WaitScan[Ожидание сканирования]
    WaitScan --> CheckStatus{Проверить<br/>статус}
    
    CheckStatus -->|waiting| WaitScan
    CheckStatus -->|2fa_required| RequestPassword[Запросить пароль 2FA]
    CheckStatus -->|authorized| SaveSession[Сохранить сессию]
    
    RequestPassword --> InputPassword[Пользователь вводит пароль]
    InputPassword --> SendPassword[POST /login/qr/2fa]
    SendPassword --> SaveSession
    
    SaveSession --> EncryptSession[Зашифровать сессию Fernet]
    EncryptSession --> SaveFile[Сохранить в файл<br/>contractor_id.session.enc]
    
    SaveFile --> NotifyBot[Отправить session_ready в бота]
    NotifyBot --> VerifySession[Проверить сессию через API]
    VerifySession --> CreateContractor[Создать запись в БД]
    CreateContractor --> ShowMenu
    
    ShowMenu --> End([Готово])
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style SaveSession fill:#87CEEB
    style ShowMenu fill:#DDA0DD
```

---

## 4. Сценарий: Создание канала

### 4.1. Диаграмма последовательности

```mermaid
sequenceDiagram
    participant U as Подрядчик
    participant B as Telegram Bot
    participant UA as Userbot API
    participant T as Telegram API
    participant DB as PostgreSQL
    participant Billing as Billing Service

    U->>B: Нажать "🆕 Новый канал"
    B->>UA: GET /session/status?contractor_id=123
    UA-->>B: {has_session: true, authorized: true}
    
    B->>U: Введите название канала
    U->>B: "Проект Иванова"
    
    B->>U: Загрузите аватарку (опционально)
    alt Аватарка загружена
        U->>B: [Фото]
        B->>B: Сохранить фото
    end
    
    B->>DB: Проверить лимиты подписки
    DB->>Billing: can_create_channel(contractor_id)
    Billing-->>DB: {can_create: true, reason: null}
    DB-->>B: OK
    
    B->>UA: POST /rooms/create {contractor_id: "123", title: "Проект Иванова"}
    UA->>UA: Загрузить сессию подрядчика
    UA->>T: CreateChannelRequest(title, megagroup=False)
    T-->>UA: Channel created (channel_id: -1001234567890)
    
    UA->>T: ToggleNoForwardsRequest(enabled=True)
    T-->>UA: OK (запрет форвардинга включён)
    
    UA-->>B: {channel_id: -1001234567890}
    
    B->>UA: POST /rooms/add_bot_admin {channel_id: -1001234567890, bot_username: "@smetabot"}
    UA->>T: EditAdminRequest(bot, rights: post_messages, invite_users)
    T-->>UA: OK (бот назначен администратором)
    UA-->>B: {ok: true}
    
    alt Аватарка загружена
        B->>T: set_chat_photo(chat_id, photo)
        T-->>B: OK
    end
    
    B->>DB: INSERT INTO core.channels (contractor_id, tg_chat_id, title, ...)
    DB-->>B: channel_db_id
    
    B->>DB: UPDATE billing.usage_counters SET channels_created_total = channels_created_total + 1
    
    B->>T: create_chat_invite_link(chat_id, creates_join_request=True, member_limit=1)
    T-->>B: invite_link: "https://t.me/join/..."
    
    B->>DB: INSERT INTO core.invites (channel_id, token, max_uses=1, ...)
    
    B->>U: ✅ Канал создан!<br/>Название: Проект Иванова<br/>Ссылка: https://t.me/join/...
```

### 4.2. Блок-схема процесса

```mermaid
flowchart TD
    Start([Пользователь: "Новый канал"]) --> CheckSession{Сессия<br/>авторизована?}
    
    CheckSession -->|Нет| RequestAuth[Запросить авторизацию]
    CheckSession -->|Да| InputTitle[Ввести название канала]
    
    InputTitle --> OptionalAvatar{Загрузить<br/>аватарку?}
    OptionalAvatar -->|Да| UploadAvatar[Загрузить фото]
    OptionalAvatar -->|Нет| CheckLimits
    UploadAvatar --> CheckLimits
    
    CheckLimits{Проверить<br/>лимиты подписки} -->|Превышен| ShowError[Ошибка: лимит превышен]
    CheckLimits -->|OK| CreateChannel[POST /rooms/create]
    
    CreateChannel --> EnableNoForwards[Включить ToggleNoForwardsRequest]
    EnableNoForwards --> AddBotAdmin[POST /rooms/add_bot_admin]
    
    AddBotAdmin --> SetAvatar{Аватарка<br/>есть?}
    SetAvatar -->|Да| SetPhoto[Установить фото канала]
    SetAvatar -->|Нет| SaveToDB
    SetPhoto --> SaveToDB
    
    SaveToDB[Сохранить в core.channels] --> IncrementCounter[Инкремент счётчика каналов]
    IncrementCounter --> CreateInvite[Создать одноразовую ссылку]
    CreateInvite --> SaveInvite[Сохранить в core.invites]
    SaveInvite --> ShowSuccess[Показать результат пользователю]
    
    ShowError --> End([Конец])
    ShowSuccess --> End
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style CreateChannel fill:#87CEEB
    style ShowSuccess fill:#DDA0DD
```

---

## 5. Сценарий: Публикация документа

### 5.1. Полный процесс обработки

```mermaid
sequenceDiagram
    participant U as Подрядчик
    participant B as Telegram Bot
    participant R as Redis
    participant WP as Worker Preview
    participant WR as Worker Render
    participant WPUB as Worker Publish
    participant T as Telegram API
    participant DB as PostgreSQL
    participant LO as LibreOffice
    participant WM as Watermark

    U->>B: Выбрать "📄 PDF → PNG"
    B->>U: Пришлите PDF-файл
    
    U->>B: [PDF файл: smeta.pdf]
    B->>R: SET pdf:uuid-123 [file_bytes] EX 86400
    R-->>B: OK
    
    B->>WP: generate_preview_task(pdf_key="pdf:uuid-123")
    WP->>R: GET pdf:uuid-123
    R-->>WP: [file_bytes]
    
    WP->>WP: PyMuPDF: PDF → PNG (300 DPI)
    WP->>WP: Создать thumbnail (JPEG 1600px)
    WP->>R: SET preview:uuid-123 [thumbnail] EX 3600
    WP-->>B: Превью готово
    
    B->>U: Показать превью страниц
    U->>B: Выбрать страницы: [1, 3, 5]
    U->>B: Водяной знак: "Иванов И.И."
    
    B->>WR: process_and_publish_pdf(chat_id, pdf_key, page_indices=[1,3,5], watermark_text)
    WR->>R: GET pdf:uuid-123
    R-->>WR: [file_bytes]
    R->>R: DEL pdf:uuid-123
    
    WR->>WR: PyMuPDF: PDF → PNG (300 DPI) для страниц [1,3,5]
    
    loop Для каждой страницы
        WR->>WM: apply_tiled_watermark(png, "Иванов И.И.")
        WM-->>WR: PNG с водяным знаком
        WR->>WPUB: send_document(chat_id, png_bytes, filename, protect_content=True)
        WPUB->>T: sendDocument(chat_id, document, protect_content=True)
        T-->>WPUB: {ok: true, message_id: 123}
        WPUB->>DB: INSERT INTO core.publications (channel_id, message_id, file_name, views)
    end
    
    WR-->>B: Успешно опубликовано 3 страницы
    B->>U: ✅ Документ опубликован в канале
```

### 5.2. Схема обработки разных форматов

```mermaid
flowchart TD
    Start([Пользователь загружает файл]) --> DetectType{Определить<br/>тип файла}
    
    DetectType -->|PDF| StorePDF[Сохранить в Redis:<br/>pdf:uuid]
    DetectType -->|DOC/DOCX| StoreDOC[Сохранить в Redis:<br/>doc:uuid]
    DetectType -->|XLS/XLSX| StoreXLS[Сохранить в Redis:<br/>xls:uuid]
    DetectType -->|PNG| StorePNG[Сохранить в Redis:<br/>png:uuid]
    
    StorePDF --> GeneratePreview[Генерация превью]
    StoreDOC --> GeneratePreview
    StoreXLS --> GeneratePreview
    StorePNG --> SkipPreview[Пропустить превью]
    
    GeneratePreview --> ShowPreview[Показать превью пользователю]
    ShowPreview --> SelectPages[Выбрать страницы/листы]
    SelectPages --> InputWatermark[Ввести текст водяного знака]
    
    SkipPreview --> InputWatermark
    
    InputWatermark --> QueueTask{Поставить в<br/>очередь}
    
    QueueTask -->|PDF| QueuePDF[Очередь: pdf]
    QueueTask -->|DOC/XLS| QueueOffice[Очередь: office]
    QueueTask -->|PNG| QueuePublish[Очередь: publish]
    
    QueuePDF --> RenderPDF[Worker: PDF → PNG 300 DPI]
    QueueOffice --> ConvertOffice[Worker: LibreOffice → PDF]
    ConvertOffice --> RenderPDF
    QueuePublish --> NormalizePNG[Worker: Нормализация PNG 300 DPI]
    
    RenderPDF --> ApplyWatermark[Наложить водяной знак]
    NormalizePNG --> ApplyWatermark
    
    ApplyWatermark --> Publish[Отправить в канал<br/>protect_content=True]
    Publish --> SaveDB[Сохранить в core.publications]
    SaveDB --> DeleteTemp[Удалить временный файл из Redis]
    DeleteTemp --> End([Готово])
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style ApplyWatermark fill:#87CEEB
    style Publish fill:#DDA0DD
```

### 5.3. Детальная схема рендеринга

```mermaid
graph TB
    subgraph "PDF Processing"
        PDF1[PDF File] --> PDF2[PyMuPDF<br/>fitz.open]
        PDF2 --> PDF3[page.get_pixmap<br/>dpi=300]
        PDF3 --> PDF4[PNG 300 DPI]
    end
    
    subgraph "DOC/DOCX Processing"
        DOC1[DOC/DOCX File] --> DOC2[LibreOffice<br/>--convert-to pdf]
        DOC2 --> DOC3[PDF File]
        DOC3 --> PDF2
    end
    
    subgraph "XLS/XLSX Processing"
        XLS1[XLS/XLSX File] --> XLS2[LibreOffice<br/>--convert-to pdf]
        XLS2 --> XLS3[PDF File]
        XLS3 --> PDF2
        XLS1 --> XLS4[openpyxl<br/>Поиск таблиц]
        XLS4 --> XLS2
    end
    
    subgraph "Watermark Application"
        PDF4 --> WM1[PIL Image.open]
        WM1 --> WM2[apply_tiled_watermark<br/>text, opacity, angle]
        WM2 --> WM3[PNG with Watermark]
    end
    
    subgraph "Publishing"
        WM3 --> PUB1[Telegram Bot API<br/>sendDocument]
        PUB1 --> PUB2[protect_content=True]
        PUB2 --> PUB3[Message in Channel]
    end
    
    style PDF2 fill:#87CEEB
    style WM2 fill:#DDA0DD
    style PUB2 fill:#90EE90
```

---

## 6. Сценарий: Клиент получает доступ

### 6.1. Диаграмма последовательности

```mermaid
sequenceDiagram
    participant C as Клиент
    participant B as Telegram Bot
    participant T as Telegram API
    participant DB as PostgreSQL

    Note over C,DB: Подрядчик создал ссылку-приглашение
    
    C->>T: Перейти по ссылке<br/>https://t.me/join/...
    T->>B: ChatJoinRequest<br/>(user_id, chat_id)
    
    B->>DB: SELECT * FROM core.channels<br/>WHERE tg_chat_id = chat_id
    DB-->>B: channel record
    
    B->>DB: SELECT * FROM core.invites<br/>WHERE channel_id = channel_id<br/>AND token = invite_link
    DB-->>B: invite record
    
    B->>B: Проверить лимиты:<br/>used_count < max_uses?<br/>expires_at > now()?
    
    alt Лимиты не превышены
        B->>T: approve_chat_join_request<br/>(chat_id, user_id)
        T-->>B: OK
        
        B->>DB: UPDATE core.invites<br/>SET used_count = used_count + 1
        
        B->>DB: INSERT INTO core.clients<br/>(channel_id, invite_id, tg_user_id, ...)
        
        B->>DB: INSERT INTO analytics.events<br/>(event_type: 'client_join', ...)
        
        C->>T: Получить доступ к каналу
        T-->>C: Канал открыт
    else Лимиты превышены
        B->>T: decline_chat_join_request<br/>(chat_id, user_id)
        T-->>B: OK
        B->>C: Запрос отклонён<br/>(лимит использований исчерпан)
    end
```

### 6.2. Блок-схема процесса

```mermaid
flowchart TD
    Start([Клиент переходит по ссылке]) --> JoinRequest[Telegram: ChatJoinRequest]
    
    JoinRequest --> CheckChannel{Канал<br/>найден в БД?}
    CheckChannel -->|Нет| Decline1[Отклонить запрос]
    CheckChannel -->|Да| CheckInvite{Инвайт<br/>найден?}
    
    CheckInvite -->|Нет| Decline1
    CheckInvite -->|Да| CheckLimits{Проверить<br/>лимиты}
    
    CheckLimits -->|used_count >= max_uses| Decline2[Отклонить:<br/>лимит использований]
    CheckLimits -->|expires_at < now| Decline3[Отклонить:<br/>срок истёк]
    CheckLimits -->|Лимиты OK| Approve[Одобрить запрос]
    
    Approve --> IncrementUsed[Инкремент used_count]
    IncrementUsed --> SaveClient[Сохранить в core.clients]
    SaveClient --> LogEvent[Логировать событие<br/>client_join]
    LogEvent --> GrantAccess[Предоставить доступ к каналу]
    
    Decline1 --> End([Конец])
    Decline2 --> End
    Decline3 --> End
    GrantAccess --> End
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style Approve fill:#87CEEB
    style GrantAccess fill:#DDA0DD
```

---

## 7. Поток данных: Обработка документа

### 7.1. Полный поток данных

```mermaid
flowchart LR
    subgraph "Input"
        File[PDF/DOC/XLS File]
    end
    
    subgraph "Storage Layer"
        Redis1[(Redis<br/>pdf:uuid<br/>TTL: 24h)]
        Redis2[(Redis<br/>preview:uuid<br/>TTL: 1h)]
        Redis3[(Redis<br/>renderpng:uuid<br/>TTL: 12h)]
    end
    
    subgraph "Processing"
        Preview[Preview Worker<br/>Generate Thumbnail]
        Render[Render Worker<br/>Convert to PNG 300 DPI]
        Watermark[Apply Watermark]
    end
    
    subgraph "Output"
        Channel[Telegram Channel<br/>protect_content=True]
        DB[(PostgreSQL<br/>core.publications)]
    end
    
    File -->|Store| Redis1
    Redis1 -->|Read| Preview
    Preview -->|Write| Redis2
    Redis2 -->|User selects pages| Render
    Redis1 -->|Read & Delete| Render
    Render -->|Write| Redis3
    Redis3 -->|Read| Watermark
    Watermark -->|Publish| Channel
    Channel -->|Metadata| DB
    DB -->|Cleanup| Redis3
    
    style File fill:#90EE90
    style Channel fill:#FFB6C1
    style Watermark fill:#87CEEB
```

### 7.2. Схема очередей Celery

```mermaid
graph TB
    subgraph "Bot"
        BotTask[Постановка задачи]
    end
    
    subgraph "Redis Queue"
        QueuePDF[Очередь: pdf]
        QueueOffice[Очередь: office]
        QueuePublish[Очередь: publish]
        QueuePreview[Очередь: preview]
    end
    
    subgraph "Workers"
        WorkerPDF[Worker PDF<br/>Concurrency: 3]
        WorkerOffice[Worker Office<br/>Concurrency: 1]
        WorkerPublish[Worker Publish<br/>Concurrency: 2]
        WorkerPreview[Worker Preview<br/>Concurrency: 2]
    end
    
    subgraph "Tasks"
        TaskPDF[process_and_publish_pdf]
        TaskDOC[process_and_publish_doc]
        TaskXLS[process_and_publish_excel]
        TaskPNG[process_and_publish_png]
        TaskPreview[generate_preview_task]
    end
    
    BotTask -->|PDF| QueuePDF
    BotTask -->|DOC/DOCX| QueueOffice
    BotTask -->|XLS/XLSX| QueueOffice
    BotTask -->|PNG| QueuePublish
    BotTask -->|Preview| QueuePreview
    
    QueuePDF --> WorkerPDF
    QueueOffice --> WorkerOffice
    QueuePublish --> WorkerPublish
    QueuePreview --> WorkerPreview
    
    WorkerPDF --> TaskPDF
    WorkerOffice --> TaskDOC
    WorkerOffice --> TaskXLS
    WorkerPublish --> TaskPNG
    WorkerPreview --> TaskPreview
    
    style BotTask fill:#90EE90
    style QueuePDF fill:#FFB6C1
    style QueueOffice fill:#FFB6C1
    style QueuePublish fill:#FFB6C1
    style QueuePreview fill:#FFB6C1
```

---

## 8. Схема базы данных

### 8.1. ER-диаграмма основных сущностей

```mermaid
erDiagram
    CONTRACTORS ||--o{ CHANNELS : owns
    CONTRACTORS ||--o{ SUBSCRIPTIONS : has
    CONTRACTORS ||--o{ USAGE_COUNTERS : tracks
    CONTRACTORS ||--o{ GIFTS_QUEUE : queued
    
    CHANNELS ||--o{ PUBLICATIONS : publishes
    CHANNELS ||--o{ INVITES : creates
    CHANNELS ||--o{ CLIENTS : serves
    CHANNELS ||--o{ CHANNEL_STATS : aggregates
    
    PUBLICATIONS ||--o{ VIEWS_DAILY : measures
    
    INVITES ||--o{ CLIENTS : via
    
    PLANS ||--o{ SUBSCRIPTIONS : selected
    PLANS ||--o{ GIFTS_QUEUE : giftPlan
    
    CONTRACTORS {
        bigint id PK
        bigint tg_user_id UK
        text username
        text full_name
        text status
        timestamptz created_at
    }
    
    CHANNELS {
        bigint id PK
        bigint contractor_id FK
        bigint tg_chat_id UK
        text title
        text username
        timestamptz created_at
    }
    
    PUBLICATIONS {
        bigint id PK
        bigint channel_id FK
        bigint message_id
        text file_name
        text file_type
        int views
        timestamptz posted_at
        boolean deleted
    }
    
    INVITES {
        bigint id PK
        bigint channel_id FK
        text token UK
        timestamptz expires_at
        int max_uses
        int used_count
        timestamptz created_at
    }
    
    CLIENTS {
        bigint id PK
        bigint channel_id FK
        bigint invite_id FK
        bigint tg_user_id
        text username
        text full_name
        timestamptz joined_at
        boolean blocked
    }
    
    SUBSCRIPTIONS {
        bigint id PK
        bigint contractor_id FK
        bigint plan_id FK
        text status
        timestamptz starts_at
        timestamptz expires_at
        text source
    }
    
    PLANS {
        bigint id PK
        text code UK
        text name
        numeric price_month
        jsonb features
        int channels_limit_one_off
    }
```

### 8.2. Схема связей между таблицами

```mermaid
graph TB
    subgraph "Core Schema"
        C[contractors]
        CH[channels]
        P[publications]
        I[invites]
        CL[clients]
    end
    
    subgraph "Billing Schema"
        PL[plans]
        S[subscriptions]
        UC[usage_counters]
        GQ[gifts_queue]
    end
    
    subgraph "Analytics Schema"
        VD[views_daily]
        CS[channel_stats]
        E[events]
    end
    
    C -->|1:N| CH
    C -->|1:1| S
    C -->|1:1| UC
    C -->|1:N| GQ
    
    PL -->|1:N| S
    PL -->|1:N| GQ
    
    CH -->|1:N| P
    CH -->|1:N| I
    CH -->|1:N| CL
    CH -->|1:1| CS
    
    I -->|1:N| CL
    
    P -->|1:N| VD
    
    CH -->|1:N| E
    CL -->|1:N| E
    
    style C fill:#87CEEB
    style CH fill:#DDA0DD
    style P fill:#90EE90
    style S fill:#FFB6C1
```

---

## 9. Инфраструктура развёртывания

### 9.1. Docker Compose архитектура

```mermaid
graph TB
    subgraph "Reverse Proxy"
        Traefik[Traefik<br/>Port: 80, 443<br/>SSL: Let's Encrypt]
    end
    
    subgraph "Database Layer"
        PostgreSQL[(PostgreSQL<br/>Port: 5432<br/>Volume: pgdata)]
        Redis[(Redis<br/>Port: 6379)]
    end
    
    subgraph "Application Layer"
        Backend[Backend API<br/>Port: 8000<br/>Health: /health]
        Userbot[Userbot API<br/>Port: 8001<br/>Health: /health]
        Bot[Telegram Bot<br/>Polling]
    end
    
    subgraph "Worker Layer"
        WorkerPDF[Worker PDF<br/>Queue: pdf<br/>Metrics: 9464]
        WorkerOffice[Worker Office<br/>Queue: office<br/>Metrics: 9466]
        WorkerPublish[Worker Publish<br/>Queue: publish<br/>Metrics: 9465]
        WorkerPreview[Worker Preview<br/>Queue: preview<br/>Metrics: 9467]
    end
    
    subgraph "Monitoring"
        Flower[Flower<br/>Port: 5555<br/>Celery Monitor]
    end
    
    subgraph "Storage"
        Sessions[Volume: userbot_sessions<br/>Encrypted .session.enc files]
        LetsEncrypt[Volume: traefik_letsencrypt<br/>SSL Certificates]
    end
    
    Traefik --> Userbot
    Traefik --> Backend
    
    Backend --> PostgreSQL
    Userbot --> PostgreSQL
    Userbot --> Sessions
    Bot --> PostgreSQL
    Bot --> Redis
    Bot --> Userbot
    Bot --> Backend
    
    WorkerPDF --> Redis
    WorkerPDF --> PostgreSQL
    WorkerOffice --> Redis
    WorkerOffice --> PostgreSQL
    WorkerPublish --> Redis
    WorkerPublish --> PostgreSQL
    WorkerPreview --> Redis
    
    Flower --> Redis
    
    style Traefik fill:#2ea6ff,color:#fff
    style PostgreSQL fill:#336791,color:#fff
    style Redis fill:#dc382d,color:#fff
    style Userbot fill:#00d4aa,color:#fff
```

### 9.2. Схема сетей

```mermaid
graph LR
    subgraph "External Network"
        Internet[Internet]
    end
    
    subgraph "Traefik Network"
        Traefik[Traefik]
        UserbotExt[Userbot<br/>External Access]
    end
    
    subgraph "Default Network"
        Bot[Bot]
        Backend[Backend]
        UserbotInt[Userbot<br/>Internal]
        Workers[Workers]
        PostgreSQL[(PostgreSQL)]
        Redis[(Redis)]
    end
    
    Internet -->|HTTPS| Traefik
    Traefik -->|HTTP| UserbotExt
    Traefik -->|HTTP| Backend
    
    Bot -->|HTTP| UserbotInt
    Bot -->|HTTP| Backend
    Bot -->|Tasks| Redis
    Bot -->|Queries| PostgreSQL
    
    UserbotInt -->|Queries| PostgreSQL
    UserbotExt -->|HTTP| UserbotInt
    
    Workers -->|Tasks| Redis
    Workers -->|Queries| PostgreSQL
    
    style Internet fill:#90EE90
    style Traefik fill:#2ea6ff,color:#fff
    style PostgreSQL fill:#336791,color:#fff
    style Redis fill:#dc382d,color:#fff
```

---

## 10. Схема взаимодействия компонентов

### 10.1. Полный цикл: от загрузки до публикации

```mermaid
sequenceDiagram
    participant U as Подрядчик
    participant B as Bot
    participant R as Redis
    participant WP as Worker Preview
    participant WR as Worker Render
    participant WPUB as Worker Publish
    participant T as Telegram API
    participant DB as PostgreSQL

    U->>B: Загрузить PDF
    B->>R: SET pdf:uuid [bytes] EX 86400
    B->>WP: generate_preview_task(pdf_key)
    
    WP->>R: GET pdf:uuid
    R-->>WP: [bytes]
    WP->>WP: PDF → PNG → JPEG (thumbnail)
    WP->>R: SET preview:uuid [thumbnail] EX 3600
    WP-->>B: Превью готово
    
    B->>U: Показать превью, выбрать страницы
    U->>B: Страницы [1,3,5], водяной знак "Иванов"
    
    B->>WR: process_and_publish_pdf(chat_id, pdf_key, pages, watermark)
    WR->>R: GET pdf:uuid
    R-->>WR: [bytes]
    R->>R: DEL pdf:uuid
    
    loop Для каждой страницы
        WR->>WR: PDF → PNG 300 DPI
        WR->>WR: apply_watermark("Иванов")
        WR->>WPUB: send_document(chat_id, png_bytes, protect_content=True)
        WPUB->>T: sendDocument(chat_id, document, protect_content=True)
        T-->>WPUB: {ok: true, message_id: 123}
        WPUB->>DB: INSERT INTO core.publications (channel_id, message_id, file_name, views)
    end
    
    WR-->>B: Успешно опубликовано
    B->>U: ✅ Документ опубликован
```

### 10.2. Схема обработки ошибок и retry

```mermaid
flowchart TD
    Start([Отправка документа]) --> Send[Telegram API: sendDocument]
    
    Send --> CheckResult{Результат}
    
    CheckResult -->|ok: true| Success[Успех]
    CheckResult -->|Error 403| Retry403{Retry<br/>403?}
    CheckResult -->|Error 429| Retry429[FloodWait<br/>Подождать N секунд]
    CheckResult -->|Error 400| LogError[Логировать ошибку]
    CheckResult -->|Network Error| RetryNetwork[Retry через 5 сек]
    
    Retry403 -->|Да| Wait403[Подождать 10 сек]
    Wait403 --> Send
    Retry403 -->|Нет| LogError
    
    Retry429 --> Wait429[Подождать N секунд]
    Wait429 --> Send
    
    RetryNetwork --> CheckRetries{Попыток<br/>< 3?}
    CheckRetries -->|Да| Send
    CheckRetries -->|Нет| LogError
    
    Success --> SaveDB[Сохранить в БД]
    SaveDB --> End([Готово])
    
    LogError --> End
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style Success fill:#87CEEB
    style LogError fill:#FF6B6B
```

---

## Примечания

### Условные обозначения

- **Зелёный** — начало процесса
- **Розовый** — конец процесса
- **Голубой** — важные операции
- **Фиолетовый** — успешное завершение
- **Красный** — ошибки

### Технические детали

1. **QR-код авторизация**: Использует `client.qr_login()` из Telethon, который генерирует QR-код для сканирования в Telegram Desktop/Web
2. **Шифрование сессий**: Fernet с ключом из `SESSION_SECRET`
3. **TTL в Redis**: 
   - Исходные файлы: 24 часа
   - Превью: 1 час
   - Полные PNG: 12 часов
4. **Защита контента**: Все публикации с `protect_content=True` и `ToggleNoForwardsRequest`

---

**Версия документа:** 1.0  
**Дата создания:** 2024  
**Последнее обновление:** 2024

