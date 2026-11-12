from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password

from .models import User


class RevocableJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if validated_token.get("version") != user.token_version:
            raise AuthenticationFailed("This session has ended. Please sign in again.")
        return user


class RevocableTokenRefreshSerializer(TokenRefreshSerializer):
    @transaction.atomic
    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        try:
            user = User.objects.select_for_update().get(pk=refresh[api_settings.USER_ID_CLAIM])
        except (User.DoesNotExist, KeyError, ValueError, TypeError):
            raise InvalidToken("This session is no longer valid.") from None
        if (not user.is_active or refresh.get("version") != user.token_version
                or refresh.get(api_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(user.password)):
            raise InvalidToken("This session has ended. Please sign in again.")
        # Revalidate after locking: concurrent requests cannot both rotate it.
        data = super().validate(attrs)
        request = self.context.get("request")
        if request:
            request._request.audit_actor = str(user.pk)
        return data
