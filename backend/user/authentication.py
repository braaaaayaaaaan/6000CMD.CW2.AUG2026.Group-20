from django.db import transaction
from django.conf import settings
from django.views.decorators.debug import sensitive_variables
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password

from .models import User
from .security import session_record


class RevocableJWTAuthentication(JWTAuthentication):
    @sensitive_variables()
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            return super().authenticate(request)
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw_token:
            return None
        # Cookie credentials are ambient: unsafe requests must pass CSRF checks.
        SessionAuthentication().enforce_csrf(request)
        validated = self.get_validated_token(raw_token)
        return self.get_user(validated), validated

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if validated_token.get("version") != user.token_version:
            raise AuthenticationFailed("This session has ended. Please sign in again.")
        session_record(user, validated_token.get("sid"), validated_token.get("mfa", False))
        return user


class VerifiedSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result:
            user, _ = result
            session_record(user, request.session.get("account_session"), True)
        return result


class RevocableTokenRefreshSerializer(TokenRefreshSerializer):
    @transaction.atomic
    @sensitive_variables()
    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        try:
            user = User.objects.select_for_update().get(pk=refresh[api_settings.USER_ID_CLAIM])
        except (User.DoesNotExist, KeyError, ValueError, TypeError):
            raise InvalidToken("This session is no longer valid.") from None
        if (not user.is_active or refresh.get("version") != user.token_version
                or refresh.get(api_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(user.password)):
            raise InvalidToken("This session has ended. Please sign in again.")
        session = session_record(user, refresh.get("sid"), refresh.get("mfa", False))
        # Revalidate after locking: concurrent requests cannot both rotate it.
        data = super().validate(attrs)
        # Rotation must not extend a login beyond its original absolute expiry.
        from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
        rotated = RefreshToken(data["refresh"])
        rotated["exp"] = min(rotated["exp"], int(session.expires_at.timestamp()))
        access = AccessToken(data["access"])
        access["exp"] = min(access["exp"], rotated["exp"])
        data = {"refresh": str(rotated), "access": str(access)}
        request = self.context.get("request")
        if request:
            request._request.audit_actor = str(user.pk)
        return data
