"""Defensive parsing of a model's requirements output.

Returns [] when nothing usable is found, so the agent can report an honest
"0 extracted" rather than a crash or a fabricated requirement. JSON extraction
itself lives in apps.core.jsonx.
"""
from __future__ import annotations

from apps.core.jsonx import extract_json


def parse_requirements(text: str) -> list[dict]:
    payload = extract_json(text)
    if isinstance(payload, dict):
        items = payload.get("requirements", [])
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        criteria = item.get("acceptance_criteria")
        criteria = (
            [str(c).strip() for c in criteria if str(c).strip()]
            if isinstance(criteria, list)
            else []
        )
        result.append(
            {
                "title": title[:255],
                "description": str(
                    item.get("description") or item.get("detail") or ""
                ).strip(),
                "acceptance_criteria": criteria,
            }
        )
    return result
