-- 0001_init.sql
-- Полное создание схемы БД для SmetaBot.
-- Идемпотентный скрипт: можно безопасно выполнять повторно.

SET lock_timeout = '5s';
SET statement_timeout = '60s';
SET client_min_messages = warning;

-- =====================================================================
-- 0. Очистка старых схем (если остались от предыдущих миграций)
-- =====================================================================
DO $$
DECLARE
    schema_name TEXT;
BEGIN
    FOR schema_name IN ('core', 'billing', 'analytics', 'referrals', 'admin')
    LOOP
        IF EXISTS (
            SELECT 1
            FROM information_schema.schemata
            WHERE schema_name = schema_name
        ) THEN
            EXECUTE format('DROP SCHEMA %I CASCADE;', schema_name);
        END IF;
    END LOOP;
END $$;

-- =====================================================================
-- 1. Создание схем
-- =====================================================================
CREATE SCHEMA core;
CREATE SCHEMA billing;
CREATE SCHEMA analytics;
CREATE SCHEMA referrals;
CREATE SCHEMA admin;

-- =====================================================================
-- 2. CORE
-- =====================================================================

CREATE TABLE core.contractors (
    id              BIGSERIAL PRIMARY KEY,
    tg_user_id      BIGINT UNIQUE,
    username        TEXT,
    full_name       TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'blocked'))
);

CREATE TABLE core.channels (
    id               BIGSERIAL PRIMARY KEY,
    contractor_id    BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    tg_chat_id       BIGINT NOT NULL UNIQUE,
    title            TEXT,
    username         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_bot   BOOLEAN NOT NULL DEFAULT TRUE,
    synced           BOOLEAN NOT NULL DEFAULT FALSE,
    last_synced_at   TIMESTAMPTZ
);
CREATE INDEX idx_channels_contractor ON core.channels(contractor_id);

CREATE TABLE core.publications (
    id           BIGSERIAL PRIMARY KEY,
    channel_id   BIGINT NOT NULL REFERENCES core.channels(id) ON DELETE CASCADE,
    message_id   BIGINT NOT NULL,
    file_name    TEXT,
    file_type    TEXT,
    views        INT NOT NULL DEFAULT 0,
    posted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (channel_id, message_id)
);
CREATE INDEX idx_publications_channel_posted ON core.publications(channel_id, posted_at DESC);

