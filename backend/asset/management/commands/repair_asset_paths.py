"""Recover stale storage references using the recorded content digest."""
from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation
from django.core.management.base import BaseCommand, CommandError

from asset.files import file_digest
from asset.models import Asset


class Command(BaseCommand):
    help = "Find missing asset files in uploads by SHA-256; pass --apply to repair their paths."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

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
        root = Path(storage.path("uploads"))
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            name = "uploads/" + path.relative_to(root).as_posix()
            try:
                with storage.open(name, "rb") as file:
                    digest = file_digest(file)
            except (OSError, ValueError, SuspiciousFileOperation):
                continue
            if digest in wanted:
                matches.setdefault(digest, name)

        repaired = unresolved = 0
        for asset in missing:
            name = matches.get(asset.sha256)
            if not name:
                unresolved += 1
                self.stderr.write(f"{asset.pk}: no upload matches the recorded SHA-256")
                continue
            if options["apply"]:
                # Recheck the candidate before updating, and preserve concurrent replacements.
                try:
                    with storage.open(name, "rb") as file:
                        if file_digest(file) != asset.sha256:
                            raise ValueError("Candidate changed")
                except (OSError, ValueError, SuspiciousFileOperation):
                    unresolved += 1
                    self.stderr.write(f"{asset.pk}: matching upload became unavailable or changed")
                    continue
                updated = Asset.objects.filter(
                    pk=asset.pk, url=asset.url.name, sha256=asset.sha256,
                ).update(url=name)
                if not updated:
                    unresolved += 1
                    self.stderr.write(f"{asset.pk}: asset changed during repair; run again")
                    continue
                repaired += 1
            self.stdout.write(f"{asset.pk}: {asset.url.name} -> {name}")

        if options["apply"]:
            self.stdout.write(f"{repaired} repaired; {unresolved} unresolved.")
        else:
            self.stdout.write(f"{len(missing) - unresolved} recoverable; {unresolved} unresolved. Run with --apply to repair.")
        if unresolved:
            raise CommandError("Some asset paths could not be recovered from local uploads.")
