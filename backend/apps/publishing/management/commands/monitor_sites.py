"""Probe every live website and record a health check (spec §36).

This is the real answer to "scheduled background probing": the scheduler is the OS.
Run it from cron / a systemd timer, e.g. every 5 minutes:

    */5 * * * * cd /app/backend && python manage.py monitor_sites

It records a genuine HealthCheck per live site (the same probe the dashboard uses),
so uptime and incident history accrue over time without any faked "continuous
monitoring".
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.publishing import monitor
from apps.publishing.models import Website


class Command(BaseCommand):
    help = "Run a health check on every published website (for cron/systemd)."

    def handle(self, *args, **options):
        checked = down = 0
        for website in Website.objects.filter(versions__is_current=True).distinct():
            check = monitor.run_check(website)
            if check is None:
                continue
            checked += 1
            if check.status == "down":
                down += 1
                self.stderr.write(f"DOWN  {website.subdomain}: {check.detail}")
        self.stdout.write(self.style.SUCCESS(
            f"Checked {checked} live site(s); {down} down."
        ))
        return f"checked={checked} down={down}"
