"""Subprocess-based sandbox.

Runs a command in a throwaway working directory as a child process in its own
session (so the whole process group can be killed on timeout), under POSIX
resource limits, with a scrubbed environment. See base.py for what this does and
does not isolate (notably: no network isolation, no filesystem jail).
"""
from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from apps.build_sandbox.base import Sandbox, SandboxError, SandboxLimits, SandboxResult

_SCRUBBED_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def _set_limit(which, soft, hard=None):
    # Best-effort: some limits aren't enforced on every OS (e.g. RLIMIT_AS on
    # macOS). Never let a failed limit abort the run.
    try:
        resource.setrlimit(which, (soft, hard if hard is not None else soft))
    except (ValueError, OSError):
        pass


def _make_preexec(limits: SandboxLimits):
    def _preexec():
        os.setsid()  # new session: the process group == child pid, killable en masse
        _set_limit(resource.RLIMIT_CPU, limits.cpu_seconds, limits.cpu_seconds + 1)
        _set_limit(resource.RLIMIT_FSIZE, limits.max_file_size_bytes)
        _set_limit(resource.RLIMIT_NOFILE, limits.max_open_files)
        if hasattr(resource, "RLIMIT_NPROC"):
            _set_limit(resource.RLIMIT_NPROC, limits.max_processes)
        for name in ("RLIMIT_AS", "RLIMIT_DATA"):
            which = getattr(resource, name, None)
            if which is not None:
                _set_limit(which, limits.memory_bytes)

    return _preexec


class SubprocessSandbox(Sandbox):
    name = "subprocess"

    def _write_files(self, workdir: Path, files: dict[str, str]):
        root = workdir.resolve()
        for rel, content in files.items():
            if os.path.isabs(rel):
                raise SandboxError(f"Absolute paths not allowed in sandbox: {rel}")
            dest = (workdir / rel).resolve()
            # Reject anything escaping the workdir (path traversal).
            if dest != root and root not in dest.parents:
                raise SandboxError(f"Path escapes sandbox: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

    def run(self, command, *, files=None, limits=None, stdin="") -> SandboxResult:
        limits = limits or SandboxLimits()
        workdir = Path(tempfile.mkdtemp(prefix="devforge-sbx-"))
        try:
            if files:
                self._write_files(workdir, files)

            env = {
                "PATH": _SCRUBBED_PATH,
                "HOME": str(workdir),
                "TMPDIR": str(workdir),
                "LANG": "C.UTF-8",
            }

            start = time.monotonic()
            timed_out = False
            proc = subprocess.Popen(
                command,
                cwd=str(workdir),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=_make_preexec(limits),
            )
            try:
                stdout, stderr = proc.communicate(
                    input=stdin, timeout=limits.wall_timeout_seconds
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_group(proc)
                stdout, stderr = proc.communicate()
            duration = time.monotonic() - start

            stdout, t1 = self._bound(stdout, limits.max_output_bytes)
            stderr, t2 = self._bound(stderr, limits.max_output_bytes)
            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                timed_out=timed_out,
                duration_seconds=round(duration, 3),
                output_truncated=t1 or t2,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _kill_group(proc):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    @staticmethod
    def _bound(text: str, max_bytes: int):
        encoded = text.encode("utf-8", "replace")
        if len(encoded) <= max_bytes:
            return text, False
        return encoded[:max_bytes].decode("utf-8", "ignore") + "\n...[truncated]", True

    def run_python(self, code: str, *, limits=None, extra_files=None) -> SandboxResult:
        """Convenience: run a Python snippet as main.py under the sandbox."""
        import sys

        files = {"main.py": code}
        if extra_files:
            files.update(extra_files)
        return self.run([sys.executable, "main.py"], files=files, limits=limits)
