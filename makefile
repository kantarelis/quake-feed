# ===========================================================================
# quake-feed operator interface.
# Run `make help` to list every available target.
# ===========================================================================

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
ISORT := $(VENV)/bin/isort
BLACK := $(VENV)/bin/black
FLAKE8 := $(VENV)/bin/flake8
MYPY := $(VENV)/bin/mypy
BANDIT := $(VENV)/bin/bandit
VULTURE := $(VENV)/bin/vulture
PYTEST := $(VENV)/bin/pytest
COVERAGE_BADGE := $(VENV)/bin/coverage-badge
PYRIGHT := npx --yes pyright --pythonpath $(VENV)/bin/python

DOCKER := docker
COMPOSE := docker compose

# dbmate runs via the official Docker image so the host doesn't need a local
# install. --network host lets the container reach localhost ports (compose
# DB on 5432, sandbox DB on 5433). The database/ directory is mounted at /db
# read-write so `dbmate dump` (and `dbmate up`'s implicit schema dump) can
# update schema.sql. --user forces the container to write as the host user
# so generated files don't end up root-owned and immovable.
DBMATE_IMAGE := amacneil/dbmate:latest
DBMATE := $(DOCKER) run --rm \
	--user $(shell id -u):$(shell id -g) \
	--network host \
	-v $(PWD)/database:/db:rw \
	-w /db \
	-e DATABASE_URL \
	$(DBMATE_IMAGE)
DBMATE_FLAGS := --migrations-dir /db/migrations \
	--schema-file /db/schema.sql \
	--migrations-table public.schema_migrations

SRC := .

.DEFAULT_GOAL := help

.PHONY: help
help: ## List every available target
	@awk 'BEGIN {FS = ":.*?## "; print "Targets:"} \
		/^[a-zA-Z_-]+:.*?## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ===========================================================================
# Static analysis
# ===========================================================================

.PHONY: check format find-unused
check: ## Run all linters (isort, black, flake8, mypy, bandit, pyright)
	$(ISORT) --check $(SRC)
	$(BLACK) --check $(SRC)
	$(FLAKE8) $(SRC)
	$(MYPY) $(SRC)
	$(BANDIT) -r -c pyproject.toml $(SRC)
	$(PYRIGHT)

format: ## Auto-format with isort + black
	$(ISORT) $(SRC)
	$(BLACK) $(SRC)

find-unused: ## Run vulture to surface possible dead code
	$(VULTURE)

# ===========================================================================
# Tests
# ===========================================================================

.PHONY: test test-report coverage-badge
test: ## Run the full test suite (unit + integration). Needs Docker + internet.
	@$(PYTEST) --ignore=tests/integration; UNIT_RC=$$?; \
		$(PYTEST) -m integration tests/integration/; INT_RC=$$?; \
		if [ $$UNIT_RC -ne 0 ]; then exit $$UNIT_RC; fi; \
		exit $$INT_RC

test-report: ## Run the full suite, emit an HTML coverage report into htmlcov/, and open it in the default browser
	@rm -f .coverage; \
		$(PYTEST) --ignore=tests/integration --cov=. --cov-report=; UNIT_RC=$$?; \
		$(PYTEST) -m integration tests/integration/ --cov=. --cov-append --cov-report=html; INT_RC=$$?; \
		if [ -f htmlcov/index.html ]; then \
			if command -v xdg-open >/dev/null 2>&1; then \
				echo "Opening htmlcov/index.html in default browser..."; \
				xdg-open htmlcov/index.html >/dev/null 2>&1 & \
			else \
				echo "(xdg-open not found; open htmlcov/index.html manually)"; \
			fi; \
		fi; \
		if [ $$UNIT_RC -ne 0 ]; then exit $$UNIT_RC; fi; \
		exit $$INT_RC

coverage-badge: ## Generate coverage.svg from the latest coverage data
	$(COVERAGE_BADGE) -f -o coverage.svg

# ===========================================================================
# Environment / dependencies
# ===========================================================================

.PHONY: install-env install install-test install-dev
install-env: ## Create .env from .env.template if missing (never overwrites)
	@if [ -f .env ]; then \
		echo ".env already exists; not overwriting."; \
	else \
		cp .env.template .env && echo "Created .env from .env.template."; \
	fi

install: ## Install runtime dependencies into the active env
	$(PIP) install -r requirements.txt

install-test: ## Install runtime + test/lint dependencies
	$(PIP) install -r requirements-test.txt

install-dev: ## Install runtime + test + ipython
	$(PIP) install -r requirements-dev.txt

# ===========================================================================
# Docker / Compose
# ===========================================================================

.PHONY: build up down restart logs status clean clean-logs full-clean prune reset
build: ## Build the application image via docker compose
	$(COMPOSE) build

up: install-env ## Bring the full stack up (creates .env if missing)
	$(COMPOSE) up -d

down: ## Stop and remove containers (named volumes preserved)
	$(COMPOSE) down

restart: down build up ## Bring the stack down, rebuild the app image, and back up

logs: ## Tail aggregated container logs
	$(COMPOSE) logs -f

status: ## Show compose container status
	$(COMPOSE) ps

clean: ## Stop & remove containers + orphan networks (volumes preserved)
	$(COMPOSE) down --remove-orphans

clean-logs: ## Truncate live container log files (may require sudo)
	@for c in $$($(DOCKER) ps -aq 2>/dev/null); do \
		path=$$($(DOCKER) inspect --format='{{.LogPath}}' $$c 2>/dev/null); \
		[ -z "$$path" ] && continue; \
		: > "$$path" 2>/dev/null || sudo truncate -s 0 "$$path" 2>/dev/null || true; \
	done
	@echo "Container log files truncated where permissions allowed."

