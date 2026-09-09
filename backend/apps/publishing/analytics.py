"""Website analytics (spec §28).

Counts REAL page views of published sites (the serve path is instrumented) and
aggregates them into the metrics a customer cares about: visitors, sessions, page
views, top pages, traffic sources, devices, and conversions (leads / sessions).

PRIVACY (spec §28 + platform privacy rules): no raw IP or personal data is stored.
A session is a one-way hash of IP + User-Agent salted per day with the secret key —
enough to count sessions, not enough to identify or follow a person. Do-Not-Track is
honored: when the browser sends DNT, nothing is recorded. Referrers are reduced to a
host. Obvious bots are labeled and excluded from visitor counts.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from apps.publishing.models import Lead, PageView


def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _device(ua: str) -> str:
    low = ua.lower()
    if any(b in low for b in ("bot", "crawler", "spider", "slurp", "curl", "wget", "python-")):
        return "bot"
    if any(m in low for m in ("mobile", "android", "iphone", "ipad", "ipod")):
        return "mobile"
    return "desktop"


def _session_key(request, day) -> str:
    raw = f"{day.isoformat()}|{settings.SECRET_KEY}|{_client_ip(request)}|{request.META.get('HTTP_USER_AGENT', '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _dnt(request) -> bool:
    return request.META.get("HTTP_DNT") == "1" or request.headers.get("Sec-GPC") == "1"


def record_view(website, request) -> PageView | None:
    """Record one page view. Returns None when Do-Not-Track is set (nothing stored)."""
    if _dnt(request):
        return None
    ua = request.META.get("HTTP_USER_AGENT", "")
    day = timezone.now().date()
    ref = request.META.get("HTTP_REFERER", "")
    ref_host = urlsplit(ref).hostname or "" if ref else ""
    # Don't count self-referrals (navigation within the same site) as a source.
    if ref_host and website.subdomain in ref_host:
        ref_host = ""
    try:
        return PageView.objects.create(
            website=website,
            path=(request.path or "/")[:512],
            referrer_host=ref_host[:255],
            device=_device(ua),
            session_key=_session_key(request, day),
            day=day,
        )
    except Exception:
        return None   # analytics must never break serving the site


def summary(website, *, days: int = 30) -> dict:
    since = timezone.now().date() - timedelta(days=days - 1)
    qs = website.page_views.filter(day__gte=since)
    human = qs.exclude(device="bot")

    pageviews = human.count()
    sessions = human.values("session_key").distinct().count()
    leads = website.leads.filter(created_at__date__gte=since).count()
    conversion = round(100 * leads / sessions, 1) if sessions else 0.0

    top_pages = list(
        human.values("path").annotate(n=Count("id")).order_by("-n")[:8]
    )
    sources = list(
        human.exclude(referrer_host="").values("referrer_host").annotate(n=Count("id")).order_by("-n")[:8]
    )
    devices = list(human.values("device").annotate(n=Count("id")).order_by("-n"))

    # Daily series for a simple trend.
    per_day = {r["day"]: r["n"] for r in human.values("day").annotate(n=Count("id"))}
    series = []
    for i in range(days):
        d = since + timedelta(days=i)
        series.append({"day": d, "views": per_day.get(d, 0)})

    return {
        "days": days,
        "pageviews": pageviews,
        "sessions": sessions,
        "visitors": sessions,      # one session_key ≈ one visitor within the window
        "leads": leads,
        "conversion": conversion,
        "top_pages": top_pages,
        "sources": sources,
        "devices": devices,
        "series": series,
        "bot_views": qs.filter(device="bot").count(),
    }
