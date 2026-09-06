"""Cloud provider abstraction.

DevForge must not be locked to one cloud (docs/PRODUCT.md §23): deploys go
through a common CloudProvider interface. The `local` provider is real — it
materializes the project's export archive into a local deployment directory (a
DevForge-Cloud-style local target, honest about being local, not a fake cloud).
Real cloud backends (AWS/GCP/…) are gated on SDK+credentials exactly like AI
providers; until configured they report unavailable and refuse to deploy rather
than pretend.
"""
from __future__ import annotations

from pathlib import Path

from apps.exporter.service import build_export
from apps.repositories.service import workspaces_root


class DeployError(Exception):
    pass


class CloudProvider:
    name = ""

    def is_available(self) -> bool:
        return True

    def deploy(self, deployment) -> tuple[str, str]:
        """Deploy and return (url, log). Raise DeployError on failure."""
        raise NotImplementedError


class LocalProvider(CloudProvider):
    name = "local"

    def deploy(self, deployment) -> tuple[str, str]:
        project = deployment.project
        filename, data = build_export(project)
        target = Path(workspaces_root()) / "deployments" / (
            f"project-{project.id}-{deployment.environment}"
        )
        target.mkdir(parents=True, exist_ok=True)
        artifact = target / filename
        artifact.write_bytes(data)
        url = f"file://{artifact}"
        log = (
            f"Local deploy of '{project.name}' to {deployment.environment}: "
            f"wrote {len(data)} bytes to {artifact}"
        )
        return url, log


class _UnavailableCloudProvider(CloudProvider):
    """A named cloud backend that isn't configured on this host."""

    def __init__(self, name):
        self.name = name

    def is_available(self) -> bool:
        return False

    def deploy(self, deployment):
        raise DeployError(
            f"Cloud provider '{self.name}' is not configured on this host "
            "(credentials/SDK required)."
        )


_PROVIDERS = {
    "local": LocalProvider(),
    "aws": _UnavailableCloudProvider("aws"),
    "gcp": _UnavailableCloudProvider("gcp"),
    "azure": _UnavailableCloudProvider("azure"),
    "digitalocean": _UnavailableCloudProvider("digitalocean"),
    "kubernetes": _UnavailableCloudProvider("kubernetes"),
}


def get_provider(name: str) -> CloudProvider | None:
    return _PROVIDERS.get(name)


def all_providers() -> list[CloudProvider]:
    return list(_PROVIDERS.values())
