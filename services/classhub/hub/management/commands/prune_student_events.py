"""Delete old student telemetry events by retention policy."""

from __future__ import annotations

import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from hub.models import StudentEvent


class Command(BaseCommand):
    help = "Prune old StudentEvent rows (append-only telemetry retention)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=int(os.getenv("CLASSHUB_STUDENT_EVENT_RETENTION_DAYS", "0")),
            help="Delete events older than this many days (0 disables by default).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report candidate count without deleting.",
        )

    def handle(self, *args, **opts):
        days = int(opts["older_than_days"])
        dry_run = bool(opts["dry_run"])
        if days <= 0:
            raise CommandError(
                "Set --older-than-days to a positive integer (or set CLASSHUB_STUDENT_EVENT_RETENTION_DAYS)."
            )

        cutoff = timezone.now() - timedelta(days=days)
        qs = StudentEvent.objects.filter(created_at__lt=cutoff)
        count = qs.count()
        self.stdout.write(f"Cutoff: {cutoff.isoformat()}")
        self.stdout.write(f"Matched events: {count}")
        if dry_run:
            self.stdout.write(self.style.WARNING(f"[dry-run] Would delete events: {count}"))
            return
        deleted, _details = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted rows: {deleted}"))
