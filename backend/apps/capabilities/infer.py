"""Infer the capabilities an app needs from a plain-language brief.

Deterministic and offline: keyword rules map what the customer said to capability
ids, on top of a baseline every app gets. This is what lets DevForge "understand"
that a CRM needs auth, a database, email and a dashboard without the customer
configuring each — an AI pass can refine it later. Returns Capability objects so
callers can show names + honest availability.
"""
from __future__ import annotations

import re

from apps.capabilities.registry import get

# Every app gets these.
_BASELINE = ["users", "auth", "database", "dashboard", "hosting"]

# (capability id, regex over the lowered brief)
_RULES = [
    ("roles", r"\brole|permission|admin|manager|approv|staff|team\b"),
    ("api", r"\bapi|integrat|webhook|mobile app\b"),
    ("email", r"\bemail|notif|remind|confirmation|receipt\b"),
    ("sms", r"\bsms|text message|whatsapp\b"),
    ("files", r"\bupload|document|file|attachment|photo|image\b"),
    ("search", r"\bsearch|find|filter|lookup\b"),
    ("payments", r"\bpay|payment|checkout|card|billing\b"),
    ("subscriptions", r"\bsubscription|recurring|monthly plan|per month\b"),
    ("invoicing", r"\binvoice|quotation|quote|receipt|billing\b"),
    ("tax", r"\bvat|tax|gst\b"),
    ("currency", r"\bcurrency|multi[- ]currency|zar|usd|gbp|exchange rate\b"),
    ("crm", r"\bcrm|customer|client|lead|deal|pipeline|contact\b"),
    ("ecommerce", r"\bshop|store|e-?commerce|product|cart|order|inventory\b"),
    ("jobs", r"\bschedule|cron|background|queue|recurring job\b"),
    ("analytics", r"\banalytics|report|metric|insight|track\b"),
    ("ai", r"\bai |chatbot|assistant|recommend|semantic|ask questions\b"),
    ("git", r"\bgithub|gitlab|repository|existing (code|project)\b"),
]


def infer_capabilities(brief: str):
    text = (brief or "").lower()
    ids = list(_BASELINE)
    for cap_id, pattern in _RULES:
        if re.search(pattern, text) and cap_id not in ids:
            ids.append(cap_id)
    return [c for c in (get(i) for i in ids) if c is not None]
