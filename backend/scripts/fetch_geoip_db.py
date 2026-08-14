"""Fetch the GeoIP city/state database (.mmdb) at Docker build time — not at runtime.

The running service (see app/services/provisioning/geoip.py) only ever reads this file
off local disk; it never makes a network call to resolve a city. This script is what
puts the file there, invoked from Dockerfile.api and Dockerfile.worker during the image
build, before USER switches away from root.

Source: DB-IP City Lite (https://db-ip.com/db/download/ip-to-city-lite), (c) DB-IP,
licensed CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/) — free, no API key,
released monthly. MaxMind's GeoLite2-City has the identical schema; an operator can drop
that file in at GEOIP_DB_PATH instead and nothing here or in geoip.py needs to change.

The current month's release can lag a few days into the month, so this tries this month
first and falls back one month. A build that cannot get either file fails loudly
(non-zero exit) rather than silently ship an image with no geo data.
"""

from __future__ import annotations

import datetime
import gzip
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL_TEMPLATE = "https://download.db-ip.com/free/dbip-city-lite-{ym}.mmdb.gz"
DEFAULT_DEST = "/app/data/geoip-city.mmdb"
TIMEOUT_SECONDS = 60


def _candidate_months(today: datetime.date) -> list[str]:
    """This month, then last month — release day varies, but never by more than that."""
    first_of_this_month = today.replace(day=1)
    last_month = first_of_this_month - datetime.timedelta(days=1)
    return [today.strftime("%Y-%m"), last_month.strftime("%Y-%m")]


def _download(url: str, dest_gz: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "bm-usa-proxy-build"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 — fixed https host, build-time only
        with open(dest_gz, "wb") as f:
            shutil.copyfileobj(resp, f)


def main() -> int:
    dest = Path(os.environ.get("GEOIP_DB_PATH", DEFAULT_DEST))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest_gz = dest.with_suffix(dest.suffix + ".gz")

    errors: list[str] = []
    for ym in _candidate_months(datetime.date.today()):
        url = URL_TEMPLATE.format(ym=ym)
        print(f"geoip: fetching {url}")
        try:
            _download(url, dest_gz)
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{url}: {exc}")
            continue

        with gzip.open(dest_gz, "rb") as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        dest_gz.unlink(missing_ok=True)
        print(f"geoip: wrote {dest} ({dest.stat().st_size} bytes) from {ym}")
        return 0

    dest_gz.unlink(missing_ok=True)
    print("geoip: could not download a GeoIP database from any candidate month:", file=sys.stderr)
    for err in errors:
        print(f"  {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
