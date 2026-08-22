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

## Deploying

Two Railway services run the same image, told apart by `ROLE`: **api** (web + migrations +
both SPAs) and **worker** (ARQ crons). See [Railway services](#railway-services) below for
the config files, env vars per service, and deploy commands.

## Railway services

Two Railway services run the same image (built from `backend/Dockerfile.api`), told
apart by the `ROLE` env var: **api** (web + migrations + seed + both SPAs) and
**worker** (ARQ crons). The repo carries two Railway config files as documented
examples — wire them to the corresponding service in the Railway dashboard:

| File | Service | Start command | Notes |
| --- | --- | --- | --- |
| `railway.json` | api | `sh start.sh` | runs `alembic upgrade head`, seed (if `SEED_ADMIN_PASSWORD` set), then uvicorn |
| `railway.worker.json` | worker | `arq app.workers.main.WorkerSettings` | `ROLE=worker` in env; waits for schema before starting arq |

**Worker env vars (Railway dashboard → worker service → Variables):**

| Variable | Value | Description |
| --- | --- | --- |
| `ROLE` | `worker` | selects the worker branch in `start.sh` |
| `DATABASE_URL` | *(same as api)* | Postgres connection string |
| `REDIS_URL` | *(same as api)* | Redis connection string |
| `CREDENTIALS_KEY` | *(same as api)* | Fernet key — worker encrypts/decrypts proxy credentials |
| `RUN_WORKER` | *(unset / `false`)* | only relevant on the api service; leave off on worker |

Deploy each by name (always pass `--service`):

```sh
railway up --ci --service api      # migrations run here, on startup
railway up --ci --service worker
```

**Always pass `--service`.** Without it `railway up` targets whatever the CLI happens to be
linked to, and it reports "Deploy complete" either way — on 2026-08-13 a console change went
to the worker and looked deployed for half an hour, while the api kept serving the previous
image. Only the api runs `alembic upgrade head`, so a misdirected deploy leaves new code in
front of an old schema.

Worth checking after any deploy that changes the console or the schema:

```sh
railway status --json | grep -A2 '"serviceName": "api"'   # is it the deploy you just made?
railway logs --service api --deployment | grep -i "Running upgrade"
curl -s https://<host>/health
```

## Key invariants (enforced in the schema + tests)

1. **One phone, one sale** — partial unique index `uq_connection_active_access`.
2. **Payment idempotency** — `UNIQUE (provider, provider_invoice_id)` on invoices.
3. **Append-only** referral ledger, access events, ToS acceptances, payment events.
4. Proxy credentials encrypted at rest (Fernet); secrets only via env.

## Required environment variables (production)

| Variable | Required | Description |
| --- | --- | --- |
| `CREDENTIALS_KEY` | yes | Fernet key for encrypting proxy credentials at rest |
| `ADMIN_JWT_SECRET` | yes | Secret for signing admin JWTs (≥ 32 chars) |
| `BOT_TOKEN` | yes | Telegram bot token from BotFather |
| `BOT_WEBHOOK_SECRET` | yes | `X-Telegram-Bot-Api-Secret-Token` webhook guard |
| `SEED_ADMIN_PASSWORD` | recommended | Initial owner admin password (required for `make seed` / first boot) |
| `SEED_ADMIN_EMAIL` | optional | Owner admin email (default `admin@bmusproxy.local`) |
| `SENTRY_DSN` | optional | Sentry DSN for error tracking (Sentry SDK initialised when set) |
| `PAYMENT_PROVIDER` | optional | `mock` (default) \| `bitpay` \| `coinbase` \| `cryptomus` \| `onchain` |
| `PAYMENT_API_KEY` | optional | API key for the chosen payment provider |
| `PAYMENT_WEBHOOK_SECRET` | optional | Secret guarding payment provider webhooks |
| `ONCHAIN_METHODS` | optional | JSON array of enabled on-chain rails + receiving addresses (see `onchain/config.py`) |
| `ONCHAIN_RPC` | optional | JSON object of per-chain RPC endpoints + optional api keys |
| `ONCHAIN_PAYOUT_SOURCES` | optional | JSON array of wallets we send referral payouts from (public addresses only) |
| `ALCHEMY_WEBHOOK_KEYS` | optional | JSON object of Alchemy address-activity webhook signing keys (e.g. `{"ETH_MAINNET":"whsec_..."}`) |
| `AI_SUPPORT_API_KEY` | optional | Anthropic API key for the bot's AI support layer (unset = layer asleep, messages go to operator) |
| `AI_SUPPORT_BASE_URL` | optional | Anthropic-compatible gateway URL (blank = direct Anthropic; e.g. `https://openrouter.ai/api`) |
| `AI_SUPPORT_MODEL` | optional | Model for AI support (default `claude-haiku-4-5`) |
| `FEATURE_REAL_PAYMENTS` | optional | `false` (default) — set `true` in prod to enable real payment processing |
| `FEATURE_REAL_PROVISIONING` | optional | `false` (default) — set `true` to enable real iproxy issuance (decoupled from payments) |
| `SEED_DEV_FIXTURES` | optional | `true` (default) — seed demo users/connections; set `false` in prod |
| `RUN_WORKER` | optional | `false` (default) — set `true` only on the api service during the staging topology transition |

Optional DB defaults (overridable via env): `POSTGRES_USER=bm`, `POSTGRES_PASSWORD=bm`, `POSTGRES_DB=bm_usa_proxy`.

## Postgres backup & restore

**Railway volume snapshots.** Railway takes automatic volume snapshots for Postgres
add-on databases. These are point-in-time filesystem snapshots — suitable for disaster
recovery but not a substitute for logical backups (a corrupted row or accidental `DELETE`
is committed to the snapshot too). Check the Railway dashboard → Postgres service →
Settings → Backups for retention policy and restore-from-snapshot.

**Recommended `pg_dump` cron.** Run a logical export on a schedule (at minimum daily) so a
restore can target a specific table or row without rewinding the whole volume:

```sh
# Daily logical backup (run from a scheduler or Railway cron job)
pg_dump "$DATABASE_URL_SYNC" \
  --no-owner --no-privileges --format=custom \
  --file="/backups/bm_usa_proxy_$(date -u +%Y%m%d_%H%M%S).dump"

# Retain 14 days, then prune
find /backups -name 'bm_usa_proxy_*.dump' -mtime +14 -delete
```

`DATABASE_URL_SYNC` is the `DATABASE_URL` with `+asyncpg` removed (the sync psycopg driver
that `pg_dump` needs). Keep the backup volume outside the Postgres data volume so a volume
failure does not take both down.

**Restore procedure.**

```sh
# Full restore (drop + recreate + load) — run against a fresh/empty database
dropdb "$DATABASE_URL_SYNC" && createdb "$DATABASE_URL_SYNC"
pg_restore --dbname="$DATABASE_URL_SYNC" --no-owner --no-privileges --clean \
  /backups/bm_usa_proxy_YYYYMMDD_HHMMSS.dump

# Single-table restore (extract + load just that table)
pg_restore --dbname="$DATABASE_URL_SYNC" --table=connections \
  /backups/bm_usa_proxy_YYYYMMDD_HHMMSS.dump
```

After a restore, run `alembic upgrade head` to bring the schema to the latest revision if
the backup predates it, then `python -m scripts.seed` (safe — seed is idempotent and
insert-if-absent).
