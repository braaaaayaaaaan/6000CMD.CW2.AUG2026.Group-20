from .models import Asset, AssetSeries, Tags
from .files import validate_file
from .media import signed_media_url
from rest_framework import serializers


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = "__all__"
        read_only_fields = ["version_no", "uploaded_by", "file_type", "file_size", "upload_datetime"]
        # The next version is allocated under a database lock, after validation.
        validators = []

    def validate_url(self, file):
        self.detected_type = validate_file(file)
        return file

    def validate(self, attrs):
        errors = {}
        for field in ("version_no", "uploaded_by", "file_type", "file_size"):
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
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update(signed_media_url(instance, self.context.get("request")))
        return data


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tags
        fields = ["id", "title"]


