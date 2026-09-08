"""React (Vite) project scaffold with a node-testable logic layer.

Produces two things around the model's output:
  1. A real, exportable Vite + React app (package.json, index.html, vite config,
     an entry point) — the framework source a customer ships. It builds with npm,
     which the offline sandbox does not have, so it is not run here.
  2. A framework-free logic layer under src/logic/ with *.test.js using Node's
     built-in test runner — this DOES run in the sandbox via `node --test`, so the
     repair loop can verify and fix the app's logic with no npm and no browser.

The devforge.json manifest points the test runner at `node --test`, which only
discovers the *.test.js logic tests (never the .jsx components), so verification
needs no build step.
"""
from __future__ import annotations

import json

_PACKAGE_JSON = json.dumps(
    {
        "name": "app",
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
            "test": "node --test",
        },
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0"},
    },
    indent=2,
) + "\n"

_INDEX_HTML = (
    "<!doctype html>\n<html lang=\"en\">\n  <head>\n"
    "    <meta charset=\"UTF-8\" />\n"
    "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
    "    <title>App</title>\n  </head>\n  <body>\n"
    "    <div id=\"root\"></div>\n"
    "    <script type=\"module\" src=\"/src/main.jsx\"></script>\n"
    "  </body>\n</html>\n"
)

_MAIN_JSX = (
    "import React from 'react';\n"
    "import { createRoot } from 'react-dom/client';\n"
    "import App from './App.jsx';\n\n"
    "createRoot(document.getElementById('root')).render(<App />);\n"
)

_VITE_CONFIG = (
    "import { defineConfig } from 'vite';\n"
    "import react from '@vitejs/plugin-react';\n\n"
    "export default defineConfig({ plugins: [react()] });\n"
)

_MANIFEST = json.dumps(
    {
        "stack": "react",
        "runnable": True,
        "test_command": ["node", "--test"],
        "note": (
            "React app builds with Vite (npm). DevForge verifies the framework-free "
            "src/logic layer with `node --test` here; the full build runs where npm "
            "is available."
        ),
    },
    indent=2,
) + "\n"


def scaffold_react_project(app_label: str, app_files: dict[str, str]) -> dict[str, str]:
    files = dict(app_files)
    files.setdefault("package.json", _PACKAGE_JSON)
    files.setdefault("index.html", _INDEX_HTML)
    files.setdefault("vite.config.js", _VITE_CONFIG)
    files.setdefault("src/main.jsx", _MAIN_JSX)
    files["devforge.json"] = _MANIFEST
    return files
