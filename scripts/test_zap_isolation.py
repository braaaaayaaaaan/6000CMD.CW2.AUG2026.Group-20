"""Boundary regression tests; no application database or .env is loaded."""
import os
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from backend import zap_safety as safety
from django.core.exceptions import ImproperlyConfigured


class IsolationTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": safety.DATABASE}},
            MEDIA_ROOT=safety.STATE / "media", ASSET_PRIVATE_ROOT=safety.STATE / "private_assets",
            STATIC_ROOT=safety.STATE / "static", EMAIL_FILE_PATH=safety.STATE / "email",
            FILE_UPLOAD_TEMP_DIR=safety.STATE / "tmp", ALLOWED_HOSTS=[safety.HOST],
            ACCOUNT_FRONTEND_URL=safety.FRONTEND, EMAIL_BACKEND="backend.zap_email.CapturedEmailBackend",
            AUTH_COOKIE_SECURE=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, DEBUG=False,
            AUTH_COOKIE_ACCESS="zap_access", AUTH_COOKIE_REFRESH="zap_refresh",
            SESSION_COOKIE_NAME="zap_sessionid", CSRF_COOKIE_NAME="zap_csrftoken",
        )

    def test_accepts_only_fixed_sqlite_configuration(self):
        with patch.object(safety, "check_state"):
            safety.assert_isolated(self.config())
            for database in (
                {"ENGINE": "django.db.backends.postgresql", "NAME": "example"},
                {"ENGINE": "django.db.backends.sqlite3", "NAME": safety.REPO / "db.sqlite3"},
                {"ENGINE": "django.db.backends.sqlite3", "NAME": safety.DATABASE, "HOST": "db.example.invalid"},
            ):
                config = self.config()
                config.DATABASES = {"default": database}
                with self.assertRaises(ImproperlyConfigured):
                    safety.assert_isolated(config)

    def test_rejects_external_storage_smtp_and_insecure_cookies(self):
        with patch.object(safety, "check_state"):
            for key, value in (
                ("MEDIA_ROOT", safety.REPO / "backend/media"),
                ("ASSET_PRIVATE_ROOT", safety.REPO / "backend/private_assets"),
                ("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"),
                ("AUTH_COOKIE_SECURE", False), ("SESSION_COOKIE_SECURE", False),
                ("CSRF_COOKIE_SECURE", False), ("ALLOWED_HOSTS", ["*"]),
                ("AUTH_COOKIE_ACCESS", "dam_access"), ("SESSION_COOKIE_NAME", "sessionid"),
                ("ACCOUNT_FRONTEND_URL", "http://127.0.0.1:3000"), ("DEBUG", True),
            ):
                config = self.config()
                setattr(config, key, value)
                with self.subTest(key=key), self.assertRaises(ImproperlyConfigured):
                    safety.assert_isolated(config)

    def test_child_environment_excludes_service_secrets_and_development_configuration(self):
        with patch.dict(os.environ, {"DB_HOST": "unsafe.invalid", "SUPABASE_KEY": "synthetic",
                                     "EMAIL_PASSWORD": "synthetic", "NEXT_PUBLIC_API_URL": "https://unsafe.invalid",
                                     "DJANGO_SECRET_KEY": "synthetic", "PGSERVICE": "synthetic",
                                     "HTTP_PROXY": "https://unsafe.invalid", "NODE_OPTIONS": "--inspect"}):
            result = safety.clean_environment()
        for key in ("DB_HOST", "SUPABASE_KEY", "EMAIL_PASSWORD", "NEXT_PUBLIC_API_URL",
                    "DJANGO_SECRET_KEY", "PGSERVICE", "HTTP_PROXY", "NODE_OPTIONS"):
            self.assertNotIn(key, result)
        self.assertEqual(result["DJANGO_SETTINGS_MODULE"], "backend.zap_settings")
        self.assertEqual(result["DJANGO_READ_DOT_ENV"], "false")

    def test_state_paths_reject_traversal_and_external_files(self):
        for path in (safety.REPO / "backend/media", safety.ROOT / "../backend/private_assets",
                     safety.REPO / "backend/.env"):
            with self.assertRaises(ImproperlyConfigured):
                safety.safe_path(path)

    def test_state_paths_reject_links(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / ".zap"
            root.mkdir()
            target = Path(directory) / "important"
            target.mkdir()
            link = root / "linked"
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(target), str(link))
            else:
                link.symlink_to(target, target_is_directory=True)
            try:
                with patch.object(safety, "ROOT", root):
                    with self.assertRaises(ImproperlyConfigured):
                        safety.safe_path(link / "asset.png")
            finally:
                if os.name == "nt":
                    link.rmdir()
                else:
                    link.unlink()

    def test_settings_reject_unsafe_inherited_configuration_before_loading_dotenv(self):
        code = '''
import sys
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
with patch("dotenv.load_dotenv", side_effect=AssertionError("dotenv must not load")):
    try:
        import backend.zap_settings
    except ImproperlyConfigured:
        sys.exit(17)
sys.exit(1)
'''
        for poison in ({"DB_HOST": "unsafe.invalid"}, {"EMAIL_HOST": "unsafe.invalid"},
                       {"SUPABASE_KEY": "synthetic"},
                       {"DJANGO_ASSET_PRIVATE_ROOT": str(safety.REPO / "backend/private_assets")}):
            result = subprocess.run([sys.executable, "-B", "-c", code],
                                    cwd=safety.REPO / "backend",
                                    env={**safety.clean_environment(), **poison}, capture_output=True)
            with self.subTest(key=next(iter(poison))):
                self.assertEqual(result.returncode, 17)


if __name__ == "__main__":
    unittest.main()
