# Task: BM USA Proxy — Stage 1 (Foundation)
Date: 2026-07-02
Gear: 3 (Full Lifecycle)
Status: Complete & verified locally · push BLOCKED (see below)

## Summary
Stood up the production monorepo foundation for BM USA Proxy: the complete PostgreSQL
schema (24 tables), Alembic migrations with zero model-drift, auth primitives, health
endpoints, a minimal secret-token-guarded Telegram bot, an ARQ worker, and an idempotent
seed with the real client data. Everything is verified at runtime and by tests. This is
Stage 1 of the 4-stage plan; Stages 2–4 (mini-app, admin, crypto pay + iproxy auto-issue,
referral + content + launch) follow.

## Files Changed (high level)
- `backend/app/models/*` — 24 tables (SQLAlchemy 2.0 typed), source of truth.
- `backend/alembic/versions/0001_extensions.py`, `0002_core_schema.py` — migrations.
- `backend/app/core/*` — config, db, redis, security (initData/JWT/Fernet), logging, errors.
- `backend/app/api/health.py`, `deps.py` — health + auth dependencies.
- `backend/app/bot/*` — aiogram factory + /start handler.
- `backend/app/workers/main.py` — ARQ worker (heartbeat).
- `backend/app/seed/*`, `scripts/seed.py` — seed data incl. verbatim Terms of Use.
- `backend/tests/*` — 13 tests.
- `docker-compose.yml`, `backend/Dockerfile.*`, `Makefile`, `.github/workflows/ci.yml`,
  `README.md`, `.env.example`, `.gitignore`.
- `demo/` — the approved prototype (moved from repo root).

## Verification Evidence
```
ruff check .        → All checks passed!
mypy app            → Success: no issues found in 29 source files
pytest -q           → 13 passed
alembic upgrade head; alembic check → "No new upgrade operations detected." (zero drift)
alembic downgrade base → upgrade head → clean (reversible)
seed                → tariffs=5, locations=9, admins=1, connections=18, tos_version=1
GET /health         → {"ok":true,"db":true,"redis":true}
POST /webhooks/telegram (no secret)      → 403
POST /webhooks/telegram (correct secret) → 200 (update dispatched)
```

Invariants proven by test:
- `test_two_active_accesses_on_one_connection_rejected` — one phone is never sold twice.
- `test_revoked_access_frees_the_connection` — revoked/expired frees the slot.
- initData valid / bad-signature / stale; JWT type + tamper; Fernet round-trip.
- seed idempotency; trial has max_user_swaps=1; ToS seeded with the email question.

## Security (Stage 1 scope)
- Webhook secret compared with `hmac.compare_digest` (constant-time).
- argon2id passwords, HS256 JWT with type+expiry checks, Fernet-encrypted credentials.
- Secrets only via env; `.env` git-ignored; gitleaks in CI.
- Full `security-audit` pass is scheduled at Stage 3 (money path) per plan §07 / INT-3.7.

## BLOCKER — remote push
`Deadline-Corp/BM-USA-PROXY` is **disabled** at the GitHub account level
("Repository is disabled. Please ask the owner to check their account.") — `git push`
returns 403. Disabled repos still allow clone (read), which is why setup worked. This is a
pre-existing org account/billing/flag issue only the org owner can resolve. Repo visibility
was left at PUBLIC (its original state). **All work is committed locally on `main`** and
pushes as-is once the account is restored (or point `origin` at another repo).

## How to Verify (reproduce)
```
cd D:/Projects/bm-usa-proxy
docker compose up -d postgres redis
cd backend && uv sync --extra dev
uv run alembic upgrade head && uv run python -m scripts.seed
uv run pytest -q && uv run ruff check . && uv run mypy app
uv run uvicorn app.main:app --port 8000   # GET http://localhost:8000/health
```

## Next (Stage 2)
Mini-app + admin scaffolds (Vite/React/TS/Tailwind with the approved brand tokens),
TWA/admin auth routers, catalog/orders/clients CRUD on the real schema behind
Mock payment/provisioning, then Playwright SCENARIOS.md bootstrap.
