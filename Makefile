.PHONY: up down logs fmt lint migrate

up:
\tdocker compose up -d --build

down:
\tdocker compose down -v

logs:
\tdocker compose logs -f --tail=200

fmt:
\tblack backend bot userbot worker || true

migrate:
\t@echo "Migrations are auto-applied by Postgres init scripts in infra/migrations"
