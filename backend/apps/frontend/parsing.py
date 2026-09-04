"""Defensive parsing of the Frontend Agent's output (screens)."""
from __future__ import annotations

from apps.core.jsonx import extract_json


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _clean_screens(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("screen") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name[:255],
                "purpose": str(item.get("purpose") or "").strip(),
                "route": str(item.get("route") or "").strip(),
                "components": _str_list(item.get("components")),
                "data_needs": _str_list(item.get("data_needs")),
            }
        )
    return out


def parse_frontend(text: str) -> dict:
    payload = extract_json(text)
    if isinstance(payload, dict):
        screens = payload.get("screens", [])
    elif isinstance(payload, list):
        screens = payload
    else:
        screens = []
    return {"screens": _clean_screens(screens)}
