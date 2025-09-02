COMPOSE ?= docker compose

.PHONY: up down ps logs logs-userbot logs-bot restart-bot restart-userbot build

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-userbot:
	$(COMPOSE) logs -f userbot

logs-bot:
	$(COMPOSE) logs -f bot

restart-bot:
	$(COMPOSE) restart bot

restart-userbot:
	$(COMPOSE) restart userbot

build:
	$(COMPOSE) build --no-cache
