"""Defensive parsing of a model's requirements output.

Real models mostly return the requested JSON but sometimes wrap it in prose or a
code fence; the offline stub returns none. Never raises — returns [] when nothing
usable is found, so the agent can report an honest "0 extracted" rather than a
crash or a fabricated requirement.
"""
from __future__ import annotations

import json


def _try_load(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_json(text: str):
    text = (text or "").strip()
    # Strip a Markdown code fence if present.
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1 :] if "\n" in text else text

    payload = _try_load(text)
    if payload is not None:
        return payload
    # Fall back to the first bracketed span.
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            payload = _try_load(text[start : end + 1])
            if payload is not None:
                return payload
    return None


def parse_requirements(text: str) -> list[dict]:
    payload = _extract_json(text)
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
