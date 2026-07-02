"""Resolve the active Provisioner. Real payments flag also switches provisioning."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.provisioning.base import Provisioner
from app.services.provisioning.mock import MockProvisioner


@lru_cache
def get_provisioner() -> Provisioner:
    if not settings.feature_real_payments:
        return MockProvisioner()
    # Stage 3: return IproxyProvisioner() (real Console API client) — wired there.
    raise NotImplementedError("real iproxy provisioner is wired in Stage 3")
