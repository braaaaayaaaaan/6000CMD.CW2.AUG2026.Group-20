import logging
import hashlib
import os
import struct
import json
import uuid
import warnings
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.db import connection, transaction
from django.db.models import F, Q
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from PIL import Image, UnidentifiedImageError

from .models import (
    Asset,
    AssetSeries,
    QUARANTINE_KEY_PATTERN,
    is_approved_key,
    is_quarantine_key,
)

logger = logging.getLogger("dam.audit")
MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "mp4": "video/mp4",
    "glb": "model/gltf-binary",
}


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
    if (
        len(header) >= 12
        and header[:4] == b"glTF"
        and struct.unpack("<I", header[4:8])[0] == 2
    ):
        return "glb"
    if (
        len(header) >= 12
        and header[4:8] == b"ftyp"
        and header[8:12]
        in {
            b"isom",
            b"iso2",
            b"mp41",
            b"mp42",
            b"avc1",
            b"M4V ",
            b"dash",
            b"MSNV",
        }
    ):
        return "mp4"
    return None


def validate_file(file):
    if not file.size or file.size > settings.ASSET_UPLOAD_MAX_BYTES:
        raise ValidationError(
            "Choose a nonempty file up to %s MB."
            % (settings.ASSET_UPLOAD_MAX_BYTES // (1024 * 1024))
        )
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
    try:
        if name and not Asset.objects.filter(url=name).exists():
            storage.delete(name)
    except Exception:
        # A storage/database outage must not hide the original upload failure.
        # The existing orphan cleanup command can retry this later.
        logger.exception("asset_file_cleanup_failed", extra={"asset_file": name})


@contextmanager
def staged_file(serializer):
    """Remove a newly stored file if the surrounding database operation fails."""
    field = Asset._meta.get_field("url")
    uploaded = serializer.validated_data.get("url")
    name = None
    try:
        if uploaded is not None:
            instance = serializer.instance or Asset()
            # Generate the private name before saving so partial writes can be removed.
            name = field.generate_filename(instance, uploaded.name)
            name = field.storage.save(name, uploaded, max_length=field.max_length)
            serializer.validated_data["url"] = name
            with field.storage.open(name, "rb") as stored:
                if file_digest(stored) != serializer.validated_data["sha256"]:
                    raise ValidationError("The stored upload failed its integrity check. Try again.")
        yield
    except BaseException:
        if name:
            delete_unreferenced(name, field.storage)
        raise


MAX_PROCESSING_ATTEMPTS = 3
PROCESSING_LEASE = timedelta(minutes=15)


def check_asset_security(asset):
    """Items 4–6 must validate the file type before this can return True."""
    raise NotImplementedError("Required file-type validation is not implemented.")


def same_file_contents(first, second):
    if (
        first.is_symlink()
        or second.is_symlink()
        or not first.is_file()
        or not second.is_file()
    ):
        raise OSError("Expected regular asset files.")
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as left, second.open("rb") as right:
        return (
            hashlib.file_digest(left, "sha256").digest()
            == hashlib.file_digest(right, "sha256").digest()
        )


def copy_private_file(source, target_key):
    """Publish a complete private copy; interrupted copies never use final keys."""
    storage = Asset._meta.get_field("url").storage
    target = Path(storage.path(target_key))
    if target.exists():
        if not same_file_contents(source, target):
            raise OSError(
                "A different file already exists at the recovery destination."
            )
        return
    temporary_key = str(
        PurePosixPath(target_key).parent / (".transfer-" + uuid.uuid4().hex)
    )
    try:
        with source.open("rb") as original:
            temporary_key = storage.save(temporary_key, File(original))
        temporary = Path(storage.path(temporary_key))
        if not same_file_contents(source, temporary):
            raise OSError("The private file copy could not be verified.")
        with temporary.open("rb") as complete:
            os.fsync(complete.fileno())
        os.replace(temporary, target)
    finally:
        try:
            storage.delete(temporary_key)
        except OSError:
            logger.exception("asset_transfer_cleanup_failed")


def promote_asset(job):
    """Validate the claimed quarantine file, then copy and commit publication.

    No public route calls this service. The source is removed only after the
    database commits; rollback leaves the original quarantined file intact.
    """
    if not is_quarantine_key(job.url.name) or not job.processing_token:
        raise ValueError("Only claimed quarantine files can be promoted.")
    live_claim = Asset.objects.filter(
        pk=job.pk,
        url=job.url.name,
        processing_status=Asset.ProcessingStatus.PROCESSING,
        processing_token=job.processing_token,
        processing_lease_until__gt=timezone.now(),
    )
    if not live_claim.exists():
        return False
    if not Path(job.url.path).is_file():
        raise FileNotFoundError("Quarantined upload is missing.")
    if check_asset_security(job) is not True:
        raise RuntimeError("Required file-type validation did not complete.")
    storage = job.url.storage
    target_key = "approved/%s/%s" % (job.pk.hex, job.processing_token.hex)
    try:
        with transaction.atomic():
            if (
                not AssetSeries.objects.select_for_update()
                .filter(code=job.code)
                .exists()
            ):
                return False
            current = live_claim.select_for_update().first()
            if current is None:
                return False
            copy_private_file(Path(storage.path(current.url.name)), target_key)
            # Copying may take time; an expired claim must never publish.
            if not live_claim.filter(processing_lease_until__gt=timezone.now()).update(
                url=target_key,
                processing_status=Asset.ProcessingStatus.APPROVED,
                processing_detail="Required file-type validation passed.",
                processing_updated_at=timezone.now(),
                processing_token=None,
                processing_lease_until=None,
            ):
                raise RuntimeError(
                    "The processing claim expired before promotion completed."
                )
            source_key = current.url.name
            transaction.on_commit(lambda: delete_unreferenced(source_key, storage))
    except BaseException:
        delete_unreferenced(target_key, storage)
        raise
    return True


def recover_processing_jobs():
    """Fence interrupted workers; retries remain explicit and bounded."""
    now = timezone.now()
    return Asset.objects.filter(
        processing_status=Asset.ProcessingStatus.PROCESSING,
        processing_lease_until__lte=now,
    ).update(
        processing_status=Asset.ProcessingStatus.ERROR,
        processing_detail="Processing was interrupted. An operator can retry it.",
        processing_updated_at=now,
        processing_token=None,
        processing_lease_until=None,
    )


def claim_processing_job(retry_errors=False, cutoff=None):
    cutoff = cutoff or timezone.now()
    eligible = Q(processing_status=Asset.ProcessingStatus.PENDING)
    if retry_errors:
        eligible |= Q(processing_status=Asset.ProcessingStatus.ERROR)
    with transaction.atomic():
        jobs = Asset.objects.filter(
            eligible,
            processing_updated_at__lte=cutoff,
            processing_attempts__lt=MAX_PROCESSING_ATTEMPTS,
            url__regex=QUARANTINE_KEY_PATTERN,
        ).order_by("upload_datetime", "id")
        if connection.features.has_select_for_update_skip_locked:
            jobs = jobs.select_for_update(skip_locked=True)
        else:
            jobs = jobs.select_for_update()
        job = jobs.first()
        if job is None:
            return None
        now, token = timezone.now(), uuid.uuid4()
        claimed = Asset.objects.filter(
            pk=job.pk,
            processing_status=job.processing_status,
            processing_attempts=job.processing_attempts,
            processing_token__isnull=True,
        ).update(
            processing_status=Asset.ProcessingStatus.PROCESSING,
            processing_detail="Checking required file-type validation.",
            processing_updated_at=now,
            processing_attempts=job.processing_attempts + 1,
            processing_token=token,
            processing_lease_until=now + PROCESSING_LEASE,
        )
        if not claimed:
            return None
        job.refresh_from_db()
        return job


def finish_processing_job(job, status, detail):
    """Finish without approval; unavailable validators do not consume retries."""
    if status not in {
        Asset.ProcessingStatus.REJECTED,
        Asset.ProcessingStatus.ERROR,
        Asset.ProcessingStatus.PENDING,
    }:
        raise ValueError("Successful checks must use private file promotion.")
    changes = {
        "processing_status": status,
        "processing_detail": detail,
        "processing_updated_at": timezone.now(),
        "processing_token": None,
        "processing_lease_until": None,
    }
    if status == Asset.ProcessingStatus.PENDING:
        changes["processing_attempts"] = F("processing_attempts") - 1
    with transaction.atomic():
        if not AssetSeries.objects.select_for_update().filter(code=job.code).exists():
            return False
        return bool(
            Asset.objects.filter(
                pk=job.pk,
                url=job.url.name,
                processing_status=Asset.ProcessingStatus.PROCESSING,
                processing_token=job.processing_token,
                processing_lease_until__gt=timezone.now(),
            ).update(**changes)
        )


def process_uploads(limit=100, retry_errors=False):
    # Process each eligible version at most once per invocation.
    cutoff = timezone.now()
    recover_processing_jobs()
    processed = 0
    for _ in range(limit):
        job = claim_processing_job(retry_errors=retry_errors, cutoff=cutoff)
        if job is None:
            break
        try:
            promote_asset(job)
        except ValidationError:
            status, detail = (
                Asset.ProcessingStatus.REJECTED,
                "This file did not pass validation. Upload a replacement.",
            )
        except NotImplementedError:
            status, detail = (
                Asset.ProcessingStatus.PENDING,
                "Awaiting required file-type validation. The file remains quarantined.",
            )
        except Exception:
            logger.exception("asset_processing_failed", extra={"asset_id": str(job.pk)})
            status, detail = (
                Asset.ProcessingStatus.ERROR,
                "File processing could not finish. An operator can retry it.",
            )
        else:
            processed += 1
            continue
        finish_processing_job(job, status, detail)
        processed += 1
    return processed


def quarantine_recovery_key(legacy_key):
    # Stable across retries, including a crash after relocation but before commit.
    digest = hashlib.sha256(("legacy:" + legacy_key).encode()).hexdigest()[:32]
    return "quarantine/" + digest


def legacy_file_path(name):
    """Legacy paths are available only to the operator migration, never media."""
    if is_approved_key(name):
        return Path(Asset._meta.get_field("url").storage.path(name))
    parts = PurePosixPath(name).parts
    if (
        not parts
        or parts[0] not in {"uploads", "unverified"}
        or ".." in parts
        or "\\" in name
    ):
        raise ValueError("Invalid historical storage key.")
    root = settings.MEDIA_ROOT if parts[0] == "uploads" else settings.ASSET_PRIVATE_ROOT
    path = Path(FileSystemStorage(location=root).path(name))
    if not path.resolve().is_relative_to(Path(root).resolve()) or path.is_symlink():
        raise ValueError("Historical storage path is not a safe regular file path.")
    return path


def quarantine_inventory():
    """Read-only; works before Item 1's status fields have been migrated."""
    storage = Asset._meta.get_field("url").storage
    rows = list(
        Asset.objects.order_by("code", "version_no", "id").values(
            "id", "code", "version_no", "url"
        )
    )
    for row in rows:
        name = row["url"]
        row["migrate"] = not is_quarantine_key(name)
        try:
            if not row["migrate"]:
                path = Path(storage.path(name))
                row["state"] = "isolated" if path.is_file() else "missing"
                continue
            source = legacy_file_path(name)
            target = Path(storage.path(quarantine_recovery_key(name)))
            if source.is_file():
                row["state"] = (
                    "ready"
                    if not target.exists() or same_file_contents(source, target)
                    else "inconsistent"
                )
                row["bytes"] = source.stat().st_size
            else:
                row["state"] = "recoverable" if target.is_file() else "missing"
        except (ValueError, OSError, SuspiciousFileOperation):
            row["state"] = "inconsistent"
    return rows


def quarantine_existing_uploads():
    """Explicit Option B operation: revoke first, then relocate legacy files.

    Relocation removes the old source only after a verified private copy exists.
    A rollback or crash leaves that deterministic copy available for a retry.
    Shared legacy filenames are relocated and updated as a group.
    """
    rows = [row for row in quarantine_inventory() if row["migrate"]]
    ids = [row["id"] for row in rows]
    with transaction.atomic():
        list(
            AssetSeries.objects.select_for_update()
            .filter(code__in={row["code"] for row in rows})
            .order_by("code")
        )
        list(Asset.objects.select_for_update().filter(pk__in=ids).order_by("id"))
        Asset.objects.filter(pk__in=ids, url__in={row["url"] for row in rows}).update(
            processing_status=Asset.ProcessingStatus.PENDING,
            processing_detail="Awaiting required file-type validation.",
            processing_attempts=0,
            processing_token=None,
            processing_lease_until=None,
            processing_updated_at=timezone.now(),
        )
    storage = Asset._meta.get_field("url").storage
    migrated, issues = 0, []
    for old_key in dict.fromkeys(row["url"] for row in rows):
        group = [row for row in rows if row["url"] == old_key]
        group_ids = [row["id"] for row in group]
        try:
            with transaction.atomic():
                list(
                    AssetSeries.objects.select_for_update()
                    .filter(code__in={row["code"] for row in group})
                    .order_by("code")
                )
                current = Asset.objects.select_for_update().filter(
                    pk__in=group_ids, url=old_key
                )
                if not list(current):
                    continue
                source = legacy_file_path(old_key)
                target_key = quarantine_recovery_key(old_key)
                target = Path(storage.path(target_key))
                if source.exists():
                    copy_private_file(source, target_key)
                    # Remove the exposed source BEFORE committing a migrated key.
                    source.unlink()
                elif not target.is_file() or target.is_symlink():
                    raise FileNotFoundError(
                        "Historical file is missing from both its original and recovery locations."
                    )
                count = current.update(
                    url=target_key,
                    processing_status=Asset.ProcessingStatus.PENDING,
                    processing_detail="Awaiting required file-type validation.",
                    processing_updated_at=timezone.now(),
                )
            migrated += count
        except Exception:
            logger.exception(
                "asset_quarantine_migration_failed", extra={"asset_file": old_key}
            )
            Asset.objects.filter(pk__in=group_ids, url=old_key).update(
                processing_status=Asset.ProcessingStatus.ERROR,
                processing_detail="Historical file could not be quarantined. An operator must check its source or recovery file.",
                processing_updated_at=timezone.now(),
            )
            issues.extend(str(row["id"]) for row in group)
    return migrated, issues


def purge_rejected_uploads(days=30, delete=False):
    """Manual retention cleanup preserves version records, metadata and tags."""
    if days < 1:
        raise ValueError("Retention must be at least one day.")
    cutoff = timezone.now() - timedelta(days=days)
    candidates = Asset.objects.filter(
        processing_status=Asset.ProcessingStatus.REJECTED,
        processing_updated_at__lt=cutoff,
        url__regex=QUARANTINE_KEY_PATTERN,
    )
    ids = list(candidates.values_list("pk", flat=True))
    removed = 0
    if delete:
        for asset_id in ids:
            with transaction.atomic():
                code = (
                    Asset.objects.filter(pk=asset_id)
                    .values_list("code", flat=True)
                    .first()
                )
                if code is None:
                    continue
                AssetSeries.objects.select_for_update().get(code=code)
                asset = candidates.select_for_update().filter(pk=asset_id).first()
                if asset is None:
                    continue
                name, storage = asset.url.name, asset.url.storage
                Asset.objects.filter(pk=asset.pk).update(
                    url="",
                    processing_detail="Rejected file removed after the retention period. Upload a replacement.",
                )
                transaction.on_commit(
                    lambda name=name, storage=storage: delete_unreferenced(
                        name, storage
                    )
                )
            removed += 1
    return removed if delete else len(ids)


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
