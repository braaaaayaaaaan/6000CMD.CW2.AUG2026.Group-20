"""Recover stale storage references without bypassing upload validation."""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from asset.files import copy_private_file, file_digest, legacy_file_path, quarantine_recovery_key
from asset.models import Asset, is_approved_key, is_quarantine_key


class Command(BaseCommand):
    help = "Find missing files by SHA-256 in private storage and legacy uploads; pass --apply to repair."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def candidates(self, storage):
        # Prefer already validated files, then quarantined and legacy originals.
        for prefix in ("approved", "quarantine", "uploads"):
            root = (Path(settings.MEDIA_ROOT) / prefix if prefix == "uploads"
                    else Path(storage.path(prefix)))
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                name = prefix + "/" + path.relative_to(root).as_posix()
                try:
                    if prefix == "uploads":
                        source = legacy_file_path(name)
                    else:
                        if not (is_approved_key(name) or is_quarantine_key(name)):
                            continue
                        source = Path(storage.path(name))
                    with source.open("rb") as file:
                        yield name, source, file_digest(file)
                except (OSError, ValueError, SuspiciousFileOperation):
                    continue

    def handle(self, *args, **options):
        storage = Asset._meta.get_field("url").storage
        missing = []
        for asset in Asset.objects.iterator():
            try:
                if asset.url and storage.exists(asset.url.name):
                    continue
            except (OSError, ValueError, SuspiciousFileOperation):
                pass
            missing.append(asset)

        if not missing:
            self.stdout.write("All asset paths are accessible.")
            return

        wanted = {asset.sha256 for asset in missing if asset.sha256}
        matches = {}
        for name, source, digest in self.candidates(storage):
            if digest in wanted:
                matches.setdefault(digest, (name, source))

        repaired = unresolved = 0
        for asset in missing:
            candidate = matches.get(asset.sha256)
            if not candidate:
                unresolved += 1
                self.stderr.write(f"{asset.pk}: no file matches the recorded SHA-256")
                continue
            name, source = candidate
            # Only previously approved content can retain approved status.
            approved = (asset.processing_status == Asset.ProcessingStatus.APPROVED
                        and is_approved_key(name))
            target = name if approved or is_quarantine_key(name) else quarantine_recovery_key(name)
            if options["apply"]:
                try:
                    with source.open("rb") as file:
                        if file_digest(file) != asset.sha256:
                            raise ValueError("Candidate changed")
                    if target != name:
                        copy_private_file(source, target)
                    with storage.open(target, "rb") as file:
                        if file_digest(file) != asset.sha256:
                            raise ValueError("Recovery copy changed")
                except (OSError, ValueError, SuspiciousFileOperation):
                    unresolved += 1
                    self.stderr.write(f"{asset.pk}: matching file became unavailable or changed")
                    continue
                values = {"url": target}
                if not approved:
                    values.update(
                        processing_status=Asset.ProcessingStatus.PENDING,
                        processing_detail="Recovered file awaiting required file-type validation.",
                        processing_updated_at=timezone.now(), processing_attempts=0,
                        processing_token=None, processing_lease_until=None,
                    )
                updated = Asset.objects.filter(
                    pk=asset.pk, url=asset.url.name, sha256=asset.sha256,
                    processing_status=asset.processing_status, processing_token=asset.processing_token,
                ).update(**values)
                if not updated:
                    unresolved += 1
                    self.stderr.write(f"{asset.pk}: asset changed during repair; run again")
                    continue
                repaired += 1
            suffix = "" if approved else " (requires processing before access)"
            self.stdout.write(f"{asset.pk}: {asset.url.name} -> {target}{suffix}")

        if options["apply"]:
            self.stdout.write(f"{repaired} repaired; {unresolved} unresolved.")
        else:
            self.stdout.write(f"{len(missing) - unresolved} recoverable; {unresolved} unresolved. Run with --apply to repair.")
        if unresolved:
            raise CommandError("Some asset paths could not be recovered from local files.")
