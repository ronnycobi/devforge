"""Stack runners — the technologies DevForge can generate AND run today.

A Stack pairs a technology profile with the concrete mechanics code generation
needs: how to scaffold a runnable project around the model's output, what code-gen
guidance to give the model, and whether it can run in the current sandbox. This is
the extensible seam: adding a stack (FastAPI, Go, Next.js, …) means adding a Stack
here with a scaffolder — the agents don't change.

Only stacks that genuinely work are registered. The broader ecosystem DevForge
*knows* about lives in the Technology Registry (registry.py) marked "planned".
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Optional

from apps.codegen.django_scaffold import scaffold_django_project

_STDLIB_HINT = (
    "Generate a COMPLETE, self-contained, standard-library-only Python project. "
    "Flat layout: modules and test files (named test_*.py, using unittest) at the "
    "repository root. It must pass `python -m unittest discover`. No third-party "
    "packages."
)

_DJANGO_HINT = (
    "Generate a Django app. DevForge supplies the project scaffold "
    "(settings/manage.py/migration-free test DB) — do NOT generate them or any "
    "migrations. Provide app-relative files (models.py, tests.py, optionally "
    "serializers.py/views.py). tests.py MUST use django.test.TestCase and exercise "
    "the models through the ORM so they run against a real test database."
)


@dataclass(frozen=True)
class Stack:
    id: str
    language: str
    framework: Optional[str]
    kind: str  # "backend" | "frontend" | "mobile"
    needs_app_label: bool
    prompt_hint: str
    # (app_label, app_files) -> full {path: content} project map. None => use files as-is.
    scaffolder: Optional[Callable] = None
    toolchain: str = "python"  # host executable required to run the stack's tests

    def is_runnable(self) -> bool:
        if self.toolchain == "python":
            return True  # this interpreter
        return shutil.which(self.toolchain) is not None

    def build_project(self, app_label: str, files: list[dict]) -> list[dict]:
        """Turn generated files into the full project file list."""
        if self.scaffolder is None:
            return files
        app_files = {f["path"]: f["content"] for f in files}
        scaffold = self.scaffolder(app_label or "app", app_files)
        return [{"path": p, "content": c} for p, c in scaffold.items()]


_STACKS = {
    "python-stdlib": Stack(
        "python-stdlib", "python", None, "backend", False, _STDLIB_HINT
    ),
    "django": Stack(
        "django", "python", "django", "backend", True, _DJANGO_HINT,
        scaffolder=scaffold_django_project,
    ),
}


def get_stack(stack_id: str) -> Stack | None:
    return _STACKS.get(stack_id)


def all_stacks() -> list[Stack]:
    return list(_STACKS.values())


def backend_stacks() -> list[Stack]:
    return [s for s in _STACKS.values() if s.kind == "backend"]
