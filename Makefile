# Developer loop.
#
# Windows users without `make` have an equivalent at ./task.ps1 - every target
# here has a matching command there, and CI exercises this file so the two do
# not drift silently.

.DEFAULT_GOAL := help
.PHONY: help setup up down logs dev web seed demo test lint fmt typecheck check evals redteam governance clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python and Node dependencies
	uv sync --all-packages
	npm install

up: ## Start the local data and observability plane
	docker compose up -d
	@echo "postgres :5432  redis :6379  prometheus :9090  grafana :3002"

down: ## Stop the local plane, keeping volumes
	docker compose down

logs: ## Tail the local plane
	docker compose logs -f --tail=100

dev: ## Run the API with reload
	uv run uvicorn backstop_api.main:create_app --factory --reload --host 0.0.0.0 --port 8000

web: ## Run the console
	npm run dev --workspace @backstop/web

seed: ## Write the synthetic dataset to seed-data/generated
	uv run python scripts/seed.py

demo: ## Resolve one ticket end to end through the tool gateway
	uv run python scripts/demo_ticket.py

test: ## Run the test suite
	uv run pytest --cov --cov-report=term-missing

lint: ## Lint
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Format
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Type check
	uv run mypy apps packages mcp-servers

check: lint typecheck test ## Everything CI runs

evals: ## Run the golden set (add ARGS=--live to score a real model)
	uv run python -m evals.runners.golden $(ARGS)

redteam: ## Run the attack corpus
	uv run python -m evals.runners.redteam

governance: ## Check prompt hashes, rule citations and planted ambiguities
	uv run python scripts/check_governance.py all

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
