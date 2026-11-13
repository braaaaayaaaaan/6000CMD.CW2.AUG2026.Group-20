import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import pyotp
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from asset.models import Asset, Tags
from asset.test_security import image_bytes
from .auditing import RULES, current_request, record_event
from .models import AuditEvent, SecurityAlert, User
from .security import decrypt_secret
from . import test_security as accounts

PASSWORD = accounts.PASSWORD


class MonitoringTests(TestCase):
    user = accounts.AccountSecurityTests.user
    login = accounts.AccountSecurityTests.login
    enrol = accounts.AccountSecurityTests.enrol
    sign_in = accounts.AccountSecurityTests.sign_in

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = override_settings(MEDIA_ROOT=temporary.name)
        override.enable()
        self.addCleanup(override.disable)

    def as_admin(self):
        user = self.user("admin", role="Admin")
        self.sign_in(user)
        return user

    def upload(self):
        response = self.client.post("/assets/", {"name": "Example", "description": "Audit fixture",
            "url": SimpleUploadedFile("image.png", image_bytes())}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def download(self, path, **headers):
        response = self.client.get(path, **headers)
        if response.streaming:
            b"".join(response.streaming_content)
            response.close()
        return response

    def test_event_creation_and_metadata_allowlist(self):
        user = self.user()
        event = record_event("asset_uploaded", user, resource_id="asset-id", metadata={
            "version_no": 2, "password": PASSWORD, "authorization": "Bearer secret", "token": "secret",
            "url": "https://example.com/?token=secret", "nested": {"mfa_secret": "secret"},
        })
        self.assertEqual(event.metadata, {"version_no": 2})
        self.assertEqual((event.actor, event.category, event.outcome, event.severity), (user, "asset", "success", "info"))

    def test_login_failure_identifies_unknown_account_and_keeps_safe_context(self):
        response = self.client.post("/api/token/", {"username": "unknown", "password": PASSWORD,
            "token": "request-token", "code": "123456"}, format="json", REMOTE_ADDR="192.0.2.5",
            HTTP_X_FORWARDED_FOR="198.51.100.4", HTTP_USER_AGENT="Audit Browser")
        self.assertEqual(response.status_code, 401)
        event = AuditEvent.objects.get(event_type="login_failed")
        self.assertIsNone(event.actor)
        self.assertEqual(event.account_identifier, "unknown")
        self.assertEqual(event.ip_address, "192.0.2.5")
        self.assertEqual(event.user_agent, "Audit Browser")
        stored = json.dumps(list(AuditEvent.objects.values()), default=str)
        for secret in (PASSWORD, "request-token", "123456"):
            self.assertNotIn(secret, stored)

    def test_password_half_is_not_login_success_and_mfa_success_is_logged_once(self):
        user = self.user()
        response = self.login(user)
        self.assertNotIn("login_succeeded", AuditEvent.objects.values_list("event_type", flat=True))
        self.enrol(user, first=response)
        self.assertEqual(AuditEvent.objects.filter(event_type="login_succeeded", actor=user).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type="mfa_verification_succeeded", actor=user).count(), 1)
        self.assertEqual(self.client.post("/api/logout/").status_code, 204)
        self.assertEqual(AuditEvent.objects.filter(event_type="logout", actor=user).count(), 1)

    def test_mfa_failure_including_invalid_challenge(self):
        user = self.user()
        self.enrol(user)
        response = self.login(user)
        self.assertEqual(self.client.post("/api/account/mfa/verify/", {
            "challenge": response.data["challenge"], "code": "not-a-factor"}, format="json").status_code, 401)
        event = AuditEvent.objects.get(event_type="mfa_verification_failed")
        self.assertEqual(event.actor, user)
        self.assertEqual(self.client.post("/api/account/mfa/verify/", {
            "challenge": "not-a-challenge", "code": "secret-factor"}, format="json").status_code, 401)
        self.assertEqual(AuditEvent.objects.filter(event_type="mfa_verification_failed", actor=None).count(), 1)
        stored = json.dumps(list(AuditEvent.objects.values()), default=str)
        self.assertNotIn("not-a-factor", stored)
        self.assertNotIn("not-a-challenge", stored)
        user.refresh_from_db()
        self.assertNotIn(user.mfa_secret, stored)
        self.assertNotIn(decrypt_secret(user.mfa_secret), stored)

    def test_upload_replace_delete_and_tag_events(self):
        user = self.as_admin()
        asset = self.upload()
        path = f"/assets/{asset['id']}/"
        self.assertEqual(self.client.patch(path, {"url": SimpleUploadedFile("new.png", image_bytes())}, format="multipart").status_code, 200)
        self.assertEqual(self.client.delete(path).status_code, 204)
        tag = self.client.post("/tags/", {"title": "New"}, format="json")
        self.assertEqual(tag.status_code, 201)
        tag_path = f"/tags/{tag.data['id']}/"
        self.assertEqual(self.client.patch(tag_path, {"title": "Updated"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(tag_path).status_code, 204)
        for name in ("asset_uploaded", "asset_replaced", "asset_deleted", "tag_created", "tag_updated", "tag_deleted"):
            self.assertEqual(AuditEvent.objects.filter(event_type=name, actor=user).count(), 1, name)

    def test_download_only_after_authorised_file_response_and_not_url_issue_head_or_preview(self):
        user = self.as_admin()
        asset = self.upload()
        path = asset["url"].replace("http://testserver", "")
        self.client.get(f"/assets/{asset['id']}/media-url/")
        response = self.client.head(path + "&download=1")
        response.close()
        self.download(path)
        self.assertEqual(AuditEvent.objects.filter(event_type="asset_downloaded").count(), 0)
        self.assertEqual(AuditEvent.objects.filter(event_type="asset_previewed").count(), 1)
        self.assertEqual(self.download(path + "&download=1").status_code, 200)
        self.assertEqual(self.download(path + "&download=1", HTTP_RANGE="bytes=0-7").status_code, 206)
        self.assertEqual(self.download(path + "&download=1", HTTP_RANGE="bytes=99999-").status_code, 416)
        events = AuditEvent.objects.filter(event_type="asset_downloaded", actor=user)
        self.assertEqual(events.count(), 2)
        self.assertEqual(set(events.values_list("resource_id", flat=True)), {asset["id"]})
        self.assertNotIn("token=", json.dumps(list(AuditEvent.objects.values()), default=str))
        Asset.objects.get(pk=asset["id"]).url.delete(save=False)
        self.assertEqual(self.download(path + "&download=1").status_code, 404)
        self.assertEqual(events.count(), 2)

    def test_denial_records_meaningful_authenticated_operation_without_body_or_query(self):
        user = self.user()
        self.sign_in(user)
        response = self.client.post("/tags/?token=never-store", {"title": "Forbidden", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 403)
        event = AuditEvent.objects.get(event_type="access_denied")
        self.assertEqual(event.actor, user)
        self.assertEqual(event.resource_id, "tags-list")
        self.assertEqual(event.metadata, {"method": "POST"})
        before = AuditEvent.objects.count()
        self.client.get("/missing-frontend-route/")
        self.client.get("/assets/")
        self.client.get("/static/missing.js")
        self.assertEqual(AuditEvent.objects.count(), before)
        self.assertIsNone(current_request.get())

    def test_account_creation_role_status_and_changes(self):
        response = self.client.post("/users/", {"username": "new", "email": "new@example.com",
            "password1": PASSWORD, "password2": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(AuditEvent.objects.filter(event_type="account_created", resource_id=response.data["id"]).count(), 1)
        actor = self.as_admin()
        target = self.user("target")
        self.assertEqual(self.client.patch(f"/users/{target.pk}/role/", {"role": "Editor"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(f"/users/{target.pk}/role/", {"role": "Editor"}, format="json").status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(event_type="role_changed", actor=actor, resource_id=str(target.pk)).count(), 1)
        self.assertEqual(AuditEvent.objects.get(event_type="role_changed").metadata, {"previous_role": "Viewer", "role": "Editor"})
        self.assertEqual(self.client.patch(f"/users/{target.pk}/status/", {"is_active": False}, format="json").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(event_type="account_disabled", actor=actor).exists())

    def test_django_admin_permission_change_and_bulk_deletion_bridge(self):
        actor = self.as_admin()
        group = Group.objects.get(name="Viewer")
        group.permissions.add(Permission.objects.first())
        LogEntry.objects.log_actions(user_id=actor.pk, queryset=[group], action_flag=CHANGE,
            change_message=[{"changed": {"fields": ["permissions"], "password": PASSWORD}}])
        self.assertEqual(AuditEvent.objects.filter(event_type="permission_changed", resource_id=str(group.pk)).count(), 1)
        tags = [Tags.objects.create(title=name) for name in ("One", "Two")]
        from django.test import RequestFactory
        request = RequestFactory().post("/admin/asset/tags/")
        request.user = actor
        admin.site._registry[Tags].log_deletions(request, Tags.objects.filter(pk__in=[tag.pk for tag in tags]))
        self.assertEqual(AuditEvent.objects.filter(event_type="tag_deleted").count(), 2)
        self.assertNotIn(PASSWORD, json.dumps(list(AuditEvent.objects.values()), default=str))

    def test_permission_changes_through_real_django_admin(self):
        actor = self.user("operator", role="Admin", is_staff=True, is_superuser=True)
        self.sign_in(actor, admin_session=True)
        group = Group.objects.get(name="Editor")
        permission = Permission.objects.first()
        response = self.client.post(f"/admin/auth/group/{group.pk}/change/", {
            "name": group.name, "permissions": [permission.pk], "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(group.permissions.filter(pk=permission.pk).exists())
        event = AuditEvent.objects.get(event_type="permission_changed")
        self.assertEqual((event.actor, event.resource_id), (actor, str(group.pk)))

    def test_authentication_material_is_excluded_from_audits_and_alerts(self):
        user = self.as_admin()
        user.refresh_from_db()
        from django.conf import settings
        credentials = [PASSWORD, user.password, user.mfa_secret, decrypt_secret(user.mfa_secret),
                       self.client.cookies[settings.AUTH_COOKIE_ACCESS].value,
                       self.client.cookies[settings.AUTH_COOKIE_REFRESH].value]
        for _ in range(5):
            record_event("login_failed", account_identifier="unknown", metadata={
                "password": PASSWORD, "csrf_token": "private-csrf-value", "recovery_codes": ["private-recovery-value"],
                "Authorization": "Bearer private-header-value", "session_cookie": "private-session-value"})
        stored = json.dumps({"events": list(AuditEvent.objects.values()), "alerts": list(SecurityAlert.objects.values())}, default=str)
        for secret in credentials + ["private-csrf-value", "private-recovery-value", "private-header-value", "private-session-value"]:
            self.assertNotIn(secret, stored)

    def test_denied_signed_link_does_not_create_successful_download(self):
        self.as_admin()
        asset = self.upload()
        path = asset["url"].replace("http://testserver", "")
        other = self.user("other")
        self.client = APIClient()
        self.sign_in(other)
        self.assertEqual(self.download(path + "&download=1").status_code, 403)
        self.assertEqual(AuditEvent.objects.filter(event_type="asset_downloaded").count(), 0)
        self.assertEqual(AuditEvent.objects.filter(event_type="access_denied", actor=other).count(), 1)

    def test_reauthentication_failure_and_sensitive_mfa_failure_remain_audited(self):
        user = self.as_admin()
        before = AuditEvent.objects.filter(event_type="authentication_failed").count()
        response = self.client.patch(f"/users/{user.pk}/", {
            "email": "changed@example.com", "current_password": "wrong"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AuditEvent.objects.filter(event_type="authentication_failed").count(), before + 1)
        failures = AuditEvent.objects.filter(event_type="mfa_verification_failed").count()
        response = self.client.post("/api/account/mfa/replace/", {"password": PASSWORD, "code": "not-a-factor"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(AuditEvent.objects.filter(event_type="mfa_verification_failed").count(), failures + 1)
        self.assertEqual(AuditEvent.objects.filter(event_type="authentication_failed").count(), before + 1)

    def test_repeated_failed_login_detection_real_flow_and_identifier_isolation(self):
        for attempt in range(6):
            response = self.client.post("/api/token/", {"username": "unknown", "password": "wrong"}, format="json")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(SecurityAlert.objects.count(), int(attempt >= 4))
        alert = SecurityAlert.objects.get()
        self.assertEqual((alert.alert_type, alert.event_count, alert.account_identifier, alert.severity),
                         ("repeated_failed_login", 6, "unknown", "medium"))
        self.assertIsNone(alert.affected_user)
        record_event("login_failed", account_identifier="another")
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_bulk_download_detection_real_flow_and_preview_exclusion(self):
        user = self.as_admin()
        asset = self.upload()
        path = asset["url"].replace("http://testserver", "")
        for _ in range(21):
            self.download(path)
        self.assertFalse(SecurityAlert.objects.filter(alert_type="bulk_download").exists())
        for index in range(21):
            self.assertEqual(self.download(path + "&download=1").status_code, 200)
            self.assertEqual(SecurityAlert.objects.filter(alert_type="bulk_download").count(), int(index >= 19))
        alert = SecurityAlert.objects.get(alert_type="bulk_download")
        self.assertEqual((alert.affected_user, alert.severity, alert.event_count), (user, "high", 21))

    def test_repeated_access_denial_detection_real_flow(self):
        user = self.user()
        self.sign_in(user)
        for _ in range(6):
            self.assertEqual(self.client.post("/tags/", {"title": "Forbidden"}, format="json").status_code, 403)
        alert = SecurityAlert.objects.get(alert_type="repeated_access_denial")
        self.assertEqual((alert.affected_user, alert.event_count), (user, 6))

    def test_rolling_windows_ignore_old_events_and_other_subjects(self):
        user = self.user()
        other = self.user("other")
        for event_type, rule in RULES.items():
            with self.subTest(event_type=event_type):
                for _ in range(rule["threshold"] - 1):
                    record_event(event_type, user, account_identifier="viewer")
                AuditEvent.objects.filter(event_type=event_type).update(timestamp=timezone.now() - timedelta(seconds=rule["seconds"] + 1))
                record_event(event_type, other, account_identifier="other")
                record_event(event_type, user, account_identifier="viewer")
                self.assertFalse(SecurityAlert.objects.filter(alert_type=rule["type"]).exists())

    def test_deduplication_resolved_alert_counts_and_next_bucket(self):
        fixed = datetime(2026, 11, 13, 0, 1, tzinfo=dt_timezone.utc)
        with patch("django.utils.timezone.now", return_value=fixed):
            for _ in range(5):
                record_event("login_failed", account_identifier="unknown")
            alert = SecurityAlert.objects.get()
            SecurityAlert.objects.filter(pk=alert.pk).update(status="resolved", resolved_at=fixed)
            record_event("login_failed", account_identifier="unknown")
            alert.refresh_from_db()
            self.assertEqual((SecurityAlert.objects.count(), alert.status, alert.event_count), (1, "resolved", 6))
        with patch("django.utils.timezone.now", return_value=fixed + timedelta(minutes=10)):
            for _ in range(5):
                record_event("login_failed", account_identifier="unknown")
        self.assertEqual(SecurityAlert.objects.count(), 2)
        self.assertEqual(SecurityAlert.objects.filter(status="open").count(), 1)

    def test_administrator_api_summary_filtering_details_resolution_and_pagination(self):
        user = self.as_admin()
        for _ in range(6):
            record_event("login_failed", account_identifier="unknown")
        record_event("access_denied", user, resource_id="tags-list")
        record_event("asset_downloaded", user, resource_id="asset-123")
        old = record_event("asset_downloaded", user)
        AuditEvent.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(days=2))
        response = self.client.get("/api/security/overview/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["counts"], {"failed_logins": 6, "access_denials": 1, "asset_downloads": 1, "open_alerts": 1})
        self.assertTrue(response.data["activity"])
        self.assertEqual(self.client.get("/api/security/overview/?hours=invalid").status_code, 400)
        response = self.client.get(f"/api/security/audit-events/?user={user.pk}&event_type=asset_downloaded&outcome=success&resource=asset-123")
        self.assertEqual(response.data["count"], 1)
        event_id = response.data["results"][0]["id"]
        self.assertEqual(self.client.get(f"/api/security/audit-events/{event_id}/").status_code, 200)
        self.assertEqual(self.client.get("/api/security/audit-events/?user=bad-uuid").status_code, 400)
        self.assertEqual(self.client.get("/api/security/audit-events/?start=bad-date").status_code, 400)
        self.assertEqual(self.client.get("/api/security/audit-events/?search=unknown&severity=medium&category=authentication").data["count"], 6)
        future = (timezone.now() + timedelta(days=1)).isoformat()
        self.assertEqual(self.client.get("/api/security/audit-events/", {"start": future}).data["count"], 0)
        alerts = self.client.get("/api/security/alerts/?alert_type=repeated_failed_login&status=open&severity=medium&search=unknown")
        self.assertEqual(alerts.data["count"], 1)
        alert_id = alerts.data["results"][0]["id"]
        self.assertNotIn("subject_key", alerts.data["results"][0])
        self.assertEqual(self.client.get(f"/api/security/alerts/{alert_id}/").status_code, 200)
        self.assertEqual(self.client.get("/api/security/alerts/?severity=high").data["count"], 0)
        self.assertEqual(self.client.get("/api/security/alerts/", {"start": future}).data["count"], 0)
        for _ in range(2):
            result = self.client.post(f"/api/security/alerts/{alert_id}/resolve/")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.data["resolved_by"], user.pk)
        self.assertEqual(AuditEvent.objects.filter(event_type="alert_resolved").count(), 1)
        self.assertEqual(self.client.get("/api/security/overview/").data["counts"]["open_alerts"], 0)
        for _ in range(42):
            record_event("tag_created", user)
        first = self.client.get("/api/security/audit-events/?event_type=tag_created")
        self.assertEqual(len(first.data["results"]), 40)
        self.assertIsNotNone(first.data["next"])
        self.assertEqual(len(self.client.get("/api/security/audit-events/?event_type=tag_created&page=2").data["results"]), 2)

    def test_activity_log_page_sizes_preserve_filters_and_bound_requests(self):
        user = self.as_admin()
        for _ in range(113):
            record_event("tag_created", user)
        record_event("tag_deleted", user)
        path = "/api/security/audit-events/"
        for size in (10, 25, 40, 50, 100):
            with self.subTest(size=size):
                first = self.client.get(path, {"event_type": "tag_created", "page_size": size})
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.data["count"], 113)
                self.assertEqual(len(first.data["results"]), size)
                self.assertIn(f"page_size={size}", first.data["next"])
                second = self.client.get(first.data["next"])
                self.assertEqual(len(second.data["results"]), min(size, 113 - size))
                self.assertTrue({row["id"] for row in first.data["results"]}.isdisjoint(
                    row["id"] for row in second.data["results"]))
                self.assertTrue(all(row["event_type"] == "tag_created" for row in second.data["results"]))
        for value, expected in (("10000", 100), ("invalid", 40), ("0", 40), ("-1", 40)):
            with self.subTest(value=value):
                response = self.client.get(path, {"event_type": "tag_created", "page_size": value})
                self.assertEqual(len(response.data["results"]), expected)

    def test_monitoring_apis_reject_anonymous_viewer_and_editor_including_details_and_resolve(self):
        alert = None
        for _ in range(5):
            record_event("login_failed", account_identifier="unknown")
        alert = SecurityAlert.objects.get()
        event = AuditEvent.objects.first()
        paths = ["/api/security/overview/", "/api/security/alerts/", "/api/security/audit-events/",
                 f"/api/security/alerts/{alert.pk}/", f"/api/security/audit-events/{event.pk}/"]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 401)
        for role in ("Viewer", "Editor"):
            self.client = APIClient()
            user = self.user(role.lower(), role=role)
            self.sign_in(user)
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post(f"/api/security/alerts/{alert.pk}/resolve/").status_code, 403)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "open")

    def test_audit_trail_keeps_event_when_actor_deleted(self):
        user = self.user()
        reference = str(user.pk)
        event = record_event("login_succeeded", user, target=user)
        user.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor)
        self.assertEqual(event.resource_id, reference)
        self.assertEqual(event.actor_reference, reference)
