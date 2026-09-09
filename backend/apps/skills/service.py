"""Skill selection + application.

select_skills() picks the playbooks whose keywords match a brief, honoring scope
(global + the org's + the project's). guidance_for() renders them into text the build
flow appends to the brief the agents receive. apply_to_project() records which skills
were applied (in the project's context + audit) for traceability.
"""
from __future__ import annotations

from apps.audit.service import record as audit
from apps.skills.builtins import BUILTIN_SKILLS, builtin_as_shape
from apps.skills.models import Skill


def _matches(keywords, text) -> bool:
    low = (text or "").lower()
    return any(kw.lower() in low for kw in (keywords or []))


def select_skills(brief, *, organization=None, project=None) -> list[dict]:
    """Return matching skills as uniform dicts (builtins first, then DB skills in
    scope). A brief that matches nothing yields an empty list."""
    picked, seen = [], set()

    for b in BUILTIN_SKILLS:
        if _matches(b["keywords"], brief):
            picked.append(builtin_as_shape(b))
            seen.add(b["slug"])

    qs = Skill.objects.filter(enabled=True)
    scope_q = _in_scope(qs, organization, project)
    for s in scope_q:
        if s.slug in seen:
            continue
        if s.matches(brief):
            picked.append({"name": s.name, "slug": s.slug, "keywords": s.keywords,
                           "body": s.body, "source": s.scope})
    return picked


def _in_scope(qs, organization, project):
    from django.db.models import Q
    q = Q(scope=Skill.SCOPE_GLOBAL)
    if organization is not None:
        q |= Q(scope=Skill.SCOPE_ORG, organization=organization)
    if project is not None:
        q |= Q(scope=Skill.SCOPE_PROJECT, project=project)
    return qs.filter(q)


def guidance_for(brief, *, organization=None, project=None) -> tuple[list[dict], str]:
    skills = select_skills(brief, organization=organization, project=project)
    if not skills:
        return [], ""
    text = "\n\n".join(f"[{s['name']}] {s['body']}" for s in skills)
    return skills, text


def apply_to_project(project, brief, *, user=None) -> list[dict]:
    """Select skills for a build and record them on the project (context + audit)."""
    skills, text = guidance_for(brief, organization=project.organization, project=project)
    if not skills:
        return []
    try:
        from apps.project_context.models import ContextKind
        from apps.project_context.services import ProjectContext
        ProjectContext(project).set(
            ContextKind.NOTE, "applied-skills", title="Applied playbooks",
            content=text, source="skills")
    except Exception:
        pass
    audit("skills.applied", actor=user, organization=project.organization,
          target=f"project:{project.id}", summary=", ".join(s["name"] for s in skills))
    return skills
