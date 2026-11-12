"""Isolated tests: never use backend/.env database credentials or media files."""

import os
from unittest.mock import patch


# Supply settings import placeholders, then replace the database before setup.
with patch.dict(os.environ, {
    "DJANGO_READ_DOT_ENV": "false",
    "DJANGO_SECRET_KEY": "test-only-key-not-for-a-running-application",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,[::1],testserver",
    "DJANGO_TIME_ZONE": "UTC",
    "CORS_ALLOWED_ORIGINS": "",
    "CSRF_TRUSTED_ORIGINS": "",
    "MEDIA_FRAME_ALLOWED_ORIGINS": "",
    "JWT_ACCESS_TOKEN_MINUTES": "40",
    "AUTH_COOKIE_SECURE": "true",
    "AUTH_COOKIE_SAMESITE": "Lax",
    "AUTH_NUM_PROXIES": "0",
    "ACCOUNT_FRONTEND_URL": "http://127.0.0.1:3000",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "DJANGO_MEDIA_ROOT": "media",
    "DJANGO_STATIC_ROOT": "staticfiles",
    "DB_NAME": "unused",
    "DB_USER": "unused",
    "DB_PASSWORD": "unused",
    "DB_HOST": "unused.invalid",
    "DB_PORT": "5432",
    "DB_SSLMODE": "disable",
    "DB_SSLROOTCERT": "",
}):
    from .settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SECURE_SSL_REDIRECT = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
ACCOUNT_EMAIL_ASYNC = False
MFA_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # Test-only key.
AUTH_COOKIE_SECURE = True
ACCOUNT_ALLOWED_EMAIL_DOMAINS = []
MFA_REQUIRED_ROLES = ["Viewer", "Editor", "Admin"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "handlers": {"null": {"class": "logging.NullHandler"}},
           "loggers": {"dam.audit": {"handlers": ["null"], "level": "INFO", "propagate": False}}}
