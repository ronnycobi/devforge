"""Defensive parsing of the Backend Agent's output (API endpoints)."""
from __future__ import annotations

from apps.core.jsonx import extract_json


def _clean_endpoints(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        path = str(item.get("path") or "").strip()
        if not method or not path:
            continue
        request = item.get("request")
        response = item.get("response")
        out.append(
            {
                "method": method[:10],
                "path": path[:255],
                "purpose": str(item.get("purpose") or "").strip(),
                "module": str(item.get("module") or "").strip(),
                "auth": str(item.get("auth") or "").strip(),
                "request": request if isinstance(request, (dict, list)) else {},
                "response": response if isinstance(response, (dict, list)) else {},
            }
        )
    return out


def parse_backend(text: str) -> dict:
    payload = extract_json(text)
    if isinstance(payload, dict):
        endpoints = payload.get("endpoints", [])
    elif isinstance(payload, list):
        endpoints = payload
    else:
        endpoints = []
    return {"endpoints": _clean_endpoints(endpoints)}
