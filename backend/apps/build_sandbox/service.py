"""Sandbox selection.

get_sandbox() returns the configured backend. Defaults to the SubprocessSandbox;
a container backend can be selected via settings later without changing callers.
"""
from __future__ import annotations

from django.conf import settings

from apps.build_sandbox.base import Sandbox
from apps.build_sandbox.subprocess_sandbox import SubprocessSandbox

_BACKENDS = {"subprocess": SubprocessSandbox}


def get_sandbox() -> Sandbox:
    backend = getattr(settings, "DEVFORGE_SANDBOX_BACKEND", "subprocess")
    cls = _BACKENDS.get(backend, SubprocessSandbox)
    return cls()
