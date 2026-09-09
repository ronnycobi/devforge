"""Store-provider capabilities (spec §3).

Every store supports a *different* subset of operations, and DevForge must never
assume otherwise. Each provider declares the capabilities it actually implements;
callers check `provider.supports(...)` before offering an action, and the UI shows
"Manual action required" for anything a store can't do through an official API.
"""
from __future__ import annotations

from enum import Enum


class StoreCapability(str, Enum):
    ACCOUNT_CONNECTION = "account_connection"
    APPLICATION_CREATION = "application_creation"
    APPLICATION_DISCOVERY = "application_discovery"
    METADATA_MANAGEMENT = "metadata_management"
    BUILD_UPLOAD = "build_upload"
    INTERNAL_TESTING = "internal_testing"
    CLOSED_TESTING = "closed_testing"
    BETA_TESTING = "beta_testing"
    SUBMISSION = "submission"
    REVIEW_STATUS = "review_status"
    RELEASE_MANAGEMENT = "release_management"
    ROLLBACK = "rollback"

    def __str__(self):  # so templates render the value, not "StoreCapability.X"
        return self.value
