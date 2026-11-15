"""Disposable DAST settings. Import the real security policy, never test_settings."""
import os
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

from .zap_safety import API, DATABASE, DIRECTORIES, FRONTEND, HOST, STATE, assert_isolated, read_secrets

# Refuse direct invocation from a shell carrying application/service configuration.
# The dedicated launcher supplies an allowlisted environment instead.
if os.environ.get("DAM_ZAP") != "1" or os.environ.get("DJANGO_READ_DOT_ENV") != "false":
    raise ImproperlyConfigured("Use scripts/zap.ps1 for the isolated ZAP environment.")
if any(key.startswith(("DB_", "PG", "SUPABASE", "DATABASE_URL", "EMAIL_", "AUTH_"))
       or key.startswith("DJANGO_") and key not in {"DJANGO_SETTINGS_MODULE", "DJANGO_READ_DOT_ENV", "DJANGO_ASSET_PRIVATE_ROOT"}
       for key in os.environ):
    raise ImproperlyConfigured("ZAP refuses inherited database, authentication, email or Django configuration.")
if os.environ.get("DJANGO_ASSET_PRIVATE_ROOT", str(STATE / "private_assets")) != str(STATE / "private_assets"):
    raise ImproperlyConfigured("ZAP refuses external asset storage.")

_secrets = read_secrets()
_values = {
    "DJANGO_READ_DOT_ENV": "false", "DJANGO_SECRET_KEY": _secrets["django"],
    "DJANGO_DEBUG": "false", "DJANGO_ALLOWED_HOSTS": HOST,
    # Import placeholders only: replaced before Django initialises any connections.
    "DB_HOST": "zap-disabled.invalid", "DB_NAME": "unused", "DB_USER": "unused",
    "DB_PASSWORD": "unused", "DB_PORT": "1", "DB_SSLMODE": "disable",
    "DJANGO_MEDIA_ROOT": str(STATE / "media"),
    "DJANGO_ASSET_PRIVATE_ROOT": str(STATE / "private_assets"),
    "DJANGO_STATIC_ROOT": str(STATE / "static"),
    "CORS_ALLOWED_ORIGINS": FRONTEND, "CSRF_TRUSTED_ORIGINS": f"{FRONTEND},{API}",
    "MEDIA_FRAME_ALLOWED_ORIGINS": FRONTEND, "ACCOUNT_FRONTEND_URL": FRONTEND,
    "EMAIL_BACKEND": "backend.zap_email.CapturedEmailBackend",
    "ACCOUNT_EMAIL_ASYNC": "false", "MFA_ENCRYPTION_KEY": _secrets["mfa"],
    "MFA_ISSUER": "ManticAI ZAP disposable", "ACCOUNT_ALLOWED_EMAIL_DOMAINS": "example.invalid",
    "AUTH_CACHE_LOCATION": "dam-zap-only",
}
with patch.dict(os.environ, _values, clear=True):
    from .settings import *  # noqa: F403

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3", "NAME": DATABASE,
    # Acquire the SQLite write reservation before security read/modify/write flows.
    # This serialises writers; it does not emulate PostgreSQL row locks.
    "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    "TEST": {"NAME": STATE / "verification.sqlite3"},
}}
ZAP_ISOLATED = True
ZAP_ENVIRONMENT_ID = hashlib.sha256(_secrets["environment"].encode()).hexdigest()
EMAIL_FILE_PATH = STATE / "email"
FILE_UPLOAD_TEMP_DIR = STATE / "tmp"
AUTH_COOKIE_ACCESS = "zap_access"
AUTH_COOKIE_REFRESH = "zap_refresh"
SESSION_COOKIE_NAME = "zap_sessionid"
CSRF_COOKIE_NAME = "zap_csrftoken"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
# Runtime failures must not include request payloads/credentials in tracebacks.
LOGGING["handlers"]["console"]["filters"] = ["media_tokens"]  # noqa: F405
assert_isolated(SimpleNamespace(**globals()))
del _secrets, _values
