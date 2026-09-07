"""Go module scaffold.

Wraps a generated Go app (package `app`, app.go + *_test.go) with a go.mod and a
devforge.json manifest telling the runner to use `go test ./...` with module
downloads disabled (GOPROXY=off) and no cgo — so a standard-library-only module
builds and tests offline. Runs wherever the `go` toolchain is installed; where it
isn't, the runner skips with an honest note.
"""
from __future__ import annotations

import json

_GO_MOD = "module app\n\ngo 1.21\n"

_MANIFEST = json.dumps(
    {
        "stack": "go",
        "runnable": True,
        "test_command": ["go", "test", "./...", "-v"],
        "env": {"GOPROXY": "off", "GOFLAGS": "-mod=mod", "CGO_ENABLED": "0"},
    },
    indent=2,
) + "\n"


def scaffold_go_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    files = dict(app_files)
    files.setdefault("go.mod", _GO_MOD)
    files["devforge.json"] = _MANIFEST
    return files
