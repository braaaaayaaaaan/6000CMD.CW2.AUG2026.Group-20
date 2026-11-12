import logging
import struct
from contextlib import contextmanager

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser

from .models import Asset

logger = logging.getLogger("dam.audit")
MIME_TYPES = {"png": "image/png", "jpg": "image/jpeg", "mp4": "video/mp4", "glb": "model/gltf-binary"}


def detect_type(file):
    position = file.tell()
    try:
        file.seek(0)
        header = file.read(32)
    finally:
        file.seek(position)
    if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(header) >= 12 and header[:4] == b"glTF" and struct.unpack("<I", header[4:8])[0] == 2:
        return "glb"
    if len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in {
        b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash", b"MSNV",
    }:
        return "mp4"
    return None


def validate_file(file):
    if not file.size or file.size > settings.ASSET_UPLOAD_MAX_BYTES:
        raise ValidationError("Choose a nonempty file up to %s MB." % (settings.ASSET_UPLOAD_MAX_BYTES // (1024 * 1024)))
    kind = detect_type(file)
    if kind is None:
        raise ValidationError("Only valid JPG, PNG, MP4, and GLB files are supported.")
    return kind


class LimitedUploadHandler(FileUploadHandler):
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        if not hasattr(self, "bytes_received"):
            self.bytes_received = 0

    def receive_data_chunk(self, raw_data, start):
        self.bytes_received += len(raw_data)
        if self.bytes_received > settings.ASSET_UPLOAD_MAX_BYTES:
            self.request.asset_upload_too_large = True
            raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None


class AssetMultiPartParser(MultiPartParser):
    def parse(self, stream, media_type=None, parser_context=None):
        result = super().parse(stream, media_type, parser_context)
        request = parser_context["request"]
        if getattr(request._request, "asset_upload_too_large", False):
            raise ValidationError({"url": "The uploaded file exceeds the size limit."})
        return result


def delete_unreferenced(name, storage):
    if not name or Asset.objects.filter(url=name).exists():
        return
    try:
        storage.delete(name)
    except OSError:
        logger.exception("asset_file_cleanup_failed", extra={"asset_file": name})


@contextmanager
def staged_file(serializer):
    """Remove a newly stored file if the surrounding database operation fails."""
    field = Asset._meta.get_field("url")
    uploaded = serializer.validated_data.get("url")
    name = None
    if uploaded is not None:
        instance = serializer.instance or Asset()
        name = field.storage.save(field.generate_filename(instance, uploaded.name), uploaded, max_length=field.max_length)
        serializer.validated_data["url"] = name
    try:
        yield
    except BaseException:
        if name:
            delete_unreferenced(name, field.storage)
        raise


@receiver(pre_save, sender=Asset)
def remove_replaced_file(sender, instance, **kwargs):
    if instance._state.adding:
        return
    old = sender.objects.filter(pk=instance.pk).values_list("url", flat=True).first()
    if old and old != instance.url.name:
        transaction.on_commit(lambda: delete_unreferenced(old, instance.url.storage))


@receiver(post_delete, sender=Asset)
def remove_deleted_file(sender, instance, **kwargs):
    name, storage = instance.url.name, instance.url.storage
    transaction.on_commit(lambda: delete_unreferenced(name, storage))
