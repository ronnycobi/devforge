"""Node.js project scaffold.

Wraps a generated Node app (flat app.js + *.test.js) with a minimal package.json
and a devforge.json manifest telling the runner to use `node --test`. Built-in
Node only — no npm packages — so it runs in the network-free sandbox.
"""
from __future__ import annotations

import json

_PACKAGE_JSON = json.dumps(
    {"name": "app", "private": True, "type": "commonjs"}, indent=2
) + "\n"

_MANIFEST = json.dumps(
    {"stack": "node", "runnable": True, "test_command": ["node", "--test"]}, indent=2
) + "\n"


def scaffold_node_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    files = dict(app_files)
    files.setdefault("package.json", _PACKAGE_JSON)
    files["devforge.json"] = _MANIFEST
    return files
