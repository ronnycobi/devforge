"""Built-in tools — capability-gated wrappers over DevForge's real services.

These are the concrete tools agents use: read/write the project repo, search
code, run the test suite, and execute code in the sandbox. Each wraps an existing,
tested service (repositories, codegen, build_sandbox) and declares the
least-privilege capability it needs. No new execution machinery — just a formal,
permissioned surface over what already works.
"""
from __future__ import annotations

import re

from apps.agents.capabilities import Capability as C
from apps.build_sandbox.base import SandboxLimits
from apps.build_sandbox.service import get_sandbox
from apps.codegen.service import run_repo_tests, verify_python
from apps.repositories.service import GitError, repo_for_project
from apps.tools.base import Tool, ToolResult
from apps.tools.registry import registry

_SKIP = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2")


def _read_repo(project) -> dict[str, str]:
    repo = repo_for_project(project)
    files: dict[str, str] = {}
    if not repo.is_initialized:
        return files
    for rel in repo.list_files():
        if rel.lower().endswith(_SKIP):
            continue
        try:
            files[rel] = (repo.path / rel).read_text()
        except (OSError, UnicodeDecodeError):
            continue
    return files


class RepoReadTool(Tool):
    name = "repo.read"
    description = "Read the project repository: list files, read a file, search, diff, log."
    required = frozenset({C.USE_REPOSITORY})
    actions = frozenset({"list_files", "read_file", "read_all", "diff", "log"})

    def _run(self, project, action, **kwargs) -> ToolResult:
        repo = repo_for_project(project)
        if not repo.is_initialized:
            if action in ("list_files", "read_all"):
                return ToolResult.success([] if action == "list_files" else {})
            return ToolResult.failed("Repository is not initialized.")
        if action == "list_files":
            return ToolResult.success(repo.list_files())
        if action == "read_all":
            return ToolResult.success(_read_repo(project))
        if action == "read_file":
            path = kwargs.get("path", "")
            if path not in repo.list_files():
                return ToolResult.failed(f"No such file '{path}'.")
            return ToolResult.success((repo.path / path).read_text())
        if action == "diff":
            return ToolResult.success(repo.diff(kwargs.get("ref", "HEAD")))
        if action == "log":
            return ToolResult.success(repo.log(kwargs.get("limit", 20)))
        return ToolResult.failed("unhandled action")


class CodeSearchTool(Tool):
    name = "code.search"
    description = "Regex search across the project's source files."
    required = frozenset({C.USE_REPOSITORY})
    actions = frozenset({"search"})

    def _run(self, project, action, **kwargs) -> ToolResult:
        pattern = kwargs.get("pattern", "")
        if not pattern:
            return ToolResult.failed("A 'pattern' is required.")
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return ToolResult.failed(f"Invalid pattern: {exc}")
        hits = []
        for path, content in _read_repo(project).items():
            for i, line in enumerate(content.splitlines(), start=1):
                if rx.search(line):
                    hits.append({"path": path, "line": i, "text": line.strip()[:200]})
                    if len(hits) >= 200:
                        return ToolResult.success(hits)
        return ToolResult.success(hits)


class RepoWriteTool(Tool):
    name = "repo.write"
    description = "Write files, commit, and branch in the project repository."
    required = frozenset({C.WRITE_REPOSITORY})
    actions = frozenset({"write_files", "commit", "create_branch"})

    def _run(self, project, action, **kwargs) -> ToolResult:
        repo = repo_for_project(project)
        if not repo.is_initialized:
            repo.init()
        if action == "write_files":
            files = kwargs.get("files") or {}
            if not isinstance(files, dict) or not files:
                return ToolResult.failed("'files' must be a non-empty {path: content} map.")
            repo.write_files(files)
            return ToolResult.success({"written": len(files)})
        if action == "commit":
            try:
                sha = repo.commit(kwargs.get("message", "DevForge change"))
            except GitError:
                sha = None  # nothing actually changed — not an error
            return ToolResult.success({"commit": sha})
        if action == "create_branch":
            name = kwargs.get("name", "")
            if not name:
                return ToolResult.failed("A branch 'name' is required.")
            repo.create_branch(name)
            return ToolResult.success({"branch": name})
        return ToolResult.failed("unhandled action")


class TestRunnerTool(Tool):
    name = "tests.run"
    description = "Run the project's test suite in the sandbox and return real results."
    required = frozenset({C.RUN_TESTS})
    actions = frozenset({"run"})

    def _run(self, project, action, **kwargs) -> ToolResult:
        return ToolResult.success(run_repo_tests(project, command=kwargs.get("command")))


class SandboxTool(Tool):
    name = "sandbox.exec"
    description = "Compile-check Python or run a command over in-memory files in the sandbox."
    required = frozenset({C.USE_SANDBOX})
    actions = frozenset({"verify_python", "run"})

    def _run(self, project, action, **kwargs) -> ToolResult:
        if action == "verify_python":
            files = kwargs.get("files") or []
            ok, log = verify_python(files)
            return ToolResult.success({"ok": ok, "log": log})
        if action == "run":
            command = kwargs.get("command")
            files = kwargs.get("files") or {}
            if not command:
                return ToolResult.failed("A 'command' is required.")
            result = get_sandbox().run(
                command, files=files,
                limits=SandboxLimits(wall_timeout_seconds=30, cpu_seconds=30),
            )
            return ToolResult.success({
                "exit_code": result.exit_code,
                "stdout": (result.stdout or "")[-4000:],
                "stderr": (result.stderr or "")[-4000:],
                "timed_out": result.timed_out,
            })
        return ToolResult.failed("unhandled action")


def _register_all():
    for tool in (RepoReadTool(), CodeSearchTool(), RepoWriteTool(),
                 TestRunnerTool(), SandboxTool()):
        if tool.name not in registry:
            registry.register(tool)


_register_all()
