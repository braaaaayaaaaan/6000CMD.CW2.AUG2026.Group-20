import time
from datetime import timedelta
from urllib.parse import parse_qs
from unittest.mock import patch

import pyotp
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.hashers import make_password
from django.contrib.auth.tokens import default_token_generator
from django.core import mail, signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from asset.models import Asset
from .models import AccountSession, User
from .security import decrypt_secret, send_verification

PASSWORD = "Strong!Account-Password-4792"
NEW_PASSWORD = "Different!Account-Password-9876"


class AccountSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def user(self, name="viewer", role="Viewer", verified=True, **kwargs):
        user = User.objects.create_user(username=name, email=f"{name}@example.com", password=PASSWORD,
                                        email_verified=verified, **kwargs)
        user.groups.add(Group.objects.get(name=role))
        return user

    def login(self, user, client=None, **kwargs):
        return (client or self.client).post("/api/token/", {"username": user.username, "password": PASSWORD, **kwargs}, format="json")

    def enrol(self, user, client=None, first=None, **kwargs):
        client = client or self.client
        first = first or self.login(user, client, **kwargs)
        self.assertEqual(first.status_code, 200, first.data)
        challenge = first.data["challenge"]
        setup = client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json")
        self.assertEqual(setup.status_code, 200, setup.data)
        secret = setup.data["secret"]
        response = client.post("/api/account/mfa/confirm/", {
            "challenge": challenge, "code": pyotp.TOTP(secret).now(),
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("recovery_codes", response.data)
        return secret, response

    def sign_in(self, user, client=None, **kwargs):
        """Complete the real password + TOTP flow for session/permission tests."""
        client = client or self.client
        response = self.login(user, client, **kwargs)
        if response.status_code != 200:
            return response
        if response.data["enrolment_required"]:
            return self.enrol(user, client, first=response)[1]
        user.refresh_from_db()
        secret = decrypt_secret(user.mfa_secret)
        step = max(int(time.time()) // 30, user.mfa_last_step + 1)
        with patch("user.security.time.time", return_value=step * 30):
            result = client.post("/api/account/mfa/verify/", {
                "challenge": response.data["challenge"], "code": pyotp.TOTP(secret).at(step * 30),
            }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        return result

    def legacy_recovery_codes(self, user):
        """Existing codes remain usable without generating any for new enrolments."""
        codes = ["legacy-test-recovery-one", "legacy-test-recovery-two"]
        User.objects.filter(pk=user.pk).update(mfa_recovery_hashes=[make_password(code) for code in codes])
        return codes

    def mail_values(self):
        return {key: value[0] for key, value in parse_qs(mail.outbox[-1].body.split("#", 1)[1].split()[0]).items()}

    def test_signup_requires_email_and_cannot_elevate_itself(self):
        data = {"username": "new", "password1": PASSWORD, "password2": PASSWORD}
        self.assertEqual(self.client.post("/users/", data, format="json").status_code, 400)
        data.update(email="NEW@example.com", groups=[Group.objects.get(name="Editor").pk])
        response = self.client.post("/users/", data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(username="new")
        self.assertFalse(user.email_verified)
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Viewer"])
        self.assertNotIn("password", response.data)
        data.update(username="attacker", email="attacker@example.com", is_superuser=True)
        self.assertEqual(self.client.post("/users/", data, format="json").status_code, 400)

    def test_unverified_user_cannot_use_login_jwt_or_django_session(self):
        user = self.user(verified=False)
        self.assertEqual(self.login(user).status_code, 401)
        token = RefreshToken.for_user(user)
        token["version"] = user.token_version
        session = AccountSession.objects.create(user=user, expires_at=timezone.now() + timedelta(hours=1))
        token["sid"] = str(session.pk)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + str(token.access_token))
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        self.client.credentials()
        self.client.force_login(user)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unverified_login_provides_resend_context_only_after_password_check(self):
        user = self.user(verified=False)
        failure = self.client.post("/api/token/", {"username": user.username, "password": "wrong"}, format="json")
        self.assertEqual(failure.status_code, 401)
        self.assertNotIn("email", failure.data)
        self.assertNotIn("verification_required", failure.data)
        response = self.login(user)
        self.assertEqual(response.status_code, 401)
        self.assertIs(response.data["verification_required"], True)
        self.assertEqual(response.data["email"], user.email)
        self.assertNotIn(settings.AUTH_COOKIE_ACCESS, response.cookies)
        self.assertNotIn(settings.AUTH_COOKIE_REFRESH, response.cookies)
        self.assertFalse(AccountSession.objects.filter(user=user).exists())

    def test_verification_is_expiring_single_use_and_resend_replaces_old_link(self):
        user = self.user(verified=False)
        send_verification(user)
        self.assertEqual(self.mail_values()["email"], user.email)
        first = self.mail_values()["token"]
        self.client.post("/api/account/resend-verification/", {"email": user.email}, format="json")
        latest = self.mail_values()["token"]
        self.assertNotEqual(first, latest)
        self.assertEqual(self.client.post("/api/account/verify-email/", {"token": first}, format="json").status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + settings.EMAIL_VERIFICATION_TIMEOUT + 1):
            self.assertEqual(self.client.post("/api/account/verify-email/", {"token": latest}, format="json").status_code, 400)
        response = self.client.post("/api/account/verify-email/", {"token": latest}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.post("/api/account/verify-email/", {"token": latest}, format="json").status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertEqual(self.login(user).status_code, 200)

    def test_recovery_and_resend_do_not_disclose_account_existence(self):
        user = self.user()
        for path in ("forgot-password", "resend-verification"):
            known = self.client.post(f"/api/account/{path}/", {"email": user.email}, format="json")
            unknown = self.client.post(f"/api/account/{path}/", {"email": "unknown@example.com"}, format="json")
            self.assertEqual(known.status_code, unknown.status_code)
            self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("?token=", mail.outbox[0].body)

    def test_password_reset_validates_password_expires_and_cannot_replay(self):
        user = self.user()
        self.client.post("/api/account/forgot-password/", {"email": user.email}, format="json")
        values = self.mail_values()
        weak = {**values, "password1": "123", "password2": "123"}
        self.assertEqual(self.client.post("/api/account/reset-password/", weak, format="json").status_code, 400)
        payload = {**values, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD}
        with patch.object(default_token_generator, "_now", return_value=default_token_generator._now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 1)):
            self.assertEqual(self.client.post("/api/account/reset-password/", payload, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/account/reset-password/", payload, format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/account/reset-password/", payload, format="json").status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PASSWORD))

    def test_password_reset_revokes_jwts_refresh_and_django_sessions_without_disabling_mfa(self):
        user = self.user(role="Admin", is_staff=True)
        secret, _ = self.enrol(user, admin_session=True)
        stolen = self.client.cookies[settings.AUTH_COOKIE_ACCESS].value
        old_refresh = self.client.cookies[settings.AUTH_COOKIE_REFRESH].value
        old_session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        recovery = APIClient()
        recovery.post("/api/account/forgot-password/", {"email": user.email}, format="json")
        recovery.post("/api/account/reset-password/", {**self.mail_values(), "password1": NEW_PASSWORD, "password2": NEW_PASSWORD}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + stolen)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        recovery.cookies[settings.AUTH_COOKIE_REFRESH] = old_refresh
        self.assertEqual(recovery.post("/api/token/refresh/").status_code, 401)
        session_client = APIClient()
        session_client.cookies[settings.SESSION_COOKIE_NAME] = old_session
        self.assertEqual(session_client.get("/assets/").status_code, 401)
        self.assertNotIn("_auth_user_id", session_client.session)
        user.refresh_from_db()
        self.assertTrue(user.mfa_enabled)
        login = recovery.post("/api/token/", {"username": user.username, "password": NEW_PASSWORD}, format="json")
        self.assertTrue(login.data["mfa_required"])

    def test_required_mfa_enrolment_issues_no_credentials_before_proof(self):
        user = self.user(role="Editor")
        response = self.login(user)
        self.assertTrue(response.data["enrolment_required"])
        self.assertNotIn(settings.AUTH_COOKIE_ACCESS, response.cookies)
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertEqual(AccountSession.objects.count(), 0)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        challenge = response.data["challenge"]
        setup = self.client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json")
        secret = setup.data["secret"]
        self.assertTrue(setup.data["qr_code"].startswith("data:image/svg+xml;base64,"))
        user.refresh_from_db()
        self.assertNotIn(secret, user.mfa_pending_secret)
        self.assertFalse(user.mfa_enabled)
        proof = {"challenge": challenge, "code": pyotp.TOTP(secret).now()}
        result = self.client.post("/api/account/mfa/confirm/", proof, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(self.client.get("/assets/").status_code, 200)
        user.refresh_from_db()
        self.assertNotIn(secret, user.mfa_secret)
        self.assertNotIn("recovery_codes", result.data)
        self.assertEqual(user.mfa_recovery_hashes, [])
        self.assertNotEqual(self.client.post("/api/account/mfa/confirm/", proof, format="json").status_code, 200)

    def test_email_verification_leads_to_qr_setup_and_requires_password_and_totp(self):
        signup = self.client.post("/users/", {"username": "new-viewer", "email": "new-viewer@example.com",
                                               "password1": PASSWORD, "password2": PASSWORD}, format="json")
        self.assertEqual(signup.status_code, 201, signup.data)
        user = User.objects.get(username="new-viewer")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Viewer"])
        self.assertFalse(user.email_verified)
        self.assertFalse(user.mfa_enabled)
        response = self.client.post("/api/account/verify-email/", {"token": self.mail_values()["token"]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["enrolment_required"])
        self.assertTrue(response.data["password_required"])
        self.assertNotIn(settings.AUTH_COOKIE_ACCESS, response.cookies)
        self.assertFalse(AccountSession.objects.exists())
        challenge = response.data["challenge"]
        setup = self.client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json")
        self.assertEqual(setup.status_code, 400)
        self.assertNotIn("secret", setup.data)
        user.refresh_from_db()
        self.assertFalse(user.mfa_pending_secret)
        self.assertEqual(self.client.post("/api/account/mfa/enrol/", {"challenge": challenge, "password": "wrong"}, format="json").status_code, 401)
        setup = self.client.post("/api/account/mfa/enrol/", {"challenge": challenge, "password": PASSWORD}, format="json")
        self.assertEqual(setup.status_code, 200, setup.data)
        self.assertTrue(setup.data["qr_code"].startswith("data:image/svg+xml;base64,"))
        old_challenge = challenge
        challenge = setup.data["challenge"]
        self.assertNotEqual(challenge, old_challenge)
        proof = {"challenge": challenge, "code": pyotp.TOTP(setup.data["secret"]).now()}
        self.assertEqual(self.client.post("/api/account/mfa/confirm/", {**proof, "challenge": old_challenge}, format="json").status_code, 401)
        self.assertEqual(self.client.post("/api/account/mfa/confirm/", {**proof, "code": "invalid"}, format="json").status_code, 401)
        self.assertFalse(AccountSession.objects.exists())
        user.refresh_from_db()
        self.assertFalse(user.mfa_enabled)
        self.assertEqual(user.auth_failures, 1)
        result = self.client.post("/api/account/mfa/confirm/", proof, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertNotIn("recovery_codes", result.data)
        self.assertEqual(self.client.get("/assets/").status_code, 200)
        self.assertNotEqual(self.client.post("/api/account/mfa/confirm/", {**proof, "password": PASSWORD}, format="json").status_code, 200)

    def test_email_reverification_preserves_existing_authenticator_and_requires_password(self):
        user = self.user()
        secret, _ = self.enrol(user)
        self.client.post("/api/logout/")
        user.refresh_from_db()
        user.email_verified = False
        user.save(update_fields=["email_verified"])
        send_verification(user)
        response = self.client.post("/api/account/verify-email/", {"token": self.mail_values()["token"]}, format="json")
        self.assertFalse(response.data["enrolment_required"])
        self.assertTrue(response.data["password_required"])
        challenge = response.data["challenge"]
        self.assertEqual(self.client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json").status_code, 400)
        with patch("user.security.time.time", return_value=time.time() + 30):
            proof = {"challenge": challenge, "code": pyotp.TOTP(secret).at(time.time())}
            self.assertEqual(self.client.post("/api/account/mfa/verify/", proof, format="json").status_code, 400)
            result = self.client.post("/api/account/mfa/verify/", {**proof, "password": PASSWORD}, format="json")
        self.assertEqual(result.status_code, 200, result.data)

    def test_viewer_password_only_jwt_session_refresh_and_signed_media_are_rejected(self):
        user = self.user()
        token = RefreshToken.for_user(user)
        token["version"] = user.token_version
        record = AccountSession.objects.create(user=user, expires_at=timezone.now() + timedelta(hours=1), mfa_verified=False)
        token["sid"] = str(record.pk)
        token["mfa"] = False
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = str(token.access_token)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(token)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        self.assertEqual(self.client.post("/api/token/refresh/").status_code, 401)
        self.client.cookies.clear()
        self.client.force_login(user)
        session = self.client.session
        session["account_session"] = str(record.pk)
        session.save()
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        asset = Asset.objects.create(name="test", description="test", uploaded_by=user.username,
                                     file_type="png", file_size=1, url="uploads/not-written.png")
        media_token = signing.dumps({"asset": str(asset.pk), "user": str(user.pk),
                                     "version": user.token_version, "auth": user.get_session_auth_hash(),
                                     "sid": str(record.pk)}, salt="asset-media")
        self.assertEqual(APIClient().get(reverse("asset-file", args=[asset.pk]), {"token": media_token}).status_code, 401)

    def test_totp_and_recovery_codes_are_single_use(self):
        user = self.user(role="Editor")
        secret, _ = self.enrol(user)
        codes = self.legacy_recovery_codes(user)
        self.client.post("/api/logout/")
        challenge = self.login(user).data["challenge"]
        response = self.client.post("/api/account/mfa/verify/", {"challenge": challenge, "code": pyotp.TOTP(secret).now()}, format="json")
        self.assertNotEqual(response.status_code, 200)
        response = self.client.post("/api/account/mfa/verify/", {"challenge": challenge, "code": codes[0]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.client.post("/api/logout/")
        challenge = self.login(user).data["challenge"]
        self.assertNotEqual(self.client.post("/api/account/mfa/verify/", {"challenge": challenge, "code": codes[0]}, format="json").status_code, 200)

    def test_mfa_challenge_expiry_and_old_unbound_tokens_are_rejected(self):
        user = self.user(role="Editor")
        challenge = self.login(user).data["challenge"]
        with patch("django.core.signing.time.time", return_value=time.time() + settings.MFA_CHALLENGE_TIMEOUT + 1):
            self.assertNotEqual(self.client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json").status_code, 200)
        legacy = RefreshToken.for_user(user)
        legacy["version"] = user.token_version
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + str(legacy.access_token))
        self.assertEqual(self.client.get("/assets/").status_code, 401)

    def test_database_lockout_applies_across_clients_and_cache_clears(self):
        user = self.user()
        for _ in range(settings.AUTH_MAX_FAILURES):
            response = self.client.post("/api/token/", {"username": user.username, "password": "wrong"}, format="json")
            self.assertNotEqual(response.status_code, 200)
            cache.clear()
        user.refresh_from_db()
        self.assertIsNotNone(user.auth_locked_until)
        self.assertNotEqual(self.login(user, APIClient()).status_code, 200)
        User.objects.filter(pk=user.pk).update(auth_locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.login(user, APIClient()).status_code, 200)

    def test_mfa_failures_cannot_be_reset_by_requesting_a_new_challenge(self):
        user = self.user(role="Editor")
        secret, _ = self.enrol(user)
        self.client.post("/api/logout/")
        for _ in range(settings.AUTH_MAX_FAILURES):
            cache.clear()
            challenge = self.login(user).data["challenge"]
            response = self.client.post("/api/account/mfa/verify/", {"challenge": challenge, "code": "invalid"}, format="json")
            self.assertNotEqual(response.status_code, 200)
        cache.clear()
        self.assertNotEqual(self.login(user).status_code, 200)

    def test_authentication_scopes_return_429_and_ignore_forged_forwarding(self):
        for _ in range(10):
            self.client.post("/api/token/", {"username": "missing", "password": PASSWORD}, format="json")
        response = self.client.post("/api/token/", {"username": "missing", "password": PASSWORD}, format="json", HTTP_X_FORWARDED_FOR="192.0.2.99")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        for endpoint in ("forgot-password", "resend-verification"):
            cache.clear()
            for _ in range(5):
                self.client.post(f"/api/account/{endpoint}/", {"email": "missing@example.com"}, format="json")
            self.assertEqual(self.client.post(f"/api/account/{endpoint}/", {"email": "missing@example.com"}, format="json").status_code, 429)

    def test_cookies_are_httponly_secure_and_no_tokens_are_returned(self):
        result = self.sign_in(self.user())
        for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            self.assertTrue(result.cookies[name]["httponly"])
            self.assertTrue(result.cookies[name]["secure"])
            self.assertEqual(result.cookies[name]["samesite"], "Lax")
        self.assertEqual(result.cookies[settings.AUTH_COOKIE_REFRESH]["path"], "/api/")
        self.assertNotIn("access", result.data)
        self.assertNotIn("refresh", result.data)
        self.assertEqual(result["Cache-Control"], "no-store")

    def test_cookie_csrf_protects_login_refresh_logout_and_unsafe_api_requests(self):
        user = self.user()
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(self.login(user, client).status_code, 403)
        csrf = client.get("/api/account/csrf/").data["csrfToken"]
        result = client.post("/api/token/", {"username": user.username, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code, 200, result.data)
        challenge = result.data["challenge"]
        setup = client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(client.post("/api/account/mfa/confirm/", {"challenge": challenge, "code": pyotp.TOTP(setup.data["secret"]).now()}, format="json").status_code, 403)
        result = client.post("/api/account/mfa/confirm/", {"challenge": challenge, "code": pyotp.TOTP(setup.data["secret"]).now()}, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code, 200, result.data)
        csrf = result.data["csrfToken"]
        for path in ("/api/token/refresh/", "/api/logout/", "/api/logout-all/"):
            self.assertEqual(client.post(path).status_code, 403)
        self.assertEqual(client.patch(f"/users/{user.pk}/", {"first_name": "changed"}, format="json").status_code, 403)
        self.assertEqual(client.patch(f"/users/{user.pk}/", {"first_name": "changed"}, format="json", HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.assertEqual(client.post("/api/token/refresh/", HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.assertEqual(client.post("/api/logout/", HTTP_X_CSRFTOKEN=csrf).status_code, 204)

    def test_refresh_rotation_replay_and_absolute_expiry(self):
        user = self.user()
        self.sign_in(user)
        old = self.client.cookies[settings.AUTH_COOKIE_REFRESH].value
        sid = RefreshToken(old)["sid"]
        session = AccountSession.objects.get(pk=sid)
        self.assertEqual(self.client.post("/api/token/refresh/").status_code, 200)
        new = RefreshToken(self.client.cookies[settings.AUTH_COOKIE_REFRESH].value)
        self.assertLessEqual(new["exp"], int(session.expires_at.timestamp()))
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = old
        self.assertEqual(self.client.post("/api/token/refresh/").status_code, 401)

    def test_current_logout_revokes_only_that_login_and_all_logout_revokes_other_devices(self):
        user = self.user()
        other = APIClient()
        self.sign_in(user)
        self.sign_in(user, other)
        stolen = self.client.cookies[settings.AUTH_COOKIE_ACCESS].value
        self.assertEqual(self.client.post("/api/logout/").status_code, 204)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + stolen)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        self.assertEqual(other.get("/assets/").status_code, 200)
        self.client.credentials()
        self.sign_in(user)
        self.assertEqual(self.client.post("/api/logout-all/").status_code, 204)
        self.assertEqual(other.get("/assets/").status_code, 401)

    def test_disabled_account_and_role_changes_revoke_existing_credentials(self):
        user = self.user()
        self.sign_in(user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        user.is_active = True
        user.save(update_fields=["is_active"])
        self.sign_in(user)
        user.groups.add(Group.objects.get(name="Editor"))
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        login = self.login(user)
        self.assertTrue(login.data["mfa_required"])

    def test_viewer_editor_admin_and_staff_are_distinct(self):
        viewer = self.user()
        self.sign_in(viewer)
        self.assertEqual(self.client.get("/assets/").status_code, 200)
        self.assertEqual(self.client.post("/tags/", {"title": "not allowed"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/users/").status_code, 403)
        cache.clear()
        editor = self.user("editor", role="Editor")
        self.enrol(editor)
        self.assertEqual(self.client.post("/tags/", {"title": "allowed"}, format="json").status_code, 201)
        self.assertEqual(self.client.get("/users/").status_code, 403)
        cache.clear()
        admin = self.user("appadmin", role="Admin")
        self.enrol(admin)
        self.assertEqual(self.client.get("/users/").status_code, 200)
        self.assertEqual(self.client.patch(f"/users/{viewer.pk}/role/", {"role": "Editor"}, format="json").status_code, 200)
        viewer.refresh_from_db()
        self.assertFalse(viewer.is_staff)
        self.assertFalse(viewer.is_superuser)
        cache.clear()
        staff = self.user("staff", is_staff=True)
        self.enrol(staff, admin_session=True)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertEqual(self.client.get("/admin/user/user/").status_code, 403)
        self.assertEqual(self.client.get("/users/").status_code, 403)
        self.assertEqual(self.client.post("/tags/", {"title": "staff only"}, format="json").status_code, 403)

    def test_profile_idor_and_privilege_manipulation_are_denied(self):
        user, other = self.user(), self.user("other")
        self.sign_in(user)
        self.assertEqual(self.client.get(f"/users/{other.pk}/").status_code, 403)
        self.assertEqual(self.client.patch(f"/users/{other.pk}/", {"first_name": "tampered"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"/users/{user.pk}/role/", {"role": "Admin"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"/users/{user.pk}/", {"is_staff": True}, format="json").status_code, 400)
        self.client.patch(f"/users/{user.pk}/", {"groups": [Group.objects.get(name="Admin").pk]}, format="json")
        user.refresh_from_db()
        self.assertFalse(user.groups.filter(name="Admin").exists())

    def test_alternate_login_surfaces_cannot_skip_mfa(self):
        user = self.user(is_staff=True)
        for path in ("/admin/login/", "/api-auth/login/", "/api-authlogin/"):
            result = self.client.post(path, {"username": user.username, "password": PASSWORD})
            self.assertEqual(result.status_code, 302)
            self.assertIn("/login?admin=1", result.url)
            self.assertNotIn("_auth_user_id", self.client.session)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_django_admin_logout_revokes_the_corresponding_jwt(self):
        user = self.user(is_staff=True)
        self.enrol(user, admin_session=True)
        stolen = self.client.cookies[settings.AUTH_COOKIE_ACCESS].value
        self.assertEqual(self.client.post("/admin/logout/").status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + stolen)
        self.assertEqual(self.client.get("/assets/").status_code, 401)

    def test_all_roles_require_mfa_and_cannot_remove_it(self):
        for role in ("Viewer", "Editor", "Admin"):
            with self.subTest(role=role):
                cache.clear()
                self.client = APIClient()
                user = self.user(role.lower(), role=role)
                first = self.login(user)
                self.assertTrue(first.data["mfa_required"])
                self.assertTrue(first.data["enrolment_required"])
                self.assertNotIn(settings.AUTH_COOKIE_ACCESS, first.cookies)
                self.assertEqual(self.client.get("/assets/").status_code, 401)
                self.enrol(user, first=first)
                self.assertEqual(self.client.post("/api/account/mfa/remove/", {"password": PASSWORD, "code": "123456"}, format="json").status_code, 400)
                user.refresh_from_db()
                self.assertTrue(user.mfa_enabled)

    def test_required_mfa_recovery_can_replace_authenticator_but_not_remove_it(self):
        user = self.user(role="Editor")
        self.enrol(user)
        codes = self.legacy_recovery_codes(user)
        self.assertEqual(self.client.post("/api/account/mfa/remove/", {"password": PASSWORD, "code": codes[0]}, format="json").status_code, 400)
        setup = self.client.post("/api/account/mfa/replace/", {"password": PASSWORD, "code": codes[0]}, format="json")
        self.assertEqual(setup.status_code, 200, setup.data)
        response = self.client.post("/api/account/mfa/confirm/", {"challenge": setup.data["challenge"], "code": pyotp.TOTP(setup.data["secret"]).now()}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("recovery_codes", response.data)
        user.refresh_from_db()
        self.assertEqual(user.mfa_recovery_hashes, [])

    def test_email_change_requires_password_reverification_and_revokes_old_credentials(self):
        user = self.user()
        self.sign_in(user)
        path = f"/users/{user.pk}/"
        self.assertEqual(self.client.patch(path, {"email": "changed@example.com"}, format="json").status_code, 400)
        response = self.client.patch(path, {"email": "changed@example.com", "current_password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        user.refresh_from_db()
        self.assertFalse(user.email_verified)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        self.assertEqual(len(mail.outbox), 1)

    def test_signed_media_is_denied_after_logout_and_for_unverified_accounts(self):
        user = self.user()
        self.sign_in(user)
        asset = Asset.objects.create(name="test", description="test", uploaded_by=user.username,
                                     file_type="png", file_size=1, url="uploads/not-written.png")
        response = self.client.get(f"/assets/{asset.pk}/")
        url = response.data["url"]
        path = url.split("http://testserver", 1)[-1]
        self.client.post("/api/logout/")
        self.assertEqual(self.client.get(path).status_code, 401)

    @override_settings(ACCOUNT_ALLOWED_EMAIL_DOMAINS=["university.example"])
    def test_optional_admission_domain_setting_is_explicit(self):
        response = self.client.post("/users/", {"username": "new", "email": "new@example.com",
                                               "password1": PASSWORD, "password2": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_missing_encryption_key_fails_closed(self):
        user = self.user(role="Editor")
        challenge = self.login(user).data["challenge"]
        with override_settings(MFA_ENCRYPTION_KEY=""):
            response = self.client.post("/api/account/mfa/enrol/", {"challenge": challenge}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(AccountSession.objects.count(), 0)

    def test_security_logs_do_not_contain_credentials_or_email_links(self):
        user = self.user()
        with self.assertLogs("dam.audit", level="INFO") as captured:
            self.sign_in(user)
            self.client.post("/api/account/forgot-password/", {"email": user.email}, format="json")
        output = "\n".join(captured.output)
        self.assertNotIn(PASSWORD, output)
        self.assertNotIn(user.email, output)
        self.assertNotIn(self.mail_values()["token"], output)

    @override_settings(MFA_REQUIRED_ROLES=[])
    def test_no_role_can_disable_mfa_through_legacy_policy_setting(self):
        for role in ("Viewer", "Editor", "Admin"):
            with self.subTest(role=role):
                result = self.login(self.user(role.lower(), role=role))
                self.assertTrue(result.data["mfa_required"])
                self.assertNotIn(settings.AUTH_COOKIE_ACCESS, result.cookies)

    def test_expired_login_record_blocks_access_refresh_and_django_admin(self):
        user = self.user(is_staff=True)
        self.enrol(user, admin_session=True)
        AccountSession.objects.filter(user=user).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        self.assertEqual(self.client.post("/api/token/refresh/").status_code, 401)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_switching_accounts_clears_the_previous_django_admin_identity(self):
        staff = self.user(is_staff=True)
        self.enrol(staff, admin_session=True)
        self.assertIn("_auth_user_id", self.client.session)
        viewer = self.user("second")
        result = self.sign_in(viewer)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertEqual(self.client.get("/api/account/me/").data["user"]["id"], str(viewer.pk))

    def test_logout_without_refresh_cookie_still_revokes_access_and_old_refresh_has_no_authority(self):
        user = self.user()
        self.sign_in(user)
        stolen_refresh = self.client.cookies[settings.AUTH_COOKIE_REFRESH].value
        stolen_access = self.client.cookies[settings.AUTH_COOKIE_ACCESS].value
        del self.client.cookies[settings.AUTH_COOKIE_REFRESH]
        self.assertEqual(self.client.post("/api/logout/").status_code, 204)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + stolen_access)
        self.assertEqual(self.client.get("/assets/").status_code, 401)
        other = APIClient()
        self.sign_in(user, other)
        attacker = APIClient()
        attacker.cookies[settings.AUTH_COOKIE_REFRESH] = stolen_refresh
        attacker.post("/api/logout-all/")
        self.assertEqual(other.get("/assets/").status_code, 200)
        self.assertEqual(attacker.post("/api/token/refresh/").status_code, 401)

    def test_browsable_api_renders_and_its_logout_revokes_cookies(self):
        user = self.user()
        self.sign_in(user)
        response = self.client.get("/assets/", HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/api-auth/logout/")
        access = self.client.cookies[settings.AUTH_COOKIE_ACCESS].value
        self.assertEqual(self.client.post("/api-auth/logout/").status_code, 302)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        self.assertEqual(self.client.get("/assets/").status_code, 401)

    def test_csrf_rejects_untrusted_origin_even_with_matching_cookie_and_token(self):
        user = self.user()
        client = APIClient(enforce_csrf_checks=True)
        csrf = client.get("/api/account/csrf/").data["csrfToken"]
        result = client.post("/api/token/", {"username": user.username, "password": PASSWORD}, format="json",
                             HTTP_X_CSRFTOKEN=csrf, HTTP_ORIGIN="https://attacker.example")
        self.assertEqual(result.status_code, 403)
        self.assertNotIn(settings.AUTH_COOKIE_ACCESS, result.cookies)

    def test_delivery_failures_keep_recovery_responses_generic_and_logs_token_free(self):
        user = self.user()
        with patch("user.security.send_mail", side_effect=RuntimeError("sensitive SMTP details")):
            with self.assertLogs("dam.audit", level="INFO") as logs:
                known = self.client.post("/api/account/forgot-password/", {"email": user.email}, format="json")
        unknown = self.client.post("/api/account/forgot-password/", {"email": "missing@example.com"}, format="json")
        self.assertEqual(known.data, unknown.data)
        self.assertNotIn("sensitive SMTP details", "\n".join(logs.output))

    def test_application_admin_can_disable_account_but_cannot_assign_django_staff(self):
        admin = self.user("admin", role="Admin")
        self.enrol(admin)
        viewer = self.user()
        other = APIClient()
        self.sign_in(viewer, other)
        response = self.client.patch(f"/users/{viewer.pk}/status/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(other.get("/assets/").status_code, 401)
        self.assertEqual(self.client.patch(f"/users/{viewer.pk}/", {"is_staff": True}, format="json").status_code, 400)

    def test_last_recovery_code_can_recover_authenticator_with_recent_mfa_and_password(self):
        user = self.user(role="Editor")
        self.enrol(user)
        codes = self.legacy_recovery_codes(user)
        self.client.post("/api/logout/")
        challenge = self.login(user).data["challenge"]
        result = self.client.post("/api/account/mfa/verify/", {"challenge": challenge, "code": codes[-1]}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        setup = self.client.post("/api/account/mfa/replace/", {"password": PASSWORD}, format="json")
        self.assertEqual(setup.status_code, 200, setup.data)
        AccountSession.objects.filter(user=user, revoked=False).update(created_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(self.client.post("/api/account/mfa/replace/", {"password": PASSWORD}, format="json").status_code, 401)

    def test_native_admin_password_change_does_not_keep_a_revoked_session_alive(self):
        user = self.user(is_staff=True, is_superuser=True)
        self.enrol(user, admin_session=True)
        response = self.client.post(f"/admin/user/user/{user.pk}/password/", {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PASSWORD))
        del self.client.cookies[settings.AUTH_COOKIE_ACCESS]
        del self.client.cookies[settings.AUTH_COOKIE_REFRESH]
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_pending_seed_is_bound_to_one_password_verified_challenge(self):
        user = self.user()
        first = self.login(user).data["challenge"]
        setup = self.client.post("/api/account/mfa/enrol/", {"challenge": first}, format="json").data
        retry = self.client.post("/api/account/mfa/enrol/", {"challenge": first}, format="json").data
        self.assertEqual(setup["secret"], retry["secret"])
        second = self.login(user).data["challenge"]
        self.assertEqual(self.client.post("/api/account/mfa/enrol/", {"challenge": first}, format="json").status_code, 401)
        next_setup = self.client.post("/api/account/mfa/enrol/", {"challenge": second}, format="json").data
        self.assertNotEqual(setup["secret"], next_setup["secret"])
        result = self.client.post("/api/account/mfa/confirm/", {"challenge": second,
            "code": pyotp.TOTP(next_setup["secret"]).now()}, format="json")
        self.assertEqual(result.status_code, 200, result.data)

    def test_profile_password_failures_commit_and_enforce_lockout(self):
        user = self.user()
        self.sign_in(user)
        url = f"/users/{user.pk}/"
        payload = {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD, "current_password": "wrong"}
        for count in range(settings.AUTH_MAX_FAILURES):
            self.assertEqual(self.client.patch(url, payload, format="json").status_code, 400)
            user.refresh_from_db()
            self.assertEqual(user.auth_failures, count + 1)
        self.assertGreater(user.auth_locked_until, timezone.now())
        payload["current_password"] = PASSWORD
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))
        User.objects.filter(pk=user.pk).update(auth_locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.auth_failures, 0)
        self.assertIsNone(user.auth_locked_until)
        self.assertEqual(self.client.get("/api/account/me/").status_code, 401)

    def test_profile_username_is_immutable_but_names_remain_editable(self):
        user = self.user()
        self.sign_in(user)
        for method in (self.client.patch, self.client.put):
            result = method(f"/users/{user.pk}/", {"username": "renamed", "first_name": "Changed"}, format="json")
            self.assertEqual(result.status_code, 400, result.data)
        user.refresh_from_db()
        self.assertEqual(user.username, "viewer")
        self.assertEqual(user.first_name, "")
        self.assertEqual(self.client.patch(f"/users/{user.pk}/", {"username": user.username, "first_name": "Changed"}, format="json").status_code, 200)

    def test_spaced_passwords_are_preserved_in_all_account_workflows(self):
        password = "  " + PASSWORD + "  "
        result = self.client.post("/users/", {"username": "spaced", "email": "spaced@example.com",
            "password1": password, "password2": password}, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        user = User.objects.get(username="spaced")
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(password.strip()))
        verified = self.client.post("/api/account/verify-email/", {"token": self.mail_values()["token"]}, format="json")
        setup = self.client.post("/api/account/mfa/enrol/", {"challenge": verified.data["challenge"], "password": password}, format="json")
        self.assertEqual(setup.status_code, 200, setup.data)
        result = self.client.post("/api/account/mfa/confirm/", {"challenge": setup.data["challenge"],
            "code": pyotp.TOTP(setup.data["secret"]).now()}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        changed = "  " + NEW_PASSWORD + "  "
        result = self.client.patch(f"/users/{user.pk}/", {"current_password": password,
            "password1": changed, "password2": changed}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        user.refresh_from_db()
        self.assertTrue(user.check_password(changed))
        self.client.post("/api/account/forgot-password/", {"email": user.email}, format="json")
        result = self.client.post("/api/account/reset-password/", {**self.mail_values(),
            "password1": password, "password2": password}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(self.client.post("/api/token/", {"username": user.username, "password": password}, format="json").status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password(password))

    def test_sensitive_profile_throttle(self):
        user = self.user()
        self.sign_in(user)
        for _ in range(10):
            self.assertEqual(self.client.patch(f"/users/{user.pk}/", {"first_name": "Name"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(f"/users/{user.pk}/", {"first_name": "Name"}, format="json").status_code, 429)

    def test_admin_assisted_recovery_requires_proof_and_revokes_target_credentials(self):
        target = self.user()
        victim = APIClient()
        self.sign_in(target, victim)
        target.refresh_from_db()
        old_secret = target.mfa_secret
        old_challenge = self.login(target, victim).data["challenge"]
        operator = self.user("operator", role="Admin")
        self.sign_in(operator)
        url = f"/users/{target.pk}/recover-mfa/"
        approval = {"identity_verified": True, "current_password": PASSWORD}
        self.assertEqual(self.client.post(url, {"current_password": PASSWORD}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {**approval, "current_password": "wrong"}, format="json").status_code, 400)
        operator.refresh_from_db()
        self.assertEqual(operator.auth_failures, 1)
        with self.assertLogs("dam.audit", level="INFO") as logs:
            result = self.client.post(url, approval, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(any("mfa_recovery_approved" in line and str(operator.pk) in line and str(target.pk) in line for line in logs.output))
        self.assertNotIn(PASSWORD, " ".join(logs.output))
        target.refresh_from_db()
        self.assertFalse(target.mfa_enabled)
        self.assertFalse(target.mfa_pending_secret)
        self.assertEqual(target.mfa_recovery_hashes, [])
        self.assertTrue(target.email_verified)
        self.assertFalse(target.account_sessions.filter(revoked=False).exists())
        self.assertEqual(victim.get("/assets/").status_code, 401)
        self.assertEqual(victim.post("/api/token/refresh/").status_code, 401)
        self.assertEqual(victim.post("/api/account/mfa/verify/", {"challenge": old_challenge, "code": "123456"}, format="json").status_code, 401)
        setup = self.login(target, victim)
        self.assertTrue(setup.data["enrolment_required"])
        self.enrol(target, victim, first=setup)
        target.refresh_from_db()
        self.assertNotEqual(old_secret, target.mfa_secret)

    def test_recovery_is_admin_only_and_requires_recent_mfa(self):
        target = self.user("target")
        for name, role in (("viewer", "Viewer"), ("editor", "Editor"), ("operator", "Admin")):
            cache.clear()
            actor = self.user(name, role=role)
            self.sign_in(actor)
            if role == "Admin":
                AccountSession.objects.filter(user=actor).update(created_at=timezone.now() - timedelta(minutes=6))
            result = self.client.post(f"/users/{target.pk}/recover-mfa/",
                {"identity_verified": True, "current_password": PASSWORD}, format="json")
            self.assertEqual(result.status_code, 400 if role == "Admin" else 403, result.data)

    def test_recovery_rejects_anonymous_self_staff_and_missing_csrf(self):
        operator = self.user("operator", role="Admin")
        target = self.user("staff", is_staff=True)
        target.refresh_from_db()
        original_version = target.token_version
        payload = {"identity_verified": True, "current_password": PASSWORD}
        url = f"/users/{target.pk}/recover-mfa/"
        self.assertEqual(APIClient().post(url, payload, format="json").status_code, 401)
        self.sign_in(operator)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/users/{operator.pk}/recover-mfa/", payload, format="json").status_code, 400)
        strict = APIClient(enforce_csrf_checks=True)
        strict.cookies = self.client.cookies
        self.assertEqual(strict.post(url, payload, format="json").status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.token_version, original_version)
