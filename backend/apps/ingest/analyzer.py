"""Import and analyze an existing codebase into a project's digital twin.

Safe by construction: only text files, path-traversal and junk-dir filtered, and
capped in count/size to avoid zip bombs and huge repos. Extraction populates the
project's git repo and its context (the twin): technology profile, dependencies,
and inferred components — so the change-request loop can then improve it.
"""
from __future__ import annotations

import zipfile
from pathlib import PurePosixPath

from apps.database.capabilities import Category, get_database
from apps.ingest.detect import detect_databases, detect_dependencies, detect_stack
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.repositories.service import repo_for_project

_SYSTEM_OF_RECORD = (Category.RELATIONAL, Category.DISTRIBUTED_SQL, Category.DOCUMENT)

MAX_FILES = 600
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 8_000_000
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env",
              "dist", "build", ".idea", ".mypy_cache", ".pytest_cache", "vendor"}
_SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
             ".gz", ".tar", ".mp4", ".mov", ".woff", ".woff2", ".ttf", ".so",
             ".dylib", ".class", ".pyc", ".lock", ".min.js", ".map")


class IngestError(Exception):
    pass


def _safe(path: str) -> bool:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        return False
    if any(part in _SKIP_DIRS for part in p.parts):
        return False
    if path.lower().endswith(_SKIP_EXT):
        return False
    return True


def extract_zip(fileobj) -> dict[str, str]:
    """Return {relpath: text} for the safe, text files in the archive."""
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as exc:
        raise IngestError("That doesn't look like a valid .zip file.") from exc

    # Many archives wrap everything in a single top folder; strip it.
    members = [m for m in zf.infolist() if not m.is_dir()]
    top = {PurePosixPath(m.filename).parts[0] for m in members if PurePosixPath(m.filename).parts}
    strip = len(top) == 1

    files: dict[str, str] = {}
    total = 0
    for m in members:
        rel = m.filename
        if strip:
            parts = PurePosixPath(rel).parts[1:]
            if not parts:
                continue
            rel = str(PurePosixPath(*parts))
        if not _safe(rel) or m.file_size > MAX_FILE_BYTES:
            continue
        try:
            content = zf.read(m).decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # skip binary / unreadable
        total += len(content.encode("utf-8"))
        if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
            break
        files[rel] = content
    if not files:
        raise IngestError("No importable source files found in the archive.")
    return files


def _components(files: dict) -> list[str]:
    """Top-level source directories become inferred components."""
    dirs = {}
    for path in files:
        parts = PurePosixPath(path).parts
        if len(parts) > 1:
            dirs[parts[0]] = dirs.get(parts[0], 0) + 1
    return [d for d, _ in sorted(dirs.items(), key=lambda kv: -kv[1])][:12]


def import_codebase(project, files: dict, created_by=None) -> dict:
    """Write files to the repo, detect the stack, and populate the twin."""
    repo = repo_for_project(project)
    if not repo.is_initialized:
        repo.init()
    repo.write_files(files)
    try:
        repo.commit(f"Import existing codebase ({len(files)} files)")
    except Exception:
        pass

    stack = detect_stack(files)
    deps = detect_dependencies(files)
    components = _components(files)
    databases = detect_databases(files)

    # The primary datastore is the first system-of-record (relational/document);
    # caches/search engines coexist but aren't the app's technology["database"].
    primary_db = next(
        (d for d in databases
         if (p := get_database(d)) and p.category in _SYSTEM_OF_RECORD),
        databases[0] if databases else None,
    )

    tech = dict(stack)
    if primary_db:
        tech.setdefault("database", primary_db)
    project.mode = "import"
    project.technology = {**(project.technology or {}), **tech}
    project.save(update_fields=["mode", "technology", "updated_at"])

    ctx = ProjectContext(project)
    source = "ingest:import"
    ctx.set(
        ContextKind.ARCHITECTURE, "codebase-overview",
        title="Imported codebase",
        content=f"Imported {len(files)} source files. Detected stack: "
                + (", ".join(f"{r}: {t}" for r, t in stack.items()) or "unknown") + ".",
        data={"files": len(files), "stack": stack, "components": components},
        source=source,
    )
    from django.utils.text import slugify
    for name in components:
        ctx.set(ContextKind.ARCHITECTURE, slugify(name)[:255] or "module",
                title=name, content="Top-level module (from imported code).", source=source)
    if deps:
        ctx.set(ContextKind.DEPENDENCY, "dependencies", title="Dependencies",
                content=", ".join(deps[:40]), data={"dependencies": deps}, source=source)
    if databases:
        profiles = {d: get_database(d) for d in databases}
        ctx.set(
            ContextKind.TECH_DECISION, "detected-databases",
            title="Detected databases",
            content=", ".join(
                f"{p.name} ({p.category.value})" if p else d
                for d, p in profiles.items()
            ),
            data={
                "databases": databases,
                "primary": primary_db,
                "capabilities": {d: (p.as_dict() if p else None) for d, p in profiles.items()},
            },
            source=source,
        )

    return {
        "files": len(files), "stack": stack, "dependencies": deps,
        "components": components, "databases": databases, "primary_database": primary_db,
    }
