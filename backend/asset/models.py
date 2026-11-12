from django.db import models
import uuid


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    upload_datetime = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.CharField(max_length=150)
    file_type = models.CharField(max_length=100)
    file_size = models.FloatField()
    url = models.FileField(upload_to="uploads/")
    tags = models.ManyToManyField(Tags, related_name="assets", blank=True)
    version_no = models.IntegerField(default=1, null=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code", "version_no"], name="unique_asset_version"),
            models.CheckConstraint(condition=models.Q(version_no__gte=1), name="positive_asset_version"),
            models.CheckConstraint(condition=models.Q(file_size__gte=0), name="nonnegative_asset_size"),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = UniqueCodeGenerator.generate_code(prefix="A")
        AssetSeries.objects.get_or_create(code=self.code)
        super().save(*args, **kwargs)
