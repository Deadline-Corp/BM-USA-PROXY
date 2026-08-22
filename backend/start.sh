#!/bin/sh
# Container entrypoint for BOTH Railway services. One image, one script, two roles —
# picked by $ROLE. Same code in both, so the worker can never drift a deploy behind the
# API, which is the failure mode that makes "why is the watcher doing something the code
# does not say" impossible to debug.
#
#   ROLE=api     (default) migrations + seed + uvicorn
#   ROLE=worker            arq only
#
# RUN_WORKER exists for the migration between the two topologies: while the worker still
# lives inside the API container it stays "true"; once the worker service is up and
# verified it goes to "false" and the API stops piggybacking. Keeping the flag means the
# rollback is a variable, not a deploy.
set -e
ROLE="${ROLE:-api}"

if [ "$ROLE" = "worker" ]; then
  # The health endpoint comes up FIRST, before the schema wait, so the platform has
  # something to check while the worker is still starting. It reports the cron
  # heartbeats, which is what makes a wedged-but-running worker restartable — the exact
  # failure this service exists to separate out.
  uvicorn app.workers.health_server:app --host 0.0.0.0 --port "${PORT:-8000}" &
  # The API service owns alembic and the seed. Starting arq against a half-migrated
  # database gives a crash-loop whose logs blame the worker for the API's timing, so
  # wait for the schema instead.
  python -m scripts.wait_for_schema || exit 1
  echo "[start] role=worker — arq"
  # exec: arq is the process the container lives and dies by. If it exits, the container
  # exits and the platform restarts it — the health server must never outlive it.
  exec arq app.workers.main.WorkerSettings
fi

echo "[start] role=api"
alembic upgrade head || exit 1

# Seed is idempotent but needs SEED_ADMIN_PASSWORD to bootstrap the owner account.
# Without it seed_admin() logs a warning and returns (see scripts/seed.py), so the
# command itself never fails — but we guard anyway so a missing password can never
# boot-loop the API under `set -e`.
if [ -n "${SEED_ADMIN_PASSWORD:-}" ]; then
  python -m scripts.seed || echo "[start] seed failed — continuing (non-fatal)"
else
  echo "[start] SEED_ADMIN_PASSWORD not set — skipping seed (admin bootstrap deferred)"
fi

# RUN_WORKER=true keeps arq inside the API container during the migration to a
# standalone worker service. The default is false: Railway should run a separate
# worker service (see railway.worker.json) and leave this flag off on the API.
if [ "${RUN_WORKER:-false}" = "true" ]; then
  echo "[start] RUN_WORKER=true — also running arq in-container (staging topology)"
  # Graceful shutdown: SIGTERM to the main process (uvicorn) must not kill arq
  # mid-job. Trap TERM, signal the arq supervisor, wait for it to drain, then exit.
  trap 'kill $ARQ_PID 2>/dev/null; wait $ARQ_PID 2>/dev/null; exit 0' TERM
  (
    while true; do
      arq app.workers.main.WorkerSettings
      echo "[start] arq worker exited (code $?) - restarting in 3s"
      sleep 3
    done
  ) &
  ARQ_PID=$!
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
