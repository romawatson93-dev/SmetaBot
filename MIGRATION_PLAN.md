# План миграции на новую схему БД

## Текущее состояние
- ✅ Миграция `0001_init.sql` создана и применена
- ✅ Сервисы созданы, но с несоответствиями схеме
- ✅ `bot/services/db.py` — инфраструктура готова (asyncpg, пулы, схемы)
- ❌ Сервисы используют устаревшие поля (`invites.active` вместо логики `used_count/expires_at`)
- ❌ Нет инициализации по умолчанию (usage_counters, подписки, рефералки)
- ❌ Worker не переписан на новые таблицы

## Этапы миграции

### Этап 1: Исправление сервисов под новую схему
**Цель**: Привести `bot/services/*` к точному соответствию `0001_init.sql`

#### 1.1. Исправить `invites.py`
- Убрать поле `active` (нет в схеме)
- Логику активности перенести на `used_count < max_uses AND (expires_at IS NULL OR expires_at > now())`
- Добавить метод `list_active()` с правильной логикой
- Добавить методы: `increment_used()`, `is_usable()`

#### 1.2. Исправить `billing.py`
- Добавить инициализацию подписки FREE по умолчанию при регистрации
- Добавить методы: `ensure_free_plan()`, `can_create_channel()`, `increment_channels()`
- Исправить `usage_counters` — добавить проверку лимитов

#### 1.3. Дополнить `analytics.py`
- Добавить методы записи в `events`
- Добавить методы для `views_daily`, `channel_stats`

#### 1.4. Дополнить `referrals.py`
- Добавить инициализацию `referral_links`
- Добавить методы для `referral_cycles`
- Добавить проверку квалификации (≥2 канала)

### Этап 2: Добавить недостающие сервисы
**Цель**: Закрыть разрывы между сервисами и хендлерами

#### 2.1. Создать `services/subscriptions.py`
- Класс `SubscriptionService` с методами:
  - `ensure_subscription(contractor_id)` — создаёт FREE если нет
  - `check_limit(contractor_id, resource)` — проверка лимитов
  - `increment_usage(contractor_id, resource)` — инкремент счётчика

#### 2.2. Создать `services/events.py`
- Запись событий в `analytics.events`
- Типы: `client_join`, `file_posted`, `invite_used` и т.д.

### Этап 3: Обновить хендлеры на новые сервисы
**Цель**: Убрать все прямые SQL-запросы, использовать сервисы

#### 3.1. `channel_wizard.py`
- Использовать `channels_service.create_project_channel()`
- Проверять лимиты через `subscriptions.check_limit()`
- Записывать события через `events.log_event()`

#### 3.2. `my_channels.py`
- Использовать `channels_service.aggregate_contractor_stats()`
- Использовать `channels_service.get_channel_stats()`

#### 3.3. `render_pdf.py`, `finalize.py`
- Публикации через `publications_service.add_publication()`
- Инвайты через `invites_service.create_invite()`
- Клиенты через `clients_service.register_client()`

#### 3.4. `profile.py`
- Использовать `analytics.profile_overview` через `contractors_service.profile_overview()`

### Этап 4: Переписать worker
**Цель**: Worker записывает данные в новые таблицы

#### 4.1. `worker/tasks/render/*`
- После публикации вызывать `publications_service.add_publication()`
- Записывать в `analytics.events` (`event_type='file_posted'`)
- Обновлять `analytics.channel_stats`

#### 4.2. Добавить периодические задачи
- `update_views_daily()` — агрегация просмотров
- `update_channel_stats()` — агрегация статистики каналов
- `apply_queued_gifts()` — обработка очереди подарков

### Этап 5: Инициализация данных при первом запуске
**Цель**: Создавать дефолтные данные при регистрации

- При `get_or_create_by_tg()` создавать `usage_counters`
- При создании канала проверять лимиты и инкрементить счётчик
- При регистрации через рефералку создавать `referrals.referrals`

### Этап 6: Тестирование
**Цель**: Убедиться, что всё работает

- Создание канала
- Публикация файла
- Создание инвайта
- Регистрация клиента
- Проверка статистики
- Проверка лимитов подписки

## Порядок выполнения

1. **Этап 1** (1–2 часа) — исправление сервисов
2. **Этап 2** (1 час) — новые сервисы
3. **Этап 3** (2–3 часа) — хендлеры
4. **Этап 4** (1–2 часа) — worker
5. **Этап 5** (30 мин) — инициализация
6. **Этап 6** (1–2 часа) — тестирование

Итого: ~8–12 часов работы

## Критические моменты

1. **Не использовать поле `active` в `invites`** — его нет в схеме
2. **Всегда создавать `usage_counters`** при регистрации подрядчика
3. **Проверять лимиты** перед созданием канала
4. **Использовать транзакции** при создании каналов (channel + usage_counter)
5. **Worker должен писать в `analytics`** — не дергать UI-методы
