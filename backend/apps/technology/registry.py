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
    Technology("go", "Go", Category.LANGUAGE, codegen=S),
    Technology("java", "Java", Category.LANGUAGE),
    Technology("csharp", "C#", Category.LANGUAGE),
    Technology("rust", "Rust", Category.LANGUAGE),
    Technology("php", "PHP", Category.LANGUAGE),
    Technology("ruby", "Ruby", Category.LANGUAGE),
    Technology("dart", "Dart", Category.LANGUAGE),
    Technology("kotlin", "Kotlin", Category.LANGUAGE),
    Technology("swift", "Swift", Category.LANGUAGE),
    Technology("cpp", "C++", Category.LANGUAGE),
    Technology("scala", "Scala", Category.LANGUAGE),
    Technology("elixir", "Elixir", Category.LANGUAGE),
    Technology("c", "C", Category.LANGUAGE),
]

_FRONTEND_FRAMEWORKS = [
    Technology("react", "React", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("vue", "Vue", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("angular", "Angular", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("svelte", "Svelte", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("sveltekit", "SvelteKit", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("nextjs", "Next.js", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("nuxt", "Nuxt", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("remix", "Remix", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("solidjs", "SolidJS", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("astro", "Astro", Category.FRAMEWORK, "typescript", Kind.FRONTEND, P),
    Technology("htmx", "htmx", Category.FRAMEWORK, "javascript", Kind.FRONTEND, P),
]

_BACKEND_FRAMEWORKS = [
    Technology("django", "Django", Category.FRAMEWORK, "python", Kind.BACKEND, S),
    Technology("fastapi", "FastAPI", Category.FRAMEWORK, "python", Kind.BACKEND, S),
    Technology("flask", "Flask", Category.FRAMEWORK, "python", Kind.BACKEND, P),
    Technology("node", "Node.js", Category.FRAMEWORK, "javascript", Kind.BACKEND, S),
    Technology("express", "Express", Category.FRAMEWORK, "javascript", Kind.BACKEND, P),
    Technology("nestjs", "NestJS", Category.FRAMEWORK, "typescript", Kind.BACKEND, P),
    Technology("spring_boot", "Spring Boot", Category.FRAMEWORK, "java", Kind.BACKEND, P),
    Technology("quarkus", "Quarkus", Category.FRAMEWORK, "java", Kind.BACKEND, P),
    Technology("dotnet", ".NET / ASP.NET", Category.FRAMEWORK, "csharp", Kind.BACKEND, P),
    Technology("gin", "Gin", Category.FRAMEWORK, "go", Kind.BACKEND, P),
    Technology("fiber", "Fiber", Category.FRAMEWORK, "go", Kind.BACKEND, P),
    Technology("echo", "Echo", Category.FRAMEWORK, "go", Kind.BACKEND, P),
    Technology("axum", "Axum", Category.FRAMEWORK, "rust", Kind.BACKEND, P),
    Technology("actix", "Actix", Category.FRAMEWORK, "rust", Kind.BACKEND, P),
    Technology("laravel", "Laravel", Category.FRAMEWORK, "php", Kind.BACKEND, P),
    Technology("symfony", "Symfony", Category.FRAMEWORK, "php", Kind.BACKEND, P),
    Technology("rails", "Ruby on Rails", Category.FRAMEWORK, "ruby", Kind.BACKEND, P),
    Technology("ktor", "Ktor", Category.FRAMEWORK, "kotlin", Kind.BACKEND, P),
    Technology("phoenix", "Phoenix", Category.FRAMEWORK, "elixir", Kind.BACKEND, P),
]

_MOBILE_FRAMEWORKS = [
    Technology("flutter", "Flutter", Category.FRAMEWORK, "dart", Kind.MOBILE, P),
    Technology("react_native", "React Native", Category.FRAMEWORK, "typescript", Kind.MOBILE, P),
    Technology("swiftui", "SwiftUI", Category.FRAMEWORK, "swift", Kind.MOBILE, P),
    Technology("jetpack_compose", "Jetpack Compose", Category.FRAMEWORK, "kotlin", Kind.MOBILE, P),
    Technology("kotlin_multiplatform", "Kotlin Multiplatform", Category.FRAMEWORK, "kotlin", Kind.MOBILE, P),
    Technology("ionic", "Ionic", Category.FRAMEWORK, "typescript", Kind.MOBILE, P),
]

_FRAMEWORKS = _FRONTEND_FRAMEWORKS + _BACKEND_FRAMEWORKS + _MOBILE_FRAMEWORKS

_DATABASES = [
    Technology("postgresql", "PostgreSQL", Category.DATABASE, kind=Kind.DATASTORE, codegen=S),
    Technology("sqlite", "SQLite", Category.DATABASE, kind=Kind.DATASTORE, codegen=S),
    Technology("mysql", "MySQL", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("mariadb", "MariaDB", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("mssql", "SQL Server", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("mongodb", "MongoDB", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("redis", "Redis", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("cassandra", "Cassandra", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("cockroachdb", "CockroachDB", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("dynamodb", "DynamoDB", Category.DATABASE, kind=Kind.DATASTORE),
    Technology("elasticsearch", "Elasticsearch", Category.DATABASE, kind=Kind.DATASTORE),
]

_TESTING = [
    Technology("pytest", "pytest", Category.TESTING, "python"),
    Technology("unittest", "unittest", Category.TESTING, "python"),
    Technology("jest", "Jest", Category.TESTING, "javascript"),
    Technology("vitest", "Vitest", Category.TESTING, "typescript"),
    Technology("playwright", "Playwright", Category.TESTING, "typescript"),
    Technology("cypress", "Cypress", Category.TESTING, "typescript"),
    Technology("junit", "JUnit", Category.TESTING, "java"),
    Technology("go_test", "go test", Category.TESTING, "go"),
    Technology("rspec", "RSpec", Category.TESTING, "ruby"),
    Technology("phpunit", "PHPUnit", Category.TESTING, "php"),
    Technology("xctest", "XCTest", Category.TESTING, "swift"),
]

_DEPLOYMENT = [
    Technology("docker", "Docker", Category.DEPLOYMENT),
    Technology("kubernetes", "Kubernetes", Category.DEPLOYMENT),
    Technology("vercel", "Vercel", Category.DEPLOYMENT),
    Technology("netlify", "Netlify", Category.DEPLOYMENT),
    Technology("fly", "Fly.io", Category.DEPLOYMENT),
    Technology("render", "Render", Category.DEPLOYMENT),
    Technology("heroku", "Heroku", Category.DEPLOYMENT),
]

_INFRA = [
    Technology("aws", "AWS", Category.INFRASTRUCTURE),
    Technology("gcp", "Google Cloud", Category.INFRASTRUCTURE),
    Technology("azure", "Azure", Category.INFRASTRUCTURE),
    Technology("digitalocean", "DigitalOcean", Category.INFRASTRUCTURE),
    Technology("cloudflare", "Cloudflare", Category.INFRASTRUCTURE),
]

TECHNOLOGIES = (
    _LANGUAGES + _FRAMEWORKS + _DATABASES + _TESTING + _DEPLOYMENT + _INFRA
)


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

