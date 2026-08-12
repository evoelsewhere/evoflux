# Makefile for evoflux

.PHONY: all run dev dev-web dev-desktop kill-dev-ports test coverage migrate revision build-web build dist clean help

# Default target
all: test

DEV_API_PORT ?= 8000

run: ## Start the API server only (no reload, no frontend; :8000)
	uv run uvicorn app.server:app --no-access-log

kill-dev-ports: ## Stop processes listening on dev ports (:8000, :5173)
	@command -v lsof >/dev/null 2>&1 || { echo "error: 'lsof' not found"; exit 1; }
	@for port in $(DEV_API_PORT) 5173; do \
		pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN); \
		if [ -n "$$pids" ]; then \
			echo "stopping processes on port $$port: $$pids"; \
			kill $$pids; \
			for i in 1 2 3 4 5; do \
				sleep 0.2; \
				pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN); \
				[ -z "$$pids" ] && break; \
			done; \
			pids=$$(lsof -tiTCP:$$port -sTCP:LISTEN); \
			if [ -n "$$pids" ]; then \
				echo "force stopping processes on port $$port: $$pids"; \
				kill -9 $$pids; \
			fi; \
		fi; \
	done

dev: dev-web ## Start web development mode (alias for dev-web)

dev-web: ## Start backend (:8000 + reload) and web UI (Vite :5173)
	@command -v uv >/dev/null 2>&1 || { echo "error: 'uv' not found — install from https://docs.astral.sh/uv/"; exit 1; }
	@uv run python scripts/run_dev.py --api-port $(DEV_API_PORT)

dev-desktop: ## Start backend, web UI, and Tauri desktop app
	@command -v uv >/dev/null 2>&1 || { echo "error: 'uv' not found — install from https://docs.astral.sh/uv/"; exit 1; }
	@uv run python scripts/run_dev.py --api-port $(DEV_API_PORT) --desktop

test: ## Run tests
	uv run pytest -q

coverage: ## Run tests with coverage report
	uv run pytest --cov=app --cov-report=term-missing tests/

migrate: ## Run Alembic migrations (dev only — production auto-migrates on startup)
	uv run alembic -c app/alembic.ini upgrade head

revision: ## Create a new Alembic revision (usage: make revision MSG="message")
	uv run alembic -c app/alembic.ini revision --autogenerate -m "$(MSG)"

build-web: ## Build web UI into web/dist/ for desktop packaging
	cd web && bun install && bun run build

build: ## Build Python wheel (API server only)
	uv build

dist: build ## Alias for build

clean: ## Remove build and cache artifacts
	rm -rf .pytest_cache .ruff_cache .coverage .ty_cache htmlcov
	rm -rf web/dist dist
	find . -type d -name "__pycache__" -exec rm -rf {} +

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
