"""Fixed, fail-closed boundaries for the disposable ZAP environment."""
import json
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / ".zap"
STATE = ROOT / "state"
HOST = "127.0.0.2"  # Separate host-only cookie jar from normal development.
FRONTEND = f"https://{HOST}:3443"
API = f"https://{HOST}:8443"
DATABASE = STATE / "zap.sqlite3"
DIRECTORIES = ("media", "private_assets", "static", "email", "tmp", "logs")


def safe_path(path):
    """Reject links/junctions/hard links before opening or deleting local state."""
    path = Path(path).absolute()
    if not path.is_relative_to(ROOT) or path == ROOT.parent:
        raise ImproperlyConfigured("ZAP state must remain inside the repository .zap directory.")
    for part in (ROOT, *reversed(path.parents), path):
        if part != ROOT and not part.is_relative_to(ROOT):
            continue
        if part.is_symlink() or part.is_junction():
            raise ImproperlyConfigured("ZAP state cannot contain symlinks or junctions.")
        if part.is_file() and part.stat().st_nlink != 1:
            raise ImproperlyConfigured("ZAP state cannot contain hard-linked files.")
    if not path.resolve().is_relative_to(ROOT):
        raise ImproperlyConfigured("ZAP state escaped its dedicated directory.")
    return path


def check_state():
    safe_path(ROOT)
    safe_path(STATE)
    if STATE.exists():
        for path in STATE.rglob("*"):
            safe_path(path)
    for name in DIRECTORIES:
        safe_path(STATE / name)
    safe_path(DATABASE)


def read_secrets():
    check_state()
    try:
        values = json.loads(safe_path(STATE / "secrets.json").read_text(encoding="utf-8"))
        if set(values) != {"django", "mfa", "environment"}:
            raise ValueError()
        if any(not isinstance(v, str) or len(v) < 32 for v in values.values()):
            raise ValueError()
        return values
    except (OSError, ValueError, TypeError):
        raise ImproperlyConfigured("Initialise ZAP using scripts/zap.ps1 init; secrets are missing or invalid.") from None


def assert_isolated(settings):
    check_state()
    db = settings.DATABASES
    if (set(db) != {"default"}
            or db["default"]["ENGINE"] != "django.db.backends.sqlite3"
            or Path(db["default"]["NAME"]) != DATABASE
            or any(db["default"].get(k) for k in ("HOST", "PORT", "USER", "PASSWORD"))):
        raise ImproperlyConfigured("ZAP requires its dedicated SQLite file and no network database.")
    for setting, name in (("MEDIA_ROOT", "media"), ("ASSET_PRIVATE_ROOT", "private_assets"),
                          ("STATIC_ROOT", "static"), ("EMAIL_FILE_PATH", "email"),
                          ("FILE_UPLOAD_TEMP_DIR", "tmp")):
        if Path(getattr(settings, setting)) != STATE / name:
            raise ImproperlyConfigured("ZAP storage must use the fixed isolated directories.")
    if (settings.ALLOWED_HOSTS != [HOST] or settings.ACCOUNT_FRONTEND_URL != FRONTEND
            or settings.EMAIL_BACKEND != "backend.zap_email.CapturedEmailBackend"
            or not settings.AUTH_COOKIE_SECURE or not settings.SESSION_COOKIE_SECURE
            or not settings.CSRF_COOKIE_SECURE or settings.DEBUG
            or settings.AUTH_COOKIE_ACCESS != "zap_access"
            or settings.AUTH_COOKIE_REFRESH != "zap_refresh"
            or settings.SESSION_COOKIE_NAME != "zap_sessionid"
            or settings.CSRF_COOKIE_NAME != "zap_csrftoken"):
        raise ImproperlyConfigured("ZAP requires its dedicated host, captured email and secure cookies.")


def clean_environment():
    """Child processes receive OS runtime paths, never development service secrets."""
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE",
               "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
               "PROGRAMDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
               "SYSTEMDRIVE", "HOMEDRIVE", "HOMEPATH"}
    values = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    values.update({"TEMP": str(STATE / "tmp"), "TMP": str(STATE / "tmp"),
                   "TMPDIR": str(STATE / "tmp"), "DJANGO_SETTINGS_MODULE": "backend.zap_settings",
                   "DJANGO_READ_DOT_ENV": "false", "PYTHONDONTWRITEBYTECODE": "1",
                   "NEXT_TELEMETRY_DISABLED": "1", "DAM_ZAP": "1"})
    return values
