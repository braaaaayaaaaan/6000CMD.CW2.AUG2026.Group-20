"""Local private storage: never expose a filesystem-backed public URL."""
from pathlib import Path, PurePosixPath

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage


class PrivateAssetStorage(FileSystemStorage):
    def path(self, name):
        relative = PurePosixPath(str(name).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("uploads",):
            raise SuspiciousFileOperation("Invalid asset storage key.")
        path = Path(super().path(name)).resolve()
        if not path.is_relative_to(Path(self.location).resolve()):
            raise SuspiciousFileOperation("Invalid asset storage key.")
        return str(path)

    def url(self, name):
        raise ValueError("Private assets require an authorised signed media URL.")