CREATE TABLE core.invites (
    id           BIGSERIAL PRIMARY KEY,
    channel_id   BIGINT NOT NULL REFERENCES core.channels(id) ON DELETE CASCADE,
    token        TEXT NOT NULL UNIQUE,
    expires_at   TIMESTAMPTZ,
    max_uses     INT,
    used_count   INT NOT NULL DEFAULT 0,
    editable     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_invites_channel ON core.invites(channel_id);

CREATE TABLE core.clients (
    id            BIGSERIAL PRIMARY KEY,
    channel_id    BIGINT NOT NULL REFERENCES core.channels(id) ON DELETE CASCADE,
    invite_id     BIGINT REFERENCES core.invites(id) ON DELETE SET NULL,
    tg_user_id    BIGINT,
    username      TEXT,
    full_name     TEXT,
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    blocked       BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_clients_channel ON core.clients(channel_id);
CREATE INDEX idx_clients_invite  ON core.clients(invite_id);

CREATE TABLE core.team_members (
    id                      BIGSERIAL PRIMARY KEY,
    owner_contractor_id     BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    member_contractor_id    BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    added_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_contractor_id, member_contractor_id)
);

-- =====================================================================
-- 3. BILLING
-- =====================================================================

CREATE TABLE billing.plans (
    id                     BIGSERIAL PRIMARY KEY,
    code                   TEXT NOT NULL UNIQUE,
    name                   TEXT NOT NULL,
    price_month            NUMERIC(10,2),
    features               JSONB NOT NULL DEFAULT '{}'::jsonb,
    channels_limit_one_off INT,
    CHECK (code IN ('FREE','PRO','BUSINESS'))
);

CREATE TABLE billing.subscriptions (
    id             BIGSERIAL PRIMARY KEY,
    contractor_id  BIGINT NOT NULL UNIQUE REFERENCES core.contractors(id) ON DELETE CASCADE,
    plan_id        BIGINT NOT NULL REFERENCES billing.plans(id),
    status         TEXT NOT NULL,
    starts_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    source         TEXT NOT NULL DEFAULT 'paid',
    CHECK (status IN ('active','trial','grace','expired','cancelled')),
    CHECK (source IN ('paid','gift','trial','admin_grant'))
);

CREATE TABLE billing.subscription_history (
    id             BIGSERIAL PRIMARY KEY,
    contractor_id  BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    plan_id        BIGINT NOT NULL REFERENCES billing.plans(id),
    status         TEXT NOT NULL,
    starts_at      TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ,
    source         TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active','trial','grace','expired','cancelled')),
    CHECK (source IN ('paid','gift','trial','admin_grant'))
);

CREATE TABLE billing.usage_counters (
    contractor_id               BIGINT PRIMARY KEY REFERENCES core.contractors(id) ON DELETE CASCADE,
    channels_created_total      INT NOT NULL DEFAULT 0,
    last_channel_created_at     TIMESTAMPTZ
);

CREATE TABLE billing.gifts_queue (
    id             BIGSERIAL PRIMARY KEY,
    contractor_id  BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    plan_id        BIGINT NOT NULL REFERENCES billing.plans(id),
    days           INT NOT NULL DEFAULT 30,
    reason         TEXT NOT NULL,
    queued_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at     TIMESTAMPTZ,
    CHECK (reason IN ('referral_reward','admin_grant'))
);

-- =====================================================================
-- 4. ANALYTICS
-- =====================================================================

CREATE TABLE analytics.views_daily (
    publication_id  BIGINT NOT NULL REFERENCES core.publications(id) ON DELETE CASCADE,
    collected_at    DATE NOT NULL,
    views           INT NOT NULL,
    PRIMARY KEY (publication_id, collected_at)
);

CREATE TABLE analytics.channel_stats (
    channel_id    BIGINT PRIMARY KEY REFERENCES core.channels(id) ON DELETE CASCADE,
    files_count   INT NOT NULL DEFAULT 0,
    views_total   INT NOT NULL DEFAULT 0,
    clients_total INT NOT NULL DEFAULT 0,
    blocked_total INT NOT NULL DEFAULT 0,
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analytics.events (
    id           BIGSERIAL PRIMARY KEY,
    channel_id   BIGINT REFERENCES core.channels(id) ON DELETE SET NULL,
    client_id    BIGINT REFERENCES core.clients(id) ON DELETE SET NULL,
    event_type   TEXT NOT NULL,
    details      JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (event_type IN (
        'client_join',
        'client_leave',
        'invite_used',
        'file_posted',
        'file_deleted',
        'sync_run'
    ))
);

-- Представление: профиль пользователя
CREATE OR REPLACE VIEW analytics.profile_overview AS
WITH subs AS (
    SELECT s.contractor_id, p.code AS plan_code, p.name AS plan_name,
           s.status, s.starts_at, s.expires_at, p.channels_limit_one_off
    FROM billing.subscriptions s
    JOIN billing.plans p ON p.id = s.plan_id
),
ch AS (
    SELECT contractor_id, COUNT(*) AS channels_cnt
    FROM core.channels
    GROUP BY contractor_id
),
pub AS (
    SELECT c.contractor_id,
           COUNT(p.id) AS files_cnt,
           COALESCE(SUM(p.views), 0) AS views_total
    FROM core.channels c
    LEFT JOIN core.publications p ON p.channel_id = c.id AND p.deleted = FALSE
    GROUP BY c.contractor_id
),
cl AS (
    SELECT c.contractor_id,
           COUNT(clt.id) AS clients_total,
           COALESCE(SUM(CASE WHEN clt.blocked THEN 1 ELSE 0 END), 0) AS blocked_total
    FROM core.channels c
    LEFT JOIN core.clients clt ON clt.channel_id = c.id
    GROUP BY c.contractor_id
),
inv AS (
    SELECT c.contractor_id,
           COUNT(i.id) AS invites_active
    FROM core.channels c
    LEFT JOIN core.invites i ON i.channel_id = c.id
    WHERE (i.expires_at IS NULL OR i.expires_at > now())
      AND (i.max_uses IS NULL OR i.used_count < i.max_uses)
    GROUP BY c.contractor_id
),
gift AS (
    SELECT contractor_id, COUNT(*) AS gifts_queued
    FROM billing.gifts_queue
    WHERE applied_at IS NULL
    GROUP BY contractor_id
),
useg AS (
    SELECT contractor_id, channels_created_total
    FROM billing.usage_counters
)
SELECT
  co.id AS contractor_id,
  co.tg_user_id,
  s.plan_code,
  s.plan_name,
  s.status AS sub_status,
  s.starts_at AS sub_starts_at,
  s.expires_at AS sub_expires_at,
  ch.channels_cnt,
  pub.files_cnt,
  pub.views_total,
  cl.clients_total,
  cl.blocked_total,
  inv.invites_active,
  CASE WHEN s.plan_code = 'FREE'
       THEN GREATEST(COALESCE(s.channels_limit_one_off,0) - COALESCE(useg.channels_created_total,0), 0)
       ELSE NULL
  END AS free_channels_left,
  COALESCE(gift.gifts_queued,0) AS gifts_queued
FROM core.contractors co
LEFT JOIN subs  s   ON s.contractor_id  = co.id
LEFT JOIN ch    ch  ON ch.contractor_id = co.id
LEFT JOIN pub   pub ON pub.contractor_id= co.id
LEFT JOIN cl    cl  ON cl.contractor_id = co.id
LEFT JOIN inv   inv ON inv.contractor_id= co.id
LEFT JOIN gift  gift ON gift.contractor_id=co.id
LEFT JOIN useg  useg ON useg.contractor_id=co.id;

-- Представление: прогресс реферальной программы
CREATE OR REPLACE VIEW analytics.profile_referral_progress AS
WITH base AS (
    SELECT r.referrer_id AS contractor_id,
           COUNT(DISTINCT r.referred_contractor_id) AS referred_total
    FROM referrals.referrals r
    GROUP BY r.referrer_id
),
qual AS (
    SELECT rp.referrer_id AS contractor_id,
           COUNT(*) FILTER (WHERE rp.qualified) AS qualified_total
    FROM referrals.referral_progress rp
    GROUP BY rp.referrer_id
),
cycle AS (
    SELECT DISTINCT ON (referrer_id)
           referrer_id AS contractor_id,
           cycle_no,
           qualified_refs_required,
           qualified_refs_done,
           state,
           created_at,
           completed_at
    FROM referrals.referral_cycles
    ORDER BY referrer_id, created_at DESC
),
gifts AS (
    SELECT contractor_id, COUNT(*) AS gifts_queued
    FROM billing.gifts_queue
    WHERE reason = 'referral_reward' AND applied_at IS NULL
    GROUP BY contractor_id
)
SELECT
    co.id AS contractor_id,
    COALESCE(base.referred_total, 0)   AS referred_total,
    COALESCE(qual.qualified_total, 0)  AS qualified_total,
    COALESCE(cycle.cycle_no, 1)        AS current_cycle_no,
    COALESCE(cycle.qualified_refs_done, 0)     AS current_cycle_done,
    COALESCE(cycle.qualified_refs_required, 3) AS current_cycle_required,
    COALESCE(cycle.state, 'in_progress')       AS current_cycle_state,
    COALESCE(gifts.gifts_queued, 0)            AS gifts_queued
FROM core.contractors co
LEFT JOIN base  ON base.contractor_id  = co.id
LEFT JOIN qual  ON qual.contractor_id  = co.id
LEFT JOIN cycle ON cycle.contractor_id = co.id
LEFT JOIN gifts ON gifts.contractor_id = co.id;

-- =====================================================================
-- 5. REFERRALS
-- =====================================================================

CREATE TABLE referrals.referral_links (
    contractor_id  BIGINT UNIQUE NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    token          TEXT UNIQUE NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE referrals.referrals (
    id                       BIGSERIAL PRIMARY KEY,
    referrer_id              BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    referred_contractor_id   BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (referrer_id, referred_contractor_id)
);

CREATE TABLE referrals.referral_progress (
    id                       BIGSERIAL PRIMARY KEY,
    referrer_id              BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    referred_contractor_id   BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    channels_created         INT NOT NULL DEFAULT 0,
    qualified                BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (referrer_id, referred_contractor_id)
);

CREATE TABLE referrals.referral_cycles (
    id                        BIGSERIAL PRIMARY KEY,
    referrer_id               BIGINT NOT NULL REFERENCES core.contractors(id) ON DELETE CASCADE,
    cycle_no                  INT NOT NULL,
    qualified_refs_required   INT NOT NULL DEFAULT 3,
    qualified_refs_done       INT NOT NULL DEFAULT 0,
    state                     TEXT NOT NULL DEFAULT 'in_progress',
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at              TIMESTAMPTZ,
    UNIQUE (referrer_id, cycle_no),
    CHECK (state IN ('in_progress','completed','reward_queued'))
);

-- =====================================================================
-- 6. ADMIN
-- =====================================================================

CREATE TABLE admin.admin_users (
    id         BIGSERIAL PRIMARY KEY,
    tg_user_id BIGINT UNIQUE NOT NULL,
    username   TEXT,
    role       TEXT NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (role IN ('support','manager','owner'))
);

CREATE TABLE admin.admin_actions (
    id           BIGSERIAL PRIMARY KEY,
    admin_id     BIGINT NOT NULL REFERENCES admin.admin_users(id) ON DELETE CASCADE,
    action       TEXT NOT NULL,
    target_type  TEXT,
    target_id    BIGINT,
    payload      JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- 7. Индексы для analytics/gifts (дополнительные)
-- =====================================================================
CREATE INDEX idx_gifts_queue_reason ON billing.gifts_queue(reason) WHERE applied_at IS NULL;
CREATE INDEX idx_events_channel_created ON analytics.events(channel_id, created_at DESC);

-- =====================================================================
-- 8. Первичное заполнение тарифов
-- =====================================================================
INSERT INTO billing.plans (code, name, price_month, features, channels_limit_one_off)
VALUES
    ('FREE',     'Free',     NULL, '{"can_edit_channel": false, "can_sync": false, "team_size": 1, "crm": false}'::jsonb, 5),
    ('PRO',      'Pro',      590.00, '{"can_edit_channel": true, "can_sync": true, "team_size": 1, "crm": false}'::jsonb, NULL),
    ('BUSINESS', 'Business',1490.00, '{"can_edit_channel": true, "can_sync": true, "team_size": 4, "crm": true}'::jsonb, NULL)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    price_month = EXCLUDED.price_month,
    features = EXCLUDED.features,
    channels_limit_one_off = EXCLUDED.channels_limit_one_off;

-- Done.
