"""Defensive parsing of the Architect Agent's output.

Expects an object with `components` and `tech_decisions`, but tolerates a bare
components array and missing/renamed keys. Never raises; returns empty lists when
nothing usable is found.
"""
from __future__ import annotations

from apps.core.jsonx import extract_json


def _clean_components(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("component") or "").strip()
        if not name:
            continue
        depends = item.get("depends_on")
        depends = (
            [str(d).strip() for d in depends if str(d).strip()]
            if isinstance(depends, list)
            else []
        )
        out.append(
            {
                "name": name[:255],
                "responsibility": str(item.get("responsibility") or "").strip(),
                "technology": str(item.get("technology") or "").strip(),
                "depends_on": depends,
            }
        )
    return out


def _clean_decisions(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("decision") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title[:255],
                "choice": str(item.get("choice") or "").strip(),
                "rationale": str(item.get("rationale") or item.get("reason") or "").strip(),
            }
        )
    return out


def parse_stacks(text: str) -> dict:
    """Extract the model's per-role stack recommendations: {role: {recommended, rationale}}."""
    payload = extract_json(text)
    stacks = payload.get("stacks") if isinstance(payload, dict) else None
    if not isinstance(stacks, dict):
        return {}
    out = {}
    for role, rec in stacks.items():
        if not isinstance(rec, dict):
            continue
        recommended = str(rec.get("recommended") or "").strip() or None
        out[str(role).strip()] = {
            "recommended": recommended,
            "rationale": str(rec.get("rationale") or "").strip(),
        }
    return out


def parse_architecture(text: str) -> dict:
    payload = extract_json(text)
    if isinstance(payload, dict):
        components = payload.get("components", [])
        decisions = payload.get("tech_decisions") or payload.get("decisions") or []
    elif isinstance(payload, list):
        components = payload  # a bare components array
        decisions = []
    else:
        components = decisions = []
    return {
        "components": _clean_components(components),
        "tech_decisions": _clean_decisions(decisions),
    }
