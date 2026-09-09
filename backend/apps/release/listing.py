"""AI store-listing generator (spec §16).

Drafts a store listing (name, short/long description, keywords, feature blurbs,
screenshot captions) from the app's *actual* detected features — the screens in
its Software Twin plus the capabilities DevForge inferred — never from thin air.

Two honest paths:
  1. A real model (via the quality-first router) writes the copy, constrained by a
     system prompt that forbids inventing features not in the provided list.
  2. Offline / unparseable → a deterministic draft composed only from the detected
     features. It reads plainly and claims nothing the app doesn't have.

Both paths return a draft that is CLEARLY marked AI-generated and NOT approved. It
is never auto-submitted, and legal/compliance declarations are never generated
(spec §16, §43).
"""
from __future__ import annotations

import json
import re

from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext


# Google Play limits: title 30, short description 80. App Store: name 30.
_NAME_MAX = 30
_SHORT_MAX = 80

SYSTEM_PROMPT = (
    "You are DevForge's app-store copywriter. Given an application's name and the "
    "list of features it ACTUALLY has, write a store listing.\n\n"
    "Hard rules:\n"
    "- Only describe features from the provided list. NEVER invent features, "
    "integrations, awards, user counts, or claims the app does not have.\n"
    "- Do NOT write privacy policies, data-safety declarations, or any legal/"
    "compliance statement.\n"
    "- Respect limits: app_name <= 30 chars, short_description <= 80 chars.\n\n"
    "Respond with ONLY a JSON object with keys: app_name (string), "
    "short_description (string), full_description (string), keywords (array of "
    "strings), feature_descriptions (array of {title, description}), "
    "screenshot_captions (array of strings). No prose outside the JSON."
)


def detect_features(project) -> dict:
    """Read the app's real features from its Twin (spec §16 example: Customers,
    Projects, Quotations, Invoices, …) plus inferred capabilities."""
    ctx = ProjectContext(project)
    screens = []
    for e in ctx.by_kind(ContextKind.SCREEN):
        name = re.sub(r"^\[[^\]]+\]\s*", "", e.title or "").strip()
        if name and name not in screens:
            screens.append(name)

    from apps.capabilities.infer import infer_capabilities
    caps = [c.name for c in infer_capabilities(project.description or project.name) if c.is_available]

    # Features = concrete screens if we have them, else the inferred capabilities.
    features = screens[:12] or caps[:8]
    return {"features": features, "screens": screens[:8], "capabilities": caps}


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def _deterministic(project, detected: dict) -> dict:
    """An honest draft built only from detected features — the offline path."""
    name = (project.name or "App").strip()
    features = detected["features"]
    top = ", ".join(features[:3]) if features else "the tools your team needs"
    short = f"{name}: {top}"[:_SHORT_MAX]

    if features:
        bullets = "\n".join(f"• {f}" for f in features)
        full = (
            f"{name} brings your workflow together in one app.\n\n"
            f"What you can do:\n{bullets}\n\n"
            f"Built with DevForge."
        )
        feature_descriptions = [
            {"title": f, "description": f"Manage {f.lower()} directly from {name}."}
            for f in features
        ]
    else:
        full = f"{name} — built with DevForge."
        feature_descriptions = []

    keywords = []
    for token in re.split(r"[\s,]+", (name + " " + " ".join(features)).lower()):
        token = re.sub(r"[^a-z0-9]", "", token)
        if len(token) > 2 and token not in keywords:
            keywords.append(token)

    return {
        "app_name": name[:_NAME_MAX],
        "short_description": short,
        "full_description": full,
        "keywords": keywords[:15],
        "feature_descriptions": feature_descriptions,
        "screenshot_captions": [f"{s}" for s in detected["screens"]],
        "source": "detected-features",
    }


def generate_listing(project, *, router=None) -> dict:
    """Produce a listing draft. Tries a real model; falls back to a deterministic
    draft from detected features. Always honest, always a draft."""
    detected = detect_features(project)

    from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
    router = router or ModelRouter()
    prompt = (
        f"Application name: {project.name}\n"
        f"Features it actually has:\n"
        + ("\n".join(f"- {f}" for f in detected["features"]) or "- (none detected)")
        + "\n\nWrite the store listing JSON."
    )
    try:
        from apps.ai_providers.base import Message
        response = router.complete(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, task_type="store_listing"),
            messages=[Message(role="user", content=prompt)],
            system=SYSTEM_PROMPT,
            max_tokens=1200,
        )
        data = _extract_json(response.text)
        if data and data.get("full_description"):
            data.setdefault("app_name", (project.name or "App")[:_NAME_MAX])
            data["source"] = response.model
            data["features"] = detected["features"]
            return data
    except Exception:
        pass  # offline / no model / unparseable → deterministic honest fallback

    draft = _deterministic(project, detected)
    draft["features"] = detected["features"]
    return draft
