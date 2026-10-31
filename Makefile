# Makefile for evoflux

.PHONY: all run dev dev-web dev-desktop kill-dev-ports test contract contract-all replay-diff perf perf-responsiveness perf-baseline validate-skills coverage migrate revision build-web build dist clean help

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

contract: ## Run one area of the black-box contract suite (usage: make contract AREA=health TARGET=python|rust|gateway)
	@test -n "$(AREA)" || { echo "error: set AREA=<directory under contract-tests/>"; exit 1; }
	TARGET=$(or $(TARGET),python) uv run --group contract pytest contract-tests/$(AREA) -q --no-cov

contract-all: ## Run the whole contract suite against one backend (usage: make contract-all TARGET=python|rust|gateway)
	TARGET=$(or $(TARGET),python) uv run --group contract pytest contract-tests -q --no-cov

shadow: ## Replay recorded GETs of one unit through a running shadow-mode gateway (usage: make shadow UNIT=<unit> RECORDINGS=<dir> STATE_DIR=<dir> BASE_URL=<url> [TOKEN=<t>])
	@test -n "$(UNIT)" -a -n "$(RECORDINGS)" -a -n "$(STATE_DIR)" -a -n "$(BASE_URL)" || { echo "error: set UNIT, RECORDINGS, STATE_DIR and BASE_URL"; exit 1; }
	uv run python scripts/migration/shadow_replay.py "$(UNIT)" --recordings "$(RECORDINGS)" --state-dir "$(STATE_DIR)" --base-url "$(BASE_URL)" --token "$(TOKEN)"

replay-diff: ## Compare a unit's contract requests and optional GET recordings (UNIT, OUT, optional RECORDINGS and NOISE=1)
	@test -n "$(UNIT)" -a -n "$(OUT)" || { echo "error: set UNIT and OUT"; exit 1; }
	uv run --group contract python scripts/migration/replay_diff.py "$(UNIT)" --out "$(OUT)" $(if $(RECORDINGS),--recordings "$(RECORDINGS)") $(if $(filter 1,$(NOISE)),--noise)

scrub: ## Remove secrets and PII from a recording in place (usage: make scrub FILE=<recording.jsonl>)
	@test -n "$(FILE)" || { echo "error: set FILE=<recording.jsonl>"; exit 1; }
	uv run python scripts/migration/scrub.py "$(FILE)"

perf: ## Compare endpoint p99, cold start and memory with baseline-v3.1.1.json (usage: make perf AREA=health|all TARGET=python|rust|gateway)
	uv run --group contract python contract-tests/perf/bench_endpoints.py compare --target $(or $(TARGET),python) --area $(or $(AREA),all)

perf-responsiveness: ## Run the freeze gate: /api/health/live and history latency under heavy load (usage: make perf-responsiveness TARGET=python|rust|gateway)
	TARGET=$(or $(TARGET),python) uv run --group contract pytest contract-tests/perf -q --no-cov

perf-baseline: ## Re-record baseline-v3.1.1.json from Python on this machine (usage: make perf-baseline MACHINE="<name>")
	@test -n "$(MACHINE)" || { echo "error: set MACHINE=<reference machine name>"; exit 1; }
	uv run --group contract python contract-tests/perf/bench_endpoints.py record --target python --machine "$(MACHINE)"

validate-skills: ## Check bundled Agent Skills against the spec and best practices
	uv run python scripts/validate_skills.py --strict-warnings

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

.PHONY: gates
gates: ## Run migration gates (usage: make gates AREA=shared)
	bash scripts/migration/gates.sh "$(AREA)"

.PHONY: db-compat
db-compat: ## Run SQLite compatibility and two-process stress gates
	cd server && cargo build -p evoflux-core --example db_stress
	uv run --group contract pytest contract-tests/db -q --no-cov