full-clean: ## Remove containers + networks + NAMED VOLUMES (destructive)
	$(COMPOSE) down -v --remove-orphans

prune: ## Reclaim disk: prune stopped containers, unused networks, dangling images
	$(DOCKER) system prune -f

reset: full-clean build up ## Nuke everything, rebuild the image, bring the stack back up

# ===========================================================================
# Vault (dev-mode container)
# `vault server -dev` auto-initializes/unseals, so init/unseal/seal are no-ops
# in the current compose setup. The targets exist so the operator interface
# stays stable when/if Vault flips to production mode.
# ===========================================================================

.PHONY: vault-status vault-init vault-unseal vault-seal
vault-status: ## Show seal/init status of the running Vault container
	@$(DOCKER) exec quake_vault vault status || true

vault-init: ## Initialize Vault; writes keys to vault_init_output.txt (gitignored)
	@$(DOCKER) exec quake_vault vault operator init -key-shares=5 -key-threshold=3 > vault_init_output.txt
	@echo "Init output saved to vault_init_output.txt. Update .env with the unseal keys + root token."

vault-unseal: ## Unseal Vault using VAULT_UNSEAL_KEYS from .env
	@set -a; . ./.env; set +a; \
	if [ -z "$$VAULT_UNSEAL_KEYS" ]; then \
		echo "VAULT_UNSEAL_KEYS empty in .env; run 'make vault-init' first."; exit 1; \
	fi; \
	IFS=','; for k in $$VAULT_UNSEAL_KEYS; do \
		$(DOCKER) exec quake_vault vault operator unseal "$$k"; \
	done

vault-seal: ## Seal Vault (requires VAULT_TOKEN in .env)
	@set -a; . ./.env; set +a; \
	$(DOCKER) exec -e VAULT_TOKEN="$$VAULT_TOKEN" quake_vault vault operator seal

# ===========================================================================
# Database migrations (dbmate)
# `db-migrate` and `db-schema` target the running compose DB.
# `migrate-test` spins up a throwaway TimescaleDB on :5433 and exercises the
# full migration cycle (up -> down -> up) to validate that every migration
# is reversible and re-appliable. Cleanup runs via trap even on failure.
# ===========================================================================

.PHONY: db-migrate migrate-test db-schema
db-migrate: ## Apply pending migrations to the local DB
	@set -a; . ./.env; set +a; \
	DATABASE_URL="postgres://$$DB_USERNAME:$$DB_PASSWORD@127.0.0.1:$$DB_PORT/$$DB_NAME?sslmode=disable" \
	$(DBMATE) $(DBMATE_FLAGS) up

migrate-test: ## Sandbox-test migrations on a throwaway TimescaleDB on :5433
	@set -e; \
	trap "$(DOCKER) rm -f quake_migrate_test >/dev/null 2>&1 || true" EXIT; \
	$(DOCKER) rm -f quake_migrate_test >/dev/null 2>&1 || true; \
	echo "==> Starting throwaway TimescaleDB on :5433..."; \
	$(DOCKER) run -d --name quake_migrate_test \
		-e POSTGRES_USER=quake \
		-e POSTGRES_PASSWORD=quake \
		-e POSTGRES_DB=quake-db \
		-p 5433:5432 \
		timescale/timescaledb:latest-pg18 >/dev/null; \
	echo "==> Waiting for DB to accept TCP connections..."; \
	ready=0; \
	for i in $$(seq 1 60); do \
		if $(DOCKER) exec quake_migrate_test pg_isready -h 127.0.0.1 -U quake -d quake-db >/dev/null 2>&1; then \
			ready=1; echo "    DB ready after $${i}s."; break; \
		fi; \
		sleep 1; \
	done; \
	if [ $$ready -eq 0 ]; then echo "    DB never accepted TCP within 60s."; exit 1; fi; \
	export DATABASE_URL="postgres://quake:quake@127.0.0.1:5433/quake-db?sslmode=disable"; \
	echo "==> dbmate up (cold start)..."; \
	$(DBMATE) $(DBMATE_FLAGS) up; \
	echo "==> dbmate down (roll back newest migration)..."; \
	$(DBMATE) $(DBMATE_FLAGS) down; \
	echo "==> dbmate up (re-apply newest migration)..."; \
	$(DBMATE) $(DBMATE_FLAGS) up; \
	echo "==> Sandbox migration test PASSED."

db-schema: ## Dump local schema to database/schema.sql (gitignored) and prettify in place
	@set -a; . ./.env; set +a; \
	DATABASE_URL="postgres://$$DB_USERNAME:$$DB_PASSWORD@127.0.0.1:$$DB_PORT/$$DB_NAME?sslmode=disable" \
	$(DBMATE) $(DBMATE_FLAGS) dump
	$(PY) -m database._pretty_schema

# ===========================================================================
# API keys (Epic 5 placeholders)
# ===========================================================================

.PHONY: issue-api-key revoke-api-key
issue-api-key: ## (stub) Mint a new API key into Vault
	@echo "not yet implemented (Epic 5)"

revoke-api-key: ## (stub) Revoke an existing API key
	@echo "not yet implemented (Epic 5)"

# ===========================================================================
# Frontend (Epic 7 placeholders)
# ===========================================================================

.PHONY: frontend-install frontend-dev frontend-build
frontend-install: ## (stub) npm install in frontend/
	@echo "not yet implemented (Epic 7)"

frontend-dev: ## (stub) Vite dev server proxied to backend
	@echo "not yet implemented (Epic 7)"

frontend-build: ## (stub) Production frontend build
	@echo "not yet implemented (Epic 7)"
