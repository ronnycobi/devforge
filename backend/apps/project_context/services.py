"""ProjectContext — the read/write API agents use for project memory.

`set` upserts a singleton fact by key (e.g. tech_decision "database"); `add`
appends a new entry with an auto key (e.g. one of many known issues). `digest`
renders a compact, size-bounded text view for injecting into a model prompt — the
retrieval step that replaces re-sending the whole repository.
"""
from __future__ import annotations

from apps.core.slugs import unique_slug
from apps.project_context.models import ContextEntry


class ProjectContext:
    def __init__(self, project):
        self.project = project

    def set(self, kind, key, *, title="", content="", data=None, source="", created_by=None):
        """Create or update the entry identified by (kind, key)."""
        entry, _ = ContextEntry.objects.update_or_create(
            project=self.project,
            kind=kind,
            key=key,
            defaults={
                "title": title or key,
                "content": content,
                "data": data or {},
                "source": source,
                "created_by": created_by,
            },
        )
        return entry

    def add(self, kind, *, title, content="", data=None, source="", created_by=None):
        """Append a new entry with an auto-generated key unique in (project, kind)."""
        key = unique_slug(
            ContextEntry,
            title,
            field="key",
            scope={"project": self.project, "kind": kind},
            fallback=kind,
        )
        return ContextEntry.objects.create(
            project=self.project,
            kind=kind,
            key=key,
            title=title,
            content=content,
            data=data or {},
            source=source,
            created_by=created_by,
        )

    def get(self, kind, key):
        return ContextEntry.objects.filter(
            project=self.project, kind=kind, key=key
        ).first()

    def by_kind(self, kind):
        return ContextEntry.objects.filter(project=self.project, kind=kind)

    def all(self):
        return ContextEntry.objects.filter(project=self.project)

    def remove(self, kind, key):
        return ContextEntry.objects.filter(
            project=self.project, kind=kind, key=key
        ).delete()

    def digest(self, *, kinds=None, max_chars=4000) -> str:
        """A compact, grouped, size-bounded text view for prompt injection."""
        qs = self.all()
        if kinds:
            qs = qs.filter(kind__in=kinds)
        qs = qs.order_by("kind", "key")

        lines = [f"# Project context: {self.project.name}"]
        current_kind = None
        for entry in qs:
            if entry.kind != current_kind:
                current_kind = entry.kind
                lines.append(f"\n## {entry.get_kind_display()}")
            excerpt = " ".join((entry.content or "").split())
            if len(excerpt) > 300:
                excerpt = excerpt[:297] + "..."
            lines.append(f"- {entry.title}: {excerpt}" if excerpt else f"- {entry.title}")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        return text
