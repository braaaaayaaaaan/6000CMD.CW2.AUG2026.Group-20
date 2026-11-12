from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from rest_framework import serializers

from .models import User
from .permissions import admitted_email
from .security import reserve_email, send_verification


class UserSerializer(serializers.HyperlinkedModelSerializer):
    email = serializers.EmailField(required=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=256)
    password1 = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=256)
    password2 = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=256)

    class Meta:
        model = User
        fields = ["id", "url", "username", "first_name", "last_name", "email", "password1", "password2",
                  "current_password", "groups", "is_active", "date_joined", "email_verified"]
        read_only_fields = ["groups", "is_active", "date_joined", "email_verified"]

    @sensitive_variables()
    def validate(self, attrs):
        forbidden = {"is_staff", "is_superuser", "user_permissions", "token_version", "email_verified",
                     "mfa_secret", "mfa_recovery_hashes", "is_active"}
        if forbidden.intersection(self.initial_data):
            raise serializers.ValidationError("Security fields cannot be changed through this endpoint.")
        if "email" in attrs:
            attrs["email"] = attrs["email"].strip().lower()
            if not admitted_email(attrs["email"]):
                raise serializers.ValidationError({"email": "This email domain is not eligible for this library."})
            duplicates = User.objects.filter(email__iexact=attrs["email"])
            if self.instance:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({"email": "This email address cannot be used."})
        pw1, pw2 = attrs.get("password1"), attrs.get("password2")
        email_changed = self.instance and "email" in attrs and attrs["email"] != self.instance.email.lower()
        if not self.instance and (not pw1 or not pw2):
            raise serializers.ValidationError({"password": "Password is required."})
        if self.instance and (pw1 or pw2 or email_changed):
            if not self.instance.check_password(attrs.get("current_password", "")):
                raise serializers.ValidationError({"current_password": "The current password is required and must be correct."})
        if pw1 or pw2:
            if pw1 != pw2:
                raise serializers.ValidationError({"password": "Passwords do not match."})
            candidate = User(**{field: attrs.get(field, getattr(self.instance, field, ""))
                                for field in ("username", "first_name", "last_name", "email")})
            try:
                validate_password(pw1, candidate)
            except ValidationError as error:
                raise serializers.ValidationError({"password": list(error.messages)}) from None
        return attrs

    @transaction.atomic
    @sensitive_variables()
    def update(self, instance, validated_data):
        email_changed = "email" in validated_data and validated_data["email"] != instance.email.lower()
        for attr in ("username", "first_name", "last_name", "email"):
            if attr in validated_data:
                setattr(instance, attr, validated_data[attr])
        if validated_data.get("password1"):
            instance.set_password(validated_data["password1"])
            instance.token_version += 1
        if email_changed:
            reserve_email(instance)
        instance.save()
        if email_changed:
            send_verification(instance)
        return instance

    @transaction.atomic
    @sensitive_variables()
    def create(self, validated_data):
        password = validated_data.pop("password1")
        validated_data.pop("password2")
        validated_data.pop("current_password", None)
        validated_data.pop("groups", None)
        group, _ = Group.objects.get_or_create(name="Viewer")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        reserve_email(user)
        user.groups.set([group])
        send_verification(user)
        return user


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ["url", "name"]
