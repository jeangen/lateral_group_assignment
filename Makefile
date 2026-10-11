.DEFAULT_GOAL := help
SHELL := /bin/bash

PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: help setup run test record-fixtures clean

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

$(BIN)/activate: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -e ".[dev]"
	@touch $(BIN)/activate

setup: $(BIN)/activate ## Create virtualenv and install dependencies

run: setup ## Run the full pipeline: ingest -> transform -> export
	@echo "TODO: pipeline entrypoint (plan task 4)"

test: setup ## Run tests (offline, fixtures only)
	$(BIN)/pytest

record-fixtures: setup ## Record live API responses into tests/fixtures/recorded (needs network)
	$(BIN)/python scripts/record_fixtures.py

clean: ## Remove local warehouse, dbt artifacts and virtualenv
	rm -rf data/*.duckdb* transform/target transform/logs $(VENV)
