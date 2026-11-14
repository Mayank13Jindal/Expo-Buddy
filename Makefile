SHELL := /bin/bash
PYTHON := .venv/bin/python
COMPOSE := docker compose -f docker-compose.yml $(if $(wildcard docker-compose.override.yml),-f docker-compose.override.yml,) $(if $(wildcard .local/compose.proxy.yml),-f .local/compose.proxy.yml,) $(if $(wildcard deploy/https.local.yml),-f deploy/https.local.yml,)
.PHONY: init-dev check-storage up stop down test test-backend test-frontend test-integration lint build dev-install probe models openapi e2e backup restore reset-password sample-export verify-upload-limits

init-dev:
	python3 scripts/setup.py --development
check-storage:
	bash scripts/check-storage.sh
up: check-storage
	$(COMPOSE) up -d --build --wait --wait-timeout 180
stop:
	$(COMPOSE) stop
down:
	$(COMPOSE) down
dev-install:
	uv venv .venv --python 3.12
	uv pip sync --python $(PYTHON) backend/requirements-dev.lock
	cd frontend && npm ci
test: lint test-backend test-frontend
lint:
	.venv/bin/ruff check backend
	cd frontend && npm run typecheck
test-backend:
	cd backend && ../$(PYTHON) -m pytest -m 'not integration' -q
test-frontend:
	cd frontend && npm test
test-integration:
	cd backend && ../$(PYTHON) -m pytest -m integration -q
build:
	$(COMPOSE) build
probe:
	$(PYTHON) scripts/probe_providers.py
models:
	python3 scripts/download_models.py --kind ocr
openapi:
	$(COMPOSE) exec -T api python -c 'from app.main import create_app; import json; print(json.dumps(create_app().openapi(), indent=2))' > backend/openapi.json
	cd frontend && npm run generate-api
e2e:
	cd frontend && npm run e2e
backup:
	$(COMPOSE) exec -T worker python -m app.worker.backup
restore:
	python3 scripts/restore.py $(BACKUP) $(if $(DATABASE),--database $(DATABASE),)
reset-password:
	$(COMPOSE) exec api python -m app.core.reset_password

sample-export:
	$(PYTHON) scripts/generate_sample_export.py

verify-upload-limits:
	$(PYTHON) scripts/verify-upload-limits.py

