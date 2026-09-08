"""Requirement-driven database recommendation.

Deterministic and offline: maps signals in the requirements to a database and an
explicit reason. Explicitly NOT "PostgreSQL for everything" — a relational SaaS
gets PostgreSQL, but a simple/embedded app gets SQLite, a cache/session workload
Redis, a flexible-document app MongoDB, and a search-heavy app a search engine.
An AI pass can refine this later; the heuristic guarantees an honest default with
a recorded rationale even offline.
"""
from __future__ import annotations

import re

# (compiled signal, database id, reason) — first match wins, most specific first.
_RULES = [
    (r"\b(full[- ]?text|search[- ]?heavy|faceted|autocomplete|fuzzy search)\b",
     "elasticsearch", "requirements centre on search/full-text retrieval"),
    (r"\b(cache|caching|session store|rate limit|leaderboard|ephemeral|pub/?sub)\b",
     "redis", "the workload is caching / ephemeral key-value, not a system of record"),
    (r"\b(document|schema[- ]?less|flexible schema|unstructured|nested json|catalog of varied)\b",
     "mongodb", "data is document-shaped with a flexible/varying schema"),
    (r"\b(graph|social network|relationship traversal|recommendation graph)\b",
     "neo4j", "the core problem is traversing a graph of relationships"),
    (r"\b(financial|invoic|payment|ledger|accounting|transaction|banking|order|reporting|analytics|relational|join)\b",
     "postgresql", "strong relational integrity, transactions and reporting are required"),
    (r"\b(prototype|simple|small|local|embedded|single[- ]?user|cli tool|desktop app|mvp)\b",
     "sqlite", "a lightweight embedded database fits a simple/local scope"),
]

# When nothing specific matches: a general web/app product is relational by default,
# but that is a stated default with a reason — not an unconditional assumption.
_DEFAULT = ("postgresql", "general-purpose relational default for an application "
            "with structured, related data (revisit if the data is document-, "
            "search- or cache-shaped)")


def recommend_database(requirements_text: str) -> dict:
    text = (requirements_text or "").lower()
    for pattern, db_id, reason in _RULES:
        if re.search(pattern, text):
            return {"database": db_id, "reason": reason, "matched": True}
    db_id, reason = _DEFAULT
    return {"database": db_id, "reason": reason, "matched": False}
