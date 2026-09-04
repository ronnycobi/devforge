"""Defensive parsing of the Code Review Agent's output (findings)."""
from __future__ import annotations

from apps.core.jsonx import extract_json

_SEVERITIES = {"low", "medium", "high", "critical"}


def _clean_findings(items) -> list[dict]:
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("finding") or "").strip()
        if not title:
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity not in _SEVERITIES:
            severity = "medium"
        out.append(
            {
                "title": title[:255],
                "severity": severity,
                "area": str(item.get("area") or "").strip(),
                "recommendation": str(item.get("recommendation") or item.get("fix") or "").strip(),
            }
        )
    return out


def parse_findings(text: str) -> dict:
    payload = extract_json(text)
    if isinstance(payload, dict):
        findings = payload.get("findings") or payload.get("issues") or []
    elif isinstance(payload, list):
        findings = payload
    else:
        findings = []
    return {"findings": _clean_findings(findings)}
