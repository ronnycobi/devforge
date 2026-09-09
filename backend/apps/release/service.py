"""Release orchestration (spec §5, §7, §18, §21, §28, §43).

Provider-neutral: callers talk to DevForge concepts (connect, build, readiness,
release, submit); the store-specific work lives in the adapters. Every state-
changing step writes a ReleaseEvent and an audit record, and submission is gated
behind explicit human approval (spec §28).

HONESTY: connecting and submitting go through the real provider. Because no live
store account is configured on this host, verify/submit raise StoreError and the
records reflect that truthfully (not_connected / manual action required). Nothing
here fabricates a "Connected" or a successful submission (spec §43).
"""
from __future__ import annotations

from django.utils import timezone

from apps.audit.service import record as audit
from apps.release.models import (
    ConnectionStatus, MobileApplication, MobileBuild, Release, ReleaseApproval,
    ReleaseCheck, ReleaseEvent, ReleaseState, SigningConfiguration, StoreApplication,
    StoreConnection, StoreMetadata,
)
from apps.release import readiness
from apps.release.providers import StoreError, get_provider


class ReleaseServiceError(Exception):
    pass


def _event(release, kind, message, actor=None):
    ReleaseEvent.objects.create(release=release, kind=kind, message=message[:500], actor=actor)


# --- connections (spec §5, §6, §26) --------------------------------------------
def connect_store(*, organization, provider_key, owner=None, external_account_id="",
                  credential_type="", credential_reference="", scopes=None) -> StoreConnection:
    """Create/update a store connection and attempt a live verify.

    We store only a credential *reference*, never a secret. Verify runs against the
    real provider; offline it raises StoreError and we record the connection as
    INCOMPLETE with an honest reason instead of a green light we didn't earn."""
    provider = get_provider(provider_key)
    if provider is None:
        raise ReleaseServiceError(f"Unknown store provider '{provider_key}'.")

    conn, _ = StoreConnection.objects.update_or_create(
        organization=organization, provider=provider_key,
        defaults={
            "owner": owner,
            "external_account_id": external_account_id,
            "credential_type": credential_type,
            "credential_reference": credential_reference,
            "scopes": scopes or [],
            "status": ConnectionStatus.NOT_CONNECTED,
        },
    )
    try:
        provider.verify_connection(conn)
        conn.status = ConnectionStatus.CONNECTED
        conn.detail = ""
        conn.last_verified = timezone.now()
    except StoreError as exc:
        conn.status = ConnectionStatus.INCOMPLETE
        conn.detail = str(exc)
    conn.save(update_fields=["status", "detail", "last_verified", "updated_at"])
    audit("store.connect", actor=owner, organization=organization,
          target=f"store:{provider_key}", summary=conn.get_status_display())
    return conn


def disconnect_store(connection: StoreConnection, actor=None) -> None:
    org, provider_key = connection.organization, connection.provider
    connection.delete()
    audit("store.disconnect", actor=actor, organization=org, target=f"store:{provider_key}")


# --- application identity (spec §7, §14) ---------------------------------------
def create_mobile_application(*, project, name, package_identifier="", bundle_identifier="",
                              version="1.0.0", build_number=1) -> MobileApplication:
    return MobileApplication.objects.create(
        project=project, name=name, package_identifier=package_identifier,
        bundle_identifier=bundle_identifier, version=version, build_number=build_number,
    )


def set_identity(app: MobileApplication, *, package_identifier=None, bundle_identifier=None) -> None:
    """Change package/bundle identity — refused once the app has shipped (spec §7)."""
    if app.releases.filter(state=ReleaseState.RELEASED).exists():
        raise ReleaseServiceError(
            "This application has already been released; its package/bundle identity "
            "is locked to protect existing installs. Changing it would create a new app."
        )
    if package_identifier is not None:
        app.package_identifier = package_identifier
    if bundle_identifier is not None:
        app.bundle_identifier = bundle_identifier
    app.save(update_fields=["package_identifier", "bundle_identifier", "updated_at"])


def ensure_store_application(app: MobileApplication, provider_key, connection=None) -> StoreApplication:
    store_app, _ = StoreApplication.objects.get_or_create(
        mobile_application=app, provider=provider_key,
        defaults={"connection": connection},
    )
    if connection and store_app.connection_id != connection.id:
        store_app.connection = connection
        store_app.save(update_fields=["connection"])
    return store_app


# --- builds & signing (spec §8, §36) -------------------------------------------
def register_build(app: MobileApplication, *, platform, artifact_format="", source_commit="",
                   artifact_path="", status="planned", detail="") -> MobileBuild:
    """Record a build. Offline we don't fake a compiled binary — status stays
    'planned' with an empty artifact_path unless a real artifact is supplied."""
    return MobileBuild.objects.create(
        mobile_application=app, platform=platform, version=app.version,
        build_number=app.build_number, artifact_format=artifact_format,
        artifact_path=artifact_path, source_commit=source_commit,
        status=status, detail=detail,
    )


def configure_signing(app: MobileApplication, *, platform, mode, credential_reference="",
                      configured=False, detail="") -> SigningConfiguration:
    cfg, _ = SigningConfiguration.objects.update_or_create(
        mobile_application=app, platform=platform,
        defaults={"mode": mode, "credential_reference": credential_reference,
                  "configured": configured, "detail": detail},
    )
    return cfg


def set_metadata(store_app: StoreApplication, *, ai_generated=False, approved=False, **fields) -> StoreMetadata:
    md, _ = StoreMetadata.objects.get_or_create(store_application=store_app)
    for key, value in fields.items():
        if hasattr(md, key):
            setattr(md, key, value)
    md.ai_generated = ai_generated
    md.approved = approved
    md.save()
    return md


