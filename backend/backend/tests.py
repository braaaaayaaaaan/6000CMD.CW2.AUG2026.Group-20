import json
import os
from pathlib import Path
import subprocess
import sys

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.middleware.clickjacking import XFrameOptionsMiddleware
from django.test import RequestFactory, SimpleTestCase, override_settings

from .environment import (
    boolean_environment,
    database_from_environment,
    integer_environment,
    list_environment,
    origins_environment,
    path_environment,
    required_environment,
)
from .middleware import MediaFramePolicyMiddleware


class DatabaseEnvironmentTests(SimpleTestCase):
    def environment(self, **overrides):
        values = {
            "DB_NAME": "placeholder_database",
            "DB_USER": "placeholder_role",
            "DB_PASSWORD": "  literal#${not_interpolated}  ",
            "DB_HOST": "placeholder.invalid",
            "DB_SSLROOTCERT": "C:/placeholder/ca.crt",
        }
        values.update(overrides)
        return values

    def test_database_uses_verified_ssl_and_preserves_password(self):
        values = self.environment()
        database = database_from_environment(values)
        self.assertEqual(database["PASSWORD"], values["DB_PASSWORD"])
        self.assertEqual(database["OPTIONS"], {
            "sslmode": "verify-full", "sslrootcert": "C:/placeholder/ca.crt",
        })
        self.assertEqual(database["PORT"], "5432")

    def test_missing_credentials_do_not_fall_back_to_existing_local_database(self):
        values = self.environment()
        del values["DB_HOST"]
        with self.assertRaisesMessage(ImproperlyConfigured, "Set DB_HOST"):
            database_from_environment(values)

    def test_verified_ssl_requires_certificate_path(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DB_SSLROOTCERT"):
            database_from_environment(self.environment(DB_SSLROOTCERT=""))

    def test_local_ssl_can_be_explicitly_disabled(self):
        database = database_from_environment(self.environment(DB_SSLMODE="disable", DB_SSLROOTCERT=""))
        self.assertEqual(database["OPTIONS"], {"sslmode": "disable"})

    def test_invalid_port_and_ssl_mode_fail_without_echoing_values(self):
        for overrides in ({"DB_PORT": "not-a-port"}, {"DB_PORT": "0"}, {"DB_SSLMODE": "invalid"}):
            with self.subTest(overrides=overrides), self.assertRaises(ImproperlyConfigured):
                database_from_environment(self.environment(**overrides))

    def test_secret_is_required(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_SECRET_KEY"):
            required_environment("DJANGO_SECRET_KEY", {})

    def test_relative_certificate_path_is_anchored_to_backend(self):
        base_dir = Path(__file__).resolve().parent.parent
        database = database_from_environment(
            self.environment(DB_SSLROOTCERT="certificate/prod-ca-2021.crt"), base_dir=base_dir,
        )
        self.assertEqual(database["OPTIONS"]["sslrootcert"], str(base_dir / "certificate/prod-ca-2021.crt"))


class EnvironmentParsingTests(SimpleTestCase):
    def test_debug_false_is_not_treated_as_a_truthy_string(self):
        for value in ("false", "0", "no", "off", " FALSE "):
            with self.subTest(value=value):
                self.assertFalse(boolean_environment("DEBUG", environ={"DEBUG": value}))
        self.assertTrue(boolean_environment("DEBUG", environ={"DEBUG": "true"}))
        self.assertFalse(boolean_environment("DEBUG", environ={}))

    def test_invalid_boolean_and_lifetime_fail_without_echoing_input(self):
        for parse, name in (
            (lambda env: boolean_environment("DEBUG", environ=env), "DEBUG"),
            (lambda env: integer_environment("LIFETIME", 40, environ=env), "LIFETIME"),
        ):
            with self.subTest(name=name), self.assertRaises(ImproperlyConfigured) as error:
                parse({name: "sensitive-invalid-value"})
            self.assertNotIn("sensitive-invalid-value", str(error.exception))
        for value in ("0", "-1"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                integer_environment("LIFETIME", 40, environ={"LIFETIME": value})

    def test_lists_trim_deduplicate_and_allow_explicit_empty_values(self):
        self.assertEqual(list_environment("HOSTS", environ={"HOSTS": "localhost, ,127.0.0.1,localhost"}),
                         ["localhost", "127.0.0.1"])
        self.assertEqual(list_environment("HOSTS", ("localhost",), {"HOSTS": ""}), [])

    def test_origin_configuration_rejects_paths_credentials_and_header_injection(self):
        for value in ("localhost:3000", "https://example.com/", "https://user:password@example.com",
                      "https://example.com;script-src", "https://example.com\r\nInjected: yes",
                      "https://example.com:invalid", "https://*.example.com"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                origins_environment("ORIGINS", environ={"ORIGINS": value})
        self.assertEqual(origins_environment("ORIGINS", environ={"ORIGINS": "https://example.com,http://[::1]:3000"}),
                         ["https://example.com", "http://[::1]:3000"])

    def test_storage_paths_are_independent_of_working_directory(self):
        base_dir = Path(__file__).resolve().parent.parent
        self.assertEqual(path_environment("MEDIA", base_dir, "media", {}), base_dir / "media")
        self.assertEqual(path_environment("MEDIA", base_dir, "media", {"MEDIA": "uploads"}), base_dir / "uploads")
        self.assertEqual(path_environment("MEDIA", base_dir, "media", {"MEDIA": str(base_dir.parent)}), base_dir.parent)

    def test_settings_load_from_process_environment_without_reading_local_secrets(self):
        base_dir = Path(__file__).resolve().parent.parent
        environ = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "backend.settings",
            "DJANGO_READ_DOT_ENV": "false",
            "DJANGO_SECRET_KEY": "test-only-key-for-settings-import",
            "DB_NAME": "unused", "DB_USER": "unused", "DB_PASSWORD": "unused",
            "DB_HOST": "unused.invalid", "DB_PORT": "5432",
            "DB_SSLMODE": "verify-full", "DB_SSLROOTCERT": "certificate/prod-ca-2021.crt",
            "DJANGO_MEDIA_ROOT": "media", "DJANGO_STATIC_ROOT": "staticfiles",
            "DJANGO_ALLOWED_HOSTS": "api.example.com",
            "CORS_ALLOWED_ORIGINS": "https://app.example.com",
            "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
            "MEDIA_FRAME_ALLOWED_ORIGINS": "https://app.example.com",
            "JWT_ACCESS_TOKEN_MINUTES": "15",
        }
        environ.pop("DJANGO_DEBUG", None)
        result = subprocess.run([
            sys.executable, "-c",
            "import json; from django.conf import settings as s; "
            "assert s.SECRET_KEY == 'test-only-key-for-settings-import'; "
            "print(json.dumps({'debug': s.DEBUG, 'hosts': s.ALLOWED_HOSTS, "
            "'cors': s.CORS_ALLOWED_ORIGINS, 'csrf': s.CSRF_TRUSTED_ORIGINS, "
            "'frames': s.MEDIA_FRAME_ALLOWED_ORIGINS, "
            "'lifetime': s.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds(), "
            "'certificate': s.DATABASES['default']['OPTIONS']['sslrootcert']}))",
        ], cwd=base_dir, env=environ, capture_output=True, text=True, check=True)
        values = json.loads(result.stdout)
        self.assertFalse(values["debug"])
        self.assertEqual(values["hosts"], ["api.example.com"])
        for key in ("cors", "csrf", "frames"):
            self.assertEqual(values[key], ["https://app.example.com"])
        self.assertEqual(values["lifetime"], 900)
        self.assertEqual(values["certificate"], str(base_dir / "certificate/prod-ca-2021.crt"))


@override_settings(MEDIA_URL="/media/", X_FRAME_OPTIONS="DENY",
                   MEDIA_FRAME_ALLOWED_ORIGINS=["http://localhost:3000"])
class MediaFramePolicyTests(SimpleTestCase):
    def response(self, path, policy=""):
        def view(request):
            response = HttpResponse()
            if policy:
                response["Content-Security-Policy"] = policy
            return response

        middleware = MediaFramePolicyMiddleware(XFrameOptionsMiddleware(view))
        return middleware(RequestFactory().get(path))

    def test_media_previews_allow_only_self_and_the_configured_frontend(self):
        response = self.response("/media/uploads/example.mp4")
        self.assertEqual(response["Content-Security-Policy"], "frame-ancestors 'self' http://localhost:3000")
        self.assertNotIn("X-Frame-Options", response)

    def test_admin_and_api_pages_cannot_be_framed(self):
        for path in ("/admin/", "/api/token/", "/media-other/"):
            with self.subTest(path=path):
                response = self.response(path)
                self.assertEqual(response["X-Frame-Options"], "DENY")
                self.assertNotIn("Content-Security-Policy", response)

    def test_existing_csp_directives_and_stricter_frame_policies_are_preserved(self):
        response = self.response("/media/example.mp4", "default-src 'self'")
        self.assertEqual(response["Content-Security-Policy"],
                         "default-src 'self'; frame-ancestors 'self' http://localhost:3000")
        response = self.response("/media/example.mp4", "frame-ancestors 'none'")
        self.assertEqual(response["Content-Security-Policy"], "frame-ancestors 'none'")

    @override_settings(MEDIA_FRAME_ALLOWED_ORIGINS=[])
    def test_empty_allowlist_does_not_permit_cross_origin_media_framing(self):
        response = self.response("/media/example.mp4")
        self.assertEqual(response["Content-Security-Policy"], "frame-ancestors 'self'")
        self.assertEqual(response["X-Frame-Options"], "DENY")
