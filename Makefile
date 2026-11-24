SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: help install dev test test-integration test-all-versions \
        lint format docker-build lock-deps pg-install pg-uninstall clean

PG_VERSION ?= 17
PG_CONFIG  ?= pg_config
EXT_NAME    = pg_purr
EXT_VERSION = 0.2.0
SHAREDIR    = $(shell $(PG_CONFIG) --sharedir 2>/dev/null)
EXTDIR      = $(SHAREDIR)/extension
COMPOSE     = docker compose -f docker/docker-compose.test.yaml

# Lock against the same Python minor that plpython3u uses in the image
# (Debian trixie ships Python 3.13).
LOCK_IMAGE        ?= python:3.13-slim-trixie
PIP_TOOLS_VERSION ?= 7.7.0
LOCK_ARGS         ?=

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	    | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install pg_purr Python package in editable mode
	pip install -e .

dev: ## Install with dev dependencies
	pip install -e ".[dev]"

test: ## Run unit tests
	python -m pytest tests/ -v -m "not integration"

test-integration: ## Run integration tests (PG_VERSION=17|18)
	trap 'PG_VERSION=$(PG_VERSION) $(COMPOSE) down -v --remove-orphans' EXIT
	PG_VERSION=$(PG_VERSION) $(COMPOSE) up -d --build --wait
	docker exec -e PGPORT=5432 pg-purr-test \
	    /opt/pg_purr/.venv/bin/python -m pytest /opt/pg_purr/tests/test_integration.py -v

test-all-versions: ## Run integration tests against all supported PG versions
	@for v in 17 18; do \
	    echo "=== Testing PostgreSQL $$v ==="; \
	    $(MAKE) test-integration PG_VERSION=$$v || exit 1; \
	done

lint: ## Run linters and format check
	ruff check pg_purr/ tests/
	ruff format --check pg_purr/ tests/

format: ## Auto-format code with ruff
	ruff format pg_purr/ tests/

docker-build: ## Build the pg_purr Docker image
	docker build -f docker/Dockerfile --target runtime \
	    --build-arg PG_VERSION=$(PG_VERSION) \
	    -t pg_purr:$(PG_VERSION) .

lock-deps: ## Regenerate hash-pinned requirements (LOCK_ARGS=--upgrade to bump all)
	docker run --rm --user "$$(id -u):$$(id -g)" -e HOME=/tmp \
	    -v "$(CURDIR):/src" -w /src $(LOCK_IMAGE) sh -euc '\
	    python -m pip install --quiet --user pip-tools==$(PIP_TOOLS_VERSION); \
	    export PATH="$$HOME/.local/bin:$$PATH"; \
	    pip-compile --quiet $(LOCK_ARGS) --generate-hashes --allow-unsafe --strip-extras \
	        --output-file=docker/requirements.txt pyproject.toml; \
	    pip-compile --quiet $(LOCK_ARGS) --generate-hashes --allow-unsafe --strip-extras \
	        --extra=dev --output-file=docker/requirements-dev.txt pyproject.toml'

pg-install: ## Install extension files into $(pg_config --sharedir)/extension
	@test -n "$(SHAREDIR)" || { echo "pg_config not found in PATH"; exit 1; }
	install -m 0644 pg_purr.control $(EXTDIR)/
	install -m 0644 sql/extension/$(EXT_NAME)--*.sql $(EXTDIR)/
	@echo "Installed. Run: CREATE EXTENSION pg_purr; (or ALTER EXTENSION pg_purr UPDATE)"

pg-uninstall: ## Remove extension files from the PG share dir
	@test -n "$(SHAREDIR)" || { echo "pg_config not found in PATH"; exit 1; }
	rm -f $(EXTDIR)/$(EXT_NAME).control
	rm -f $(EXTDIR)/$(EXT_NAME)--*.sql

clean: ## Remove build artefacts
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