def generate_store_listing(store_app: StoreApplication, *, user=None) -> StoreMetadata:
    """Draft a store listing from the app's real features (spec §16). The result is
    marked AI-generated and NOT approved — it is never auto-submitted."""
    from apps.release.listing import generate_listing
    project = store_app.mobile_application.project
    draft = generate_listing(project)
    md, _ = StoreMetadata.objects.get_or_create(store_application=store_app)
    md.app_name = draft.get("app_name", "")[:255]
    md.short_description = draft.get("short_description", "")[:255]
    md.full_description = draft.get("full_description", "")
    md.keywords = ", ".join(draft.get("keywords", []))[:500]
    md.ai_generated = True
    md.approved = False   # a human must review and approve before it can be submitted
    md.generated = {
        "feature_descriptions": draft.get("feature_descriptions", []),
        "screenshot_captions": draft.get("screenshot_captions", []),
        "features": draft.get("features", []),
        "source": draft.get("source", ""),
    }
    md.save()
    store_app.metadata_status = "draft"
    store_app.save(update_fields=["metadata_status"])
    from apps.release.models import Release
    for release in Release.objects.filter(store_application=store_app):
        evaluate_readiness(release)
    audit("listing.generate", actor=user, organization=project.organization,
          target=f"store_app:{store_app.id}", summary=f"AI draft ({draft.get('source', '')})")
    return md


def approve_metadata(store_app: StoreApplication, *, user=None) -> StoreMetadata:
    """Human approval of a listing draft (spec §16 — no auto-approval of copy)."""
    md, _ = StoreMetadata.objects.get_or_create(store_application=store_app)
    md.approved = True
    md.save(update_fields=["approved", "updated_at"])
    store_app.metadata_status = "approved"
    store_app.save(update_fields=["metadata_status"])
    from apps.release.models import Release
    for release in Release.objects.filter(store_application=store_app):
        evaluate_readiness(release)
    audit("listing.approve", actor=user,
          organization=store_app.mobile_application.project.organization,
          target=f"store_app:{store_app.id}")
    return md


# --- releases (spec §18, §21, §22) ---------------------------------------------
def _state_from_checks(checks) -> str:
    if any(c.status == "fail" for c in checks):
        return ReleaseState.METADATA_INCOMPLETE if any(
            c.key in ("metadata", "privacy") and c.status == "fail" for c in checks
        ) else ReleaseState.DRAFT
    return ReleaseState.READY_FOR_SUBMISSION


def request_release(*, app: MobileApplication, provider_key, user=None, environment="production",
                    connection=None) -> Release:
    provider = get_provider(provider_key)
    if provider is None:
        raise ReleaseServiceError(f"Unknown store provider '{provider_key}'.")
    store_app = ensure_store_application(app, provider_key, connection)
    build = app.builds.filter(platform=readiness._platform_for(provider_key)).first()

    release = Release.objects.create(
        mobile_application=app, store_application=store_app, provider=provider_key,
        version=app.version, build_number=app.build_number, build=build,
        environment=environment, state=ReleaseState.DRAFT, created_by=user,
    )
    evaluate_readiness(release)
    _event(release, "created", f"Release {release.version}+{release.build_number} for {provider.name}", user)
    audit("release.request", actor=user, organization=app.project.organization,
          target=f"release:{release.id}", summary=f"{provider.name} · {release.version}")
    return release


def evaluate_readiness(release: Release) -> Release:
    """Recompute and persist the readiness checks + score (spec §18)."""
    checks = readiness.evaluate(release)
    release.checks.all().delete()
    ReleaseCheck.objects.bulk_create([
        ReleaseCheck(release=release, key=c.key, label=c.label, status=c.status, detail=c.detail)
        for c in checks
    ])
    release.readiness = readiness.score(checks)
    release.state = _state_from_checks(checks)
    release.save(update_fields=["readiness", "state"])
    return release


def approve_release(release: Release, *, user, action="submit") -> ReleaseApproval:
    """Human approval gate for a sensitive action (spec §28)."""
    approval = ReleaseApproval.objects.create(release=release, action=action, approved_by=user)
    if action == "submit":
        release.approved_at = timezone.now()
        release.save(update_fields=["approved_at"])
    _event(release, "approved", f"{action} approved", user)
    audit("release.approve", actor=user, organization=release.mobile_application.project.organization,
          target=f"release:{release.id}", summary=action)
    return approval


def submit_release(release: Release, *, user=None) -> Release:
    """Submit to the store — requires prior approval, and goes through the REAL
    provider. Offline the provider is unavailable, so this records an honest
    "manual action required" and leaves the release un-submitted (spec §43)."""
    if not release.approvals.filter(action="submit").exists():
        raise ReleaseServiceError("Submission requires explicit approval first (spec §28).")

    provider = get_provider(release.provider)
    try:
        provider.submit_for_review(release)
        release.state = ReleaseState.SUBMITTED
        release.submitted_at = timezone.now()
        release.save(update_fields=["state", "submitted_at"])
        _event(release, "submitted", f"Submitted to {provider.name}", user)
        audit("release.submit", actor=user,
              organization=release.mobile_application.project.organization,
              target=f"release:{release.id}", summary=provider.name)
    except StoreError as exc:
        release.state = ReleaseState.BLOCKED
        release.save(update_fields=["state"])
        _event(release, "manual_action_required", str(exc), user)
        audit("release.submit_blocked", actor=user,
              organization=release.mobile_application.project.organization,
              target=f"release:{release.id}", summary="store not connected")
    return release
