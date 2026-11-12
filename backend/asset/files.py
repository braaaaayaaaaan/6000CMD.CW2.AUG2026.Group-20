import logging
import struct
import hashlib
import json
import uuid
import warnings
from pathlib import PurePosixPath
from contextlib import contextmanager

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from PIL import Image, UnidentifiedImageError

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
    name = str(file.name)
    if ("\\" in name or "/" in name or "\x00" in name
            or any(ord(char) < 32 for char in name) or PurePosixPath(name).suffix.lower() != "." + kind):
        raise ValidationError("Use a safe filename with an extension matching the file content.")
    position = file.tell()
    try:
        file.seek(0)
        if kind in {"png", "jpg"}:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(file) as image:
                    if image.format != {"png": "PNG", "jpg": "JPEG"}[kind] or image.width * image.height > 25_000_000:
                        raise ValueError()
                    image.verify()
                file.seek(0)
                with Image.open(file) as image:
                    image.load()
        elif kind == "glb":
            validate_glb(file, file.size)
        else:
            validate_mp4(file, file.size)
    except (ValueError, OSError, SyntaxError, struct.error, KeyError, TypeError, AttributeError, RecursionError,
            UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValidationError("The file is malformed, truncated, or uses unsupported external resources.") from None
    finally:
        file.seek(position)
    return kind


def file_digest(file):
    position = file.tell()
    try:
        file.seek(0)
        digest = hashlib.sha256()
        while block := file.read(1024 * 1024):
            digest.update(block)
        return digest.hexdigest()
    finally:
        file.seek(position)


def validate_glb(file, size):
    file.seek(0)
    magic, version, length = struct.unpack("<4sII", file.read(12))
    if magic != b"glTF" or version != 2 or length != size:
        raise ValueError()
    document, binary_size, chunks = None, 0, []
    while file.tell() < size:
        length, kind = struct.unpack("<I4s", file.read(8))
        if length % 4 or file.tell() + length > size:
            raise ValueError()
        chunks.append(kind)
        if kind == b"JSON" and len(chunks) == 1 and length <= 4 * 1024 * 1024:
            document = json.loads(file.read(length).decode("utf-8"))
        elif kind == b"BIN\x00" and len(chunks) == 2:
            binary_size = length
            file.seek(length, 1)
        else:
            raise ValueError()
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise ValueError()

    def private_resources(value):
        if isinstance(value, dict):
            # GLB uploads must be self-contained; deny extension-defined URLs too.
            if any(key.lower() in {"uri", "url"} for key in value):
                raise ValueError()
            for child in value.values():
                private_resources(child)
        elif isinstance(value, list):
            for child in value:
                private_resources(child)
    private_resources(document)
    buffers = document.get("buffers", [])
    if len(buffers) > 1 or (buffers and not 0 <= binary_size - buffers[0]["byteLength"] <= 3):
        raise ValueError()
    for view in document.get("bufferViews", []):
        if view.get("buffer") != 0 or not buffers or view.get("byteOffset", 0) < 0 or view["byteLength"] < 0:
            raise ValueError()
        if view.get("byteOffset", 0) + view["byteLength"] > buffers[0]["byteLength"]:
            raise ValueError()


def validate_mp4(file, size):
    """Bounded ISO-BMFF structural checks; not a codec decoder/transcoder."""
    budget = [0]
    video = [False]
    containers = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"dinf", b"edts", b"mvex", b"moof", b"traf"}

    def boxes(start, end, depth=0):
        if depth > 12:
            raise ValueError()
        found = []
        while start < end:
            budget[0] += 1
            if budget[0] > 100000 or end - start < 8:
                raise ValueError()
            file.seek(start)
            length, kind = struct.unpack(">I4s", file.read(8))
            header = 8
            if length == 1:
                length = struct.unpack(">Q", file.read(8))[0]
                header = 16
            elif length == 0:
                length = end - start
            if length < header or start + length > end:
                raise ValueError()
            minimum = {b"ftyp": 8, b"mvhd": 100, b"tkhd": 84, b"mdhd": 24, b"hdlr": 24,
                       b"stsd": 8, b"stts": 8, b"stsc": 8, b"stsz": 12, b"stco": 8, b"co64": 8}
            if length - header < minimum.get(kind, 0):
                raise ValueError()
            if kind == b"hdlr":
                file.seek(start + header + 8)
                video[0] |= file.read(4) == b"vide"
            children = boxes(start + header, start + length, depth + 1) if kind in containers else []
            if kind == b"dref":
                file.seek(start + header)
                flags, count = struct.unpack(">II", file.read(8))
                entries = boxes(start + header + 8, start + length, depth + 1)
                if flags != 0 or len(entries) != count:
                    raise ValueError()
            if kind in {b"url ", b"urn "}:
                file.seek(start + header)
                # Only an empty, self-contained data reference is allowed.
                if length != header + 4 or file.read(4) != b"\x00\x00\x00\x01":
                    raise ValueError()
            if kind == b"moov" and not {b"mvhd", b"trak"}.issubset(children):
                raise ValueError()
            if kind == b"trak" and not {b"tkhd", b"mdia"}.issubset(children):
                raise ValueError()
            if kind == b"mdia" and not {b"mdhd", b"hdlr", b"minf"}.issubset(children):
                raise ValueError()
            if kind == b"minf" and not {b"dinf", b"stbl"}.issubset(children):
                raise ValueError()
            if kind == b"stbl" and (not {b"stsd", b"stts", b"stsc", b"stsz"}.issubset(children)
                    or not {b"stco", b"co64"}.intersection(children)):
                raise ValueError()
            if kind == b"mdat" and length == header:
                raise ValueError()
            found.append(kind)
            start += length
        return found
    if not {b"ftyp", b"moov", b"mdat"}.issubset(boxes(0, size)) or not video[0]:
        raise ValueError()


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
        if result.files and (set(result.files) != {"url"} or len(result.files.getlist("url")) != 1):
            raise ValidationError({"url": "Upload exactly one asset file per request."})
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
        name = field.storage.save("uploads/" + uuid.uuid4().hex + PurePosixPath(uploaded.name).suffix.lower(), uploaded, max_length=field.max_length)
        serializer.validated_data["url"] = name
    try:
        if name:
            with field.storage.open(name, "rb") as stored:
                if file_digest(stored) != serializer.validated_data["sha256"]:
                    raise ValidationError("The stored upload failed its integrity check. Try again.")
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
