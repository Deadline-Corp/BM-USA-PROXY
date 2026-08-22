"""Resolve the active Provisioner. FEATURE_REAL_PROVISIONING switches mock ↔ real iproxy."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.provisioning.base import Provisioner
from app.services.provisioning.mock import MockProvisioner


@lru_cache
def get_provisioner() -> Provisioner:
    # Mirror the guard in payments/registry.py: MockProvisioner issues fake proxies that
    # look real to the rest of the system. In prod (or when real provisioning is enabled)
    # it must never be the active provider — a misconfigured FEATURE_REAL_PROVISIONING=off
    # in prod would otherwise silently hand customers pretend credentials.
    if settings.is_prod and not settings.feature_real_provisioning:
        raise RuntimeError(
            "MockProvisioner is forbidden in production — set FEATURE_REAL_PROVISIONING=true "
            "and IPROXY_API_KEY"
        )
    if settings.feature_real_provisioning:
        if not settings.iproxy_api_key:
            raise RuntimeError("FEATURE_REAL_PROVISIONING=true requires IPROXY_API_KEY to be set")
        from app.services.provisioning.iproxy import IproxyProvisioner

        return IproxyProvisioner()
    return MockProvisioner()
