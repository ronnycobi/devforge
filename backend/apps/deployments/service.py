"""Deployment orchestration.

Requesting a deploy creates a record; production deploys start gated on approval.
Running a deploy refuses production without approval, then delegates to the
selected CloudProvider and records the outcome. No autonomous production changes.
"""
from __future__ import annotations

from django.utils import timezone

from apps.deployments.models import (
    DeployEnvironment,
    Deployment,
    DeploymentStatus,
)
from apps.deployments.providers import DeployError, get_provider


class DeploymentError(Exception):
    pass


def request_deploy(*, project, environment, provider, workspace=None, created_by=None) -> Deployment:
    if environment not in DeployEnvironment.values:
        raise DeploymentError(f"Unknown environment '{environment}'")
    if get_provider(provider) is None:
        raise DeploymentError(f"Unknown provider '{provider}'")

    status = (
        DeploymentStatus.WAITING_FOR_APPROVAL
        if environment == DeployEnvironment.PRODUCTION
        else DeploymentStatus.PENDING
    )
    return Deployment.objects.create(
        project=project,
        workspace=workspace,
        environment=environment,
        provider=provider,
        status=status,
        created_by=created_by,
    )


def approve(deployment: Deployment, user) -> Deployment:
    deployment.approved = True
    deployment.approved_by = user
    deployment.approved_at = timezone.now()
    if deployment.status == DeploymentStatus.WAITING_FOR_APPROVAL:
        deployment.status = DeploymentStatus.PENDING
    deployment.save(
        update_fields=["approved", "approved_by", "approved_at", "status"]
    )
    return deployment


def run(deployment: Deployment) -> Deployment:
    if deployment.status in (
        DeploymentStatus.SUCCEEDED,
        DeploymentStatus.DEPLOYING,
        DeploymentStatus.CANCELLED,
    ):
        return deployment

    # Production is approval-gated — never deploy to prod autonomously.
    if deployment.is_production and not deployment.approved:
        return _fail(deployment, "Production deploy requires approval.")

    provider = get_provider(deployment.provider)
    if provider is None or not provider.is_available():
        return _fail(
            deployment, f"Provider '{deployment.provider}' is unavailable."
        )

    deployment.status = DeploymentStatus.DEPLOYING
    deployment.save(update_fields=["status"])
    try:
        url, log = provider.deploy(deployment)
    except DeployError as exc:
        return _fail(deployment, str(exc))
    except Exception as exc:  # boundary: record, don't crash the caller
        return _fail(deployment, f"Unexpected deploy error: {exc}")

    deployment.status = DeploymentStatus.SUCCEEDED
    deployment.url = url
    deployment.log = log
    deployment.completed_at = timezone.now()
    deployment.save(update_fields=["status", "url", "log", "completed_at"])
    return deployment


def _fail(deployment: Deployment, message: str) -> Deployment:
    deployment.status = DeploymentStatus.FAILED
    deployment.log = message
    deployment.completed_at = timezone.now()
    deployment.save(update_fields=["status", "log", "completed_at"])
    return deployment
