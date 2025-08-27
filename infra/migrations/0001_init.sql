-- Basic schema
CREATE TABLE IF NOT EXISTS owners (
  tg_user_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS contractors (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', -- active|frozen
  plan_id INT,
  quotas JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS contractor_users (
  id SERIAL PRIMARY KEY,
  contractor_id INT NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
  tg_user_id BIGINT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin' -- admin|operator
);

CREATE TABLE IF NOT EXISTS rooms (
  id SERIAL PRIMARY KEY,
  contractor_id INT NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
  tg_chat_id BIGINT NOT NULL,
  title TEXT NOT NULL,
  protected_content BOOLEAN NOT NULL DEFAULT TRUE,
  toc_msg_id BIGINT,
  client_user_id BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id SERIAL PRIMARY KEY,
  room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  version INT NOT NULL,
  jpg_count INT NOT NULL DEFAULT 1,
  watermark_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
  id SERIAL PRIMARY KEY,
  room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  msg_id BIGINT NOT NULL,
  page_no INT NOT NULL DEFAULT 1,
  views INT DEFAULT 0,
  last_views_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS invites (
  id SERIAL PRIMARY KEY,
  room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  invite_link TEXT NOT NULL,
  expire_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plans (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  limits JSONB NOT NULL DEFAULT '{}'::jsonb,
  price_minor INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stats_rollup_daily (
  room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  views_delta INT NOT NULL DEFAULT 0,
  joins INT NOT NULL DEFAULT 0,
  PRIMARY KEY (room_id, date)
);

CREATE TABLE IF NOT EXISTS audits (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_type TEXT NOT NULL, -- owner|contractor|system
  actor_id BIGINT,
  action TEXT NOT NULL,
  payload JSONB
);
