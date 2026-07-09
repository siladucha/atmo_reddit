# Reddit SaaS — Docker Commands
# ================================
# Quick reference for working with Docker containers and data.

.PHONY: up down restart logs build db-dump db-restore db-shell app-shell health

# --- Container Lifecycle ---

up:  ## Start all containers (detached)
	docker compose up -d

dev:  ## Start with hot-reload (mounts source, no rebuild needed)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

dev-d:  ## Start with hot-reload in background
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

down:  ## Stop all containers (preserves data volume)
	docker compose down

down-clean:  ## Stop all containers AND delete data volume (DESTRUCTIVE)
	docker compose down -v

restart:  ## Restart app container (after code changes)
	docker compose build app && docker compose up -d app

restart-all:  ## Rebuild and restart all containers
	docker compose build && docker compose up -d

build:  ## Build images without starting
	docker compose build

logs:  ## Tail all container logs
	docker compose logs -f --tail=50

logs-app:  ## Tail app container logs only
	docker compose logs -f --tail=50 app

# --- Database Operations ---

DB_CONTAINER = reddit_saas-db-1
DB_USER = reddit_saas_user
DB_NAME = reddit_saas
DUMP_FILE = /tmp/reddit_saas_dump.custom

db-dump-local:  ## Dump LOCAL PostgreSQL to file (for import into Docker)
	pg_dump -h localhost -U user -d $(DB_NAME) --no-owner --no-acl --format=custom -f $(DUMP_FILE)
	@echo "Dump saved to $(DUMP_FILE)"

db-restore-to-docker:  ## Restore dump file into Docker PostgreSQL
	docker compose cp $(DUMP_FILE) db:/tmp/dump.custom
	docker compose exec db pg_restore -U $(DB_USER) -d $(DB_NAME) --clean --if-exists --no-owner --no-acl /tmp/dump.custom
	docker compose restart app
	@echo "Data restored. App restarted."

db-dump-docker:  ## Dump Docker PostgreSQL to file (backup)
	docker compose exec db pg_dump -U $(DB_USER) -d $(DB_NAME) --no-owner --no-acl --format=custom -f /tmp/dump.custom
	docker compose cp db:/tmp/dump.custom $(DUMP_FILE)
	@echo "Docker DB dumped to $(DUMP_FILE)"

db-sync:  ## Full sync: dump local → restore to Docker → restart app
	$(MAKE) db-dump-local
	$(MAKE) db-restore-to-docker

db-shell:  ## Open psql shell inside Docker PostgreSQL
	docker compose exec db psql -U $(DB_USER) -d $(DB_NAME)

db-tables:  ## List all tables and row counts in Docker DB
	docker compose exec db psql -U $(DB_USER) -d $(DB_NAME) -c "\
		SELECT schemaname, relname as table, n_live_tup as rows \
		FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"

# --- App Operations ---

app-shell:  ## Open bash shell inside app container
	docker compose exec app bash

health:  ## Check app health endpoint
	@curl -s http://localhost:8000/health | python3 -m json.tool

status:  ## Show container status
	docker compose ps

# --- Development Workflow ---

fresh-start:  ## Clean start: rebuild + sync local DB data
	docker compose down -v
	docker compose build
	docker compose up -d
	@echo "Waiting for DB to be healthy..."
	@sleep 10
	$(MAKE) db-sync
	@echo "Fresh start complete. App running at http://localhost:8000"

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help

# --- Pre-Flight & Deployment ---

preflight:  ## Run agent pre-flight checks (Phase 1 of deploy protocol)
	python3 scripts/agent_preflight.py

preflight-all:  ## Run pre-flight on ALL app/ files
	python3 scripts/agent_preflight.py --all

deploy:  ## Smart deploy — auto-detect changes, deploy only what's needed
	./deploy.sh auto

deploy-app:  ## Deploy main app only (app + celery + celery-beat)
	./deploy.sh app

deploy-mkt:  ## Deploy marketing site only
	./deploy.sh marketing

deploy-nginx:  ## Reload nginx config (zero downtime)
	./deploy.sh nginx

deploy-all:  ## Full rebuild and deploy everything
	./deploy.sh all

deploy-status:  ## Show container status on server
	./deploy.sh status

server-logs:  ## Tail production logs (all services)
	ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50"

server-logs-app:  ## Tail production app logs only
	ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50 app"

# --- UI Observability ---

lint-ui:  ## Run UI lint checks (inline styles, arbitrary Tailwind, markers)
	python3 scripts/lint_ui.py app/templates/ --allowlist ui_lint_allowlist.txt

generate-ui-map:  ## Auto-generate UI_MAP.md from template scanning
	python3 scripts/generate_ui_map.py --output ../UI_MAP.md
	@echo "UI_MAP.md regenerated"

validate-specs:  ## Validate screen spec YAML files
	python3 scripts/validate_screen_specs.py docs/screen_specs/

ci-ui:  ## Run all UI compliance checks (lint + drift + specs)
	@echo "=== UI Lint ==="
	python3 scripts/lint_ui.py app/templates/ --allowlist ui_lint_allowlist.txt
	@echo "=== UI MAP Drift Check ==="
	python3 scripts/generate_ui_map.py --check --output ../UI_MAP.md
	@echo "=== Screen Spec Validation ==="
	python3 scripts/validate_screen_specs.py docs/screen_specs/
	@echo "=== All UI checks passed ==="

# UX Manual coverage verification
verify-manual:
	@python scripts/verify_manual_coverage.py
