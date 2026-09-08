"""Deterministic stack + dependency detection for imported codebases.

Reads manifest files and file extensions to infer the technology stack (mapped to
Technology Registry ids) and dependencies — no model, no network, so it always
works offline and never fabricates. An AI deep-dive can enrich this later.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath


def _basenames(files: dict) -> set[str]:
    return {PurePosixPath(p).name for p in files}


def _raw(files: dict, name: str) -> str:
    for path, content in files.items():
        if PurePosixPath(path).name == name:
            return content or ""
    return ""


def _text(files: dict, name: str) -> str:
    return _raw(files, name).lower()


def _has_ext(files: dict, *exts: str) -> bool:
    return any(p.lower().endswith(exts) for p in files)


def detect_stack(files: dict) -> dict:
    """Return a best-effort technology profile: {backend, frontend, mobile}."""
    base = _basenames(files)
    tech: dict[str, str] = {}

    # --- backend / language ---
    pkg = _text(files, "package.json")
    if "manage.py" in base or "django" in _text(files, "requirements.txt") or "django" in _text(files, "pyproject.toml"):
        tech["backend"] = "django"
    elif "fastapi" in _text(files, "requirements.txt") or "fastapi" in _text(files, "pyproject.toml"):
        tech["backend"] = "fastapi"
    elif "flask" in _text(files, "requirements.txt"):
        tech["backend"] = "flask"
    elif "go.mod" in base:
        tech["backend"] = "go"
    elif "pom.xml" in base or "build.gradle" in base:
        tech["backend"] = "spring_boot"
    elif "gemfile" in base:
        tech["backend"] = "rails"
    elif "composer.json" in base:
        tech["backend"] = "laravel" if "laravel" in _text(files, "composer.json") else "php"
    elif "cargo.toml" in base:
        tech["backend"] = "axum"
    elif pkg:
        if "nestjs" in pkg or "@nestjs" in pkg:
            tech["backend"] = "nestjs"
        elif "express" in pkg:
            tech["backend"] = "express"
        else:
            tech["backend"] = "node"

    # --- frontend (from package.json deps) ---
    if pkg:
        for dep, fid in [("next", "nextjs"), ("nuxt", "nuxt"), ("@angular/core", "angular"),
                         ("svelte", "svelte"), ("vue", "vue"), ("react", "react")]:
            if dep in pkg:
                tech["frontend"] = fid
                break

    # --- mobile ---
    if "pubspec.yaml" in base:
        tech["mobile"] = "flutter"
    elif pkg and "react-native" in pkg:
        tech["mobile"] = "react_native"

    return tech


def detect_dependencies(files: dict) -> list[str]:
    """Best-effort dependency list from the primary manifest."""
    req = _raw(files, "requirements.txt")
    if req:
        return [re.split(r"[=<>~! ]", line, 1)[0].strip()
                for line in req.splitlines() if line.strip() and not line.startswith("#")][:40]
    pkg = _raw(files, "package.json")
    if pkg:
        try:
            data = json.loads(pkg)
            return sorted({**data.get("dependencies", {}), **data.get("devDependencies", {})})[:40]
        except (json.JSONDecodeError, TypeError):
            return []
    gomod = _raw(files, "go.mod")
    if gomod:
        return re.findall(r"\t([\w./-]+) v", gomod)[:40]
    return []


# Database signals, checked only against config/manifest files (not all source)
# to keep the signal clean. Ids match the database capability registry.
_DB_SIGNALS = [
    ("postgresql", ("postgres", "psycopg", "asyncpg")),
    ("mysql", ("mysql", "pymysql")),
    ("mariadb", ("mariadb",)),
    ("sqlite", ("sqlite",)),
    ("mongodb", ("mongo",)),
    ("redis", ("redis",)),
    ("elasticsearch", ("elasticsearch", "opensearch")),
]

_DB_CONFIG_NAMES = {
    "settings.py", "requirements.txt", "pyproject.toml", "package.json",
    "composer.json", "docker-compose.yml", "docker-compose.yaml", "compose.yml",
    "compose.yaml", "gemfile", "database.yml", "go.mod",
}


def _config_text(files: dict) -> str:
    """Lowercased text of just the config/manifest files that name a database."""
    parts = []
    for path, content in files.items():
        name = PurePosixPath(path).name.lower()
        if (name in _DB_CONFIG_NAMES or name.endswith("settings.py")
                or name.endswith(".prisma") or name.startswith(".env")):
            parts.append((content or "").lower())
    return "\n".join(parts)


def detect_databases(files: dict) -> list[str]:
    """Best-effort list of database ids an existing codebase uses (may be empty)."""
    text = _config_text(files)
    found: list[str] = []
    for db_id, signals in _DB_SIGNALS:
        if any(s in text for s in signals):
            found.append(db_id)
    return found
