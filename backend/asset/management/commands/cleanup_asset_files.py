from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from asset.models import Asset


class Command(BaseCommand):
    help = "List unreferenced asset uploads; pass --delete to remove them."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true")

    def handle(self, *args, **options):
        storage = Asset._meta.get_field("url").storage
        referenced = set(Asset.objects.values_list("url", flat=True))
        # Leave recent files alone: a current upload may not have committed yet.
        cutoff = timezone.now() - timedelta(days=1)

        def files(path):
            try:
                directories, names = storage.listdir(path)
            except FileNotFoundError:
                return
            for name in names:
                yield path + "/" + name
            for directory in directories:
                yield from files(path + "/" + directory)

        count = 0
        for name in files("uploads"):
            if name in referenced:
                continue
            if storage.get_modified_time(name) >= cutoff:
                continue
            if options["delete"] and not Asset.objects.filter(url=name).exists():
                storage.delete(name)
            self.stdout.write(name)
            count += 1
        self.stdout.write("%s unreferenced file(s)." % count)
