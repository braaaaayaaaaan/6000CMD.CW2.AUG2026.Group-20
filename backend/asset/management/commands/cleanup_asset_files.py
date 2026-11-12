from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone
from datetime import timedelta
from pathlib import Path
import argparse
import json
from rest_framework.exceptions import ValidationError

from asset.models import Asset
from asset.files import (
    process_uploads,
    purge_rejected_uploads,
    quarantine_existing_uploads,
    quarantine_inventory,
    quarantine_recovery_key,
    validate_image,
)
from asset.models import is_quarantine_key


class Command(BaseCommand):
    help = "Inspect/migrate quarantine, run processing, or manually clean retained/orphaned files."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true")
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument("--process-uploads", action="store_true")
        modes.add_argument("--quarantine-existing", action="store_true")
        modes.add_argument("--purge-rejected", action="store_true")
        modes.add_argument("--validate-image", help=argparse.SUPPRESS)
        parser.add_argument(
            "--image-type", choices=("jpg", "png"), help=argparse.SUPPRESS
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Execute the existing-file quarantine migration; otherwise inspect only.",
        )
        parser.add_argument("--retention-days", type=int, default=30)
        parser.add_argument("--retry-errors", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["apply"] and not options["quarantine_existing"]:
            raise CommandError("--apply requires --quarantine-existing.")
        if options["retry_errors"] and not options["process_uploads"]:
            raise CommandError("--retry-errors requires --process-uploads.")
        if options["validate_image"]:
            if options["delete"] or not options["image_type"]:
                raise CommandError(
                    "Internal image validation requires an image type and cannot delete files."
                )
            try:
                if validate_image(
                    options["validate_image"], options["image_type"]
                ) is not True:
                    raise RuntimeError("Image validation did not complete.")
            except ValidationError as error:
                self.stdout.write(
                    json.dumps({"valid": False, "reason": str(error.detail[0])})
                )
            else:
                self.stdout.write(json.dumps({"valid": True}))
            return
        if options["quarantine_existing"]:
            if options["delete"]:
                raise CommandError(
                    "Quarantine relocation must not be combined with orphan deletion."
                )
            rows = quarantine_inventory()
            affected = [row for row in rows if row["migrate"]]
            self.stdout.write(
                "%s asset version(s), %s series; %s version(s) require quarantine relocation."
                % (
                    len(rows),
                    len({row["code"] for row in rows}),
                    len(affected),
                )
            )
            for row in rows:
                self.stdout.write(
                    "%s %s v%s %r: %s"
                    % (
                        row["id"],
                        row["code"],
                        row["version_no"],
                        row["url"],
                        row["state"],
                    )
                )
            if not options["apply"]:
                self.stdout.write(
                    "Inspection only. After approval and the pending asset migrations, use --apply to revoke and quarantine existing files."
                )
                return
            if not MigrationRecorder.Migration.objects.filter(
                app="asset", name="0012_upload_processing"
            ).exists():
                raise CommandError(
                    "Apply asset.0012_upload_processing before migrating existing files."
                )
            count, issues = quarantine_existing_uploads()
            self.stdout.write(
                "%s version(s) quarantined; %s issue(s). No records or version numbers were removed."
                % (count, len(issues))
            )
            if issues:
                raise CommandError(
                    "Some files need operator attention; their records remain unavailable: "
                    + ", ".join(issues)
                )
            return
        if options["purge_rejected"]:
            if options["retention_days"] < 1:
                raise CommandError("Use a positive --retention-days.")
            count = purge_rejected_uploads(
                days=options["retention_days"], delete=options["delete"]
            )
            self.stdout.write(
                "%s rejected file(s) %s; version records retained."
                % (
                    count,
                    (
                        "removed"
                        if options["delete"]
                        else "eligible (inspection only; use --delete to remove)"
                    ),
                )
            )
            return
        if options["process_uploads"]:
            if options["delete"] or options["limit"] < 1:
                raise CommandError(
                    "Use a positive --limit and do not combine processing with --delete."
                )
            count = process_uploads(
                limit=options["limit"], retry_errors=options["retry_errors"]
            )
            self.stdout.write(
                "%s upload job(s) processed. Files passing their required image, video or GLB checks can be published."
                % count
            )
            return
        storage = Asset._meta.get_field("url").storage
        referenced = set(Asset.objects.values_list("url", flat=True))
        # A failed migration may have moved bytes before its DB commit failed.
        protected_recovery = {
            quarantine_recovery_key(name)
            for name in referenced
            if not is_quarantine_key(name)
        }
        # Leave recent files alone: a current upload may not have committed yet.
        cutoff = timezone.now() - timedelta(days=1)

        def files(file_storage, path):
            # Never follow filesystem links while inspecting/deleting orphans.
            if (Path(file_storage.location) / path).is_symlink():
                return
            try:
                directories, names = file_storage.listdir(path)
            except FileNotFoundError:
                return
            for name in names:
                key = path + "/" + name
                if not (Path(file_storage.location) / key).is_symlink():
                    yield key
            for directory in directories:
                yield from files(file_storage, path + "/" + directory)

        count = 0
        locations = (
            (storage, "quarantine"),
            (storage, "approved"),
            (FileSystemStorage(location=settings.MEDIA_ROOT), "uploads"),
            (FileSystemStorage(location=settings.ASSET_PRIVATE_ROOT), "unverified"),
        )
        for file_storage, directory in locations:
            for name in files(file_storage, directory):
                if name in referenced or name in protected_recovery:
                    continue
                if file_storage.get_modified_time(name) >= cutoff:
                    continue
                if options["delete"] and not Asset.objects.filter(url=name).exists():
                    file_storage.delete(name)
                self.stdout.write(name)
                count += 1
        self.stdout.write("%s unreferenced file(s)." % count)
