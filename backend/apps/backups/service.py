"""Create and restore project backups (restore points over the repo)."""
from __future__ import annotations

from apps.backups.models import ProjectBackup
from apps.repositories.service import repo_for_project


class BackupError(Exception):
    pass


def create_backup(project, *, label: str, created_by=None) -> ProjectBackup:
    repo = repo_for_project(project)
    sha = repo.head() if repo.is_initialized else ""
    if not sha:
        raise BackupError("Nothing to back up yet — build the project first.")
    backup = ProjectBackup.objects.create(
        project=project, label=(label or "Snapshot").strip()[:200],
        commit_sha=sha, created_by=created_by,
    )
    from apps.audit.service import record
    record("backup.created", actor=created_by, organization=project.organization,
           target=f"project:{project.id}", summary=f"{backup.label} @ {sha}")
    return backup


def restore_backup(backup: ProjectBackup, *, actor=None) -> ProjectBackup:
    repo = repo_for_project(backup.project)
    if not repo.is_initialized:
        raise BackupError("This project has no repository to restore into.")
    repo.reset_hard(backup.commit_sha)
    from apps.audit.service import record
    record("backup.restored", actor=actor, organization=backup.project.organization,
           target=f"project:{backup.project.id}", summary=f"{backup.label} @ {backup.commit_sha}")
    return backup
