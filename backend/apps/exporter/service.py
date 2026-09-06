"""Project export.

Packages everything DevForge knows about a project into a single, independently
understandable zip (docs/PRODUCT.md §26): human-readable docs generated from the
project context, a machine-readable API spec and data model, an env template, and
any git-tracked generated source. No artificial lock-in — a user can take this and
leave.
"""
from __future__ import annotations

import io
import json
import zipfile

from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.repositories.service import repo_for_project

# Which context kinds render into which doc file.
_DOC_SECTIONS = [
    ("requirements", [ContextKind.REQUIREMENT], "Requirements"),
    ("architecture", [ContextKind.ARCHITECTURE, ContextKind.TECH_DECISION], "Architecture"),
    ("api", [ContextKind.API], "API"),
    ("data-model", [ContextKind.SCHEMA], "Data model"),
    ("screens", [ContextKind.SCREEN], "Screens"),
    ("tests", [ContextKind.TESTING], "Test plan"),
    ("review", [ContextKind.REVIEW], "Review findings"),
]


def _render_section(ctx: ProjectContext, kinds, heading: str) -> str:
    entries = ctx.all().filter(kind__in=kinds).order_by("kind", "key")
    lines = [f"# {heading}", ""]
    if not entries:
        lines.append("_Nothing recorded yet._")
        return "\n".join(lines) + "\n"
    for e in entries:
        lines.append(f"## {e.title}")
        if e.content:
            lines.append("")
            lines.append(e.content)
        if e.data:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(e.data, indent=2))
            lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"


def _readme(project, ctx: ProjectContext) -> str:
    counts = {label: ctx.by_kind(kinds[0]).count() for _, kinds, label in _DOC_SECTIONS}
    lines = [
        f"# {project.name}",
        "",
        (project.description or "Exported from DevForge.").strip(),
        "",
        "## Contents",
        "- `docs/` — requirements, architecture, API, data model, screens, tests, review",
        "- `api-spec.json` — machine-readable endpoint list",
        "- `data-model.json` — entities and fields",
        "- `.env.example` — configuration template",
        "- `source/` — generated source (git-tracked), when present",
        "",
        "## Summary",
    ]
    for _, _, label in _DOC_SECTIONS:
        lines.append(f"- {label}: {counts[label]}")
    lines.append("")
    lines.append("_Exported from DevForge. This project is yours to run anywhere._")
    return "\n".join(lines) + "\n"


def _api_spec(ctx: ProjectContext) -> list[dict]:
    spec = []
    for e in ctx.by_kind(ContextKind.API).order_by("key"):
        d = e.data or {}
        spec.append(
            {
                "method": d.get("method", ""),
                "path": d.get("path", ""),
                "purpose": e.content,
                "module": d.get("module", ""),
                "auth": d.get("auth", ""),
                "request": d.get("request", {}),
                "response": d.get("response", {}),
            }
        )
    return spec


def _data_model(ctx: ProjectContext) -> list[dict]:
    models = []
    for e in ctx.by_kind(ContextKind.SCHEMA).order_by("key"):
        d = e.data or {}
        models.append(
            {
                "name": e.title,
                "description": e.content,
                "fields": d.get("fields", []),
                "relations": d.get("relations", []),
            }
        )
    return models


def build_export(project) -> tuple[str, bytes]:
    """Return (filename, zip_bytes) for the project's export archive."""
    ctx = ProjectContext(project)
    files: dict[str, str] = {"README.md": _readme(project, ctx)}

    for filename, kinds, heading in _DOC_SECTIONS:
        files[f"docs/{filename}.md"] = _render_section(ctx, kinds, heading)

    files["api-spec.json"] = json.dumps(_api_spec(ctx), indent=2) + "\n"
    files["data-model.json"] = json.dumps(_data_model(ctx), indent=2) + "\n"
    files[".env.example"] = (
        "# Configuration template for this project.\n"
        "# Fill in and copy to .env. Never commit secrets.\n"
    )

    # Include git-tracked generated source, if any.
    repo = repo_for_project(project)
    if repo.is_initialized:
        for rel in repo.list_files():
            try:
                files[f"source/{rel}"] = (repo.path / rel).read_text()
            except (OSError, UnicodeDecodeError):
                continue

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, content in files.items():
            archive.writestr(arcname, content)
    return f"{project.slug}-export.zip", buffer.getvalue()
