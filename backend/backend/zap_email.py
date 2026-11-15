"""Private local email capture usable with DEBUG=False; no SMTP connection."""
from django.core.mail.backends.filebased import EmailBackend
from .zap_safety import STATE, safe_path


class CapturedEmailBackend(EmailBackend):
    def __init__(self, *args, **kwargs):
        safe_path(STATE / "email")
        # Callers cannot redirect verification/recovery messages elsewhere.
        kwargs["file_path"] = str(STATE / "email")
        super().__init__(*args, **kwargs)
