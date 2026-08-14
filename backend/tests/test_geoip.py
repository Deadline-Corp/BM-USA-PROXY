"""Parsing of the .mmdb city record — the part that decides what city a proxy is sold as.

These tests feed the resolver the record shapes the two supported databases actually
return, captured from real lookups, rather than a mock of the resolver itself. That
distinction is the whole point of this file: the first version of this code read only
`subdivisions[].iso_code`, which GeoLite2 has and DB-IP City Lite does not, so against the
database we actually ship every lookup returned None — every phone would have lost its
city, and the sync tests never saw it because they mocked `resolve_city_state` away.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.provisioning import geoip

# Captured verbatim from DB-IP City Lite for 174.224.240.8 (the phone iproxy claimed was
# in Boston). Note `subdivisions[0]` carries a name and no iso_code.
DBIP_RECORD: dict[str, Any] = {
    "city": {"names": {"en": "Saint Francis"}},
    "continent": {"code": "NA", "names": {"en": "North America"}},
    "country": {"geoname_id": 6252001, "iso_code": "US", "names": {"en": "United States"}},
    "location": {"latitude": 42.9675, "longitude": -87.8776},
    "subdivisions": [{"names": {"en": "Wisconsin"}}],
}

# The same place as MaxMind's GeoLite2 renders it: an iso_code is present.
GEOLITE2_RECORD: dict[str, Any] = {
    "city": {"geoname_id": 5263045, "names": {"en": "Saint Francis"}},
    "country": {"iso_code": "US", "names": {"en": "United States"}},
    "subdivisions": [{"geoname_id": 5279468, "iso_code": "WI", "names": {"en": "Wisconsin"}}],
}


class _StubReader:
    """Stands in for an open maxminddb reader over a single canned record."""

    def __init__(self, record: dict[str, Any] | None) -> None:
        self._record = record

    def get(self, ip: str) -> dict[str, Any] | None:
        if not ip or ip == "not-an-ip":
            raise ValueError("malformed address")
        return self._record


@pytest.fixture
def _reader(monkeypatch: pytest.MonkeyPatch):
    """Install a canned record as the database this process reads."""

    def _install(record: dict[str, Any] | None) -> None:
        monkeypatch.setattr(geoip, "_reader", lambda: _StubReader(record))

    return _install


def test_dbip_record_resolves_even_though_it_has_no_iso_code(_reader) -> None:
    """The regression this file exists for: a spelled-out state still yields its code."""
    _reader(DBIP_RECORD)
    assert geoip.resolve_city_state("174.224.240.8") == ("Saint Francis", "WI")


def test_geolite2_record_resolves_from_its_iso_code(_reader) -> None:
    """The other supported database keeps working — an operator may swap the file in."""
    _reader(GEOLITE2_RECORD)
    assert geoip.resolve_city_state("174.224.240.8") == ("Saint Francis", "WI")


def test_city_outside_the_old_seventeen_is_not_lost(_reader) -> None:
    """Sun Prairie was silently dropped by the hardcoded dictionary this replaced."""
    _reader(
        {
            "city": {"names": {"en": "Sun Prairie"}},
            "subdivisions": [{"names": {"en": "Wisconsin"}}],
        }
    )
    assert geoip.resolve_city_state("1.2.3.4") == ("Sun Prairie", "WI")


def test_state_already_stored_as_a_two_letter_name_is_accepted(_reader) -> None:
    _reader({"city": {"names": {"en": "Austin"}}, "subdivisions": [{"names": {"en": "TX"}}]})
    assert geoip.resolve_city_state("1.2.3.4") == ("Austin", "TX")


@pytest.mark.parametrize(
    "record",
    [
        pytest.param({"subdivisions": [{"names": {"en": "Wisconsin"}}]}, id="no city"),
        pytest.param({"city": {"names": {"en": "Saint Francis"}}}, id="no subdivision"),
        pytest.param(
            {"city": {"names": {"en": "Somewhere"}}, "subdivisions": [{"names": {"en": "Bavaria"}}]},
            id="non-US subdivision",
        ),
        pytest.param(None, id="ip not in database"),
    ],
)
def test_incomplete_records_resolve_to_nothing(_reader, record) -> None:
    """A partial answer is worse than none: it would be sold as a city we cannot stand behind."""
    _reader(record)
    assert geoip.resolve_city_state("1.2.3.4") is None


@pytest.mark.parametrize("ip", ["", None, "not-an-ip"])
def test_bad_input_never_raises(_reader, ip) -> None:
    """The sync job must survive a phone with a missing or malformed exit IP."""
    _reader(DBIP_RECORD)
    assert geoip.resolve_city_state(ip) is None


def test_missing_database_degrades_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No database file must not take the pool sync down with it."""
    monkeypatch.setattr(geoip, "_reader", lambda: None)
    assert geoip.resolve_city_state("174.224.240.8") is None
