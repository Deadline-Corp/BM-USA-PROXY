.PHONY: help up down logs seed migrate revision test lint typecheck fmt install

help:
	@echo "up        - start postgres, redis, api, worker (docker compose)"
	@echo "down      - stop all containers"
	@echo "logs      - tail api+worker logs"
	@echo "migrate   - alembic upgrade head (inside api container)"
	@echo "seed      - run seed script (inside api container)"
	@echo "revision  - create a new alembic revision (m=message)"
	@echo "test      - run backend test suite"
	@echo "lint      - ruff check"
	@echo "typecheck - mypy"
	@echo "install   - uv sync backend dev deps"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m scripts.seed

revision:
	docker compose exec api alembic revision -m "$(m)"

install:
	cd backend && uv sync --extra dev

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check .

typecheck:
	cd backend && uv run mypy app

fmt:
	cd backend && uv run ruff format .
