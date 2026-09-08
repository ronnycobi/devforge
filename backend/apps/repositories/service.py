"""Per-project git working trees.

DevForge version-controls each project's generated code in its own local git
repository (docs/PRODUCT.md §17). This wraps the git operations the code-gen and
export phases need: init, write files, commit, branch, diff, log. It performs
LOCAL operations only — pushing to remotes belongs to deployment/external phases
and is deliberately not here.

Commit identity is passed per-commit with `-c`, so no global git config is
required or mutated.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from django.conf import settings

BOT_NAME = "DevForge"
BOT_EMAIL = "devforge@localhost"


class GitError(Exception):
    pass


def workspaces_root() -> Path:
    root = getattr(settings, "DEVFORGE_WORKSPACES_ROOT", None)
    if root:
        return Path(root)
    return Path(settings.BASE_DIR).parent / "workspaces"


def repo_for_project(project) -> "ProjectRepo":
    return ProjectRepo(workspaces_root() / f"project-{project.id}")


class ProjectRepo:
    def __init__(self, path):
        self.path = Path(path)

    # --- git plumbing -----------------------------------------------------

    def _git(self, *args, check=True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed: {result.stderr.strip()}"
            )
        return result

    # --- lifecycle --------------------------------------------------------

    @property
    def is_initialized(self) -> bool:
        return (self.path / ".git").is_dir()

    def init(self) -> "ProjectRepo":
        self.path.mkdir(parents=True, exist_ok=True)
        if not self.is_initialized:
            self._git("init", "-q", "-b", "main")
        return self

    # --- files ------------------------------------------------------------

    def write_files(self, files: dict[str, str]):
        root = self.path.resolve()
        for rel, content in files.items():
            if os.path.isabs(rel):
                raise GitError(f"Absolute paths not allowed: {rel}")
            dest = (self.path / rel).resolve()
            if dest != root and root not in dest.parents:
                raise GitError(f"Path escapes repository: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

    def list_files(self) -> list[str]:
        return [line for line in self._git("ls-files").stdout.splitlines() if line]

    # --- commits / branches ----------------------------------------------

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        if not self._git("status", "--porcelain").stdout.strip():
            raise GitError("Nothing to commit.")
        self._git(
            "-c", f"user.name={BOT_NAME}",
            "-c", f"user.email={BOT_EMAIL}",
            "commit", "-q", "-m", message,
        )
        return self._git("rev-parse", "--short", "HEAD").stdout.strip()

    def current_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def create_branch(self, name: str):
        self._git("checkout", "-q", "-b", name)

    def checkout(self, name: str):
        self._git("checkout", "-q", name)

    def log(self, limit: int = 20) -> list[dict]:
        out = self._git(
            "log", f"-{limit}", "--pretty=format:%h%x1f%s", check=False
        ).stdout
        entries = []
        for line in out.splitlines():
            if "\x1f" in line:
                sha, subject = line.split("\x1f", 1)
                entries.append({"sha": sha, "subject": subject})
        return entries

    def diff(self, ref: str = "HEAD") -> str:
        return self._git("diff", ref, check=False).stdout

    def head(self) -> str:
        """Short SHA of the current HEAD, or '' if the repo has no commits."""
        r = self._git("rev-parse", "--short", "HEAD", check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    def reset_hard(self, sha: str):
        """Restore the working tree exactly to `sha` (used to roll back a change)."""
        self._git("reset", "--hard", sha)

    def diff_between(self, base: str, target: str = "HEAD") -> str:
        return self._git("diff", base, target, check=False).stdout
