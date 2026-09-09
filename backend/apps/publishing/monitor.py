"""Website health monitoring (spec §36).

run_check() performs a REAL probe of the site DevForge serves: it asks the host
whether the current published snapshot is present and readable and times how long
that takes, recording a HealthCheck row. uptime_summary() aggregates those real
checks into current status, uptime %, average response time, and incidents.

HONEST SCOPE (spec §50): this monitors what DevForge actually hosts. Remote-server
resource metrics (CPU/memory/bandwidth of a box DevForge doesn't run), and true
network-RTT uptime from external probes, need a connected server / probe network
that isn't configured here — those are reported as "not monitored", never faked.
Automatic scheduled probing needs a scheduler; checks here run on publish and on
demand, which is stated plainly rather than pretended to be continuous.
"""
from __future__ import annotations

import time
from datetime import timedelta

from django.utils import timezone

from apps.publishing.hosting import get_host
from apps.publishing.models import HealthCheck


def run_check(website) -> HealthCheck | None:
    version = website.current
    if version is None:
        return None
    host = get_host(version.host)
    start = time.perf_counter()
    try:
        status, detail = host.health(version) if host else ("unknown", "Unknown host")
    except Exception as exc:
        status, detail = "down", f"Probe error: {exc}"[:255]
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    up = status == "healthy"
    return HealthCheck.objects.create(
        website=website, version=version,
        status="up" if up else "down",
        detail=detail[:255], response_ms=elapsed_ms,
    )


def uptime_summary(website, *, days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=days)
    checks = list(website.health_checks.filter(checked_at__gte=since))
    total = len(checks)
    up = sum(1 for c in checks if c.status == "up")
    latest = website.health_checks.first()
    resp = [c.response_ms for c in checks if c.status == "up"]

    # Count incidents = transitions into a "down" run (chronological order).
    incidents, prev_up = 0, True
    for c in sorted(checks, key=lambda c: c.checked_at):
        is_up = c.status == "up"
        if not is_up and prev_up:
            incidents += 1
        prev_up = is_up

    return {
        "days": days,
        "current": latest.status if latest else "unknown",
        "current_detail": latest.detail if latest else "No checks run yet.",
        "checks": total,
        "uptime_pct": round(100 * up / total, 2) if total else None,
        "avg_response_ms": round(sum(resp) / len(resp)) if resp else None,
        "incidents": incidents,
        "recent": checks[:20] if checks else list(website.health_checks.all()[:20]),
        "last_checked": latest.checked_at if latest else None,
    }
