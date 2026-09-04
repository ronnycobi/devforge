"""Defensive JSON extraction from model output.

Models mostly return the requested JSON but sometimes wrap it in prose or a
Markdown code fence; the offline stub returns none. `extract_json` never raises —
it returns the parsed value, or None when nothing usable is found, so callers can
report an honest "nothing extracted" rather than crash.
"""
from __future__ import annotations

import json


def _try_load(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def extract_json(text: str):
    text = (text or "").strip()
    # Strip a Markdown code fence if present.
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1 :] if "\n" in text else text

    payload = _try_load(text)
    if payload is not None:
        return payload
    # Fall back to the first bracketed span (array or object).
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            payload = _try_load(text[start : end + 1])
            if payload is not None:
                return payload
    return None
