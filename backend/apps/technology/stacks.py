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

import importlib.util
import shutil
from dataclasses import dataclass, field
from typing import Callable, Optional

from apps.codegen.django_scaffold import scaffold_django_project
from apps.codegen.go_scaffold import scaffold_go_project
from apps.codegen.node_scaffold import scaffold_node_project
from apps.codegen.react_scaffold import scaffold_react_project
from apps.codegen.stdlib_scaffold import scaffold_stdlib_project

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

_FASTAPI_HINT = (
    "Generate a COMPLETE, runnable FastAPI project using ONLY FastAPI and the "
    "standard library (both are installed; do NOT use a database or other "
    "third-party packages — keep state in memory). Flat layout at the repository "
    "root: put the app in main.py as `app = FastAPI()`, and put tests in "
    "test_*.py using `from fastapi.testclient import TestClient` and "
    "`from main import app` — the TestClient makes in-process HTTP calls, so no "
    "server or network is needed. It must pass `python -m unittest discover`."
)

_NODE_HINT = (
    "Generate a COMPLETE, runnable Node.js project using ONLY Node's built-in "
    "modules (node:http, etc.) and the built-in test runner — NO npm packages "
    "(no Express, no supertest), because the sandbox has no network to install "
    "them. Flat layout at the repository root: put the app in app.js exporting a "
    "factory via module.exports; put tests in files named *.test.js using "
    "node:test and node:assert, starting the server with .listen(0) and calling "
    "it over http://127.0.0.1 with the global fetch(). It must pass `node --test`."
)

_GO_HINT = (
    "Generate a COMPLETE, runnable Go module using ONLY the Go standard library "
    "(net/http, net/http/httptest, testing) — NO third-party modules, because the "
    "sandbox has no network. Use package name `app`. Put the app in app.go and "
    "tests in *_test.go using the testing package and net/http/httptest. Expose "
    "`func Handler() http.Handler` returning your router/mux (tests and the "
    "preview server both use it). DevForge supplies go.mod and the server "
    "entrypoint. It must pass `go test .`."
)

_REACT_HINT = (
    "Generate a runnable React app (built with Vite) AND a framework-free logic "
    "layer that is unit-tested without a browser. Use ES modules (import/export) "
    "with explicit .js/.jsx extensions in relative imports. Layout at the repo "
    "root:\n"
    "- React components in src/ as .jsx files; put the root component in "
    "src/App.jsx.\n"
    "- ALL non-UI logic (state, validation, formatting, data-shaping, building API "
    "requests) in src/logic/ as plain .js modules with NO react/react-dom/DOM "
    "imports.\n"
    "- Tests as *.test.js files under src/logic/, using Node's built-in runner "
    "(import { test } from 'node:test'; import assert from 'node:assert';) and "
    "importing ONLY from the logic modules — never the .jsx components — so they "
    "pass `node --test` with no npm packages and no browser.\n"
    "The .jsx components import and use the logic. DevForge supplies package.json, "
    "index.html and the Vite config — do NOT generate those. Keep it small and "
    "coherent."
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
    # Host executable required to run the stack's tests (python = this interpreter).
    toolchain: str = "python"
    # Python modules that must be importable for the stack to run.
    requires_import: tuple = ()

    def is_runnable(self) -> bool:
        if self.toolchain != "python" and shutil.which(self.toolchain) is None:
            return False
        return all(
            importlib.util.find_spec(mod) is not None for mod in self.requires_import
        )

    def build_project(self, app_label: str, files: list[dict]) -> list[dict]:
        """Turn generated files into the full project file list."""
        if self.scaffolder is None:
            return files
        app_files = {f["path"]: f["content"] for f in files}
        scaffold = self.scaffolder(app_label or "app", app_files)
        return [{"path": p, "content": c} for p, c in scaffold.items()]


_STACKS = {
    "python-stdlib": Stack(
        "python-stdlib", "python", None, "backend", False, _STDLIB_HINT,
        scaffolder=scaffold_stdlib_project,
    ),
    "django": Stack(
        "django", "python", "django", "backend", True, _DJANGO_HINT,
        scaffolder=scaffold_django_project,
    ),
    "fastapi": Stack(
        "fastapi", "python", "fastapi", "backend", False, _FASTAPI_HINT,
        requires_import=("fastapi",),
    ),
    "node": Stack(
        "node", "javascript", None, "backend", False, _NODE_HINT,
        scaffolder=scaffold_node_project, toolchain="node",
    ),
    "go": Stack(
        "go", "go", None, "backend", False, _GO_HINT,
        scaffolder=scaffold_go_project, toolchain="go",
    ),
    "react": Stack(
        "react", "javascript", "react", "frontend", False, _REACT_HINT,
        scaffolder=scaffold_react_project, toolchain="node",
    ),
}


def get_stack(stack_id: str) -> Stack | None:
    return _STACKS.get(stack_id)


def all_stacks() -> list[Stack]:
    return list(_STACKS.values())


def backend_stacks() -> list[Stack]:
    return [s for s in _STACKS.values() if s.kind == "backend"]


def frontend_stacks() -> list[Stack]:
    return [s for s in _STACKS.values() if s.kind == "frontend"]
