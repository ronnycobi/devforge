"""Deployment/hosting abstraction for websites (spec §13, §14, §50).

One interface, many hosts. The `devforge_local` host is REAL: it snapshots the
project's built site into an immutable per-version directory that DevForge serves
over HTTP at a working URL. It executes no customer code — it serves files — so it
is safe for local/single-tenant hosting (same posture as the preview runner).

Cloud hosts (Vercel/Cloudflare/AWS/DigitalOcean) are declared but report
unavailable until real credentials + integration exist — they refuse rather than
fake a deploy (spec §13/§50). Adding a working one = implement the adapter; the
publish flow doesn't change.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from apps.repositories.service import repo_for_project, workspaces_root


class HostError(Exception):
    pass


def published_root() -> Path:
    root = Path(workspaces_root()) / "published"
    root.mkdir(parents=True, exist_ok=True)
    return root


class HostTarget:
    key = ""
    name = ""

    def is_available(self) -> bool:
        return False

    def publish(self, version) -> tuple[str, str]:
        """Publish and return (url, log). Raise HostError on failure."""
        raise NotImplementedError

    def health(self, version) -> tuple[str, str]:
        raise NotImplementedError


class DevForgeLocalHost(HostTarget):
    """Snapshots the built site and serves it from DevForge at a stable URL."""

    key = "devforge_local"
    name = "DevForge hosting"

    def is_available(self) -> bool:
        return True

    def publish(self, version) -> tuple[str, str]:
        project = version.website.project
        repo = repo_for_project(project)
        if not repo.is_initialized or not repo.list_files():
            raise HostError("There's nothing to publish yet — build/preview the site first.")

        dest = published_root() / version.website.subdomain / version.version
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        # Copy the built site (files only; skip the .git dir).
        copied = 0
        for rel in repo.list_files():
            src = Path(repo.path) / rel
            if not src.is_file():
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied += 1
        if copied == 0:
            raise HostError("No servable files were produced by the build.")

        url = f"/sites/{version.website.subdomain}/"
        return url, f"Published {copied} file(s) to {dest}"

    def health(self, version) -> tuple[str, str]:
        """Real check: the served snapshot exists and has an entry document."""
        d = Path(version.artifact_dir or "")
        if not d.exists():
            return "down", "Published files are missing."
        if (d / "index.html").is_file():
            return "healthy", "Serving index.html"
        # Any file at all is still servable, just without a default document.
        for _ in d.rglob("*"):
            return "healthy", "Serving published files"
        return "down", "No published files found."


class _UnavailableHost(HostTarget):
    def __init__(self, key, name):
        self.key, self.name = key, name

    def is_available(self) -> bool:
        return False

    def publish(self, version):
        raise HostError(
            f"{self.name} hosting is not configured on this host "
            "(credentials/integration required). DevForge does not fake a deploy."
        )

    def health(self, version):
        return "unknown", f"{self.name} not configured"


_HOSTS: dict[str, HostTarget] = {
    "devforge_local": DevForgeLocalHost(),
    "vercel": _UnavailableHost("vercel", "Vercel"),
    "cloudflare": _UnavailableHost("cloudflare", "Cloudflare"),
    "aws": _UnavailableHost("aws", "AWS"),
    "digitalocean": _UnavailableHost("digitalocean", "DigitalOcean"),
}


def get_host(key: str) -> HostTarget | None:
    return _HOSTS.get(key)


def host_status() -> list[dict]:
    return [{"key": h.key, "name": h.name, "available": h.is_available()} for h in _HOSTS.values()]
