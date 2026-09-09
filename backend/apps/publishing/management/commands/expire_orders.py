"""Auto-cancel unpaid orders that have held their reservations too long (spec §32).

The scheduler is the OS — run from cron / a systemd timer, e.g. every 15 minutes:

    */15 * * * * cd /app/backend && python manage.py expire_orders

It frees the stock and discount-code uses held by abandoned pending/awaiting-payment
orders older than the TTL (DEVFORGE_ORDER_RESERVATION_TTL_MINUTES, default 24h;
override with --minutes). Paid/refunded/cancelled orders are never touched.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.publishing.ecommerce_service import expire_stale_orders


class Command(BaseCommand):
    help = "Release reservations from stale unpaid orders (for cron/systemd)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes", type=int,
            default=getattr(settings, "DEVFORGE_ORDER_RESERVATION_TTL_MINUTES", 1440),
            help="Cancel unpaid orders older than this many minutes.",
        )

    def handle(self, *args, **options):
        minutes = options["minutes"]
        n = expire_stale_orders(older_than_minutes=minutes)
        self.stdout.write(self.style.SUCCESS(
            f"Expired {n} unpaid order(s) older than {minutes} minute(s)."
        ))
        return f"expired={n}"
