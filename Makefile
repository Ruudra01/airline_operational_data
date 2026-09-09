# ===========================================================================
# Airline Data Platform - developer entry points (owner: Person 7, Platform)
#
#   make setup      spin up Postgres (OLTP + DW), apply all DDL/migrations
#   make seed       generate mock DL857 flights into the OLTP database
#   make extract    OLTP  -> stg_flight_ops   (raw copy, no cleaning)
#   make transform  staging -> clean DataFrame (validate/standardize/dedupe)
#   make load       clean DataFrame -> star schema (dimensions, then fact)
#   make test       pytest unit tests + warehouse referential-integrity SQL
#   make clean      tear down containers, volumes and generated artifacts
#
# Full happy path:
#   make setup && make seed && make extract && make transform && make load && make test
# ===========================================================================

SHELL := /bin/bash
PYTHON ?= python3
COMPOSE ?= docker compose

# Only used by the psql-* convenience targets; the Python code reads .env.
OLTP_DB_USER ?= airline
OLTP_DB_NAME ?= airline_oltp
DW_DB_USER   ?= airline
DW_DB_NAME   ?= airline_dw

# Every script imports `config` from the repo root, so put it on the path.
export PYTHONPATH := $(CURDIR)

.DEFAULT_GOAL := help
.PHONY: help env deps up down wait migrate setup seed extract transform load \
        test test-unit test-integrity ci clean logs psql-oltp psql-dw

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

deps: ## Install Python dependencies
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

up: env ## Start postgres_oltp, postgres_dw and adminer
	$(COMPOSE) up -d postgres_oltp postgres_dw adminer

down: ## Stop containers (keep volumes)
	$(COMPOSE) down

wait: ## Block until both databases accept connections
	$(PYTHON) scripts/wait_for_db.py

migrate: ## Apply OLTP migrations, staging DDL and warehouse DDL (idempotent)
	$(PYTHON) scripts/migrate.py --db oltp --dir oltp/migrations
	$(PYTHON) scripts/migrate.py --db oltp --dir elt/staging
	$(PYTHON) scripts/migrate.py --db dw   --dir warehouse/ddl

setup: env up wait migrate ## One-shot local bootstrap
	@echo "Adminer: http://localhost:8080  (server: postgres_oltp | postgres_dw)"

seed: ## Load mock DL857 operational data into the OLTP database
	$(PYTHON) oltp/seeds/generate_mock_data.py

extract: ## OLTP -> stg_flight_ops
	$(PYTHON) elt/extract/extract_to_staging.py

transform: ## staging -> cleaned/validated DataFrame (writes data/*.csv)
	$(PYTHON) elt/transform/main.py

load: ## cleaned DataFrame -> star schema (dims first, then fact)
	$(PYTHON) warehouse/load/load_warehouse.py

test: test-unit test-integrity ## Run everything CI runs

test-unit: ## Pytest unit tests
	$(PYTHON) -m pytest -q tests

test-integrity: ## Referential-integrity checks against the loaded warehouse
	$(PYTHON) scripts/check_integrity.py tests/test_integrity.sql

ci: migrate seed extract transform load test ## Pipeline used by GitHub Actions

logs: ## Tail database logs
	$(COMPOSE) logs -f postgres_oltp postgres_dw

psql-oltp: ## Interactive psql on the OLTP database
	$(COMPOSE) exec postgres_oltp psql -U $(OLTP_DB_USER) -d $(OLTP_DB_NAME)

psql-dw: ## Interactive psql on the warehouse
	$(COMPOSE) exec postgres_dw psql -U $(DW_DB_USER) -d $(DW_DB_NAME)

clean: ## Remove containers, volumes and generated artifacts
	-$(COMPOSE) down -v --remove-orphans
	rm -rf data/*.csv .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "clean"
