import uuid
from collections.abc import Mapping
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.cache import never_cache
from rest_framework import permissions, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from .authentication import RevocableJWTAuthentication, RevocableTokenRefreshSerializer, VerifiedSessionAuthentication
from .models import AccountSession, User
from .permissions import admitted_email, requires_mfa
from .security import (
    GENERIC_EMAIL_MESSAGE, activate_mfa, challenge_for, challenge_user, clear_auth_cookies,
    consume_factor, event, failed_attempt, issue_credentials, locked_out, password_user, profile,
    reserve_email, send_password_reset, send_verification, set_auth_cookies, start_enrolment,
    session_record, verify_sensitive_password,
)
from .throttling import AccountRateThrottle


def text_field(request, name, maximum=512):
    if not isinstance(request.data, Mapping):
        raise ValidationError("Expected a JSON object.")
    return serializers.CharField(max_length=maximum, trim_whitespace=False).run_validation(request.data.get(name))


@method_decorator(sensitive_post_parameters(), name="dispatch")
class AccountEndpoint(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle, AccountRateThrottle]
    throttle_scope = "mfa"

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'

    def initial(self, request, *args, **kwargs):
        request.django_user = request._request.user
        super().initial(request, *args, **kwargs)
        SessionAuthentication().enforce_csrf(request)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class ProtectedAccountEndpoint(AccountEndpoint):
    authentication_classes = [RevocableJWTAuthentication, VerifiedSessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class CsrfView(AccountEndpoint):
    throttle_scope = "refresh"

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class NewTokenObtainPairView(AccountEndpoint):
    throttle_scope = "login"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 401:
            values = request.data if isinstance(request.data, Mapping) else {}
            event("login_failed", request=request, account_identifier=values.get("username"))
        return response

    @sensitive_variables()
    def post(self, request):
        user = password_user(text_field(request, "username", 150), text_field(request, "password", 256))
        if not user:
            raise AuthenticationFailed("Unable to sign in. Check your credentials or try again later.")
        if not admitted_email(user.email):
            raise AuthenticationFailed("Verify your email address before signing in.")
        if not user.email_verified:
            # Only expose resend context after the account password was checked.
            return Response({"detail": "Verify your email address before signing in.",
                             "verification_required": True, "email": user.email},
                            status=401, headers={"WWW-Authenticate": self.get_authenticate_header(request)})
        admin_session = request.data.get("admin_session") is True
        if admin_session and not user.is_staff:
            raise AuthenticationFailed("This account cannot access Django Admin.")
        password_hash, version = user.password, user.token_version
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            if user.password != password_hash or user.token_version != version:
                raise AuthenticationFailed("The account changed. Sign in again.")
            if user.mfa_enabled or requires_mfa(user):
                challenge = challenge_for(user, admin_session)
                return Response({"mfa_required": True, "enrolment_required": not user.mfa_enabled,
                                 "challenge": challenge})
            refresh = issue_credentials(user, request, admin_session=admin_session)
        rotate_token(request)
        return set_auth_cookies(Response({"user": profile(user), "csrfToken": get_token(request)}), refresh)


class NewTokenRefreshView(AccountEndpoint):
    throttle_scope = "refresh"

    @sensitive_variables()
    def post(self, request):
        # Refresh credentials are accepted only from the HttpOnly cookie.
        token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not token:
            raise AuthenticationFailed("Please sign in again.")
        serializer = RevocableTokenRefreshSerializer(data={"refresh": token}, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            raise InvalidToken("This session has ended. Please sign in again.") from None
        refresh = RefreshToken(serializer.validated_data["refresh"])
        user = User.objects.get(pk=refresh["user_id"])
        return set_auth_cookies(Response({"user": profile(user)}), refresh)


class VerificationResendView(AccountEndpoint):
    throttle_scope = "verification"

    @sensitive_variables()
    def post(self, request):
        email = serializers.EmailField().run_validation(text_field(request, "email", 254)).lower()
        with transaction.atomic():
            users = list(User.objects.select_for_update().filter(email__iexact=email, is_active=True)[:2])
            if len(users) == 1 and not users[0].email_verified and admitted_email(email):
                send_verification(users[0])
        return Response({"detail": GENERIC_EMAIL_MESSAGE})


class VerifyEmailView(AccountEndpoint):
    throttle_scope = "verification"

    @sensitive_variables()
    def post(self, request):
        try:
            payload = signing.loads(text_field(request, "token", 2048), salt="verify-email",
                                    max_age=settings.EMAIL_VERIFICATION_TIMEOUT)
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=payload["user"], is_active=True)
                if (user.email_verified or payload["email"] != user.email.lower()
                        or payload["nonce"] != str(user.verification_nonce) or not admitted_email(user.email)):
                    raise ValueError()
                reserve_email(user)
                user.email_verified = True
                user.verification_nonce = uuid.uuid4()
                user.save()
                event("email_verified", user)
                # Email ownership permits setup, but password + TOTP must still
                # be proven before this challenge can create a login session.
                result = {"detail": "Email verified. Complete authenticator security to continue.",
                          "mfa_required": True, "enrolment_required": not user.mfa_enabled,
                          "password_required": True,
                          "challenge": challenge_for(user, purpose="email-verify")}
        except (signing.BadSignature, User.DoesNotExist, KeyError, ValueError, TypeError, DjangoValidationError):
            raise ValidationError("This verification link is invalid or expired. Request a new email.") from None
        return Response(result)


class ForgotPasswordView(AccountEndpoint):
    throttle_scope = "recovery"

    @sensitive_variables()
    def post(self, request):
        email = serializers.EmailField().run_validation(text_field(request, "email", 254)).lower()
        users = list(User.objects.filter(email__iexact=email, is_active=True, email_verified=True)[:2])
        if len(users) == 1 and users[0].has_usable_password():
            send_password_reset(users[0])
        return Response({"detail": GENERIC_EMAIL_MESSAGE})


class ResetPasswordView(AccountEndpoint):
    throttle_scope = "recovery"

    @sensitive_variables()
    def post(self, request):
        try:
            uid = urlsafe_base64_decode(text_field(request, "uid", 128)).decode()
        except (ValueError, UnicodeError, TypeError):
            raise ValidationError("This reset link is invalid or expired.") from None
        token = text_field(request, "token", 256)
        with transaction.atomic():
            try:
                user = User.objects.select_for_update().get(pk=uid, is_active=True, email_verified=True)
            except (User.DoesNotExist, DjangoValidationError):
                raise ValidationError("This reset link is invalid or expired.") from None
            if not default_token_generator.check_token(user, token):
                raise ValidationError("This reset link is invalid or expired.")
            first, second = text_field(request, "password1", 256), text_field(request, "password2", 256)
            if first != second:
                raise ValidationError("Passwords do not match.")
            try:
                validate_password(first, user)
            except DjangoValidationError as error:
                raise ValidationError({"password": list(error.messages)}) from None
            user.set_password(first)
            user.token_version += 1
            user.save()
            user.account_sessions.update(revoked=True)
            event("password_reset", user)
        # A password reset never removes or satisfies the second factor.
        logout(request._request)
        return clear_auth_cookies(Response({"detail": "Password reset has been successful! Proceed to sign in with your new password."}))


class MfaEnrolView(AccountEndpoint):
    @sensitive_variables()
    def post(self, request):
        accepted = True
        with transaction.atomic():
            user, payload = challenge_user(text_field(request, "challenge", 2048))
            if user.mfa_enabled and payload.get("purpose") != "replace":
                raise ValidationError("MFA is already enabled.")
            if payload.get("purpose") == "email-verify":
                accepted = verify_sensitive_password(user, text_field(request, "password", 256))
                if accepted:
                    challenge = challenge_for(user, purpose="enrol")
            elif payload.get("purpose") in ("login", "enrol", "replace"):
                challenge = text_field(request, "challenge", 2048)
            else:
                raise AuthenticationFailed("Start sign-in again.")
            if accepted:
                result = {"challenge": challenge, **start_enrolment(user, replace=payload.get("purpose") == "replace")}
        if not accepted:
            raise AuthenticationFailed("Unable to verify your password. Try again later.")
        return Response(result)


class MfaVerifyView(AccountEndpoint):
    enrol = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code in {200, 401}:
            event("mfa_verification_succeeded" if response.status_code == 200 else "mfa_verification_failed",
                  getattr(request, "audit_mfa_user", None), request=request)
        return response

    @sensitive_variables()
    def post(self, request):
        code = text_field(request, "code", 64)
        with transaction.atomic():
            user, payload = challenge_user(text_field(request, "challenge", 2048))
            request.audit_mfa_user = user
            if self.enrol and payload.get("purpose") == "email-verify":
                raise ValidationError("Verify your password before starting authenticator setup.")
            if self.enrol and user.mfa_enabled and payload.get("purpose") != "replace":
                raise ValidationError("MFA is already enabled.")
            if not self.enrol and payload.get("purpose") not in ("login", "email-verify"):
                raise ValidationError("Complete authenticator enrolment instead.")
            accepted = True
            if payload.get("purpose") == "email-verify":
                accepted = user.check_password(text_field(request, "password", 256))
                if not accepted:
                    failed_attempt(user, log_event=False)
            if accepted:
                # This endpoint records verification once after the transaction.
                accepted = consume_factor(user, code, enrol=self.enrol, log_verification=False)
            if accepted:
                if self.enrol:
                    activate_mfa(user)
                refresh = issue_credentials(user, request, mfa_verified=True, admin_session=payload["admin"])
        if not accepted:
            raise AuthenticationFailed("Invalid authenticator code or password. Try again later if you are locked out.")
        rotate_token(request)
        result = {"user": profile(user), "csrfToken": get_token(request)}
        return set_auth_cookies(Response(result), refresh)


class MfaConfirmView(MfaVerifyView):
    enrol = True


class MfaSetupView(ProtectedAccountEndpoint):
    @sensitive_variables()
    def post(self, request):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if locked_out(user):
                raise AuthenticationFailed("Try again later.")
            accepted = user.check_password(text_field(request, "password", 256))
            if not accepted:
                failed_attempt(user)
            else:
                challenge = challenge_for(user, purpose="enrol")
                result = {"challenge": challenge, **start_enrolment(user)}
        if not accepted:
            raise AuthenticationFailed("Unable to verify your password.")
        return Response(result)


class MfaReplaceView(ProtectedAccountEndpoint):
    @sensitive_variables()
    def post(self, request):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            accepted = not locked_out(user) and user.check_password(text_field(request, "password", 256))
            if accepted:
                code = serializers.CharField(allow_blank=True, max_length=64).run_validation(request.data.get("code", ""))
                if code:
                    accepted = consume_factor(user, code)
                else:
                    # A just-completed MFA login is proof, including the last recovery code.
                    sid = request.auth.get("sid") if request.auth else request.session.get("account_session")
                    accepted = AccountSession.objects.filter(
                        pk=sid, user=user, revoked=False, mfa_verified=True,
                        created_at__gte=timezone.now() - timedelta(seconds=300), expires_at__gt=timezone.now(),
                    ).exists()
            elif not locked_out(user):
                failed_attempt(user)
            if accepted:
                user.mfa_pending_secret = ""
                user.mfa_pending_at = None
                user.save(update_fields=["mfa_pending_secret", "mfa_pending_at"])
                result = {"challenge": challenge_for(user, purpose="replace"), **start_enrolment(user, replace=True)}
        if not accepted:
            raise AuthenticationFailed("Use your password and a current code, or sign in with MFA again before replacing the authenticator.")
        return Response(result)


class MfaRemoveView(ProtectedAccountEndpoint):
    @sensitive_variables()
    def post(self, request):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if requires_mfa(user):
                raise ValidationError("Authenticator security is required for every account and cannot be disabled.")
            accepted = not locked_out(user) and user.check_password(text_field(request, "password", 256))
            if accepted:
                accepted = consume_factor(user, text_field(request, "code", 64))
            elif not locked_out(user):
                failed_attempt(user)
            if accepted:
                user.mfa_secret = user.mfa_pending_secret = ""
                user.mfa_pending_at = None
                user.mfa_recovery_hashes = []
                user.mfa_last_step = -1
                user.token_version += 1
                user.challenge_nonce = uuid.uuid4()
                user.save()
                event("mfa_removed", user)
        if not accepted:
            raise AuthenticationFailed("Unable to verify your credentials.")
        logout(request._request)
        return clear_auth_cookies(Response({"detail": "MFA removed. Sign in again."}))


class MeView(ProtectedAccountEndpoint):
    throttle_scope = "refresh"

    def get(self, request):
        return Response({"user": profile(request.user)})


class LogoutView(AccountEndpoint):
    throttle_scope = "refresh"
    all_devices = False

    @sensitive_variables()
    def post(self, request):
        # Also works when the access token has expired, using the refresh cookie.
        user = None
        sid = request.session.get("account_session")
        raw = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if raw:
            try:
                refresh = RefreshToken(raw)
                candidate = User.objects.filter(pk=refresh["user_id"], token_version=refresh.get("version")).first()
                if candidate:
                    session_record(candidate, refresh.get("sid"), refresh.get("mfa", False))
                    user, sid = candidate, refresh.get("sid")
                refresh.blacklist()
            except (TokenError, KeyError, ValueError, DjangoValidationError, AuthenticationFailed):
                pass
        if not user:
            try:
                authenticated = RevocableJWTAuthentication().authenticate(request)
                if authenticated:
                    user, access = authenticated
                    sid = access.get("sid")
            except AuthenticationFailed:
                pass
        if not user and request.django_user.is_authenticated:
            user = request.django_user
        if user:
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=user.pk)
                if self.all_devices:
                    user.token_version += 1
                    user.challenge_nonce = uuid.uuid4()
                    user.save()
                    user.account_sessions.update(revoked=True)
                else:
                    AccountSession.objects.filter(pk=sid, user=user).update(revoked=True)
            event("logout_all" if self.all_devices else "logout", user)
        logout(request._request)
        return clear_auth_cookies(Response(status=204))


class LogoutAllView(LogoutView):
    all_devices = True


class BrowsableLogoutView(LogoutView):
    @sensitive_variables()
    def post(self, request):
        super().post(request)
        return clear_auth_cookies(redirect(settings.ACCOUNT_FRONTEND_URL + "/login"))


@never_cache
def admin_login(request, extra_context=None):
    # Every login surface uses the same password + email + MFA workflow.
    return redirect(settings.ACCOUNT_FRONTEND_URL + "/login?admin=1")
