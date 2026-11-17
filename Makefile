PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
SAATHI_COMPOSE := docker compose --env-file .env -f apps/saathi/docker-compose.yml
HIREFINCH_COMPOSE := docker compose --env-file .env -f apps/hirefinch/docker-compose.yml
HIREFINCH_BACKEND := apps/hirefinch/backend

.PHONY: install test lint saathi-up saathi-down saathi-logs saathi-frontend-build \
	hirefinch-migrate hirefinch-api hirefinch-web hirefinch-test hirefinch-frontend-build hirefinch-up hirefinch-down hirefinch-logs hirefinch-prod-up \
	hirefinch-deploy hirefinch-backup hirefinch-check hirefinch-extension hirefinch-home-up hirefinch-home-down hirefinch-home-logs

install:  ## Create .venv and install every Python package in editable mode
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements-dev.txt

test:  ## Run the Python tests of every package
	$(BIN)/pytest -q

lint:  ## Check every Python package with ruff
	$(BIN)/ruff check apps libs

saathi-up:  ## Build and start Saathi (db + backend + frontend) on http://localhost:8080
	$(SAATHI_COMPOSE) up --build -d

saathi-down:  ## Stop Saathi (data is kept in the saathi-pgdata volume)
	$(SAATHI_COMPOSE) down

saathi-logs:  ## Follow Saathi logs (development OTP codes appear here)
	$(SAATHI_COMPOSE) logs -f backend

saathi-frontend-build:  ## Type-check and build the React app (runs in a node container)
	docker run --rm --user $$(id -u):$$(id -g) -e HOME=/tmp -v "$$PWD/apps/saathi/frontend":/app -w /app node:22-alpine \
		sh -c "npm ci --no-audit --no-fund && npm run build"

hirefinch-migrate:  ## Create/upgrade the hirefinch database (SQLite in apps/hirefinch/data by default)
	cd $(HIREFINCH_BACKEND) && ../../../$(BIN)/alembic upgrade head

hirefinch-api: hirefinch-migrate  ## Run the hirefinch API on http://127.0.0.1:8000 (localhost only)
	$(BIN)/uvicorn --factory hirefinch.app:create_app --host 127.0.0.1 --port 8000

hirefinch-web:  ## Run the hirefinch UI dev server on http://localhost:5173 (needs hirefinch-api)
	docker run --rm -it --user $$(id -u):$$(id -g) -e HOME=/tmp --network host -v "$$PWD/apps/hirefinch/frontend":/app -w /app node:22-alpine \
		sh -c "npm ci --no-audit --no-fund && npx vite --host 127.0.0.1"

hirefinch-test:  ## Run the hirefinch tests (mocked sources and email; nothing is sent)
	$(BIN)/pytest -q $(HIREFINCH_BACKEND)/tests

hirefinch-frontend-build: hirefinch-extension  ## Type-check and build the hirefinch React app (runs in a node container)
	docker run --rm --user $$(id -u):$$(id -g) -e HOME=/tmp -v "$$PWD/apps/hirefinch/frontend":/app -w /app node:22-alpine \
		sh -c "npm ci --no-audit --no-fund && npm run build"

hirefinch-up:  ## Build and start hirefinch (PostgreSQL + API + UI) on http://localhost:8090
	$(HIREFINCH_COMPOSE) up --build -d

hirefinch-down:  ## Stop hirefinch (data is kept in the hirefinch-* volumes)
	$(HIREFINCH_COMPOSE) down

hirefinch-logs:  ## Follow hirefinch backend logs
	$(HIREFINCH_COMPOSE) logs -f backend

hirefinch-prod-up:  ## Production: PostgreSQL + API + UI behind Caddy (HTTPS for HIREFINCH_DOMAIN)
	$(HIREFINCH_COMPOSE) -f apps/hirefinch/docker-compose.prod.yml up --build -d

hirefinch-home-up: hirefinch-frontend-build  ## Share hirefinch from this PC; restarts on its own, also after a reboot
	apps/hirefinch/deploy/home-up.sh

hirefinch-home-down:  ## Stop the hirefinch services shared from this PC
	HOME_UID=$$(id -u) HOME_GID=$$(id -g) docker compose -f apps/hirefinch/docker-compose.home.yml --profile tailscale --profile cloudflare down

hirefinch-home-logs:  ## Follow the logs of the hirefinch services shared from this PC
	HOME_UID=$$(id -u) HOME_GID=$$(id -g) docker compose -f apps/hirefinch/docker-compose.home.yml --profile tailscale --profile cloudflare logs -f --tail 50

hirefinch-extension:  ## Zip the browser extension into the web app (served at /hirefinch-extension.zip)
	apps/hirefinch/deploy/build-extension.sh

hirefinch-check: hirefinch-test hirefinch-frontend-build  ## Everything CI runs: backend tests, then UI type-check, build and tests
	docker run --rm --user $$(id -u):$$(id -g) -e HOME=/tmp -v "$$PWD/apps/hirefinch":/hf -w /hf/frontend node:22-alpine npx vitest run --maxWorkers=4  # extension tests import ../extension; fewer workers keep this PC responsive

hirefinch-deploy: hirefinch-check  ## Run the checks, then deploy to TARGET=user@host (on the server itself: apps/hirefinch/deploy/deploy.sh)
	@test -n "$(TARGET)" || { echo "set TARGET=user@host"; exit 1; }
	apps/hirefinch/deploy/deploy.sh $(TARGET)

hirefinch-backup:  ## Production: back up database + files to ./backups (keeps 14 days)
	apps/hirefinch/deploy/backup.sh
