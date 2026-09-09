"""ReleaseReadinessEngine (spec §18).

Scores a release from checks against the *actual* records — a build that really
exists, signing that is really configured, metadata that is really filled in. It
never claims that passing DevForge's checks guarantees store approval; the verdict
is "Ready to submit", not "Guaranteed approval" (spec §18).

Statuses: ok / warn / fail / manual. `manual` means the store needs a human step
DevForge can't do through an official API — it does not drag the score down to
zero, but it is surfaced honestly.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.release.providers import get_provider


@dataclass
class Check:
    key: str
    label: str
    status: str      # ok / warn / fail / manual
    detail: str = ""


def evaluate(release) -> list[Check]:
    app = release.mobile_application
    store_app = release.store_application
    provider = get_provider(release.provider)
    checks: list[Check] = []

    # Build
    if release.build and release.build.status == "ready" and release.build.artifact_path:
        checks.append(Check("build", "Build ready", "ok"))
    elif release.build:
        checks.append(Check("build", "Build ready", "warn",
                            "Build is planned but no signed artifact exists yet."))
    else:
        checks.append(Check("build", "Build ready", "fail", "No build attached."))

    # Signing
    sign = app.signing_configs.filter(platform=_platform_for(release.provider)).first()
    if sign and sign.configured:
        checks.append(Check("signing", "Signing configured", "ok"))
    else:
        checks.append(Check("signing", "Signing configured", "fail",
                            "Signing is not configured for this platform."))

    # Identity
    ident = app.package_identifier or app.bundle_identifier
    checks.append(
        Check("identity", "Application identity", "ok" if ident else "fail",
              "" if ident else "Package/bundle identifier missing.")
    )

    # Metadata
    md = getattr(store_app, "metadata", None)
    if md and md.app_name and md.short_description and md.full_description:
        status = "ok" if md.approved else "warn"
        detail = "" if md.approved else "Draft metadata not yet approved."
        checks.append(Check("metadata", "Store metadata", status, detail))
    else:
        checks.append(Check("metadata", "Store metadata", "fail", "Store listing is incomplete."))

    # Privacy policy
    checks.append(
        Check("privacy", "Privacy policy URL", "ok" if md and md.privacy_url else "fail",
              "" if md and md.privacy_url else "A privacy policy URL is required by stores.")
    )

    # Live connection to the store — honest: not connected here
    if provider and provider.is_available():
        checks.append(Check("connection", f"{provider.name} connection", "ok"))
    else:
        name = provider.name if provider else release.provider
        checks.append(Check("connection", f"{name} connection", "manual",
                            "Store account not connected — submission is a manual step."))

    return checks


def score(checks: list[Check]) -> int:
    """0-100. `fail` counts fully against; `warn`/`manual` count as half credit."""
    if not checks:
        return 0
    weights = {"ok": 1.0, "warn": 0.5, "manual": 0.5, "fail": 0.0}
    got = sum(weights.get(c.status, 0.0) for c in checks)
    return round(100 * got / len(checks))


def verdict(checks: list[Check]) -> str:
    if any(c.status == "fail" for c in checks):
        return "Not ready"
    if any(c.status in ("warn", "manual") for c in checks):
        return "Ready to submit (with manual steps)"
    return "Ready to submit"


def _platform_for(provider_key: str) -> str:
    return {
        "google_play": "android",
        "apple_app_store": "ios",
        "huawei_appgallery": "harmony",
    }.get(provider_key, "android")
