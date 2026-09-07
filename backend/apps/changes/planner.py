"""Change planner — turns a natural-language change into an impact plan.

Reads the project's digital twin (its context) and asks a model which areas the
change touches — WITHOUT rewriting the whole app. Defensive parsing; offline
(stub) yields an empty plan honestly (no fabricated impact).
"""
from __future__ import annotations

from apps.ai_providers.base import Message
from apps.core.jsonx import extract_json
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity

_AREAS = ["database", "backend", "api", "frontend", "testing", "infrastructure"]

SYSTEM_PROMPT = (
    "You are DevForge's change planner. Given an existing application's design and "
    "a requested change, produce a focused impact plan — do NOT propose rewriting "
    "the whole app.\n\n"
    "Respond with ONLY a JSON object:\n"
    '  "summary": one sentence describing the change,\n'
    '  "affected_areas": an object whose keys are among database, backend, api, '
    "frontend, testing, infrastructure — each a list of specific things to add or "
    "modify,\n"
    '  "steps": an ordered list of implementation steps,\n'
    '  "risk": "low" | "medium" | "high",\n'
    '  "requires_approval": boolean (true for significant or risky changes).\n'
    "No prose outside the JSON object."
)


def _clean(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    areas = payload.get("affected_areas")
    clean_areas = {}
    if isinstance(areas, dict):
        for key, items in areas.items():
            k = str(key).strip().lower()
            if k in _AREAS and isinstance(items, list):
                vals = [str(i).strip() for i in items if str(i).strip()]
                if vals:
                    clean_areas[k] = vals
    risk = str(payload.get("risk") or "").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    steps = payload.get("steps")
    steps = [str(s).strip() for s in steps if str(s).strip()] if isinstance(steps, list) else []
    return {
        "summary": str(payload.get("summary") or "").strip(),
        "affected_areas": clean_areas,
        "steps": steps,
        "risk": risk,
        "requires_approval": bool(payload.get("requires_approval", risk != "low")),
    }


def plan_change(description: str, twin_digest: str, router: ModelRouter | None = None) -> dict:
    router = router or ModelRouter()
    user = (
        (f"Existing application:\n{twin_digest}\n\n" if twin_digest.strip() else "")
        + f"Requested change:\n{description}\n\nReturn the JSON impact plan."
    )
    response = router.complete(
        RoutingRequest(complexity=TaskComplexity.HIGH, task_type="change_plan"),
        messages=[Message("user", user)],
        system=SYSTEM_PROMPT,
        max_tokens=2000,
    )
    return {"model": response.model, **_clean(extract_json(response.text) or {})}
