"""Technology Registry — the catalog of ecosystems DevForge reasons about.

DevForge is stack-agnostic: it builds software in the technology the customer
chooses. This registry is the authoritative catalog of languages, frameworks,
databases, and infra targets. It is intentionally broad (DevForge *knows* these
ecosystems) and honest about reach: `codegen` marks whether DevForge can actually
generate and run that technology today ("supported") or knows it but hasn't wired
generation yet ("planned"). Django + Flutter are DevForge's reference stack — the
one it bootstraps itself in — not a restriction on customers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    INFRASTRUCTURE = "infrastructure"


class CodegenStatus(StrEnum):
    SUPPORTED = "supported"  # DevForge can generate AND run this today
    PLANNED = "planned"      # known ecosystem, generation not yet wired


class Kind(StrEnum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    MOBILE = "mobile"
    DATASTORE = "datastore"
    NONE = ""


@dataclass(frozen=True)
class Technology:
    id: str
    name: str
    category: Category
    language: str | None = None  # for frameworks: their language
    kind: Kind = Kind.NONE
    codegen: CodegenStatus = CodegenStatus.PLANNED


S = CodegenStatus.SUPPORTED
P = CodegenStatus.PLANNED

_LANGUAGES = [
    Technology("python", "Python", Category.LANGUAGE, codegen=S),
    Technology("typescript", "TypeScript", Category.LANGUAGE),
    Technology("javascript", "JavaScript", Category.LANGUAGE),
    Technology("go", "Go", Category.LANGUAGE),
    Technology("java", "Java", Category.LANGUAGE),
    Technology("csharp", "C#", Category.LANGUAGE),
    Technology("rust", "Rust", Category.LANGUAGE),
    Technology("php", "PHP", Category.LANGUAGE),
    Technology("ruby", "Ruby", Category.LANGUAGE),
    Technology("dart", "Dart", Category.LANGUAGE),
    Technology("kotlin", "Kotlin", Category.LANGUAGE),
    Technology("swift", "Swift", Category.LANGUAGE),
    Technology("cpp", "C++", Category.LANGUAGE),
]

_FRAMEWORKS = [
    # Python
    Technology("django", "Django", Category.FRAMEWORK, "python", Kind.BACKEND, S),
    Technology("fastapi", "FastAPI", Category.FRAMEWORK, "python", Kind.BACKEND, P),
    Technology("flask", "Flask", Category.FRAMEWORK, "python", Kind.BACKEND, P),
    # JS/TS
    Technology("node", "Node.js", Category.FRAMEWORK, "javascript", Kind.BACKEND, P),
    Technology("nextjs", "Next.js", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("nestjs", "NestJS", Category.FRAMEWORK, "typescript", Kind.BACKEND, P),
    # Others
    Technology("spring_boot", "Spring Boot", Category.FRAMEWORK, "java", Kind.BACKEND, P),
    Technology("dotnet", ".NET / ASP.NET", Category.FRAMEWORK, "csharp", Kind.BACKEND, P),
    Technology("gin", "Gin", Category.FRAMEWORK, "go", Kind.BACKEND, P),
    Technology("fiber", "Fiber", Category.FRAMEWORK, "go", Kind.BACKEND, P),
    Technology("axum", "Axum", Category.FRAMEWORK, "rust", Kind.BACKEND, P),
    Technology("actix", "Actix", Category.FRAMEWORK, "rust", Kind.BACKEND, P),
    Technology("laravel", "Laravel", Category.FRAMEWORK, "php", Kind.BACKEND, P),
    Technology("rails", "Ruby on Rails", Category.FRAMEWORK, "ruby", Kind.BACKEND, P),
    Technology("ktor", "Ktor", Category.FRAMEWORK, "kotlin", Kind.BACKEND, P),
    Technology("flutter", "Flutter", Category.FRAMEWORK, "dart", Kind.MOBILE, P),
    Technology("swiftui", "SwiftUI", Category.FRAMEWORK, "swift", Kind.MOBILE, P),
]

_DATABASES = [
    Technology("postgresql", "PostgreSQL", Category.DATABASE, kind=Kind.DATASTORE, codegen=S),
    Technology("sqlite", "SQLite", Category.DATABASE, kind=Kind.DATASTORE, codegen=S),
    Technology("mysql", "MySQL", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("mongodb", "MongoDB", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("redis", "Redis", Category.DATABASE, kind=Kind.DATASTORE),
]

_INFRA = [
    Technology("docker", "Docker", Category.DEPLOYMENT),
    Technology("kubernetes", "Kubernetes", Category.DEPLOYMENT),
    Technology("aws", "AWS", Category.INFRASTRUCTURE),
    Technology("gcp", "Google Cloud", Category.INFRASTRUCTURE),
    Technology("azure", "Azure", Category.INFRASTRUCTURE),
    Technology("digitalocean", "DigitalOcean", Category.INFRASTRUCTURE),
]

TECHNOLOGIES = _LANGUAGES + _FRAMEWORKS + _DATABASES + _INFRA


class TechnologyRegistry:
    def __init__(self, technologies):
        self._by_id = {t.id: t for t in technologies}

    def get(self, tech_id):
        return self._by_id.get(tech_id)

    def all(self):
        return list(self._by_id.values())

    def by_category(self, category):
        return [t for t in self._by_id.values() if t.category == category]

    def frameworks_for(self, language):
        return [
            t
            for t in self._by_id.values()
            if t.category == Category.FRAMEWORK and t.language == language
        ]

    def __contains__(self, tech_id):
        return tech_id in self._by_id

    def options_for_role(self, role):
        """Candidate technologies a project can pick for a given role."""
        if role == "database":
            return self.by_category(Category.DATABASE)
        kind = {
            "backend": Kind.BACKEND,
            "frontend": Kind.FRONTEND,
            "mobile": Kind.MOBILE,
        }.get(role)
        if not kind:
            return []
        return [
            t
            for t in self._by_id.values()
            if t.category == Category.FRAMEWORK and t.kind == kind
        ]


registry = TechnologyRegistry(TECHNOLOGIES)

ROLES = ("backend", "frontend", "database", "mobile")


def technology_for_role(project, role):
    """The Technology a project has chosen for a role, or None."""
    tech_id = (getattr(project, "technology", None) or {}).get(role)
    return registry.get(tech_id) if tech_id else None

