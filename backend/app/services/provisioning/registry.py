"""Resolve the active Provisioner. FEATURE_REAL_PROVISIONING switches mock ↔ real iproxy."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.provisioning.base import Provisioner
from app.services.provisioning.mock import MockProvisioner


@lru_cache
def get_provisioner() -> Provisioner:
    if settings.feature_real_provisioning and settings.iproxy_api_key:
        from app.services.provisioning.iproxy import IproxyProvisioner

        return IproxyProvisioner()
    return MockProvisioner()
