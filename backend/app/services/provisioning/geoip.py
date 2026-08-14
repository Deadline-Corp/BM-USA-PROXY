"""Local MaxMind-format (.mmdb) city/state lookup for a connection's real exit IP.

No network calls happen here or ever did: the database file is baked into the Docker
image at build time (see backend/scripts/fetch_geoip_db.py and Dockerfile.api /
Dockerfile.worker), and this module only ever reads it off local disk.

Default source: DB-IP City Lite (https://db-ip.com/db/download/ip-to-city-lite),
(c) DB-IP, licensed CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/) — free, no
API key, updated monthly. MaxMind's GeoLite2-City ships the exact same schema (city
name, subdivision ISO code, ...), so dropping that file in at GEOIP_DB_PATH instead
works unmodified — nothing here is DB-IP-specific.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import maxminddb

from app.core.config import settings
from app.core.logging import log

# US state/territory name → USPS code. Needed because the two databases that fit this
# schema do not agree on how they name a subdivision: MaxMind's GeoLite2 carries an
# `iso_code` ("WI"), DB-IP's City Lite carries only the English name ("Wisconsin"). We
# sell by the short code, so the name is translated when the code is absent.
#
# Unlike the 17-city dictionary this replaced, the risk here is bounded: the set of US
# states is fixed, so an entry cannot silently go missing the way an unlisted city did.
_US_STATE_CODES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "puerto rico": "PR", "guam": "GU", "american samoa": "AS",
    "united states virgin islands": "VI", "northern mariana islands": "MP",
}


def _subdivision_code(subdivision: dict[str, Any]) -> str | None:
    """The state's short code, whether the database spells it out or abbreviates it."""
    iso = subdivision.get("iso_code")
    if iso:
        return str(iso)
    name = ((subdivision.get("names") or {}).get("en") or "").strip()
    if not name:
        return None
    if len(name) == 2 and name.isalpha():  # already a code, just stored as the name
        return name.upper()
    return _US_STATE_CODES.get(name.lower())


@lru_cache(maxsize=1)
def _reader() -> Any | None:
    """The open database, opened once per process. None if the file is missing/unreadable.

    A missing file must degrade to "no geo data" everywhere it is used, not crash the
    sync job or the app — the pool must keep syncing (carrier, online status, allocation)
    even before an operator has a database in place.
    """
    try:
        return maxminddb.open_database(settings.geoip_db_path)
    except (OSError, ValueError) as exc:
        log.error("geoip.db_unavailable", path=settings.geoip_db_path, error=str(exc))
        return None


def resolve_city_state(ip: str | None) -> tuple[str, str] | None:
    """(city, state_code) for a US public IP, or None if it can't be resolved.

    Reads the standard GeoIP2/GeoLite2 City record tree, which DB-IP's City Lite mirrors
    closely — but not field-for-field: GeoLite2 gives a subdivision an `iso_code`, while
    City Lite gives only its English name. `_subdivision_code` bridges that, so the same
    code works whichever file is installed.
    """
    if not ip:
        return None
    reader = _reader()
    if reader is None:
        return None
    try:
        data = reader.get(ip)
    except ValueError:  # malformed/unparseable address
        return None
    if not isinstance(data, dict):
        return None
    city = ((data.get("city") or {}).get("names") or {}).get("en")
    subdivisions = data.get("subdivisions") or []
    state = _subdivision_code(subdivisions[-1]) if subdivisions else None
    if not city or not state:
        return None
    return str(city), str(state)
