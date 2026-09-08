"""Go module scaffold.

Wraps a generated Go app (package `app`, app.go + *_test.go) with a go.mod, a
DevForge-owned server entrypoint (cmd/server) that serves the app's Handler() on
$PORT for the preview runner, and a devforge.json manifest declaring both the
test command (root package only, so the entrypoint never affects tests) and a
`run` block. Standard-library-only, module downloads disabled (GOPROXY=off), so it
builds/tests/runs offline wherever the `go` toolchain is installed.
"""
from __future__ import annotations

import json

_GO_MOD = "module app\n\ngo 1.21\n"

# DevForge-owned entrypoint: boots the app's exported Handler() on $PORT. Lives in
# its own package/dir so `go test .` (root) never compiles it.
_MAIN_GO = (
    "package main\n\n"
    "import (\n\t\"net/http\"\n\t\"os\"\n\n\t\"app\"\n)\n\n"
    "func main() {\n"
    "\tport := os.Getenv(\"PORT\")\n"
    "\tif port == \"\" {\n\t\tport = \"3000\"\n\t}\n"
    "\thttp.ListenAndServe(\"127.0.0.1:\"+port, app.Handler())\n"
    "}\n"
)

_GO_ENV = {"GOPROXY": "off", "GOFLAGS": "-mod=mod", "CGO_ENABLED": "0"}

_MANIFEST = json.dumps(
    {
        "stack": "go",
        "runnable": True,
        "test_command": ["go", "test", ".", "-v"],
        "env": _GO_ENV,
        "run": {
            "command": ["go", "run", "./cmd/server"],
            "port_env": "PORT",
            "health_path": "/",
            "ready_timeout_s": 40,
            "env": _GO_ENV,
        },
    },
    indent=2,
) + "\n"


def scaffold_go_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    files = dict(app_files)
    files.setdefault("go.mod", _GO_MOD)
    files.setdefault("cmd/server/main.go", _MAIN_GO)
    files["devforge.json"] = _MANIFEST
    return files
