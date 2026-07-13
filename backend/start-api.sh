#!/bin/sh
# API container entrypoint.
# STAGING NOTE: this also runs the arq worker IN-CONTAINER, auto-restarting, so the
# cron jobs run (access-expiry + iproxy revoke, invoice expiry, pool sync,
# notification delivery). Production should run the worker as its OWN Railway
# service instead of piggybacking on the API container.
alembic upgrade head || exit 1
python -m scripts.seed || exit 1
(
  while true; do
    arq app.workers.main.WorkerSettings
    echo "[start-api] arq worker exited (code $?) - restarting in 3s"
    sleep 3
  done
) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
