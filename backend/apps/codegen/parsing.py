"""Parse a model's file-generation output into safe {path, content} entries.

Guards every path (no absolute paths, no traversal), caps the number and size of
files, and requires string content. Returns [] on garbage so a code-gen agent can
report an honest "0 files" instead of crashing or writing something unsafe.
"""
from __future__ import annotations

import os
from pathlib import PurePosixPath

from apps.core.jsonx import extract_json

_MAX_FILES = 100
_MAX_BYTES = 200_000  # per file


def _safe_path(path: str) -> bool:
    if not path or os.path.isabs(path):
        return False
    parts = PurePosixPath(path).parts
    return ".." not in parts and "" not in parts


def parse_files(text: str) -> list[dict]:
    payload = extract_json(text)
    if isinstance(payload, dict):
        items = payload.get("files", [])
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        content = item.get("content")
        if not _safe_path(path) or not isinstance(content, str):
            continue
        if len(content.encode("utf-8")) > _MAX_BYTES:
            continue
        out.append({"path": path, "content": content})
        if len(out) >= _MAX_FILES:
            break
    return out
