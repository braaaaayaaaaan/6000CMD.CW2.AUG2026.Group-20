"""Read-only integrity verification; never silently bless legacy files."""
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import SuspiciousFileOperation

from asset.files import file_digest
from asset.models import Asset


class Command(BaseCommand):
    help = "Read-only SHA-256 verification of stored asset versions (no backfill or repairs)."

    def handle(self, *args, **options):
        failures = untracked = checked = 0
        for asset in Asset.objects.iterator():
            try:
                with asset.url.open("rb") as file:
                    digest = file_digest(file)
                if not asset.sha256:
                    untracked += 1
                    self.stdout.write(f"{asset.pk}: no trusted digest (legacy upload)")
                elif digest != asset.sha256:
                    failures += 1
                    self.stderr.write(f"{asset.pk}: integrity mismatch; restrict access and restore a trusted copy")
                else:
                    checked += 1
            except (OSError, ValueError, SuspiciousFileOperation):
                failures += 1
                self.stderr.write(f"{asset.pk}: file missing or inaccessible")
        self.stdout.write(f"{checked} verified; {untracked} without baseline; {failures} failed.")
        if failures or untracked:
            raise CommandError("Integrity is not fully established. Review reported asset IDs; no records or files were changed.")
