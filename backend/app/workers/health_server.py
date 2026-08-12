"""A port for the worker to be judged on.

The worker has no HTTP surface of its own, which left the platform with nothing to check
but "is the process running" — and the failure this whole split exists to fix is a worker
whose process is running and whose crons are not. So it gets one endpoint, and the
platform's restart decision is made on whether the work is happening rather than on
whether the executable is loaded.

Grace period: at boot there are no heartbeats yet, and the worker waits for the schema
before arq even starts. Reporting unhealthy then would make the platform kill a service
that is starting normally, forever. So the first few minutes are healthy by definition,
and after that the heartbeats have to speak for themselves.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Response

from app.workers.heartbeat import REQUIRED_JOBS, stale_jobs

# Long enough for the schema wait (up to 180s) plus arq's first cron pass. Shorter than
# Railway's healthcheckTimeout, so a worker that never starts still fails the deploy
# rather than being declared fine.
GRACE_SECONDS = 240

_started_at = time.monotonic()
app = FastAPI(title="BM USA Proxy worker health", docs_url=None, redoc_url=None)


@app.get("/health")
async def health(response: Response) -> dict[str, object]:
    uptime = time.monotonic() - _started_at
    if uptime < GRACE_SECONDS:
        return {"ok": True, "starting": True, "uptime_seconds": int(uptime)}
    stale = await stale_jobs()
    if stale:
        # 503 is the point of this endpoint: it is what makes the platform restart a
        # worker that is up but not working.
        response.status_code = 503
    return {"ok": not stale, "stale": stale, "required": list(REQUIRED_JOBS)}
