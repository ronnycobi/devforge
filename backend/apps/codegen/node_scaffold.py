"""Node.js project scaffold.

Wraps a generated Node app (flat app.js + *.test.js) with a minimal package.json,
a DevForge-supplied server entrypoint (server.js) that boots the app on $PORT for
the preview runner, and a devforge.json manifest declaring both `test_command`
(`node --test`) and a `run` block. Built-in Node only — no npm packages — so it
runs in the network-free sandbox and previews without any install step.
"""
from __future__ import annotations

import json

_PACKAGE_JSON = json.dumps(
    {"name": "app", "private": True, "type": "commonjs"}, indent=2
) + "\n"

# DevForge-owned entrypoint. The generated app.js exports a factory (or a server);
# this boots it on the port the preview runner assigns, defensively handling the
# common export shapes.
_SERVER_JS = (
    "const mod = require('./app.js');\n"
    "const make = mod.makeServer || mod.createServer || mod.default || mod;\n"
    "const server = (typeof make === 'function') ? make() : make;\n"
    "const port = process.env.PORT || 3000;\n"
    "if (server && typeof server.listen === 'function') {\n"
    "  server.listen(port, '127.0.0.1', () => console.log('listening on ' + port));\n"
    "} else {\n"
    "  console.error('DevForge: app.js did not export a startable server');\n"
    "  process.exit(1);\n"
    "}\n"
)

_MANIFEST = json.dumps(
    {
        "stack": "node",
        "runnable": True,
        "test_command": ["node", "--test"],
        "run": {
            "command": ["node", "server.js"],
            "port_env": "PORT",
            "health_path": "/",
            "ready_timeout_s": 15,
        },
    },
    indent=2,
) + "\n"


def scaffold_node_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    files = dict(app_files)
    files.setdefault("package.json", _PACKAGE_JSON)
    files.setdefault("server.js", _SERVER_JS)
    files["devforge.json"] = _MANIFEST
    return files
