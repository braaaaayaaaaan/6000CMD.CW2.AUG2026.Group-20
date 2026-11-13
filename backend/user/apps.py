from django.apps import AppConfig


class UserConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'user'

    def ready(self):
        from . import signals  # noqa: F401
        from . import audit_signals  # noqa: F401
