.PHONY: up down rebuild logs-bot logs-userbot ps

up:
	docker compose up -d userbot backend bot worker

down:
	docker compose down

rebuild:
	docker compose build --no-cache userbot backend bot worker
	docker compose up -d userbot backend bot worker

logs-bot:
	docker compose logs -f --tail=200 bot

logs-userbot:
	docker compose logs -f --tail=200 userbot

ps:
	docker compose ps

# --- Dev shortcuts (use .env.dev) ---
.PHONY: dev-up dev-down dev-rebuild dev-logs-bot dev-logs-userbot dev-ps

dev-up:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d userbot backend bot worker

dev-down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down

dev-rebuild:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml build --no-cache userbot backend bot worker
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d userbot backend bot worker

dev-logs-bot:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f --tail=200 bot

dev-logs-userbot:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f --tail=200 userbot

dev-ps:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
