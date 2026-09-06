"""Sandbox contract for executing generated/untrusted code.

Generated code is untrusted until tested and reviewed (CLAUDE.md §18), and must
never run inside the DevForge process. This defines the interface and the limits;
concrete backends enforce them to the extent the host allows.

Isolation honesty: the SubprocessSandbox backend enforces wall-clock timeout,
CPU/memory/file-size/process/open-file limits, a scratch working directory, and a
scrubbed environment. It does NOT provide network isolation or a filesystem jail —
those require OS namespaces or containers. For untrusted code with network
concerns, a container-backed sandbox must be used; this interface is written so
one can be dropped in without changing callers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

MB = 1024 * 1024


@dataclass
class SandboxLimits:
    wall_timeout_seconds: float = 10.0
    cpu_seconds: int = 10
    memory_bytes: int = 512 * MB
    max_processes: int = 64
    max_file_size_bytes: int = 32 * MB
    max_open_files: int = 256
    max_output_bytes: int = 1 * MB
    # Desired network state. Not enforced by SubprocessSandbox (see module docs);
    # a container backend honours it.
    network: bool = False


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool = False
    duration_seconds: float = 0.0
    output_truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxError(Exception):
    pass


class Sandbox(ABC):
    name: str = ""

    def available(self) -> bool:
        return True

    @abstractmethod
    def run(
        self,
        command: list[str],
        *,
        files: dict[str, str] | None = None,
        limits: SandboxLimits | None = None,
        stdin: str = "",
    ) -> SandboxResult:
        """Write `files` into an isolated workdir, run `command` there under
        `limits`, and return the captured result."""
        raise NotImplementedError
