"""Account workflows using Django tokens/hashers and standard TOTP/Fernet."""
import base64
import logging
import secrets
import time
import uuid
from datetime import timedelta
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from urllib.parse import urlencode

import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken as InvalidCiphertext
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import AuthenticationFailed, APIException, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AccountSession, EmailIdentity, User
from .permissions import account_allowed, application_role, requires_mfa

audit = logging.getLogger("dam.audit")
GENERIC_EMAIL_MESSAGE = "If an eligible account exists, an email will be sent."
_mail_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="account-mail")
_mail_slots = BoundedSemaphore(100)


def profile(user):
    return {"id": str(user.pk), "username": user.username, "group": application_role(user),
            "email": user.email, "email_verified": user.email_verified,
            "mfa_enabled": user.mfa_enabled, "mfa_required": requires_mfa(user)}


def event(name, user=None, target=None):
    # Never log identifiers supplied by clients, tokens, codes, or SMTP exceptions.
    audit.info("event=%s actor=%s target=%s", name, str(user.pk) if user else "anonymous",
               str(target.pk) if target else "none")


def reserve_email(user):
    email = user.email.strip().lower()
    if not email or User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        raise ValidationError("This email address cannot be used. Contact support if you need help.")
    try:
        with transaction.atomic():
            EmailIdentity.objects.update_or_create(user=user, defaults={"email": email})
    except IntegrityError:
        raise ValidationError("This email address cannot be used. Contact support if you need help.") from None


@sensitive_variables()
def deliver(user, subject, path, values):
    # Fragments are not sent in HTTP request URLs or Referer headers.
    link = settings.ACCOUNT_FRONTEND_URL + path + "#" + urlencode(values)
    destination = user.email

    def send():
        try:
            send_mail(subject, f"Open this link to continue:\n\n{link}\n\nIf you did not request this, ignore this email.",
                      settings.DEFAULT_FROM_EMAIL, [destination], fail_silently=False)
            return True
        except Exception:
            event("account_email_delivery_failed")
            return False

    if not settings.ACCOUNT_EMAIL_ASYNC:
        return send()

    def enqueue():
        if not _mail_slots.acquire(blocking=False):
            event("account_email_queue_full")
            return
        try:
            _mail_workers.submit(send).add_done_callback(lambda future: _mail_slots.release())
        except RuntimeError:
            _mail_slots.release()
            event("account_email_delivery_failed")
    # Keep SMTP timing out of public recovery responses and avoid rolled-back mail.
    transaction.on_commit(enqueue)
    return True


@sensitive_variables()
def send_verification(user):
    # Call while holding the user lock when resending; newest link replaces old.
    user.verification_nonce = uuid.uuid4()
    user.save(update_fields=["verification_nonce"])
    token = signing.dumps({"user": str(user.pk), "email": user.email.lower(),
                           "nonce": str(user.verification_nonce)}, salt="verify-email")
    return deliver(user, "Verify your email address", "/verify-email", {"token": token, "email": user.email})


@sensitive_variables()
def send_password_reset(user):
    return deliver(user, "Reset your password", "/reset-password", {
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": default_token_generator.make_token(user),
    })


def locked_out(user):
    return bool(user.auth_locked_until and user.auth_locked_until > timezone.now())


def failed_attempt(user):
    if user.auth_locked_until and user.auth_locked_until <= timezone.now():
        user.auth_failures = 0
    user.auth_failures += 1
    if user.auth_failures >= settings.AUTH_MAX_FAILURES:
        user.auth_locked_until = timezone.now() + timedelta(seconds=settings.AUTH_LOCK_SECONDS)
    user.save(update_fields=["auth_failures", "auth_locked_until"])
    event("authentication_failed", user)


def clear_failures(user):
    user.auth_failures = 0
    user.auth_locked_until = None
    user.save(update_fields=["auth_failures", "auth_locked_until"])


@sensitive_variables()
def verify_sensitive_password(user, password):
    # Caller holds the row lock and commits before reporting validation errors.
    if locked_out(user):
        return False
    if not user.check_password(password):
        failed_attempt(user)
        return False
    clear_failures(user)
    return True


@sensitive_variables()
def password_user(username, password):
    # Commit failures before returning; raising inside atomic would undo lockouts.
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username=username).first()
        if not user:
            make_password(password)
            event("authentication_failed")
            return None
        if locked_out(user):
            return None
        if not user.check_password(password) or not user.is_active:
            failed_attempt(user)
            return None
        # Only a completed login clears failures (not the password half of MFA).
        return user


@sensitive_variables()
def challenge_for(user, admin_session=False, purpose="login"):
    user.challenge_nonce = uuid.uuid4()
    # Pending seeds belong only to this challenge, never its predecessor.
    user.mfa_pending_secret = ""
    user.mfa_pending_at = None
    user.save(update_fields=["challenge_nonce", "mfa_pending_secret", "mfa_pending_at"])
    return signing.dumps({"user": str(user.pk), "nonce": str(user.challenge_nonce),
                          "version": user.token_version, "auth": user.get_session_auth_hash(),
                          "admin": bool(admin_session), "purpose": purpose}, salt="mfa-challenge")


@sensitive_variables()
def challenge_user(token):
    try:
        payload = signing.loads(token, salt="mfa-challenge", max_age=settings.MFA_CHALLENGE_TIMEOUT)
        user = User.objects.select_for_update().get(pk=payload["user"], is_active=True, email_verified=True)
        if (payload["nonce"] != str(user.challenge_nonce) or payload["version"] != user.token_version
                or not secrets.compare_digest(payload["auth"], user.get_session_auth_hash())
                or locked_out(user)):
            raise ValueError()
    except (signing.BadSignature, User.DoesNotExist, KeyError, ValueError, TypeError):
        raise AuthenticationFailed("This sign-in attempt is invalid or expired. Start again.") from None
    return user, payload


