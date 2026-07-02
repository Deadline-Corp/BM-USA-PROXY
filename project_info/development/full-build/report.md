# Task: BM USA Proxy — full build (Stages 1–4)
Date: 2026-07-03
Gear: 3 (Full Lifecycle), autonomous
Status: Complete & verified (on mock provider/provisioner) · pending client live-keys for go-live

## Summary
Built the entire BM USA Proxy platform end-to-end: FastAPI backend (all 4 stages),
Telegram Mini-App, operator admin panel, worker automation, and a production Docker image
that serves everything. Runs fully on a mock crypto provider + mock proxy provisioner
(`FEATURE_REAL_PAYMENTS=false`); flipping to real is adding the client's keys + one adapter.

## Delivered (all verified)
- **Backend** — 24-table PostgreSQL schema (migrations, zero drift, real-data seeds);
  TWA API; Admin API (~70 endpoints + auth/RBAC/audit); crypto payments (webhook,
  idempotency, reconcile); iproxy provisioning client; referral ledger engine;
  ARQ automation (expiry sweeper, invoice expirer, reconcile, hold release, outbox
  delivery, iproxy sync, post publishing, broadcasts); minimal aiogram bot with
  deep-link attribution + Terms gate.
- **Mini-App** — 8 screens (React/TS/Vite/Tailwind/TanStack Query), initData auth,
  crypto checkout, My Access, referral, ToS gate. Served at `/app`.
- **Admin panel** — login + 13 screens (React/TS/Vite/Tailwind/TanStack Table),
  JWT refresh interceptor, RBAC. Served at `/admin`.
- **Deploy** — docker-compose; multi-stage image (builds both SPAs, serves from
  `/static`); GitHub Actions CI.

## Verification evidence
```
backend:  ruff clean · mypy clean (65 files) · pytest 37 passed
migrations: alembic upgrade→check (no drift)→downgrade→upgrade  clean
miniapp:  tsc --noEmit clean · vite build exit 0
admin:    tsc --noEmit clean · vite build exit 0
docker:   image built (both SPAs + backend) · container serves /app + /admin (200)
runtime:  /health {ok,db,redis}=true · /app + /admin serve SPAs · /api/* → 401 unauth
```
Tests cover the load-bearing guarantees: one-phone-one-sale allocation invariant,
payment idempotency (1 paid event = 1 activation), referral ledger math incl. pro-rata
reversal, ToS gate, trial one-per-user + swap, expiry sweeper, admin auth + RBAC.

## Bugs caught by tests before shipping
- Partial-index `ON CONFLICT` requires `index_where` (referral accrual, notification &
  payment dedupe) — would have thrown at runtime.
- Missing auth header returned 422 instead of 401 — would have broken the admin
  refresh interceptor.

## Remaining (pre-launch)
- Client live-keys: crypto processor (DG-1), iproxy key + INT-1.1 shape confirmation,
  prod bot token, hosting/domain (DG-2/3).
- Config-file (OpenVPN/WireGuard) byte delivery — wired; source is iproxy/operator.
- Full security-audit money-path pass (INT-3.7); Playwright browser E2E over the SPAs.

## How to run
```
cd D:/Projects/bm-usa-proxy
docker compose up -d postgres redis
cd backend && uv sync --extra dev && uv run alembic upgrade head && uv run python -m scripts.seed
uv run uvicorn app.main:app --port 8000     # /health · /app · /admin · /api
uv run pytest -q                             # 37 passing
# or full stack:  docker compose up -d --build
```
