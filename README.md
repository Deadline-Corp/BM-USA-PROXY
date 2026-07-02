# BM USA Proxy

Telegram ecosystem for reselling US mobile proxies (sourced from iproxy.online):
a minimal **bot**, a **Telegram Mini-App** (all customer actions), and a **web admin**.
Core: crypto payment → automatic 24/7 proxy provisioning via the iproxy Console API.

> Full spec & staged plan live in the Obsidian vault:
> `Business/Projects/Deadline/BM_USA_Proxy/Plan/` (00_Master_plan … 07_DevOps).
> The approved visual prototype (light brand) is in [`demo/`](demo/).

## Status

**Stage 1 — Foundation (done, verified):** monorepo, Docker, CI, full PostgreSQL schema
(24 tables, migrations, seeds with real client data), config, auth primitives
(Telegram initData + admin JWT + Fernet), health endpoints, ARQ worker skeleton,
minimal aiogram bot with a secret-token-guarded webhook.

Stages 2–4 (mini-app + admin, crypto pay + iproxy auto-issue, referral + content + launch)
follow per the plan.

## Layout

```
backend/           FastAPI + SQLAlchemy(async) + Alembic + aiogram + ARQ
  app/core/        config, db, redis, security, logging, errors
  app/models/      all tables (source of truth for migrations)
  app/api/         health (+ TWA/admin routers in Stage 2)
  app/bot/         aiogram: /start, open-app button, webhook
  app/workers/     ARQ worker (heartbeat now; jobs in Stage 3/4)
  app/seed/        tariffs, locations, FAQ, Terms of Use text
  alembic/         0001_extensions, 0002_core_schema
  tests/           security (unit) + allocation invariant + seed (Postgres)
demo/              approved clickable prototype (index/admin/miniapp .html)
docker-compose.yml postgres, redis, api, worker
```

## Quickstart

```bash
cp .env.example .env
# set CREDENTIALS_KEY: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
# set SEED_ADMIN_PASSWORD

make up        # postgres, redis, api, worker (api runs migrations on start)
make seed      # tariffs, locations, FAQ, owner admin, Terms v1, dev fixtures
# API at http://localhost:8000  ·  GET /health
```

Local backend dev without Docker (Postgres/Redis still needed):

```bash
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run python -m scripts.seed
uv run uvicorn app.main:app --reload
uv run pytest -q && uv run ruff check . && uv run mypy app
```

## Key invariants (enforced in the schema + tests)

1. **One phone, one sale** — partial unique index `uq_connection_active_access`.
2. **Payment idempotency** — `UNIQUE (provider, provider_invoice_id)` on invoices.
3. **Append-only** referral ledger, access events, ToS acceptances, payment events.
4. Proxy credentials encrypted at rest (Fernet); secrets only via env.
