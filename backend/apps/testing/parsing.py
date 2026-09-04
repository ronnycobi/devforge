"""Defensive parsing of the Testing Agent's output (test cases)."""
from __future__ import annotations

from apps.core.jsonx import extract_json

_KINDS = {"unit", "integration", "e2e", "acceptance"}


def _clean_cases(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        kind = str(item.get("kind") or item.get("type") or "").strip().lower()
        if kind not in _KINDS:
            kind = "integration"
        steps = item.get("steps")
        steps = (
            [str(s).strip() for s in steps if str(s).strip()]
            if isinstance(steps, list)
            else []
        )
        out.append(
            {
                "title": title[:255],
                "kind": kind,
                "target": str(item.get("target") or "").strip(),
                "steps": steps,
                "expected": str(item.get("expected") or "").strip(),
            }
        )
    return out


def parse_tests(text: str) -> dict:
    payload = extract_json(text)
    if isinstance(payload, dict):
        cases = payload.get("test_cases") or payload.get("tests") or []
    elif isinstance(payload, list):
        cases = payload
    else:
        cases = []
    return {"test_cases": _clean_cases(cases)}
