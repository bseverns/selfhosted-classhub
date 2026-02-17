"""Delete old student submissions according to retention policy."""

from __future__ import annotations

import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from hub.models import Submission


class Command(BaseCommand):
    help = "Prune old student submissions and optionally remove files from disk."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=int(os.getenv("CLASSHUB_SUBMISSION_RETENTION_DAYS", "0")),
            help="Delete submissions older than this many days (0 disables by default).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting.",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="Batch size for scanning/deleting rows.",
        )

    def handle(self, *args, **opts):
        days = int(opts["older_than_days"])
        dry_run = bool(opts["dry_run"])
        chunk_size = max(int(opts["chunk_size"]), 1)

        if days <= 0:
            raise CommandError("Set --older-than-days to a positive integer (or set CLASSHUB_SUBMISSION_RETENTION_DAYS).")

        cutoff = timezone.now() - timedelta(days=days)
        qs = Submission.objects.filter(uploaded_at__lt=cutoff).order_by("id")
        total = qs.count()
        self.stdout.write(f"Cutoff: {cutoff.isoformat()}")
        self.stdout.write(f"Matched submissions: {total}")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to prune."))
            return

        deleted_rows = 0
        deleted_files = 0
        file_errors = 0

        start_id = 0
        while True:
            batch = list(
                qs.filter(id__gt=start_id)
                .only("id", "file")
                .order_by("id")[:chunk_size]
            )
            if not batch:
                break

            for row in batch:
                start_id = row.id
                if dry_run:
                    deleted_rows += 1
                    continue

                try:
                    if row.file:
                        row.file.delete(save=False)
                        deleted_files += 1
                except Exception:
                    file_errors += 1

                row.delete()
                deleted_rows += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f"[dry-run] Would delete rows: {deleted_rows}"))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted rows: {deleted_rows}; files deleted: {deleted_files}; file delete errors: {file_errors}"
            )
        )
