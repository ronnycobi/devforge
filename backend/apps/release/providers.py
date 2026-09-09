"""Store provider abstraction + registry (spec §2, §3, §34).

The release system is provider-agnostic: Google Play, Apple App Store and Huawei
AppGallery are three adapters behind ONE interface, and adding Amazon/Samsung/etc.
later means writing an adapter + capability map, not rewriting release logic.

HONESTY (spec §43 — do not fake integrations): every adapter here declares the
capabilities it is *designed* to perform through official store APIs, but none is
wired to a live account on this host. `is_available()` is False for all three
because live publishing requires the developer's own credentials + outbound
network to Google/Apple/Huawei, which are not configured. Every operation raises
StoreError explaining that, rather than returning a fake success. This mirrors the
cloud-deploy providers (apps.deployments.providers): named backends that report
"not configured" until real credentials exist.

DevForge automates the official process; it never bypasses store auth, signing,
testing or review, and it never asks for or stores a Google/Apple/Huawei password
(spec §1) — only official API keys / service accounts / tokens, held as opaque
references (apps.release.credentials), never as plaintext.
"""
from __future__ import annotations

from apps.release.capabilities import StoreCapability as Cap


class StoreError(Exception):
    pass


class StoreProvider:
    """Common interface every store adapter implements (spec §3).

    Methods that a provider does not support (per its capability map) should not be
    called; callers gate on `supports()`. Providers that are not connected to a live
    account raise StoreError from every operation rather than pretend.
    """

    key = ""
    name = ""
    # Which operations this adapter implements through official APIs.
    capabilities: frozenset[Cap] = frozenset()
    # Official authentication mechanism (shown in connect help; never a password).
    auth_mechanism = ""
    # The artifact this store consumes.
    artifact_format = ""

    def supports(self, capability: Cap) -> bool:
        return capability in self.capabilities

    def is_available(self) -> bool:
        """True only when a live, authorized connection is configured on this host."""
        return False

    # --- lifecycle (all gated on a live connection) -----------------------------
    def verify_connection(self, connection):
        raise self._offline()

    def get_applications(self, connection):
        raise self._offline()

    def create_application(self, connection, *, name, identifier):
        raise self._offline()

    def upload_build(self, connection, build):
        raise self._offline()

    def update_metadata(self, store_application, metadata):
        raise self._offline()

    def submit_for_review(self, release):
        raise self._offline()

    def get_release_status(self, release):
        raise self._offline()

    def get_review_status(self, release):
        raise self._offline()

    def rollback_release(self, release):
        raise self._offline()

    def _offline(self) -> StoreError:
        return StoreError(
            f"{self.name} is not connected on this host. Live publishing needs the "
            f"developer's own {self.auth_mechanism or 'official API credentials'} and "
            f"network access to {self.name}, which are not configured. DevForge has "
            f"prepared everything it can offline; the store step is a manual action."
        )


class GooglePlayProvider(StoreProvider):
    """Google Play Developer API (spec §4). Verify against current official docs
    before wiring live endpoints — do not invent API endpoints."""

    key = "google_play"
    name = "Google Play"
    auth_mechanism = "Google Play service-account key"
    artifact_format = "aab"  # Android App Bundle
    capabilities = frozenset({
        Cap.ACCOUNT_CONNECTION, Cap.APPLICATION_DISCOVERY, Cap.METADATA_MANAGEMENT,
        Cap.BUILD_UPLOAD, Cap.INTERNAL_TESTING, Cap.CLOSED_TESTING,
        Cap.SUBMISSION, Cap.RELEASE_MANAGEMENT, Cap.REVIEW_STATUS,
        # Note: Play does not create the app listing via API — that is a manual
        # first step in Play Console, so APPLICATION_CREATION is intentionally absent.
    })


class AppleAppStoreProvider(StoreProvider):
    """App Store Connect API (spec §9). Uses API key + Issuer ID + Key ID; never a
    password. TestFlight where officially available."""

    key = "apple_app_store"
    name = "Apple App Store"
    auth_mechanism = "App Store Connect API key (Issuer ID + Key ID)"
    artifact_format = "ipa"
    capabilities = frozenset({
        Cap.ACCOUNT_CONNECTION, Cap.APPLICATION_CREATION, Cap.APPLICATION_DISCOVERY,
        Cap.METADATA_MANAGEMENT, Cap.BUILD_UPLOAD, Cap.INTERNAL_TESTING,
        Cap.BETA_TESTING, Cap.SUBMISSION, Cap.RELEASE_MANAGEMENT, Cap.REVIEW_STATUS,
    })


class HuaweiAppGalleryProvider(StoreProvider):
    """Huawei AppGallery Connect (spec §13). Its API and workflow are NOT assumed to
    match Google Play — its own capability map, verified against Huawei docs."""

    key = "huawei_appgallery"
    name = "Huawei AppGallery"
    auth_mechanism = "AppGallery Connect API client (client ID + secret)"
    artifact_format = "apk"  # AAB also supported; APK is the safe baseline
    capabilities = frozenset({
        Cap.ACCOUNT_CONNECTION, Cap.APPLICATION_DISCOVERY, Cap.METADATA_MANAGEMENT,
        Cap.BUILD_UPLOAD, Cap.SUBMISSION, Cap.RELEASE_MANAGEMENT, Cap.REVIEW_STATUS,
        # No first-class beta-testing API surface assumed → those caps absent →
        # DevForge will show "Manual action required" for testing on AppGallery.
    })


# --- Registry (spec §34) -------------------------------------------------------
_PROVIDERS: dict[str, StoreProvider] = {
    p.key: p for p in (
        GooglePlayProvider(),
        AppleAppStoreProvider(),
        HuaweiAppGalleryProvider(),
    )
}


def get_provider(key: str) -> StoreProvider | None:
    return _PROVIDERS.get(key)


def all_providers() -> list[StoreProvider]:
    return list(_PROVIDERS.values())


def provider_choices() -> list[tuple[str, str]]:
    return [(p.key, p.name) for p in _PROVIDERS.values()]


def provider_status() -> list[dict]:
    """For the admin/store UI — honest availability + declared capability count."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "available": p.is_available(),
            "auth_mechanism": p.auth_mechanism,
            "artifact_format": p.artifact_format,
            "capabilities": sorted(str(c) for c in p.capabilities),
        }
        for p in _PROVIDERS.values()
    ]
