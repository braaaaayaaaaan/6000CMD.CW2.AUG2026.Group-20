from .models import Asset, AssetSeries, Tags
from .files import validate_file, file_digest
from .media import signed_media_url
from rest_framework import serializers


class AssetSerializer(serializers.ModelSerializer):
    # Never ask storage for a raw URL, even while constructing a response.
    url = serializers.FileField(write_only=True)

    class Meta:
        model = Asset
        fields = [
            "id",
            "code",
            "name",
            "description",
            "upload_datetime",
            "uploaded_by",
            "file_type",
            "file_size",
            "sha256",
            "url",
            "tags",
            "version_no",
            "processing_status",
            "processing_detail",
            "processing_updated_at",
        ]
        read_only_fields = [
            "version_no",
            "uploaded_by",
            "file_type",
            "file_size",
            "sha256",
            "upload_datetime",
            "processing_status",
            "processing_detail",
            "processing_updated_at",
        ]
        # The next version is allocated under a database lock, after validation.
        validators = []

    def validate_url(self, file):
        self.detected_type = validate_file(file)
        return file

    def validate(self, attrs):
        errors = {}
        for field in (
            "version_no",
            "uploaded_by",
            "file_type",
            "file_size",
            "sha256",
            "processing_status",
            "processing_detail",
            "processing_updated_at",
            "processing_attempts",
            "processing_token",
            "processing_lease_until",
            "storage_location",
            "storage_key",
        ):
            if field in self.initial_data:
                errors[field] = "This field is determined by the server."
        code = attrs.get("code")
        if self.instance:
            if code is not None and code != self.instance.code:
                errors["code"] = "An existing asset cannot be moved to another code."
            attrs.pop("code", None)
        elif code and not AssetSeries.objects.filter(code=code).exists():
            errors["code"] = "Choose an existing asset code when adding a version."
        if errors:
            raise serializers.ValidationError(errors)
        if "url" in attrs:
            attrs["file_type"] = self.detected_type
            attrs["file_size"] = attrs["url"].size / (1024 * 1024)
            attrs["sha256"] = file_digest(attrs["url"])
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update(signed_media_url(instance, self.context.get("request")))
        return data


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tags
        fields = ["id", "title"]
