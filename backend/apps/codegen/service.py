"""Turn generated files into committed, verified source.

`materialize` writes files into the project's git repo and commits them.
`verify_python` compile-checks the generated Python files in the build sandbox —
real verification that the code parses, without needing the whole app scaffolded
or its dependencies installed. Non-Python files aren't compile-checked here (e.g.
Dart needs its own toolchain); callers get an honest "no Python to compile".
"""
from __future__ import annotations

import re
import sys

from apps.build_sandbox.base import SandboxLimits
from apps.build_sandbox.service import get_sandbox
from apps.repositories.service import GitError, repo_for_project


def materialize(project, files: list[dict], *, message: str):
    """Write files into the project repo and commit. Returns (repo, commit_sha)."""
    repo = repo_for_project(project)
    if not repo.is_initialized:
        repo.init()
    repo.write_files({f["path"]: f["content"] for f in files})
    try:
        sha = repo.commit(message)
    except GitError:
        sha = None  # nothing actually changed
    return repo, sha


def verify_python(files: list[dict]) -> tuple[bool, str]:
    """Compile-check generated .py files in the sandbox. Returns (ok, log)."""
    py = {f["path"]: f["content"] for f in files if f["path"].endswith(".py")}
    if not py:
        return True, "No Python files to compile."
    result = get_sandbox().run(
        [sys.executable, "-m", "py_compile", *py.keys()],
        files=py,
        limits=SandboxLimits(wall_timeout_seconds=30, cpu_seconds=30),
    )
    if result.ok:
        return True, f"Compiled {len(py)} Python file(s) successfully."
    return False, (result.stderr or result.stdout or "compilation failed").strip()


def _int(match) -> int:
    return int(match.group(1)) if match else 0


def run_repo_tests(project, *, command=None) -> dict:
    """Run the project repo's test suite in the sandbox and parse the results.

    Loads every tracked file into an isolated sandbox and runs `command` (default
    `python -m unittest discover`). Returns real ran/failure/error counts and a
    pass flag from the process exit code — a genuine test run, not a claim.
    `passed` is None when there is nothing to run (no repo / no Python).
    """
    repo = repo_for_project(project)
    if not repo.is_initialized:
        return {"ran": 0, "passed": None, "note": "no repository"}

    files = {}
    for rel in repo.list_files():
        try:
            files[rel] = (repo.path / rel).read_text()
        except (OSError, UnicodeDecodeError):
            continue
    if not any(k.endswith(".py") for k in files):
        return {"ran": 0, "passed": None, "note": "no Python files to test"}

    command = command or [sys.executable, "-m", "unittest", "discover", "-v"]
    result = get_sandbox().run(
        command, files=files, limits=SandboxLimits(wall_timeout_seconds=60, cpu_seconds=60)
    )
    output = (result.stderr or "") + (result.stdout or "")
    return {
        "ran": _int(re.search(r"Ran (\d+) test", output)),
        "failures": _int(re.search(r"failures=(\d+)", output)),
        "errors": _int(re.search(r"errors=(\d+)", output)),
        "passed": result.exit_code == 0 and not result.timed_out,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "output": output[-2000:],
    }
