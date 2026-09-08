"""Preview runner — serve a project's generated files as a real, running site.

Starts `python -m http.server` bound to an ephemeral localhost port, rooted at the
project's repository, and tracks it so the dashboard can proxy it into an iframe.
This is a genuine running server (not a mock) that executes NO customer code — it
only serves files — which makes it safe for local/single-tenant preview.

Running a customer's own server (FastAPI/Django/Node) is a heavier, security-
sensitive step (needs container/network isolation + a per-stack run entrypoint);
it is intentionally NOT done here. There is no background reaper, so previews are
stopped explicitly or when they exceed their TTL on next access — a production
deployment would add a sweeper and stronger isolation.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass

from apps.repositories.service import repo_for_project


class PreviewError(Exception):
    pass


@dataclass
class PreviewProcess:
    project_id: int
    port: int
    proc: subprocess.Popen
    started_at: float
    ttl: int

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None and (time.time() - self.started_at) < self.ttl


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class PreviewRunner:
    def __init__(self):
        self._runs: dict[int, PreviewProcess] = {}

    def get(self, project_id: int) -> PreviewProcess | None:
        pv = self._runs.get(project_id)
        if pv is None:
            return None
        if not pv.alive:
            self.stop(project_id)
            return None
        return pv

    def start_static(self, project, *, ttl: int = 600) -> PreviewProcess:
        repo = repo_for_project(project)
        if not repo.is_initialized or not repo.list_files():
            raise PreviewError("There's nothing to preview yet — build the project first.")
        self.stop(project.id)  # replace any existing preview
        port = _free_port()
        proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port),
             "--bind", "127.0.0.1", "--directory", str(repo.path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if not self._wait_ready(port):
            self._kill(proc)
            raise PreviewError("The preview server did not start.")
        pv = PreviewProcess(project.id, port, proc, time.time(), ttl)
        self._runs[project.id] = pv
        return pv

    def stop(self, project_id: int) -> None:
        pv = self._runs.pop(project_id, None)
        if pv is not None:
            self._kill(pv.proc)

    # --- internals --------------------------------------------------------

    @staticmethod
    def _wait_ready(port: int, tries: int = 20, delay: float = 0.15) -> bool:
        url = f"http://127.0.0.1:{port}/"
        for _ in range(tries):
            try:
                urllib.request.urlopen(url, timeout=1).read(1)
                return True
            except Exception:
                time.sleep(delay)
        return False

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        import os
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


# Process-local registry. (Single-process dev/runserver; a multi-process or
# production deployment would externalize this + add a reaper.)
runner = PreviewRunner()
