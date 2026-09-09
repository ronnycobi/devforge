"""Store rejection analysis (spec §23).

When a store rejects a release, DevForge parses the reason, explains it, points to
the feature it affects, and suggests a fix — then a human approves before anything
is changed. Compliance-sensitive functionality is never modified automatically.

HONESTY: the rejection text is REAL data — either fetched from the store API (when
connected) or pasted by the customer from the rejection they received. The
classifier is deterministic keyword matching; it never invents a reason the text
doesn't contain, and "affected features" are drawn only from the app's ACTUAL
capabilities/screens. Categories flagged `compliance` always recommend manual
review rather than an automated code change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    patterns: tuple[str, ...]
    # Capability/feature ids this category tends to affect (matched against the
    # app's real capabilities so we only ever point at features it actually has).
    affects: tuple[str, ...] = ()
    compliance: bool = False           # if True → recommend manual review, no auto-edit
    recommendation: str = ""


# Ordered by specificity — first match wins.
CATEGORIES: tuple[Category, ...] = (
    Category("permissions", "Permissions", (
        r"permission", r"location", r"background location", r"camera access",
        r"contacts", r"microphone",
    ), affects=("location", "files", "sms"), compliance=True,
        recommendation="Confirm each requested permission maps to a feature that needs it, "
                       "remove any that don't, and declare the rest with a clear purpose string."),
    Category("privacy_policy", "Privacy policy", (
        r"privacy policy", r"privacy url", r"privacy statement",
    ), affects=(), compliance=True,
        recommendation="Publish a reachable privacy policy URL and set it on the store listing."),
    Category("data_safety", "Data safety / data collection", (
        r"data safety", r"data collection", r"data disclosure", r"account deletion",
        r"user data",
    ), affects=("users", "auth", "database"), compliance=True,
        recommendation="Complete the data-safety declaration to match what the app actually "
                       "collects; add in-app account deletion if user accounts exist."),
    Category("login", "Reviewer login / demo access", (
        r"unable to (sign|log) in", r"demo account", r"login credentials", r"test account",
        r"could not log in",
    ), affects=("auth",),
        recommendation="Provide working reviewer demo credentials in the review notes."),
    Category("crash", "Crash / stability", (
        r"crash", r"bug", r"did not (launch|start)", r"freeze", r"unresponsive",
    ), affects=(),
        recommendation="Reproduce the crash from the reviewer's steps, fix it, and add a "
                       "regression test before resubmitting."),
    Category("metadata", "Metadata / listing", (
        r"screenshot", r"description", r"keyword", r"metadata", r"app name", r"misleading",
    ), affects=(),
        recommendation="Correct the flagged listing content (screenshots/description/keywords) "
                       "so it accurately reflects the app."),
    Category("payments", "Payments / billing", (
        r"in-app purchase", r"billing", r"subscription", r"payment", r"external purchase",
    ), affects=("payments", "subscriptions"), compliance=True,
        recommendation="Use the store's official billing where required; review the payment flow "
                       "against store policy."),
)

_FALLBACK = Category("other", "Needs review", (), affects=(),
                     recommendation="Read the store's message and address the specific point it raises.")


def classify(text: str) -> Category:
    low = (text or "").lower()
    for cat in CATEGORIES:
        if any(re.search(p, low) for p in cat.patterns):
            return cat
    return _FALLBACK


def analyze(text: str, *, app_capability_ids: list[str], app_features: list[str]) -> dict:
    """Produce a structured, honest analysis of a rejection.

    `app_capability_ids` and `app_features` come from the real app so we only point
    at features it actually has."""
    cat = classify(text)
    # Only surface affected features the app truly has.
    have = set(app_capability_ids or [])
    affected = [c for c in cat.affects if c in have]
    return {
        "category": cat.key,
        "label": cat.label,
        "compliance": cat.compliance,
        "affected_capabilities": affected,
        "recommendation": cat.recommendation,
        "summary": _summarize(cat, text),
    }


def _summarize(cat: Category, text: str) -> str:
    snippet = " ".join((text or "").split())[:180]
    return f"The store flagged an issue in the “{cat.label}” area. What they said: “{snippet}”"


def fix_description(analysis: dict, *, app_name: str) -> str:
    """The change-request description used to drive DevForge's normal modify→test→
    build loop. For compliance categories it asks for a reviewed change, not a
    silent automated one."""
    lead = f"Address the app-store rejection for {app_name} in the “{analysis['label']}” area."
    body = analysis["recommendation"]
    if analysis["compliance"]:
        body += (" This is compliance-sensitive — propose the change for human review; "
                 "do not modify this behaviour automatically without approval.")
    return f"{lead}\n\n{body}"
