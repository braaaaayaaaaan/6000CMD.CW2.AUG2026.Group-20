import os
import re
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone
from django.utils.deconstruct import deconstructible

QUARANTINE_KEY_PATTERN = r"^quarantine/[0-9a-f]{32}$"
APPROVED_KEY_PATTERN = r"^approved/[0-9a-f]{32}/[0-9a-f]{32}$"


def is_quarantine_key(name):
    return bool(re.fullmatch(QUARANTINE_KEY_PATTERN, name or ""))


def is_approved_key(name):
    return bool(re.fullmatch(APPROVED_KEY_PATTERN, name or ""))


@deconstructible
class AssetFileStorage(FileSystemStorage):
    """Quarantine and approved files are private; legacy keys require migration."""

    @property
    def location(self):
        return os.path.abspath(settings.ASSET_PRIVATE_ROOT)

    def path(self, name):
        if name and name.split("/", 1)[0] not in {"quarantine", "approved"}:
            raise SuspiciousFileOperation(
                "Legacy or invalid asset storage key. Run the quarantine migration."
            )
        path = super().path(name)
        root = os.path.realpath(self.location)
        if os.path.commonpath([root, os.path.realpath(path)]) != root:
            raise SuspiciousFileOperation("Asset storage path escapes private storage.")
        return path

    def url(self, name):
        raise ValueError("Asset files require an approved, signed media URL.")


def private_asset_name(instance, filename):
    return "quarantine/" + uuid.uuid4().hex


# Create your models here.
class UniqueCodeGenerator(models.Model):
    """
    Generate a unique model code for each asset.

    Prefix = 'A', Suffix = 000000

    Note: Code will auto increment.

    """

    created_datetime = models.DateTimeField(auto_now_add=True)

    @classmethod
    def generate_code(cls, prefix):
        # Legacy imports may already use a generated-looking code.
        while True:
            instance = cls.objects.create()
            code = f"{prefix}-{instance.pk:06d}"
            if not AssetSeries.objects.filter(code=code).exists():
                return code


class Tags(models.Model):
    """
    Tags for assets.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=50, null=False, blank=False, unique=True)


class AssetSeries(models.Model):
    """A stable row to lock while creating or deleting versions."""

    code = models.CharField(max_length=100, primary_key=True)


class Asset(models.Model):
    """
    Stores, handles, and holds asset data.

    """

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Waiting for processing"
        PROCESSING = "processing", "Processing"
        APPROVED = "approved", "Approved and available"
        REJECTED = "rejected", "Rejected"
        ERROR = "error", "Processing error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    upload_datetime = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.CharField(max_length=150)
    file_type = models.CharField(max_length=100)
    file_size = models.FloatField()
    sha256 = models.CharField(max_length=64, blank=True, editable=False)
    url = models.FileField(
        upload_to=private_asset_name,
        storage=AssetFileStorage(
            file_permissions_mode=0o600, directory_permissions_mode=0o700
        ),
    )
    tags = models.ManyToManyField(Tags, related_name="assets", blank=True)
    version_no = models.IntegerField(default=1, null=False)
    # Each immutable file version is also its persistent processing job.
    processing_status = models.CharField(
        max_length=12,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
        editable=False,
    )
    processing_detail = models.TextField(blank=True, editable=False)
    processing_updated_at = models.DateTimeField(default=timezone.now, editable=False)
    processing_attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    processing_token = models.UUIDField(null=True, editable=False)
    processing_lease_until = models.DateTimeField(null=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "version_no"], name="unique_asset_version"
            ),
            models.CheckConstraint(
                condition=models.Q(version_no__gte=1), name="positive_asset_version"
            ),
            models.CheckConstraint(
                condition=models.Q(file_size__gte=0), name="nonnegative_asset_size"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    processing_status__in=[
                        "pending",
                        "processing",
                        "approved",
                        "rejected",
                        "error",
                    ]
                ),
                name="valid_asset_processing_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        processing_status="processing",
                        processing_token__isnull=False,
                        processing_lease_until__isnull=False,
                    )
                    | (
                        ~models.Q(processing_status="processing")
                        & models.Q(
                            processing_token__isnull=True,
                            processing_lease_until__isnull=True,
                        )
                    )
                ),
                name="valid_asset_processing_lease",
            ),
        ]

    @classmethod
    def published(cls):
        return cls.objects.filter(
            processing_status=cls.ProcessingStatus.APPROVED,
            url__regex=APPROVED_KEY_PATTERN,
        )

    @property
    def is_published(self):
        return (
            self.processing_status == self.ProcessingStatus.APPROVED
            and is_approved_key(self.url.name)
        )

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = UniqueCodeGenerator.generate_code(prefix="A")
        AssetSeries.objects.get_or_create(code=self.code)
        super().save(*args, **kwargs)
