"""Publish-readiness checklist (spec §12, §41).

Checks the website against the project's REAL state. Verdict is "Ready to publish",
never a guarantee. Only "build" blocks (you cannot serve nothing); the rest surface
honestly as warnings so the customer sees what is unverified rather than a fake tick.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.repositories.service import repo_for_project


@dataclass
class Check:
    key: str
    label: str
    status: str      # ok / warn / fail / manual
    detail: str = ""


def evaluate(website) -> list[Check]:
    project = website.project
    repo = repo_for_project(project)
    files = repo.list_files() if repo.is_initialized else []
    checks: list[Check] = []

    # Build — the one blocker: is there a servable site?
    if files:
        checks.append(Check("build", "Build", "ok", f"{len(files)} file(s) ready."))
    else:
        checks.append(Check("build", "Build", "fail", "Nothing built yet — build the site first."))

    # Tests — did a test run pass? (honest: warn if none recorded)
    tests = project.agent_tasks.filter(agent_key="testing").order_by("-created_at").first()
    if tests and tests.status == "completed":
        checks.append(Check("tests", "Tests", "ok"))
    elif tests:
        checks.append(Check("tests", "Tests", "warn", "Latest test run did not pass."))
    else:
        checks.append(Check("tests", "Tests", "warn", "No test run recorded."))

    # Security — was a scan run and clean? (honest: warn if not scanned)
    checks.append(_security_check(project))

    # SEO — does the entry document carry a title + description?
    checks.append(_seo_check(repo, files))

    # Forms — informational: does the app declare forms?
    ctx = ProjectContext(project)
    has_forms = ctx.by_kind(ContextKind.SCREEN).filter(content__icontains="form").exists()
    checks.append(Check("forms", "Forms", "ok" if has_forms else "manual",
                        "" if has_forms else "No forms detected (fine for a static site)."))

    # Environment — the DevForge host is always available locally.
    checks.append(Check("environment", "Environment", "ok", "DevForge hosting available."))

    return checks


def _security_check(project) -> Check:
    """Honest: findings are persisted as SECURITY context entries by the security
    agent. If no security task has run, say so; if it ran, grade by severity."""
    ran = project.agent_tasks.filter(agent_key="security", status="completed").exists()
    if not ran:
        return Check("security", "Security", "warn", "No security scan recorded.")
    entries = ProjectContext(project).by_kind(ContextKind.SECURITY)
    high = sum(
        1 for e in entries
        if (isinstance(e.data, dict) and e.data.get("severity", "").lower() in ("critical", "high"))
    )
    if high:
        return Check("security", "Security", "fail", f"{high} high/critical finding(s).")
    return Check("security", "Security", "ok", "Scanned, no high/critical findings.")


def _seo_check(repo, files) -> Check:
    index = next((f for f in files if f.endswith("index.html")), None)
    if not index:
        return Check("seo", "SEO", "warn", "No index.html to check.")
    try:
        text = (Path(repo.path) / index).read_text(errors="ignore").lower()
    except Exception:
        return Check("seo", "SEO", "warn", "Could not read index.html.")
    has_title = "<title" in text
    has_desc = 'name="description"' in text or "name='description'" in text
    if has_title and has_desc:
        return Check("seo", "SEO", "ok")
    missing = ", ".join(m for m, ok in [("title", has_title), ("meta description", has_desc)] if not ok)
    return Check("seo", "SEO", "warn", f"Missing {missing}.")


def score(checks: list[Check]) -> int:
    if not checks:
        return 0
    weights = {"ok": 1.0, "warn": 0.5, "manual": 0.5, "fail": 0.0}
    return round(100 * sum(weights.get(c.status, 0.0) for c in checks) / len(checks))


def can_publish(checks: list[Check]) -> bool:
    """Only a failed BUILD blocks publishing (nothing to serve)."""
    return not any(c.key == "build" and c.status == "fail" for c in checks)
