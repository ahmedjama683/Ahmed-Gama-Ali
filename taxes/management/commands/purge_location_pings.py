"""
Delete old collector location points to keep the database small and limit how
long staff movements are stored. Payments keep their own GPS forever.

    python manage.py purge_location_pings --days 90
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from taxes.models import LocationPing


class Command(BaseCommand):
    help = "Delete collector location points older than --days (default 90)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        deleted, _ = LocationPing.objects.filter(recorded_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} location points before {cutoff:%Y-%m-%d}."))