@sensitive_variables()
def cipher():
    try:
        return Fernet(settings.MFA_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, UnicodeError):
        error = APIException("MFA is unavailable. Ask the administrator to configure its encryption key.")
        error.status_code = 503
        raise error from None


@sensitive_variables()
def decrypt_secret(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidCiphertext:
        error = APIException("MFA is unavailable. Contact the administrator.")
        error.status_code = 503
        raise error from None


@sensitive_variables()
def start_enrolment(user, replace=False):
    if user.mfa_enabled and not replace:
        raise ValidationError("MFA is already enabled.")
    if not user.mfa_pending_secret or not user.mfa_pending_at or (
        timezone.now() - user.mfa_pending_at).total_seconds() > settings.MFA_ENROLMENT_TIMEOUT:
        user.mfa_pending_secret = cipher().encrypt(pyotp.random_base32().encode()).decode()
        user.mfa_pending_at = timezone.now()
        user.save(update_fields=["mfa_pending_secret", "mfa_pending_at"])
    secret = decrypt_secret(user.mfa_pending_secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.MFA_ISSUER)
    output = BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(output)
    return {"secret": secret, "qr_code": "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()}


@sensitive_variables()
def consume_factor(user, code, enrol=False):
    code = str(code).strip()
    if locked_out(user):
        return False
    if not enrol:
        for index, encoded in enumerate(user.mfa_recovery_hashes):
            if check_password(code, encoded):
                user.mfa_recovery_hashes = [value for i, value in enumerate(user.mfa_recovery_hashes) if i != index]
                user.save(update_fields=["mfa_recovery_hashes"])
                return True
    value = user.mfa_pending_secret if enrol else user.mfa_secret
    if not value or (enrol and (not user.mfa_pending_at or (
        timezone.now() - user.mfa_pending_at).total_seconds() > settings.MFA_ENROLMENT_TIMEOUT)):
        return False
    totp = pyotp.TOTP(decrypt_secret(value))
    step = int(time.time()) // totp.interval
    if len(code) == 6 and code.isascii() and code.isdigit():
        for candidate in (step - 1, step, step + 1):
            if (enrol or candidate > user.mfa_last_step) and secrets.compare_digest(totp.at(candidate * totp.interval), code):
                user.mfa_last_step = candidate
                user.save(update_fields=["mfa_last_step"])
                return True
    failed_attempt(user)
    return False


@sensitive_variables()
def activate_mfa(user):
    user.mfa_secret = user.mfa_pending_secret
    user.mfa_pending_secret = ""
    user.mfa_pending_at = None
    user.mfa_recovery_hashes = []
    user.token_version += 1
    user.save()
    event("mfa_enabled", user)


@sensitive_variables()
def issue_credentials(user, request, mfa_verified=False, admin_session=False):
    if not account_allowed(user, mfa_verified):
        raise AuthenticationFailed("Complete email verification and required MFA before signing in.")
    if admin_session and not user.is_staff:
        raise AuthenticationFailed("This account cannot access Django Admin.")
    clear_failures(user)
    user.challenge_nonce = uuid.uuid4()  # Consume the password/MFA challenge.
    user.last_login = timezone.now()
    user.save(update_fields=["challenge_nonce", "last_login"])
    expires = timezone.now() + settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    session = AccountSession.objects.create(user=user, expires_at=expires, mfa_verified=mfa_verified)
    refresh = RefreshToken.for_user(user)
    refresh["version"] = user.token_version
    refresh["sid"] = str(session.pk)
    refresh["mfa"] = bool(mfa_verified)
    if not admin_session and request.session.get("_auth_user_id"):
        # Switching accounts must never leave an older Django Admin identity active.
        from django.contrib.auth import logout
        logout(request._request)
    if admin_session:
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["account_session"] = str(session.pk)
        request.session.set_expiry(min(settings.SESSION_COOKIE_AGE, int((expires - timezone.now()).total_seconds())))
    request._request.audit_actor = str(user.pk)
    event("login_succeeded", user)
    return refresh


def session_record(user, sid, mfa_verified):
    try:
        session = AccountSession.objects.get(pk=sid, user=user, revoked=False, expires_at__gt=timezone.now())
    except (AccountSession.DoesNotExist, ValueError, TypeError, DjangoValidationError):
        raise AuthenticationFailed("This session has ended. Please sign in again.") from None
    if not account_allowed(user, mfa_verified and session.mfa_verified):
        raise AuthenticationFailed("Complete email verification and required MFA before signing in.")
    return session


@sensitive_variables()
def set_auth_cookies(response, refresh):
    access = refresh.access_token
    access["exp"] = min(access["exp"], refresh["exp"])
    for name, token, path in ((settings.AUTH_COOKIE_ACCESS, access, "/"),
                              (settings.AUTH_COOKIE_REFRESH, refresh, "/api/")):
        response.set_cookie(name, str(token), max_age=max(0, int(token["exp"] - time.time())),
                            httponly=True, secure=settings.AUTH_COOKIE_SECURE,
                            samesite=settings.AUTH_COOKIE_SAMESITE, path=path)
    response["Cache-Control"] = "no-store"
    return response


def clear_auth_cookies(response):
    response.delete_cookie(settings.AUTH_COOKIE_ACCESS, path="/", samesite=settings.AUTH_COOKIE_SAMESITE)
    response.delete_cookie(settings.AUTH_COOKIE_REFRESH, path="/api/", samesite=settings.AUTH_COOKIE_SAMESITE)
    response["Cache-Control"] = "no-store"
    return response
