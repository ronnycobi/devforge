"""Python standard-library project scaffold.

python-stdlib is the generic Python baseline — usually plain modules + unittest,
not a web app. So this scaffolder is a no-op UNLESS the app opts into being a web
server by exposing a WSGI callable `application` in app.py. When it does, DevForge
adds a wsgiref server entrypoint (stdlib only, no installs) and a devforge.json
`run` block so the preview runner can serve it on $PORT. Non-web projects are left
exactly as generated.
"""
from __future__ import annotations

import json
import re

_SERVER_PY = (
    "import os\n"
    "from wsgiref.simple_server import make_server\n"
    "from app import application\n\n"
    "port = int(os.environ.get('PORT', '3000'))\n"
    "make_server('127.0.0.1', port, application).serve_forever()\n"
)

_MANIFEST = json.dumps(
    {
        "stack": "python-stdlib",
        "runnable": True,
        "test_command": ["python", "-m", "unittest", "discover", "-v"],
        "run": {
            "command": ["python", "server.py"],
            "port_env": "PORT",
            "health_path": "/",
            "ready_timeout_s": 15,
        },
    },
    indent=2,
) + "\n"

_WSGI = re.compile(r"(?m)^\s*application\s*=|def\s+application\s*\(")


def scaffold_stdlib_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    files = dict(app_files)
    if "app.py" in files and _WSGI.search(files["app.py"]):
        files.setdefault("server.py", _SERVER_PY)
        files["devforge.json"] = _MANIFEST
    return files  # non-web project: unchanged
