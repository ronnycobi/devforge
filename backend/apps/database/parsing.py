"""Defensive parsing of the Database Agent's output (data models)."""
from __future__ import annotations

from apps.core.jsonx import extract_json


def _clean_fields(value) -> list[dict]:
    out = []
    if not isinstance(value, list):
        return out
    for f in value:
        if isinstance(f, dict):
            name = str(f.get("name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name[:128],
                    "type": str(f.get("type") or "").strip(),
                    "nullable": bool(f.get("nullable", False)),
                    "note": str(f.get("note") or "").strip(),
                }
            )
        elif isinstance(f, str) and f.strip():
            out.append({"name": f.strip()[:128], "type": "", "nullable": False, "note": ""})
    return out


def _clean_models(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("entity") or item.get("model") or "").strip()
        if not name:
            continue
        relations = item.get("relations")
        relations = (
            [str(r).strip() for r in relations if str(r).strip()]
            if isinstance(relations, list)
            else []
        )
        out.append(
            {
                "name": name[:255],
                "description": str(item.get("description") or "").strip(),
                "fields": _clean_fields(item.get("fields")),
                "relations": relations,
            }
        )
    return out


def parse_schema(text: str) -> dict:
    payload = extract_json(text)
    if isinstance(payload, dict):
        models = payload.get("models") or payload.get("entities") or []
    elif isinstance(payload, list):
        models = payload
    else:
        models = []
    return {"models": _clean_models(models)}
